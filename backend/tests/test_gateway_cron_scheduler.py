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


def test_cron_scheduler_env_helpers_prefer_primary_names_and_fall_back_to_legacy_aliases(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.gateway.cron_scheduler import cron_scheduler_enabled, cron_scheduler_is_leader, cron_scheduler_poll_interval

    for name in (
        "DEERFLOW_CRON_SCHEDULER_ENABLED",
        "DEER_FLOW_CRON_SCHEDULER_ENABLED",
        "DEERFLOW_CRON_SCHEDULER_LEADER",
        "DEER_FLOW_CRON_SCHEDULER_LEADER",
        "DEERFLOW_CRON_SCHEDULER_POLL_INTERVAL",
        "DEER_FLOW_CRON_SCHEDULER_POLL_INTERVAL",
    ):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("DEER_FLOW_CRON_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("DEER_FLOW_CRON_SCHEDULER_LEADER", "yes")
    monkeypatch.setenv("DEER_FLOW_CRON_SCHEDULER_POLL_INTERVAL", "12.5")
    assert cron_scheduler_enabled() is True
    assert cron_scheduler_is_leader() is True
    assert cron_scheduler_poll_interval(default=30.0) == 12.5

    monkeypatch.setenv("DEERFLOW_CRON_SCHEDULER_ENABLED", "0")
    monkeypatch.setenv("DEERFLOW_CRON_SCHEDULER_LEADER", "off")
    monkeypatch.setenv("DEERFLOW_CRON_SCHEDULER_POLL_INTERVAL", "0")
    assert cron_scheduler_enabled() is False
    assert cron_scheduler_is_leader() is False
    assert cron_scheduler_poll_interval(default=30.0) == 30.0

    monkeypatch.setenv("DEERFLOW_CRON_SCHEDULER_POLL_INTERVAL", "not-a-number")
    assert cron_scheduler_poll_interval(default=15.0) == 15.0


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


@pytest.mark.anyio
async def test_start_gateway_cron_scheduler_skips_when_leader_mode_is_off(monkeypatch: pytest.MonkeyPatch):
    from app.gateway.cron_scheduler import start_gateway_cron_scheduler

    app = FastAPI()
    app.state.store = object()
    app.state.stream_bridge = object()
    app.state.run_manager = object()
    app.state.checkpointer = object()

    create_calls = 0

    def fake_create_scheduler(app_obj):
        nonlocal create_calls
        create_calls += 1
        return object()

    monkeypatch.setenv("DEERFLOW_CRON_SCHEDULER_ENABLED", "1")
    monkeypatch.delenv("DEER_FLOW_CRON_SCHEDULER_ENABLED", raising=False)
    monkeypatch.delenv("DEER_FLOW_CRON_SCHEDULER_LEADER", raising=False)
    monkeypatch.setenv("DEERFLOW_CRON_SCHEDULER_LEADER", "0")
    monkeypatch.setattr("app.gateway.cron_scheduler.create_cron_scheduler_service", fake_create_scheduler)

    started = await start_gateway_cron_scheduler(app)

    assert started is None
    assert create_calls == 0
    assert app.state.cron_scheduler is None
