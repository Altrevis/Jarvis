#!/usr/bin/env bash
# Launches MARK LV using the virtual environment setup.py created.
set -e
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
    echo "No .venv found — run 'python3 setup.py' first." >&2
    exit 1
fi

exec .venv/bin/python main.py "$@"
