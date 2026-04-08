"""Tests for app.gateway.cron_scheduler."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI


@pytest.mark.anyio
async def test_build_cron_run_launcher_normalizes_enqueue(monkeypatch: pytest.MonkeyPatch):
    from app.gateway.cron_scheduler import build_cron_run_launcher
    from deerflow.runtime import CronJobPayload

    captured: dict[str, object] = {}

    async def fake_start_run_with_deps(payload, thread_id, **kwargs):
        captured["payload"] = payload
        captured["thread_id"] = thread_id
        return SimpleNamespace(run_id="run-1")

    monkeypatch.setattr("app.gateway.cron_scheduler.start_run_with_deps", fake_start_run_with_deps)

    launcher = build_cron_run_launcher(
        bridge=object(),
        run_mgr=object(),
        checkpointer=object(),
        store=object(),
    )
    await launcher(
        "thread-1",
        CronJobPayload(
            input={"messages": [{"role": "user", "content": "hello"}]},
            multitask_strategy="enqueue",
            metadata={"source": "cron"},
        ),
    )

    payload = captured["payload"]
    assert captured["thread_id"] == "thread-1"
    assert payload.multitask_strategy == "reject"
    assert payload.on_disconnect == "continue"
    assert payload.metadata["source"] == "cron"


@pytest.mark.anyio
async def test_start_and_stop_gateway_cron_scheduler(monkeypatch: pytest.MonkeyPatch):
    from app.gateway.cron_scheduler import start_gateway_cron_scheduler, stop_gateway_cron_scheduler

    app = FastAPI()
    app.state.store = object()
    app.state.stream_bridge = object()
    app.state.run_manager = object()
    app.state.checkpointer = object()

    class FakeScheduler:
        def __init__(self):
            self.started = 0
            self.stopped = 0

        def start(self):
            self.started += 1

        async def stop(self):
            self.stopped += 1

    scheduler = FakeScheduler()

    monkeypatch.setenv("DEERFLOW_CRON_SCHEDULER_ENABLED", "1")
    monkeypatch.setenv("DEERFLOW_CRON_SCHEDULER_LEADER", "1")
    monkeypatch.setattr("app.gateway.cron_scheduler.create_cron_scheduler_service", lambda app_obj: scheduler)

    started = await start_gateway_cron_scheduler(app)
    await stop_gateway_cron_scheduler(app)

    assert started is scheduler
    assert scheduler.started == 1
    assert scheduler.stopped == 1
    assert app.state.cron_scheduler is None
