#!/usr/bin/env sh
# Start the PS-16 backend on 127.0.0.1 (macOS / Linux).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  echo "No python3 found." >&2
  exit 1
fi
[ -f "$ROOT/.env" ] || echo "warning: no .env; copy .env.example and fill in keys" >&2
cd "$ROOT"
exec "$PY" -m app.main
