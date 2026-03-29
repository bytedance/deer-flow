#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/frontend"
LOG_DIR="$REPO_ROOT/logs"
PID_FILE="$LOG_DIR/frontend-wsl.pid"
source "$REPO_ROOT/scripts/local-runtime-lib.sh"
mkdir -p "$LOG_DIR"

cd "$FRONTEND_DIR"
node -e "require('./node_modules/.pnpm/lightningcss@1.30.2/node_modules/lightningcss'); console.log('lightningcss:ok')"
node -e "require('./node_modules/.pnpm/unrs-resolver@1.11.1/node_modules/unrs-resolver'); console.log('unrs:ok')"

cd "$REPO_ROOT"
./stop-local-wsl.sh >/dev/null 2>&1 || true
pkill -f "nginx: master process.*nginx.local.conf" >/dev/null 2>&1 || true

./run-local-wsl.sh >"$LOG_DIR/card6-stack.log" 2>"$LOG_DIR/card6-stack.err.log"
DEERFLOW_LOG_DIR="$LOG_DIR" \
DEERFLOW_FRONTEND_PID_FILE="$(basename "$PID_FILE")" \
DEERFLOW_FRONTEND_STDOUT_LOG="card6-wsl-frontend-webpack.log" \
DEERFLOW_FRONTEND_STDERR_LOG="card6-wsl-frontend-webpack.err.log" \
python3 "$REPO_ROOT/scripts/start-frontend-wsl-daemon.py" >/dev/null
frontend_pid="$(cat "$PID_FILE")"

nginx -c "$REPO_ROOT/docker/nginx/nginx.local.conf" -p "$REPO_ROOT"

frontend_code="000"
route_code="000"
api_code="000"
frontend_pid_alive="0"
stable_count="0"

for _ in $(seq 1 45); do
  if kill -0 "$frontend_pid" >/dev/null 2>&1; then
    frontend_pid_alive="1"
  else
    frontend_pid_alive="0"
  fi

  frontend_code="$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3000/workspace/chats/new || true)"
  route_code="$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:2026/workspace/chats/new || true)"
  api_code="$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:2026/api/models || true)"
  stable_count="$(next_stable_health_count "$stable_count" "$frontend_code" "$route_code" "$api_code" "$frontend_pid_alive")"

  echo "probe frontend=$frontend_code route=$route_code api=$api_code pid_alive=$frontend_pid_alive stable=$stable_count"

  if [[ "$stable_count" -ge 3 ]]; then
    break
  fi

  sleep 2
done

echo "3000:$frontend_code"
echo "2026:$route_code"
echo "api:$api_code"
if [[ "$stable_count" -lt 3 ]]; then
  exit 1
fi
