#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$PWD/.runtime/node-bin:$PATH"
for port in 3000 8000; do
 if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Порт $port уже занят. Остановите предыдущий запуск CaspiFlow и повторите."
  exit 1
 fi
done
if [[ ! -f .env ]]; then
 python3 - <<'PY'
import secrets
from pathlib import Path
p=Path('.env')
p.write_text('CUSTOMS_API_KEY='+secrets.token_urlsafe(36)+'\nAPI_URL=http://127.0.0.1:8000\n')
p.chmod(0o600)
PY
fi
set -a
source .env
set +a
npm --prefix frontend run build
CASPIFLOW_API_PID=''
CASPIFLOW_UI_PID=''
cleanup() {
 [[ -z "$CASPIFLOW_UI_PID" ]] || kill "$CASPIFLOW_UI_PID" 2>/dev/null || true
 [[ -z "$CASPIFLOW_API_PID" ]] || kill "$CASPIFLOW_API_PID" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT TERM
backend/.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 &
CASPIFLOW_API_PID=$!
CASPIFLOW_API_READY=0
for attempt in {1..30}; do
 if curl --silent --fail http://127.0.0.1:8000/health >/dev/null; then
  CASPIFLOW_API_READY=1
  break
 fi
 kill -0 "$CASPIFLOW_API_PID" 2>/dev/null || { echo 'FastAPI не запустился'; exit 1; }
 sleep 1
done
[[ "$CASPIFLOW_API_READY" == 1 ]] || { echo 'FastAPI не готов за 30 секунд'; exit 1; }
echo 'CaspiFlow demo: http://127.0.0.1:3000 — Ctrl+C для остановки'
cd frontend
node node_modules/next/dist/bin/next start --hostname 127.0.0.1 &
CASPIFLOW_UI_PID=$!
wait "$CASPIFLOW_UI_PID"
