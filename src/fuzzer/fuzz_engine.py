import logging
from typing import Any, Dict, List
from src.config import AppConfig
from src.models.rules import SpecificationRules, ResourceRule
from src.client.http_client import SwordfishHttpClient

logger = logging.getLogger("swordfish_fuzzer")

class SwordfishFuzzer:
    """
    Модуль фаззинга, адаптированный под обработку любых обнаруженных урлов.
    """
    def __init__(self, config: AppConfig, rules: SpecificationRules, client: SwordfishHttpClient):
        self.config = config
        self.rules = rules
        self.client = client
        self.results: List[Dict[str, Any]] = []

    def _find_res_rule(self, res_name: str):
        if res_name in self.rules.resources:
            return self.rules.resources[res_name]
        for key, rule in self.rules.resources.items():
            if key.lower() in res_name.lower() or res_name.lower() in key.lower():
                return rule
        return None

    async def run_fuzzing(self, discovered_endpoints: Dict[str, List[str]]) -> List[Dict[str, Any]]:
        self.results = []

        for res_name, urls in discovered_endpoints.items():
            if self.config.validator.resources_filter and res_name not in self.config.validator.resources_filter:
                continue
                
            res_rule = self._find_res_rule(res_name)
            
            for url in urls:
                if res_rule:
                    await self._fuzz_http_methods(res_rule, url)
                    await self._fuzz_payload_mutations(res_rule, url)
                else:
                    # Если схемы нет, мы все равно фаззим методы (базовая уязвимость на 405 Method Not Allowed)
                    fake_rule = ResourceRule(resource_name=res_name, endpoint_path=url, allowed_methods=["GET"])
                    await self._fuzz_http_methods(fake_rule, url)

        return self.results

    async def _fuzz_http_methods(self, res_rule: ResourceRule, url: str):
        all_methods = ["POST", "PUT", "DELETE", "PATCH"]
        forbidden_methods = [m for m in all_methods if m not in res_rule.allowed_methods]

        for method in forbidden_methods:
            response_packet = await self.client.send_request(method, url, json_data={"fuzz": "test"})
            
            if response_packet["status_code"] == 500:
                self._add_result(
                    resource=res_rule.resource_name,
                    endpoint=url,
                    method=method,
                    check_type="FUZZING_HTTP_METHOD",
                    status="FAIL",
                    message=f"Сервер упал в HTTP 500 при отправке запрещенного метода {method}."
                )
            else:
                self._add_result(
                    resource=res_rule.resource_name,
                    endpoint=url,
                    method=method,
                    check_type="FUZZING_HTTP_METHOD",
                    status="PASS",
                    message=f"Сервер отклонил метод {method} (Код: {response_packet['status_code']})."
                )

    async def _fuzz_payload_mutations(self, res_rule: ResourceRule, url: str):
        target_method = "PATCH" if "PATCH" in res_rule.allowed_methods else "POST"
        
        bad_json = [{"malformed": "structure"}]
        response = await self.client.send_request(target_method, url, json_data=bad_json) # type: ignore
        self._evaluate_fuzz_response(res_rule, url, target_method, "FUZZING_MALFORMED_JSON", response, "Передача массива вместо объекта")

        for field_name, field_rule in res_rule.expected_fields.items():
            if "." in field_name:
                continue

            mutated_payload = {}
            if field_rule.field_type in ["integer", "number"]:
                mutated_payload[field_name] = "not_a_number"
            else:
                mutated_payload[field_name] = 99999
                
            response = await self.client.send_request(target_method, url, json_data=mutated_payload)
            self._evaluate_fuzz_response(res_rule, url, target_method, f"FUZZING_TYPE_MISMATCH [{field_name}]", response, f"Подмена типа поля {field_name}")

    def _evaluate_fuzz_response(self, res_rule: ResourceRule, url: str, method: str, check_type: str, response: Dict[str, Any], scenario_desc: str):
        if response["status_code"] == 500:
            self._add_result(res_rule.resource_name, url, method, check_type, "FAIL", f"Сбой: {scenario_desc}. HTTP 500.")
        else:
            self._add_result(res_rule.resource_name, url, method, check_type, "PASS", f"Защита ОК: {scenario_desc}. Код {response['status_code']}.")

    def _add_result(self, resource: str, endpoint: str, method: str, check_type: str, status: str, message: str):
        self.results.append({
            "resource": resource,
            "endpoint": endpoint,
            "method": method,
            "check_type": check_type,
            "status": status,
            "message": message
        })