#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$PWD/.runtime/node-bin:$PATH"
if [[ ! -f .env ]]; then
 python3 - <<'PY'
import secrets
from pathlib import Path
p=Path('.env');p.write_text('CUSTOMS_API_KEY='+secrets.token_urlsafe(36)+'\nAPI_URL=http://127.0.0.1:8000\n');p.chmod(0o600)
PY
fi
set -a
source .env
set +a
backend/.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
trap 'kill "$BACKEND_PID" 2>/dev/null || true' EXIT INT TERM
cd frontend
npm run dev
