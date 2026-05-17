#!/usr/bin/env bash
# DeerFlow — Railway entrypoint
# Starts langgraph dev server (port 2024) and the gateway (port $PORT / 8001).
# Both processes are supervised; if either exits, the container exits.

set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────────────
GATEWAY_PORT="${PORT:-8001}"
LANGGRAPH_PORT=2024
BACKEND_DIR="/app/backend"

# config.yaml is baked into the image at build time (see Dockerfile.railway).

# ── Start langgraph ───────────────────────────────────────────────────────────
echo "[entrypoint] Starting langgraph on port ${LANGGRAPH_PORT} …"
cd "${BACKEND_DIR}"
.venv/bin/langgraph dev \
  --host 0.0.0.0 \
  --port "${LANGGRAPH_PORT}" \
  --no-browser \
  &
LANGGRAPH_PID=$!

# ── Wait for langgraph to be ready ───────────────────────────────────────────
echo "[entrypoint] Waiting for langgraph to be ready …"
for i in $(seq 1 30); do
  if curl -sf "http://localhost:${LANGGRAPH_PORT}/ok" > /dev/null 2>&1; then
    echo "[entrypoint] langgraph is ready."
    break
  fi
  sleep 2
done

# ── Start gateway ─────────────────────────────────────────────────────────────
echo "[entrypoint] Starting gateway on port ${GATEWAY_PORT} …"
.venv/bin/python -m uvicorn app.gateway.app:app \
  --host 0.0.0.0 \
  --port "${GATEWAY_PORT}" \
  &
GATEWAY_PID=$!

# ── Supervisor loop ───────────────────────────────────────────────────────────
echo "[entrypoint] Both services started (langgraph PID=${LANGGRAPH_PID}, gateway PID=${GATEWAY_PID})."

wait_any() {
  while kill -0 "${LANGGRAPH_PID}" 2>/dev/null && kill -0 "${GATEWAY_PID}" 2>/dev/null; do
    sleep 5
  done
}

wait_any

echo "[entrypoint] A service exited — shutting down."
kill "${LANGGRAPH_PID}" "${GATEWAY_PID}" 2>/dev/null || true
exit 1
