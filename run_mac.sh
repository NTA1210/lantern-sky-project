#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  ./setup_mac.sh
fi

source .venv/bin/activate

if [ ! -f print/lantern_template_balloon.png ] || [ ! -f print/lantern_template_round.png ] || [ ! -f print/lantern_template_rectangle.png ]; then
  python tools/generate_template.py
fi

python run.py
