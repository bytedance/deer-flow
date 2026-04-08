"""Gateway integration helpers for the built-in cron scheduler."""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from app.gateway.services import RunLaunchRequest, start_run_with_deps
from deerflow.runtime import CronJobPayload, CronSchedulerService

logger = logging.getLogger(__name__)


def _env_flag_preferred(*names: str) -> bool:
    """Return the boolean value of the first present environment variable."""
    for name in names:
        value = os.environ.get(name)
        if value is not None and value != "":
            return value.lower() in {"1", "true", "yes", "on"}
    return False


def _first_env_value(*names: str) -> str | None:
    """Return the first non-empty environment variable value."""
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def cron_scheduler_enabled() -> bool:
    """Whether the cron scheduler feature is enabled at all."""
    return _env_flag_preferred("DEERFLOW_CRON_SCHEDULER_ENABLED", "DEER_FLOW_CRON_SCHEDULER_ENABLED")


def cron_scheduler_is_leader() -> bool:
    """Whether this gateway process should own cron dispatch."""
    return _env_flag_preferred("DEERFLOW_CRON_SCHEDULER_LEADER", "DEER_FLOW_CRON_SCHEDULER_LEADER")


def cron_scheduler_poll_interval(default: float = 30.0) -> float:
    """Return the configured poll interval, clamped to positive values."""
    raw_value = _first_env_value("DEERFLOW_CRON_SCHEDULER_POLL_INTERVAL", "DEER_FLOW_CRON_SCHEDULER_POLL_INTERVAL")
    if raw_value is None:
        return default

    try:
        parsed = float(raw_value)
    except ValueError:
        logger.warning("Invalid cron scheduler poll interval %r, using default %.1fs", raw_value, default)
        return default
    return parsed if parsed > 0 else default


def build_cron_run_launcher(
    *,
    bridge: Any,
    run_mgr: Any,
    checkpointer: Any,
    store: Any,
):
    """Build the non-HTTP launcher used by cron dispatch and manual trigger."""

    async def _launch(thread_id: str, payload: CronJobPayload):
        strategy = "reject" if payload.multitask_strategy == "enqueue" else payload.multitask_strategy
        return await start_run_with_deps(
            RunLaunchRequest(
                assistant_id=payload.assistant_id,
                input=payload.input,
                metadata=payload.metadata,
                config=payload.config,
                context=payload.context,
                on_disconnect="continue",
                multitask_strategy=strategy,
            ),
            thread_id,
            bridge=bridge,
            run_mgr=run_mgr,
            checkpointer=checkpointer,
            store=store,
        )

    return _launch


def build_request_cron_scheduler(request: Request) -> CronSchedulerService:
    """Return the running scheduler service or build a request-scoped manual-trigger helper."""
    scheduler = getattr(request.app.state, "cron_scheduler", None)
    if scheduler is not None:
        return scheduler

    store = getattr(request.app.state, "store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Cron scheduler store not available")

    return CronSchedulerService(
        store,
        build_cron_run_launcher(
            bridge=request.app.state.stream_bridge,
            run_mgr=request.app.state.run_manager,
            checkpointer=request.app.state.checkpointer,
            store=store,
        ),
        poll_interval=cron_scheduler_poll_interval(),
    )


def create_cron_scheduler_service(app: FastAPI) -> CronSchedulerService | None:
    """Create the gateway's shared cron scheduler service if store-backed persistence is available."""
    store = getattr(app.state, "store", None)
    if store is None:
        return None

    return CronSchedulerService(
        store,
        build_cron_run_launcher(
            bridge=app.state.stream_bridge,
            run_mgr=app.state.run_manager,
            checkpointer=app.state.checkpointer,
            store=store,
        ),
        poll_interval=cron_scheduler_poll_interval(),
    )


async def start_gateway_cron_scheduler(app: FastAPI) -> CronSchedulerService | None:
    """Start the background scheduler only when leader mode is enabled."""
    app.state.cron_scheduler = None

    if not cron_scheduler_enabled():
        logger.info("Cron scheduler disabled")
        return None
    if not cron_scheduler_is_leader():
        logger.info("Cron scheduler enabled but leader mode is off; skipping background loop")
        return None

    scheduler = create_cron_scheduler_service(app)
    if scheduler is None:
        logger.warning("Cron scheduler enabled but store is unavailable; skipping background loop")
        return None

    scheduler.start()
    app.state.cron_scheduler = scheduler
    logger.info("Cron scheduler started in leader mode")
    return scheduler


async def stop_gateway_cron_scheduler(app: FastAPI) -> None:
    """Stop the background scheduler if it was started for this gateway."""
    scheduler = getattr(app.state, "cron_scheduler", None)
    if scheduler is not None:
        await scheduler.stop()
        app.state.cron_scheduler = None
        logger.info("Cron scheduler stopped")
