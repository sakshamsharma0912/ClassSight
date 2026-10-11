#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -r requirements.txt
echo "ClassSight: http://127.0.0.1:5000"
echo "Register a teacher account; invite students from their profiles. Press Ctrl+C to stop."
exec .venv/bin/python app.py
