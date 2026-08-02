#!/usr/bin/env bash
# DeerFlow — Railway entrypoint
# Starts the gateway (port $PORT / 8001) as the container's only process.
#
# There is deliberately NO LangGraph server here. The gateway implements the
# LangGraph Platform runs API in-process (app/gateway/routers/thread_runs.py),
# which is what upstream's own production compose does — docker-compose.yaml
# runs nginx + frontend + gateway and no LangGraph server at all, with
# DEER_FLOW_CHANNELS_LANGGRAPH_URL pointed back at the gateway.
#
# This used to run `langgraph dev` alongside the gateway. That is the
# DEVELOPMENT server: it stamps api_variant=local_dev, watches the filesystem
# for hot reload, and holds threads and runs in memory via
# langgraph-runtime-inmem. Nothing AlphaFRS calls was ever served by it — every
# endpoint in alphaFRS backend/deerflow.py hits the gateway's /api/threads
# routes — so it was pure overhead and a misleading log signature.
#
# Durability now comes from Postgres (config.yaml: database.backend=postgres,
# run_events.backend=db), not from a LangGraph server. If you find yourself
# wanting to add one back, note that the supported production LangGraph servers
# are LangSmith Cloud (Plus, $39/seat) and Standalone Server (Enterprise
# licence) — neither is needed for this architecture.

set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────────────
GATEWAY_PORT="${PORT:-8001}"
BACKEND_DIR="/app/backend"

# config.yaml is baked into the image at build time (see Dockerfile.railway).
# DATABASE_URL is injected by Railway from the Postgres service and expanded by
# config.yaml's native $ENV_VAR support. Fail fast rather than let the gateway
# start against an empty postgres_url and surface as a confusing runtime error.
if [ -z "${DATABASE_URL:-}" ]; then
  echo "[entrypoint] FATAL: DATABASE_URL is unset."
  echo "[entrypoint] config.yaml sets database.backend=postgres and reads \$DATABASE_URL."
  echo "[entrypoint] Attach the Railway Postgres service to this environment."
  exit 1
fi

cd "${BACKEND_DIR}"

# Pin the config path. Without this it still resolves, but only by falling
# through to the "legacy monorepo" candidate list in app_config.py, which finds
# /app/config.yaml two levels up from cwd. Being explicit means a missing or
# misplaced config fails at startup with a clear error instead of silently
# resolving somewhere else after a layout change.
export DEER_FLOW_CONFIG_PATH="/app/config.yaml"

# The IM channels service talks to the LangGraph-compatible API. That is us.
export DEER_FLOW_CHANNELS_LANGGRAPH_URL="http://localhost:${GATEWAY_PORT}/api"
export DEER_FLOW_CHANNELS_GATEWAY_URL="http://localhost:${GATEWAY_PORT}"

# ── Create the schema once, before any worker starts ─────────────────────────
# Every worker runs create_all() and the checkpointer/store setup() at startup.
# Against a fresh database they race, and the loser dies on
#   UniqueViolationError: duplicate key ... "pg_type_typname_nsp_index"
#   ERROR: Application startup failed. Exiting.
# because CREATE TABLE is not atomic against a concurrent identical CREATE.
# uvicorn respawns the dead worker and the retry succeeds, so it converges — but
# it is a crash on every deploy against a new database, and converging by
# restart is not something to leave in the boot path.
#
# Doing it here, in one process before uvicorn forks, means the workers always
# find the schema already present. Idempotent, so it costs a no-op round trip
# on every subsequent boot.
echo "[entrypoint] Ensuring database schema …"
.venv/bin/python - <<'PY'
import asyncio

from deerflow.config.app_config import get_app_config
from deerflow.persistence.engine import close_engine, init_engine_from_config
from deerflow.runtime.checkpointer.async_provider import make_checkpointer
from deerflow.runtime.store.async_provider import make_store


async def main() -> None:
    config = get_app_config()
    # create_all() for the application tables (runs, threads_meta, feedback,
    # run_events).
    await init_engine_from_config(config.database)
    # Entering each context manager runs its own setup() — the LangGraph
    # checkpoint tables and the store tables respectively.
    async with make_checkpointer(config):
        pass
    async with make_store(config):
        pass
    await close_engine()


asyncio.run(main())
print("[entrypoint] Schema ready.")
PY

# ── Start gateway ─────────────────────────────────────────────────────────────
# exec: the gateway becomes PID 1 so Railway's stop/restart signals reach uvicorn
# directly instead of a shell that would have to forward them.
#
# --workers 2 is safe only because run state is shared through Postgres. Do not
# raise workers (or railway.toml's numReplicas) while database.backend is
# sqlite or memory — each worker would keep its own runs and status lookups
# would 404 depending on which one answered.
echo "[entrypoint] Starting gateway on port ${GATEWAY_PORT} …"
exec .venv/bin/python -m uvicorn app.gateway.app:app \
  --host 0.0.0.0 \
  --port "${GATEWAY_PORT}" \
  --workers 2
