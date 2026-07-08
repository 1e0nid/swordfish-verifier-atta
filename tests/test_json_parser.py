import json
import pytest
from src.parser.json_parser import JsonSchemaParser

# --- ЭТАЛОННЫЙ ШАБЛОН JSON-СХЕМЫ ДЛЯ ТЕСТОВ ---
MOCK_SCHEMA = {
    "definitions": {
        "Volume": {
            "type": "object",
            "required": ["Id", "CapacityBytes"],
            "properties": {
                "Id": {
                    "type": "string"
                },
                # Проверка обработки массива в типе данных
                "CapacityBytes": {
                    "type": ["integer", "null"],
                    "minimum": 0
                },
                # Проверка обработки $ref объектов
                "Status": {
                    "$ref": "#/definitions/Status"
                },
                # Проверка ENUM и дополнительных форматов
                "StorageType": {
                    "type": "string",
                    "enum": ["SSD", "HDD"],
                    "format": "custom-uuid"
                }
            }
        },
        # Эта схема должна быть проигнорирована, так как тип не object
        "InvalidDefinition": {
            "type": "string"
        }
    }
}


def test_parse_single_file(tmp_path):
    """Проверка успешного парсинга одного корректного JSON-файла"""
    # Создаем временный файл схемы
    file_path = tmp_path / "volume_schema.json"
    file_path.write_text(json.dumps(MOCK_SCHEMA), encoding="utf-8")

    parser = JsonSchemaParser()
    rules = parser.parse(str(file_path))

    # Проверяем, что ресурс распарсился, а невалидный пропущен
    assert "Volume" in rules.resources
    assert "InvalidDefinition" not in rules.resources

    volume_rule = rules.resources["Volume"]
    assert volume_rule.endpoint_path == "/redfish/v1/Volume"
    assert volume_rule.allowed_methods == ["GET"]

    # Проверяем логику обработки полей
    fields = volume_rule.expected_fields

    # 1. Обычная строка и обязательность
    assert fields["Id"].field_type == "string"
    assert fields["Id"].is_required is True

    # 2. Массив типов (должен взять первый элемент) и минимальное значение
    assert fields["CapacityBytes"].field_type == "integer"
    assert fields["CapacityBytes"].is_required is True
    assert fields["CapacityBytes"].min_value == 0

    # 3. Объект без явного типа, но с наличием $ref
    assert fields["Status"].field_type == "object"
    assert fields["Status"].is_required is False

    # 4. Проверка Enum-значений и формата данных
    assert fields["StorageType"].field_type == "string"
    assert fields["StorageType"].is_required is False
    assert fields["StorageType"].enum_values == ["SSD", "HDD"]
    assert fields["StorageType"].data_format == "custom-uuid"


def test_parse_directory(tmp_path):
    """Проверка сканирования директории и фильтрации не-JSON файлов"""
    # Создаем первый файл схемы
    file1 = tmp_path / "schema_one.json"
    file1.write_text(json.dumps(MOCK_SCHEMA), encoding="utf-8")

    # Создаем второй файл схемы
    file2 = tmp_path / "schema_two.json"
    another_schema = {
        "definitions": {
            "Chassis": {
                "type": "object",
                "properties": {"Name": {"type": "string"}}
            }
        }
    }
    file2.write_text(json.dumps(another_schema), encoding="utf-8")

    # Создаем мусорный файл, который парсер должен проигнорировать
    trash_file = tmp_path / "readme.txt"
    trash_file.write_text("some text data", encoding="utf-8")

    parser = JsonSchemaParser()
    rules = parser.parse(str(tmp_path))

    # Должны успешно собраться ресурсы из обоих файлов
    assert "Volume" in rules.resources
    assert "Chassis" in rules.resources
    assert len(rules.resources) == 2


def test_parse_invalid_json_syntax(tmp_path):
    """Проверка устойчивости парсера к битым JSON-файлам (JSONDecodeError)"""
    corrupted_file = tmp_path / "broken.json"
    corrupted_file.write_text("{ 'invalid_json': true ...", encoding="utf-8")

    parser = JsonSchemaParser()
    rules = parser.parse(str(corrupted_file))

    # Перехват ошибки сработал корректно, возвращены пустые правила
    assert len(rules.resources) == 0