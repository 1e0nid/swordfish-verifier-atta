import os
import json
from datetime import datetime, timezone
from typing import List, Dict, Any
from src.config import AppConfig

class SwordfishJsonReporter:
    def __init__(self, config: AppConfig):
        self.config = config

    def generate_report(self, validation_results: List[Dict[str, Any]], fuzzing_results: List[Dict[str, Any]]) -> str:
        all_checks = validation_results + fuzzing_results
        
        total_checks = len(all_checks)
        pass_count = sum(1 for c in all_checks if c.get("status") == "PASS")
        fail_count = sum(1 for c in all_checks if c.get("status") == "FAIL")
        not_supported_count = sum(1 for c in all_checks if c.get("status") == "NOT_SUPPORTED")

        report_data = {
            "metadata": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "emulator_url": str(self.config.emulator.url),
                "specification_version": "Swordfish v1.2.9"
            },
            "summary": {
                "total_checks": total_checks,
                "pass_count": pass_count,
                "fail_count": fail_count,
                "not_supported_count": not_supported_count
            },
            "detailed_results": all_checks
        }

        output_dir = self.config.storage.output_path
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        file_name = f"swordfish_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        full_path = os.path.join(output_dir, file_name)

        with open(full_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=4, ensure_ascii=False)

        return full_path