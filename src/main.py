import asyncio
import sys
import logging
from src.config import load_config
from src.parser.json_parser import JsonSchemaParser
from src.client.http_client import SwordfishHttpClient
from src.verifier.validator import SwordfishValidator
from src.fuzzer.fuzz_engine import SwordfishFuzzer
from src.reporter.json_reporter import SwordfishJsonReporter

# Настройка глобального логирования в консоль
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("swordfish_main")

async def main():
    logger.info("Инициализация системы верификации Swordfish API...")
    
    try:
        # 1. Загрузка конфигурационного файла
        config = load_config("config/config.yml")
        logger.info("Конфигурация успешно применена.")

        # 2. Парсинг спецификации (из папки со схемами)
        parser = JsonSchemaParser()
        logger.info(f"Запуск разбора спецификации из: {config.storage.specification_path}")
        rules = parser.parse(config.storage.specification_path)
        logger.info("Спецификация успешно обработана.")

        # 3. Запуск сетевой сессии и выполнения тестов
        async with SwordfishHttpClient(config.emulator) as client:
            
            # Позитивное тестирование (Валидация схемы контракта)
            validator = SwordfishValidator(config, rules, client)
            logger.info("Запуск позитивного сценария проверки...")
            val_results = await validator.validate_all()
            
            # Негативное тестирование (Фаззинг)
            fuzzer = SwordfishFuzzer(config, rules, client)
            logger.info("Запуск негативного сценария (фаззинга)...")
            fuzz_results = await fuzzer.run_fuzzing()

        # 4. Формирование и сохранение результатов
        reporter = SwordfishJsonReporter(config)
        report_path = reporter.generate_report(val_results, fuzz_results)
        logger.info(f"Тестирование успешно завершено. Отчет сохранен по пути: {report_path}")

    except Exception as e:
        logger.critical(f"Критический сбой при выполнении верификатора: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    # Запуск асинхронного цикла событий
    asyncio.run(main())