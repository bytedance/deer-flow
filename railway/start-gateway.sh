#!/bin/sh
set -eu

export DEER_FLOW_HOME="${DEER_FLOW_HOME:-${RAILWAY_VOLUME_MOUNT_PATH:-/data/deerflow}}"
export DEER_FLOW_RUNTIME_DIR="${DEER_FLOW_RUNTIME_DIR:-/tmp/deerflow-runtime}"
export DEER_FLOW_CONFIG_PATH="${DEER_FLOW_CONFIG_PATH:-$DEER_FLOW_RUNTIME_DIR/config.yaml}"
export DEER_FLOW_EXTENSIONS_CONFIG_PATH="${DEER_FLOW_EXTENSIONS_CONFIG_PATH:-$DEER_FLOW_HOME/extensions_config.json}"
export CODEX_AUTH_PATH="${CODEX_AUTH_PATH:-$DEER_FLOW_RUNTIME_DIR/codex-auth.json}"
export GATEWAY_PORT="${GATEWAY_PORT:-${PORT:-8001}}"

mkdir -p "$DEER_FLOW_HOME" "$DEER_FLOW_RUNTIME_DIR"

cd /app/backend
PYTHONPATH=. uv run python -m app.gateway.railway_runtime

exec sh -c "cd /app/backend && PYTHONPATH=. uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port ${GATEWAY_PORT} --workers ${GATEWAY_WORKERS:-1}"
