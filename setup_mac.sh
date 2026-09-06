#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python tools/generate_template.py
python tools/self_test.py

echo
echo "Lantern Sky setup complete."
echo "Run with: ./run_mac.sh"
