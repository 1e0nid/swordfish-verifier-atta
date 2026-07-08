import os
import json
from typing import Dict, Any
from src.parser.base import BaseParser
from src.models.rules import SpecificationRules, ResourceRule, FieldRule


class JsonSchemaParser(BaseParser):

    def parse(self, target_path: str) -> SpecificationRules:
        spec_rules = SpecificationRules(
            specification_version="Swordfish (JSON Schemas)"
        )

        if os.path.isfile(target_path):
            self._process_file(target_path, spec_rules)
        elif os.path.isdir(target_path):
            for file_name in os.listdir(target_path):
                if file_name.endswith(".json"):
                    full_path = os.path.join(target_path, file_name)
                    self._process_file(full_path, spec_rules)

        return spec_rules
            

    def _process_file(self, file_path: str, spec_rules: SpecificationRules):
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                schema = json.load(f)
            except json.JSONDecodeError:
                return

        definitions = schema.get("definitions", {})

        for res_name, res_def in definitions.items():
            if res_def.get("type") != "object" or "properties" not in res_def:
                continue

            endpoint_path = f"/redfish/v1/{res_name}"

            required_fileds = res_def.get("required", [])
            properties = res_def.get("properties", {})

            expected_fields: Dict[str, FieldRule] = {}

            for prom_name, prop_def in properties.items():
                raw_type = prop_def.get("type", "string")
                field_type = raw_type[0] if isinstance(raw_type, list) else raw_type

                if "type" not in prop_def and "$ref" in prop_def:
                    field_type = "object"

                field_rule = FieldRule(
                    field_type=str(field_type),
                    is_required=(prom_name in required_fileds),
                    enum_values=prop_def.get("enum"),
                    min_value=prop_def.get("minimum")
                )

                if "format" in prop_def:
                    field_rule.data_format = prop_def["format"]

                expected_fields[prom_name] = field_rule

            spec_rules.resources[res_name] = ResourceRule(
                resource_name=res_name,
                endpoint_path=endpoint_path,
                allowed_methods=["GET"],
                expected_fields=expected_fields
            )



