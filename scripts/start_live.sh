#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v uv >/dev/null 2>&1; then
  printf 'Thiếu uv trong PATH; cài đặt rồi chạy lại.\n' >&2
  exit 1
fi
uv sync --frozen
uv run --frozen pytest -q backend/tests/test_connectivity.py backend/tests/test_secure_dnse.py backend/tests/test_live_local.py
exec bash scripts/start_local.sh LIVE
