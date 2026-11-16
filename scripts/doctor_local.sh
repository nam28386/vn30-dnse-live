#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python scripts/doctor_local.py "$@"
elif command -v python3 >/dev/null 2>&1; then
  exec python3 scripts/doctor_local.py "$@"
else
  printf 'Thiếu Python 3.11+; cài Python và uv rồi chạy lại.\n' >&2
  exit 1
fi
