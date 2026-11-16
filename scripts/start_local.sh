#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mode=${1:-MOCK}
if [[ "$mode" != MOCK && "$mode" != LIVE ]]; then
  printf 'Chế độ phải là MOCK hoặc LIVE.\n' >&2
  exit 1
fi
for tool in uv node npm; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf 'Thiếu %s trong PATH; cài đặt rồi chạy lại.\n' "$tool" >&2
    exit 1
  fi
done
uv sync --frozen
if ! (cd frontend && node --input-type=module -e 'await Promise.all([import("vite"),import("react"),import("lightweight-charts")])' >/dev/null 2>&1); then
  npm --prefix frontend ci --no-audit --no-fund
fi
exec uv run --frozen python scripts/local_start.py --mode "$mode"
