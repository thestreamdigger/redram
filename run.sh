#!/bin/bash
# RedRAM - Run Script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CD_DEVICE="${CD_DEVICE:-/dev/sr0}"

cd "$SCRIPT_DIR"

if [ ! -f "src/main.py" ]; then
    echo -e "\033[0;31m✗\033[0m src/main.py not found"
    exit 1
fi

# Activate venv
if [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
fi

export CD_DEVICE

exec python3 src/main.py "$@"
