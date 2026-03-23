"""Unit tests for cron scheduling, persistence, and router mappings."""

import asyncio
import importlib
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.cron.service import CronService, NoFutureRunTimeError
from src.cron.types import CronPayload, CronSchedule

cron_service_module = importlib.import_module("src.cron.service")
cron_router_module = importlib.import_module("app.gateway.routers.cron")


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(cron_router_module.router)
    return app


def _make_store_path(tmp_path: Path) -> Path:
    return tmp_path / "jobs.json"


def _run(coro):
    return asyncio.run(coro)


def test_compute_next_run_for_at_schedule():
    schedule = CronSchedule(kind="at", at_ms=2_000)

    assert cron_service_module._compute_next_run(schedule, now_ms=1_000) == 2_000
    assert cron_service_module._compute_next_run(schedule, now_ms=2_000) is None
    assert cron_service_module._compute_next_run(schedule, now_ms=3_000) is None


def test_compute_next_run_for_every_schedule_preserves_anchor():
    schedule = CronSchedule(kind="every", every_ms=60_000)

    assert cron_service_module._compute_next_run(schedule, now_ms=125_000) == 185_000
    assert cron_service_module._compute_next_run(schedule, now_ms=125_000, anchor_ms=60_000) == 180_000


def test_compute_next_run_for_cron_schedule(monkeypatch):
    captured: dict = {}
    croniter_module = ModuleType("croniter")

    def fake_croniter(expr, base_dt):
        captured["expr"] = expr
        captured["base_dt"] = base_dt

        class FakeIterator:
            def get_next(self, value_type):
                assert value_type is datetime
                return datetime(2026, 3, 12, 9, 30, tzinfo=base_dt.tzinfo)

        return FakeIterator()

    croniter_module.croniter = fake_croniter
    monkeypatch.setitem(sys.modules, "croniter", croniter_module)

    schedule = CronSchedule(kind="cron", expr="30 9 * * *", tz="UTC")

    next_run = cron_service_module._compute_next_run(
        schedule,
        now_ms=int(datetime(2026, 3, 12, 8, 0, tzinfo=UTC).timestamp() * 1000),
    )

    assert captured["expr"] == "30 9 * * *"
    assert captured["base_dt"].tzinfo is not None
    assert next_run == int(datetime(2026, 3, 12, 9, 30, tzinfo=UTC).timestamp() * 1000)


def test_add_job_rejects_invalid_interval_schedule(tmp_path: Path):
    service = CronService(store_path=_make_store_path(tmp_path))

    with pytest.raises(ValueError, match="positive 'every_ms'"):
        _run(
            service.add_job(
                name="Invalid interval",
                schedule=CronSchedule(kind="every", every_ms=0),
                payload=CronPayload(message="bad"),
            )
        )


def test_add_job_api_returns_422_for_schema_validation_error(monkeypatch, tmp_path: Path):
    service = CronService(store_path=_make_store_path(tmp_path))
    monkeypatch.setattr(cron_router_module, "get_cron_service", lambda: service)

    with TestClient(_make_app()) as client:
        response = client.post(
            "/api/cron",
            json={
                "name": "Invalid interval",
                "schedule": {"kind": "every"},
                "payload": {"message": "bad"},
            },
        )

    assert response.status_code == 422
    assert "every schedules require a positive 'every_ms'" in str(response.json()["detail"])


def test_add_job_api_returns_400_for_no_future_run(monkeypatch, tmp_path: Path):
    service = CronService(store_path=_make_store_path(tmp_path))
    monkeypatch.setattr(cron_router_module, "get_cron_service", lambda: service)

    with TestClient(_make_app()) as client:
        response = client.post(
            "/api/cron",
            json={
                "name": "Expired reminder",
                "schedule": {"kind": "at", "at_ms": 1},
                "payload": {"message": "too late"},
            },
        )

    assert response.status_code == 400
    assert "future run time" in response.json()["detail"]


