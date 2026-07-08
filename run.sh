#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

cd "$SCRIPT_DIR"

export PYTHONPATH="$SCRIPT_DIR"

echo "=== Запуск верификатора API Swordfish ==="
python3 src/main.py