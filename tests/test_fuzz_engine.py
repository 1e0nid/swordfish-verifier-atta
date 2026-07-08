import pytest
from unittest.mock import AsyncMock, MagicMock
from src.fuzzer.fuzz_engine import SwordfishFuzzer


# --- МОКИ ДЛЯ СТРУКТУР ДАННЫХ ---

class MockFieldRule:
    def __init__(self, field_type):
        self.field_type = field_type


class MockResourceRule:
    def __init__(self, resource_name, allowed_methods, expected_fields=None):
        self.resource_name = resource_name
        self.allowed_methods = allowed_methods
        self.expected_fields = expected_fields or {}


class MockSpecificationRules:
    def __init__(self, resources):
        self.resources = resources


class MockAppConfig:
    def __init__(self, resources_filter=None):
        self.validator = MagicMock()
        self.validator.resources_filter = resources_filter or []


# --- ТЕСТЫ ---

def test_fuzzer_find_res_rule():
    """Проверка нечеткого поиска схем ресурсов"""
    rule = MockResourceRule("Chassis", ["GET"])
    rules = MockSpecificationRules({"Chassis": rule})
    fuzzer = SwordfishFuzzer(MockAppConfig(), rules, MagicMock())

    assert fuzzer._find_res_rule("Chassis") == rule
    assert fuzzer._find_res_rule("chassiscollection") == rule
    assert fuzzer._find_res_rule("Storage") is None


@pytest.mark.asyncio
async def test_fuzz_http_methods_server_crash(mocker):
    """Сервер падает в 500 ошибку при отправке запрещенного метода (FAIL)"""
    config = MockAppConfig()
    fuzzer = SwordfishFuzzer(config, MockSpecificationRules({}), MagicMock())

    # Мокаем клиент: пусть он возвращает статус 500
    fuzzer.client.send_request = AsyncMock(return_value={"status_code": 500})

    # Ресурс разрешает только GET. Значит POST, PUT, DELETE, PATCH — запрещены
    res_rule = MockResourceRule("Volume", allowed_methods=["GET"])

    await fuzzer._fuzz_http_methods(res_rule, "/redfish/v1/Volumes/1")

    # Проверяем, что зафиксированы падения (FAIL)
    assert len(fuzzer.results) > 0
    for res in fuzzer.results:
        assert res["status"] == "FAIL"
        assert "HTTP 500" in res["message"]


@pytest.mark.asyncio
async def test_fuzz_http_methods_server_protects(mocker):
    """Сервер корректно отклоняет запрещенные методы кодом 405 (PASS)"""
    config = MockAppConfig()
    fuzzer = SwordfishFuzzer(config, MockSpecificationRules({}), MagicMock())

    # Имитируем правильное поведение сервера (например, 405 Method Not Allowed)
    fuzzer.client.send_request = AsyncMock(return_value={"status_code": 405})
    res_rule = MockResourceRule("Volume", allowed_methods=["GET"])

    await fuzzer._fuzz_http_methods(res_rule, "/redfish/v1/Volumes/1")

    assert len(fuzzer.results) > 0
    for res in fuzzer.results:
        assert res["status"] == "PASS"
        assert "Защита ОК" in res["message"] or "отклонил метод" in res["message"]


@pytest.mark.asyncio
async def test_fuzz_payload_mutations_logic(mocker):
    """Проверка генерации мутаций: сломанный JSON и подмена типов данных"""
    config = MockAppConfig()
    fuzzer = SwordfishFuzzer(config, MockSpecificationRules({}), MagicMock())
    fuzzer.client.send_request = AsyncMock(
        return_value={"status_code": 400})  # Сервер вернул 400 Bad Request (это успех)

    # Задаем поля: одно числовое, одно строковое
    fields = {
        "CapacityBytes": MockFieldRule("integer"),
        "Name": MockFieldRule("string")
    }
    res_rule = MockResourceRule("Storage", allowed_methods=["POST"], expected_fields=fields)

    await fuzzer._fuzz_payload_mutations(res_rule, "/redfish/v1/Storage")

    # Считаем типы проверок
    check_types = [r["check_type"] for r in fuzzer.results]

    # Должен быть один тест на Malformed JSON и два на Type Mismatch (для каждого поля)
    assert "FUZZING_MALFORMED_JSON" in check_types
    assert "FUZZING_TYPE_MISMATCH [CapacityBytes]" in check_types
    assert "FUZZING_TYPE_MISMATCH [Name]" in check_types

    # Проверяем, какие данные уходили в запросах к клиенту
    calls = fuzzer.client.send_request.call_args_list

    # Первый вызов — отправка массива вместо объекта
    assert calls[0].kwargs["json_data"] == [{"malformed": "structure"}]
    # Второй вызов — для integer ушла строка
    assert calls[1].kwargs["json_data"] == {"CapacityBytes": "not_a_number"}
    # Третий вызов — для string ушло число
    assert calls[2].kwargs["json_data"] == {"Name": 99999}


@pytest.mark.asyncio
async def test_run_fuzzing_no_schema_fallback(mocker):
    """Если схемы нет в базе, фаззер создает fake_rule и все равно проверяет методы"""
    config = MockAppConfig()

    # Подменяем реальный класс ResourceRule внутри движка фаззинга моком,
    # чтобы не упасть на инициализации Pydantic модели
    mock_resource_rule_class = mocker.patch("src.fuzzer.fuzz_engine.ResourceRule")
    mock_resource_rule_instance = MagicMock()
    mock_resource_rule_instance.resource_name = "UnknownRes"
    mock_resource_rule_instance.allowed_methods = ["GET"]
    mock_resource_rule_class.return_value = mock_resource_rule_instance

    fuzzer = SwordfishFuzzer(config, MockSpecificationRules({}), MagicMock())

    # Мокаем внутренние методы, чтобы протестировать только высокоуровневую логику run_fuzzing
    fuzzer._fuzz_http_methods = AsyncMock()
    fuzzer._fuzz_payload_mutations = AsyncMock()

    discovered = {"UnknownRes": ["/redfish/v1/Unknown"]}
    await fuzzer.run_fuzzing(discovered)

    # Проверяем, что fake_rule был создан с дефолтным GET методом
    mock_resource_rule_class.assert_called_once_with(
        resource_name="UnknownRes",
        endpoint_path="/redfish/v1/Unknown",
        allowed_methods=["GET"]
    )
    # И метод _fuzz_http_methods был вызван
    fuzzer._fuzz_http_methods.assert_called_once()
    fuzzer._fuzz_payload_mutations.assert_not_called()  # Без схемы мутации полей невозможны


@pytest.mark.asyncio
async def test_run_fuzzing_filter_out(mocker):
    """Проверяем, что фильтр ресурсов пропускает ненужные эндпоинты"""
    # Разрешаем фаззить только Chassis
    config = MockAppConfig(resources_filter=["Chassis"])
    fuzzer = SwordfishFuzzer(config, MockSpecificationRules({}), MagicMock())

    fuzzer._fuzz_http_methods = AsyncMock()

    discovered = {"Storage": ["/redfish/v1/Storage"]}
    await fuzzer.run_fuzzing(discovered)

    # Метод фаззинга не должен быть вызван, так как Storage отфильтрован
    fuzzer._fuzz_http_methods.assert_not_called()