def test_enable_job_raises_when_schedule_has_no_future_run(tmp_path: Path):
    service = CronService(store_path=_make_store_path(tmp_path))
    expired_job = _run(
        service.add_job(
            name="Expired reminder",
            schedule=CronSchedule(kind="at", at_ms=1),
            payload=CronPayload(message="too late"),
            enabled=False,
        )
    )

    with pytest.raises(NoFutureRunTimeError, match="no future run time"):
        _run(service.enable_job(expired_job.id, enabled=True))


def test_enable_job_api_returns_409_when_schedule_has_no_future_run(monkeypatch, tmp_path: Path):
    service = CronService(store_path=_make_store_path(tmp_path))
    expired_job = _run(
        service.add_job(
            name="Expired reminder",
            schedule=CronSchedule(kind="at", at_ms=1),
            payload=CronPayload(message="too late"),
            enabled=False,
        )
    )
    monkeypatch.setattr(cron_router_module, "get_cron_service", lambda: service)

    with TestClient(_make_app()) as client:
        response = client.post(f"/api/cron/{expired_job.id}/enable")

    assert response.status_code == 409
    assert "no future run time" in response.json()["detail"]


def test_persistence_round_trip_reloads_saved_job(monkeypatch, tmp_path: Path):
    store_path = _make_store_path(tmp_path)
    now_ms = 1_700_000_000_000
    monkeypatch.setattr(cron_service_module, "_now_ms", lambda: now_ms)
    monkeypatch.setattr(cron_service_module, "_generate_id", lambda: "job-1")

    writer = CronService(store_path=store_path)
    created = _run(
        writer.add_job(
            name="Heartbeat",
            schedule=CronSchedule(kind="every", every_ms=60_000),
            payload=CronPayload(
                message="Ping",
                deliver=True,
                channel="slack",
                to="ops-room",
                thread_id="thread-123",
                assistant_id="assistant-1",
                agent_name="ops-helper",
                thinking_enabled=False,
                subagent_enabled=True,
            ),
        )
    )

    reloaded = CronService(store_path=store_path)
    [saved_job] = _run(reloaded.get_jobs())

    assert saved_job.to_dict() == created.to_dict()


def test_one_time_failed_job_is_disabled_instead_of_deleted(tmp_path: Path):
    async def boom(job):
        del job
        raise RuntimeError("run failed")

    service = CronService(
        store_path=_make_store_path(tmp_path),
        on_job=boom,
    )

    async def run():
        await service.start()
        try:
            job = await service.add_job(
                name="Dinner reminder",
                schedule=CronSchedule(kind="at", at_ms=32_503_680_000_000),
                payload=CronPayload(message="Remind me to eat"),
                delete_after_run=True,
            )
            await service.run_job(job.id)
            return (await service.get_jobs())[0]
        finally:
            service.stop()

    saved_job = asyncio.run(run())

    assert saved_job.name == "Dinner reminder"
    assert saved_job.enabled is False
    assert saved_job.state.last_status == "error"
    assert saved_job.state.last_error == "run failed"


def test_service_admin_calls_remain_available_while_job_runs(tmp_path: Path):
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_job(job):
        del job
        started.set()
        await release.wait()
        return "done"

    service = CronService(
        store_path=_make_store_path(tmp_path),
        on_job=slow_job,
    )

    async def run():
        await service.start()
        try:
            job = await service.add_job(
                name="Long task",
                schedule=CronSchedule(kind="every", every_ms=60_000),
                payload=CronPayload(message="Wait for release"),
            )

            run_task = asyncio.create_task(service.run_job(job.id))
            await asyncio.wait_for(started.wait(), timeout=1)

            status = await asyncio.wait_for(service.status(), timeout=0.5)
            jobs = await asyncio.wait_for(service.list_jobs(include_disabled=True), timeout=0.5)

            release.set()
            result = await asyncio.wait_for(run_task, timeout=1)
            return job.id, status, jobs, result
        finally:
            service.stop()

    job_id, status, jobs, result = asyncio.run(run())

    assert status["running"] is True
    assert status["jobs"] == 1
    assert jobs[0]["id"] == job_id
    assert result == "ok"
