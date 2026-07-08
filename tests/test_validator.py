import pytest
from unittest.mock import AsyncMock, MagicMock
from src.verifier.validator import get_nested_value, SwordfishValidator


# --- МОКИ ДЛЯ СУЩНОСТЕЙ (Чтобы не зависеть от Pydantic-моделей проекта) ---

class MockFieldRule:
    def __init__(self, is_required=True, field_type="string", enum_values=None):
        self.is_required = is_required
        self.field_type = field_type
        self.enum_values = enum_values


class MockResourceRule:
    def __init__(self, resource_name, expected_fields):
        self.resource_name = resource_name
        self.expected_fields = expected_fields
        self.endpoint_path = ""


class MockSpecificationRules:
    def __init__(self, resources):
        self.resources = resources


class MockValidatorConfig:
    def __init__(self, resources_filter=None):
        self.resources_filter = resources_filter or []


class MockAppConfig:
    def __init__(self, resources_filter=None):
        self.validator = MockValidatorConfig(resources_filter)


# --- 1. ТЕСТЫ ДЛЯ ВСПОМОГАТЕЛЬНЫХ ФУНКЦИЙ ---

def test_get_nested_value_success():
    data = {"outer": {"inner": {"target": "value"}}}
    assert get_nested_value(data, "outer.inner.target") == "value"


def test_get_nested_value_missing_key():
    data = {"outer": {"inner": "value"}}
    # Функция возвращает сам класс KeyError при ошибке
    assert get_nested_value(data, "outer.wrong_key") is KeyError


def test_check_type():
    # Создаем минимальный валидатор для проверки приватного метода _check_type
    validator = SwordfishValidator(MagicMock(), MagicMock(), MagicMock())

    assert validator._check_type(123, "integer") is True
    assert validator._check_type("text", "string") is True
    assert validator._check_type(True, "boolean") is True
    assert validator._check_type(12.34, "number") is True
    assert validator._check_type([1, 2], "array") is True
    assert validator._check_type({"k": "v"}, "object") is True
    assert validator._check_type("not_an_int", "integer") is False


def test_find_res_rule():
    rule_storage = MockResourceRule("Storage", {})
    rules = MockSpecificationRules(resources={"Storage": rule_storage})
    validator = SwordfishValidator(MagicMock(), rules, MagicMock())

    # Точное совпадение
    assert validator._find_res_rule("Storage") == rule_storage
    # Нечеткое совпадение (регистр и подстрока)
    assert validator._find_res_rule("storagecollection") == rule_storage
    # Нет совпадений
    assert validator._find_res_rule("Chassis") is None


# --- 2. АСИНХРОННЫЕ ТЕСТЫ ВАЛИДАТОРА (validate_all) ---

@pytest.mark.asyncio
async def test_validate_all_resource_filtered_out():
    """Проверяем, что фильтр ресурсов корректно игнорирует эндпоинты"""
    config = MockAppConfig(resources_filter=["Storage"])  # Разрешен только Storage
    validator = SwordfishValidator(config, MockSpecificationRules({}), MagicMock())

    discovered = {"Chassis": ["/redfish/v1/Chassis"]}
    results = await validator.validate_all(discovered)

    assert len(results) == 0  # Сlassis должен быть проигнорирован


@pytest.mark.asyncio
async def test_validate_all_no_schema_available():
    """Если схемы нет, проверяется только доступность ручки (ENDPOINT_AVAILABILITY)"""
    config = MockAppConfig(resources_filter=[])
    rules = MockSpecificationRules(resources={})  # Пустые схемы

    # Мокаем HTTP-клиент
    mock_client = MagicMock()
    mock_client.send_request = AsyncMock(return_value={
        "success": True,
        "status_code": 200,
        "error_message": "",
        "data": {}
    })

    validator = SwordfishValidator(config, rules, mock_client)
    discovered = {"UnknownResource": ["/redfish/v1/Unknown"]}

    results = await validator.validate_all(discovered)

    assert len(results) == 1
    assert results[0]["check_type"] == "ENDPOINT_AVAILABILITY"
    assert results[0]["status"] == "PASS"


@pytest.mark.asyncio
async def test_validate_resource_http_fail():
    """Эндпоинт вернул ошибку сети (например, 404 или 500)"""
    config = MockAppConfig()
    res_rule = MockResourceRule("Storage", {})
    rules = MockSpecificationRules({"Storage": res_rule})

    mock_client = MagicMock()
    mock_client.send_request = AsyncMock(return_value={
        "success": False,
        "status_code": 500,
        "error_message": "Internal Server Error",
        "data": None
    })

    validator = SwordfishValidator(config, rules, mock_client)
    discovered = {"Storage": ["/redfish/v1/Storage"]}

    results = await validator.validate_all(discovered)

    assert len(results) == 1
    assert results[0]["check_type"] == "ENDPOINT_AVAILABILITY"
    assert results[0]["status"] == "FAIL"
    assert "Код ответа: 500" in results[0]["message"]


@pytest.mark.asyncio
async def test_validate_resource_field_validation_logic():
    """Комплексный тест валидации полей JSON структуры"""
    config = MockAppConfig()

    # Настраиваем ожидаемые правила для полей ресурса Storage
    expected_fields = {
        "Status.State": MockFieldRule(is_required=True, field_type="string", enum_values=["Enabled", "Disabled"]),
        "CapacityBytes": MockFieldRule(is_required=True, field_type="integer"),
        "OptionalField": MockFieldRule(is_required=False, field_type="string"),  # Отсутствует, но необязателен
        "MissingRequired": MockFieldRule(is_required=True, field_type="boolean")  # Отсутствует и обязателен
    }
    res_rule = MockResourceRule("Storage", expected_fields)
    rules = MockSpecificationRules({"Storage": res_rule})

    # Имитируем реальный ответ от эмулятора
    mock_client = MagicMock()
    mock_client.send_request = AsyncMock(return_value={
        "success": True,
        "status_code": 200,
        "error_message": "",
        "data": {
            "Status": {"State": "InvalidEnumState"},  # Ошибка ENUM
            "CapacityBytes": "строка_вместо_числа",  # Ошибка типа данных
        }
    })

    validator = SwordfishValidator(config, rules, mock_client)
    discovered = {"Storage": ["/redfish/v1/Storage"]}

    results = await validator.validate_all(discovered)

    # Нам важны типы проверок, которые зафиксировал валидатор
    check_types = [r["check_type"] for r in results]
    statuses = {r["check_type"]: r["status"] for r in results}

    # 1. Проверка доступности самой ручки должна пройти успешно
    assert "ENDPOINT_AVAILABILITY" in check_types
    assert statuses["ENDPOINT_AVAILABILITY"] == "PASS"

    # 2. Обязательное поле MissingRequired отсутствует в JSON
    assert "FIELD_REQUIRED" in check_types
    assert statuses["FIELD_REQUIRED"] == "FAIL"

    # 3. Поле CapacityBytes имеет неверный тип (str вместо int)
    assert "FIELD_TYPE" in check_types
    assert statuses["FIELD_TYPE"] == "FAIL"

    # 4. Поле Status.State вернуло значение не из ENUM
    assert "FIELD_ENUM" in check_types
    assert statuses["FIELD_ENUM"] == "FAIL"