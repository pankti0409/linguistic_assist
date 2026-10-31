#!/usr/bin/env sh
# Start the PS-16 backend on 127.0.0.1 (macOS / Linux).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || { echo "No .venv found. See README: python3.10 -m venv .venv" >&2; exit 1; }
[ -f "$ROOT/.env" ] || echo "warning: no .env; copy .env.example and fill in keys" >&2
cd "$ROOT"
exec "$PY" -m app.main
