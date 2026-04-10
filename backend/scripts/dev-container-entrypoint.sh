#!/bin/sh
set -eu

SERVICE="${1:-}"
LOG_PREFIX="[dev-entrypoint:${SERVICE:-unknown}]"

cd /app/backend

require_file() {
  path="$1"
  if [ ! -f "$path" ]; then
    echo "${LOG_PREFIX} required file is missing or not a regular file: $path"
    exit 1
  fi
}

repair_venv() {
  echo "${LOG_PREFIX} repairing /app/backend/.venv with 'uv sync --frozen --reinstall'"
  mkdir -p .venv
  (
    cd .venv
    find . -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  )
  uv sync --frozen --reinstall
}

ensure_venv_cli() {
  cli="$1"
  shift

  if [ ! -x .venv/bin/python ] || [ ! -x ".venv/bin/${cli}" ]; then
    echo "${LOG_PREFIX} missing virtualenv interpreter or ${cli}; rebuilding environment"
    repair_venv
    return
  fi

  if ! uv run "${cli}" "$@" >/dev/null 2>&1; then
    echo "${LOG_PREFIX} existing virtualenv cannot run '${cli} $*'; rebuilding environment"
    repair_venv
  fi
}

ensure_python_imports() {
  probe_code="$1"

  if ! PYTHONPATH=. uv run python -c "$probe_code" >/dev/null 2>&1; then
    echo "${LOG_PREFIX} existing virtualenv failed Python import probe; rebuilding environment"
    repair_venv
  fi
}

start_gateway() {
  ensure_venv_cli uvicorn --version
  ensure_python_imports "import annotated_doc; import fastapi; import app.gateway.app"
  export PYTHONPATH=.
  exec uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001
}

start_langgraph() {
  ensure_venv_cli langgraph --help
  exec uv run langgraph dev --no-browser --allow-blocking --host 0.0.0.0 --port 2024 --n-jobs-per-worker 10
}

require_file /app/config.yaml
require_file /app/extensions_config.json

case "$SERVICE" in
  gateway)
    start_gateway
    ;;
  langgraph)
    start_langgraph
    ;;
  *)
    echo "Usage: $0 {gateway|langgraph}"
    exit 64
    ;;
esac
