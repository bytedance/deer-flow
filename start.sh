#!/bin/bash
set -e
echo "[start] DeerFlow 2.0 booting..."

DEER_FLOW_HOME="${DEER_FLOW_HOME:-/persist/.deer-flow}"
mkdir -p "$DEER_FLOW_HOME"/{logs,skills}

export CI=true
export DEER_FLOW_HOME
export DEER_FLOW_CONFIG_PATH="${DEER_FLOW_CONFIG_PATH:-/app/config.yaml}"
export PYTHONPATH="/app/backend:$PYTHONPATH"
export NODE_ENV=production

# ── Docker daemon (DinD) ───────────────────────────────────────────────────
echo "[start] Docker daemon..."
dockerd --iptables=false --storage-driver=vfs > "$DEER_FLOW_HOME/logs/dockerd.log" 2>&1 &
for i in $(seq 1 20); do
  sleep 2
  docker info >/dev/null 2>&1 && echo "[start] Docker ready" && break
  [ $i -eq 20 ] && echo "[start] Docker timeout" && tail -10 "$DEER_FLOW_HOME/logs/dockerd.log"
done

# ── Pre-pull sandbox image ─────────────────────────────────────────────────
[ -n "$AIO_SANDBOX_IMAGE" ] && docker pull "$AIO_SANDBOX_IMAGE" 2>/dev/null || true

# ── LangGraph Backend :2024 ─────────────────────────────────────────────────
echo "[start] LangGraph :2024..."
cd /app/backend
PYTHONPATH=/app/backend:$PYTHONPATH \
  uv run langgraph dev --no-browser --allow-blocking --no-reload \
    --host 0.0.0.0 --port 2024 \
    > "$DEER_FLOW_HOME/logs/langgraph.log" 2>&1 &
sleep 8

# ── Gateway API :8001 ───────────────────────────────────────────────────────
echo "[start] Gateway :8001..."
cd /app/backend
PYTHONPATH=/app/backend:$PYTHONPATH \
  uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001 \
    > "$DEER_FLOW_HOME/logs/gateway.log" 2>&1 &
sleep 5

# ── Frontend :3000 ─────────────────────────────────────────────────────────
echo "[start] Frontend :3000..."
cd /app/frontend
PORT=3000 npm start > "$DEER_FLOW_HOME/logs/frontend.log" 2>&1 &
sleep 10

# ── Health checks ───────────────────────────────────────────────────────────
echo "[start] Health checks..."
curl -sf http://localhost:8001/health >/dev/null 2>&1 && echo "[start] ✓ Gateway" || echo "[start] ✗ Gateway"
curl -sf http://localhost:3000 >/dev/null 2>&1 && echo "[start] ✓ Frontend" || echo "[start] ✗ Frontend"
curl -sf http://localhost:2024/health >/dev/null 2>&1 && echo "[start] ✓ LangGraph" || echo "[start] ✗ LangGraph"

echo "[start] All services up. Entering wait..."
wait
