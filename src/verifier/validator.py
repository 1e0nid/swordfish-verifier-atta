from typing import Any, Dict, List
import logging
from src.config import AppConfig
from src.models.rules import SpecificationRules, ResourceRule, FieldRule
from src.client.http_client import SwordfishHttpClient


logger = logging.getLogger("swordfish_validator")

def get_nested_value(data: Dict[str, Any], path: str) -> Any:
    parts = path.split(".")
    current = data

    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return KeyError
        
    return current


class SwordfishValidator:
    def __init__(self, config: AppConfig, rules: SpecificationRules, client: SwordfishHttpClient):
        self.config = config
        self.rules = rules
        self.client = client
        self.results: List[Dict[str, Any]] = []

    async def validate_all(self) -> List[Dict[str, Any]]:
        self.results = []
        resources_to_check = self.rules.resources

        active_filter = self.config.validator.resources_filter
        if active_filter:
            resources_to_check = {
                k: v for k, v in resources_to_check.items() if k in active_filter
            }

        logger.info(f"Запуск валидации для ресурсов: {list(resources_to_check.keys())}")

        for res_name, res_rule in resources_to_check.items():
            await self._validate_resources(res_rule)
        
        return self.results

    async def _validate_resources(self, res_rule: ResourceRule):
        response_packet = await self.client.send_request("GET", res_rule.endpoint_path)

        if not response_packet["success"]:
            self._add_result(
                resource=res_rule.resource_name,
                endpoint=res_rule.endpoint_path,
                check_type="ENDPOINT_AVAILABILITY",
                status="FAIL",
                message=f"Эндпоинт недоступен. Код ответа: {response_packet['status_code']}. Ошибка: {response_packet['error_message']}"
            )
            return

        self._add_result(
            resource=res_rule.resource_name,
            endpoint=res_rule.endpoint_path,
            check_type="ENDPOINT_AVAILABILITY",
            status="PASS",
            message=f"Эндпоинт успешно вернул HTTP {response_packet['status_code']}"
        )

        actual_json = response_packet["data"]

        for field_path, field_rule in res_rule.expected_fields.items():
            value = get_nested_value(actual_json, field_path)

            if value is KeyError:
                if field_rule.is_required:
                    self._add_result(
                        resource=res_rule.resource_name,
                        endpoint=res_rule.endpoint_path,
                        check_type="FIELD_REQUIRED",
                        status="FAIL",
                        message=f"Отсутствует обязательное поле '{field_path}'"
                    )
                else:
                    pass
                continue

            if value is None:
                if field_rule.is_required:
                    self._add_result(
                        resource=res_rule.resource_name,
                        endpoint=res_rule.endpoint_path,
                        check_type="FIELD_TYPE",
                        status="FAIL",
                        message=f"Ожидалось поле '{field_path}' типа {field_rule.field_type}, получен null"
                    )
                continue

            if not self._check_type(value, field_rule.field_type):
                self._add_result(
                    resource=res_rule.resource_name,
                    endpoint=res_rule.endpoint_path,
                    check_type="FIELD_TYPE",
                    status="FAIL",
                    message=f"Неверный тип поля '{field_path}'. Ожидался {field_rule.field_type}, получен {type(value).__name__}"
                )
                continue

            if field_rule.enum_values and value not in field_rule.enum_values:
                self._add_result(
                    resource=res_rule.resource_name,
                    endpoint=res_rule.endpoint_path,
                    check_type="FIELD_ENUM",
                    status="FAIL",
                    message=f"Значение '{value}' поля '{field_path}' отсутствует в списке допустимых ENUM: {field_rule.enum_values}"
                )
                continue

            self._add_result(
                resource=res_rule.resource_name,
                endpoint=res_rule.endpoint_path,
                check_type=f"FIELD_VALIDATION [{field_path}]",
                status="PASS",
                message=f"Поле корректно: тип {field_rule.field_type}"
            )

    def _check_type(self, value: Any, expected_type: str) -> bool:
        """
        Сопоставляет строковое описание типа из спецификации с нативными типами Python.
        """
        type_mapping = {
            "integer": int,
            "string": str,
            "boolean": bool,
            "number": (int, float),
            "array": list,
            "object": dict
        }
        target_type = type_mapping.get(expected_type)
        if target_type:
            return isinstance(value, target_type)
        return False

    def _add_result(self, resource: str, endpoint: str, check_type: str, status: str, message: str):
        """
        Формирует атомарную запись в лог результатов верификации.
        """
        self.results.append({
            "resource": resource,
            "endpoint": endpoint,
            "check_type": check_type,
            "status": status,
            "message": message
        })