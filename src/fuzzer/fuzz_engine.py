import logging
from typing import Any, Dict, List
from src.config import AppConfig
from src.models.rules import SpecificationRules, ResourceRule
from src.client.http_client import SwordfishHttpClient

logger = logging.getLogger("swordfish_fuzzer")

class SwordfishFuzzer:
    def __init__(self, config: AppConfig, rules: SpecificationRules, client: SwordfishHttpClient):
        self.config = config
        self.rules = rules
        self.client = client
        self.results: List[Dict[str, Any]] = []

    async def run_fuzzing(self) -> List[Dict[str, Any]]:
        self.results = []
        resources_to_fuzz = self.rules.resources

        active_filter = self.config.validator.resources_filter
        if active_filter:
            resources_to_fuzz = {k: v for k, v in resources_to_fuzz.items() if k in active_filter}

        logger.info(f"Запуск фаззинг-тестов для ресурсов: {list(resources_to_fuzz.keys())}")

        for res_name, res_rule in resources_to_fuzz.items():
            await self._fuzz_http_methods(res_rule)
            await self._fuzz_payload_mutations(res_rule)

        return self.results

    async def _fuzz_http_methods(self, res_rule: ResourceRule):
        all_methods = ["POST", "PUT", "DELETE", "PATCH"]
        forbidden_methods = [m for m in all_methods if m not in res_rule.allowed_methods]

        for method in forbidden_methods:
            response_packet = await self.client.send_request(
                method=method, 
                endpoint=res_rule.endpoint_path, 
                json_data={"fuzz": "data"}
            )
            
            if response_packet["status_code"] == 500:
                self._add_result(
                    resource=res_rule.resource_name,
                    endpoint=res_rule.endpoint_path,
                    method=method,
                    check_type="FUZZING_HTTP_METHOD",
                    status="FAIL",
                    message=f"Сервер вернул код 500 Internal Server Error на запрещенный метод {method}."
                )
            else:
                self._add_result(
                    resource=res_rule.resource_name,
                    endpoint=res_rule.endpoint_path,
                    method=method,
                    check_type="FUZZING_HTTP_METHOD",
                    status="PASS",
                    message=f"Сервер корректно обработал запрещенный метод {method} (Код: {response_packet['status_code']})."
                )

    async def _fuzz_payload_mutations(self, res_rule: ResourceRule):
        target_method = "POST" if "POST" in res_rule.allowed_methods else "PUT"
        
        # Сценарий A: Передача невалидной структуры (массив вместо объекта/словаря)
        bad_json_structure: List[Any] = [{"malformed": "json_structure_test"}]
        response = await self.client.send_request(target_method, res_rule.endpoint_path, json_data=bad_json_structure)
        self._evaluate_fuzz_response(res_rule, target_method, "FUZZING_MALFORMED_STRUCTURE", response, "Передача массива вместо JSON-объекта")

        for field_name, field_rule in res_rule.expected_fields.items():
            if "." in field_name:
                continue

            # Сценарий B: Нарушение типов данных (передаем инт вместо строки или наоборот)
            mutated_payload = {}
            if field_rule.field_type in ["integer", "number"]:
                mutated_payload[field_name] = "not_a_number_string"
            else:
                mutated_payload[field_name] = 123456789
                
            response = await self.client.send_request(target_method, res_rule.endpoint_path, json_data=mutated_payload)
            self._evaluate_fuzz_response(res_rule, target_method, f"FUZZING_INVALID_TYPE [{field_name}]", response, f"Передано невалидное значение типа для поля {field_name}")

            # Сценарий C: Выход за числовые границы (если это числовое поле, передаем отрицательное значение)
            if field_rule.field_type in ["integer", "number"]:
                boundary_payload = {field_name: -1}
                response = await self.client.send_request(target_method, res_rule.endpoint_path, json_data=boundary_payload)
                self._evaluate_fuzz_response(res_rule, target_method, f"FUZZING_BOUNDARY_VALUE [{field_name}]", response, f"Передано отрицательное значение (-1) в числовое поле {field_name}")

            # Сценарий D: Нарушение специфичных форматов (UUID / ISO 8601 Date)
            if field_rule.data_format:
                format_payload = {}
                if field_rule.data_format == "uri-reference":
                    format_payload[field_name] = "invalid_uri_##_invalid"
                elif "date" in field_rule.data_format:
                    format_payload[field_name] = "2026-13-40"
                else:
                    format_payload[field_name] = "abc-123-not-valid-format"

                response = await self.client.send_request(target_method, res_rule.endpoint_path, json_data=format_payload)
                self._evaluate_fuzz_response(res_rule, target_method, f"FUZZING_BAD_FORMAT [{field_name}]", response, f"Передано нарушение формата {field_rule.data_format} в поле {field_name}")

    def _evaluate_fuzz_response(self, res_rule: ResourceRule, method: str, check_type: str, response: Dict[str, Any], scenario_desc: str):
        """
        Анализирует ответ эмулятора на фаззинг-запрос. Если сервер упал в 500 — тест провален.
        """
        if response["status_code"] == 500:
            self._add_result(
                resource=res_rule.resource_name,
                endpoint=res_rule.endpoint_path,
                method=method,
                check_type=check_type,
                status="FAIL",
                message=f"Критический дефект: {scenario_desc}. Сервер упал с ошибкой HTTP 500 Internal Server Error."
            )
        else:
            self._add_result(
                resource=res_rule.resource_name,
                endpoint=res_rule.endpoint_path,
                method=method,
                check_type=check_type,
                status="PASS",
                message=f"Тест пройден успешно: {scenario_desc}. Сервер отклонил или безопасно обработал запрос (Код: {response['status_code']})."
            )

    def _add_result(self, resource: str, endpoint: str, method: str, check_type: str, status: str, message: str):
        self.results.append({
            "resource": resource,
            "endpoint": endpoint,
            "method": method,
            "check_type": check_type,
            "status": status,
            "message": message
        })