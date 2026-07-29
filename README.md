# swordfish-verifier-atta

Верификатор атак/эксплойтов для сервиса **Swordfish**, написанный на Python

## Возможности

- **API/сервер**: FastAPI, Starlette, Uvicorn
- **Работа с бинарями и эксплуатация**: `pwntools`, `capstone`, `unicorn`, `ROPGadget`, `pyelftools` — похоже, верификатор сам выполняет/анализирует переданный PoC против целевого бинарника
- **Очереди и кэш**: `aio-pika` / `pika` (RabbitMQ), `redis`
- **Хранилище отчётов**: `boto3` (S3-совместимое хранилище) — согласуется с каталогом `reports/`
- **Уведомления**: `python-telegram-bot`
- **Удалённый доступ**: `paramiko` (SSH)
- **Тесты**: `pytest`, `pytest-asyncio`, `pytest-cov`, `pytest-mock`

## Структура проекта

```
.
├── .github/workflows/   # CI-пайплайны (GitHub Actions)
├── config/              # Конфигурация верификатора
├── reports/             # Отчёты/результаты проверок
├── src/                 # Исходный код (точка входа — src/main.py)
├── tests/                # Тесты (pytest)
├── pytest.ini
├── requirements.txt
└── run.sh               # Скрипт запуска
```

## Требования

- Python 3.10+ (рекомендуется — не зафиксировано явно, уточни при необходимости)
- Доступ к RabbitMQ и Redis, если сервис их использует в текущей конфигурации
- Для функций `pwntools`/`capstone`/`unicorn`/`ROPGadget` могут понадобиться системные пакеты для работы с бинарями (`binutils`, отладчики и т.п.)

## Установка

```bash
git clone https://github.com/1e0nid/swordfish-verifier-atta.git
cd swordfish-verifier-atta
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Запуск

```bash
./run.sh
```

Скрипт выставляет `PYTHONPATH` в корень проекта и запускает `src/main.py`.

## Конфигурация

Настройки читаются из каталога `config/` (формат и конкретные параметры — уточни, чтобы дополнить этот раздел точными переменными окружения/файлами).

## Тесты

```bash
pytest
```

`pytest.ini` уже настраивает `pythonpath = .`, поэтому тесты можно запускать из корня без дополнительной настройки окружения.

## Лицензия

Не указана в репозитории — добавь файл `LICENSE`, если планируешь делать проект публичным.
