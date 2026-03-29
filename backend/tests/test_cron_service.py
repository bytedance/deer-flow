"""Unit tests for cron scheduling, persistence, and router mappings."""

import asyncio
import importlib
import json
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.cron.service import CronService, NoFutureRunTimeError
from src.cron.types import CronPayload, CronSchedule

cron_service_module = importlib.import_module("src.cron.service")
cron_timezones_module = importlib.import_module("src.cron.timezones")
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


def test_format_timestamp_ms_uses_local_timezone_for_legacy_cron_schedule(monkeypatch):
    monkeypatch.setattr(
        cron_timezones_module,
        "_local_timezone",
        lambda: timezone(timedelta(hours=8), "UTC+08:00"),
    )

    formatted = cron_timezones_module.format_timestamp_ms(
        1_774_863_000_000,
        schedule={"kind": "cron", "tz": None},
    )

    assert formatted == "2026-03-30T17:30:00+08:00"


def test_format_timestamp_ms_uses_utc_for_non_cron_schedule(monkeypatch):
    monkeypatch.setattr(
        cron_timezones_module,
        "_local_timezone",
        lambda: timezone(timedelta(hours=8), "UTC+08:00"),
    )

    formatted = cron_timezones_module.format_timestamp_ms(
        0,
        schedule={"kind": "at", "at_ms": 0},
    )

    assert formatted == "1970-01-01T00:00:00+00:00"


def test_normalize_cron_schedule_timezone_uses_configured_default_timezone(monkeypatch):
    monkeypatch.setattr(cron_timezones_module, "get_default_timezone_name", lambda: "Asia/Tokyo")

    schedule = cron_timezones_module.normalize_cron_schedule_timezone(
        CronSchedule(kind="cron", expr="30 17 * * *")
    )

    assert schedule.tz == "Asia/Tokyo"


def test_job_to_response_formats_times_using_schedule_timezone():
    response = cron_router_module._job_to_response(
        {
            "id": "job-1",
            "name": "Dinner reminder",
            "enabled": True,
            "schedule": {
                "kind": "cron",
                "at_ms": None,
                "every_ms": None,
                "expr": "30 17 * * *",
                "tz": "UTC+08:00",
            },
            "payload": {"kind": "agent_turn", "message": "Eat"},
            "state": {
                "next_run_at_ms": 1_774_863_000_000,
                "last_run_at_ms": 1_774_776_600_012,
                "last_status": "ok",
                "last_error": None,
            },
            "delete_after_run": False,
            "created_at_ms": 1_774_774_183_250,
        }
    )

    assert response.schedule.tz == "UTC+08:00"
    assert response.state.next_run_at == "2026-03-30T17:30:00+08:00"
    assert response.state.last_run_at == "2026-03-29T17:30:00.012000+08:00"
    assert response.created_at == "2026-03-29T08:49:43.250000+00:00"


def test_job_to_response_handles_missing_created_at_ms():
    response = cron_router_module._job_to_response(
        {
            "id": "job-1",
            "name": "Dinner reminder",
            "enabled": True,
            "schedule": {
                "kind": "cron",
                "at_ms": None,
                "every_ms": None,
                "expr": "30 17 * * *",
                "tz": "Asia/Shanghai",
            },
            "payload": {"kind": "agent_turn", "message": "Eat"},
            "state": {
                "next_run_at_ms": None,
                "last_run_at_ms": None,
                "last_status": "pending",
                "last_error": None,
            },
            "delete_after_run": False,
            "created_at_ms": None,
        }
    )

    assert response.created_at == "1970-01-01T00:00:00+00:00"


def test_add_job_normalizes_missing_cron_timezone(monkeypatch, tmp_path: Path):
    captured: dict = {}
    croniter_module = ModuleType("croniter")

    def fake_croniter(expr, base_dt):
        captured["expr"] = expr
        captured["base_dt"] = base_dt

        class FakeIterator:
            def get_next(self, value_type):
                assert value_type is datetime
                return datetime(2026, 3, 30, 17, 30, tzinfo=base_dt.tzinfo)

        return FakeIterator()

    croniter_module.croniter = fake_croniter
    monkeypatch.setitem(sys.modules, "croniter", croniter_module)
    monkeypatch.setattr(cron_service_module, "_now_ms", lambda: 1_774_849_620_000)
    monkeypatch.setattr(cron_timezones_module, "get_default_timezone_name", lambda: "Asia/Shanghai")

    service = CronService(store_path=_make_store_path(tmp_path))
    created = _run(
        service.add_job(
            name="Dinner reminder",
            schedule=CronSchedule(kind="cron", expr="30 17 * * *"),
            payload=CronPayload(message="Eat"),
        )
    )

    [saved_job] = _run(CronService(store_path=_make_store_path(tmp_path)).get_jobs())

    assert captured["expr"] == "30 17 * * *"
    assert created.schedule.tz == "Asia/Shanghai"
    assert saved_job.schedule.tz == "Asia/Shanghai"
    assert created.state.next_run_at_ms == 1_774_863_000_000


def test_start_does_not_persist_legacy_cron_timezones(monkeypatch, tmp_path: Path):
    store_path = _make_store_path(tmp_path)
    store_path.write_text(
        json.dumps(
            {
                "version": 1,
                "jobs": [
                    {
                        "id": "job-1",
                        "name": "Dinner reminder",
                        "enabled": True,
                        "schedule": {
                            "kind": "cron",
                            "at_ms": None,
                            "every_ms": None,
                            "expr": "30 17 * * *",
                            "tz": None,
                        },
                        "payload": {"kind": "agent_turn", "message": "Eat"},
                        "state": {
                            "next_run_at_ms": 1_774_863_000_000,
                            "last_run_at_ms": None,
                            "last_status": "pending",
                            "last_error": None,
                        },
                        "delete_after_run": False,
                        "created_at_ms": 1_774_774_183_250,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    service = CronService(store_path=store_path)

    def fail_write(_store):
        raise AssertionError("start() should not write the cron store")

    monkeypatch.setattr(service, "_write_store_to_disk", fail_write)
    _run(service.start())
    service.stop()

    persisted = json.loads(store_path.read_text(encoding="utf-8"))
    assert persisted["jobs"][0]["schedule"]["tz"] is None


def test_enable_job_preserves_legacy_cron_timezone(monkeypatch, tmp_path: Path):
    captured: dict = {}
    croniter_module = ModuleType("croniter")

    def fake_croniter(expr, base_dt):
        captured["expr"] = expr
        captured["base_dt"] = base_dt

        class FakeIterator:
            def get_next(self, value_type):
                assert value_type is datetime
                return datetime(2026, 3, 30, 17, 30, tzinfo=base_dt.tzinfo)

        return FakeIterator()

    croniter_module.croniter = fake_croniter
    monkeypatch.setitem(sys.modules, "croniter", croniter_module)
    monkeypatch.setattr(cron_timezones_module, "get_default_timezone_name", lambda: "Asia/Shanghai")
    monkeypatch.setattr(
        cron_timezones_module,
        "_local_timezone",
        lambda: timezone(timedelta(hours=8), "UTC+08:00"),
    )
    monkeypatch.setattr(cron_service_module, "_now_ms", lambda: 1_774_849_620_000)

    service = CronService(store_path=_make_store_path(tmp_path))
    created = _run(
        service.add_job(
            name="Dinner reminder",
            schedule=CronSchedule(kind="cron", expr="30 17 * * *"),
            payload=CronPayload(message="Eat"),
            enabled=False,
        )
    )

    store_path = _make_store_path(tmp_path)
    persisted = json.loads(store_path.read_text(encoding="utf-8"))
    persisted["jobs"][0]["schedule"]["tz"] = None
    store_path.write_text(json.dumps(persisted), encoding="utf-8")

    reloaded_service = CronService(store_path=store_path)
    updated = _run(reloaded_service.enable_job(created.id, enabled=True))
    [saved_job] = _run(CronService(store_path=store_path).get_jobs())

    assert updated is True
    assert captured["expr"] == "30 17 * * *"
    assert saved_job.schedule.tz is None
    assert saved_job.state.next_run_at_ms == 1_774_863_000_000


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


def test_start_raises_when_existing_store_is_unreadable(tmp_path: Path):
    store_path = _make_store_path(tmp_path)
    store_path.write_text("{not valid json", encoding="utf-8")

    service = CronService(store_path=store_path)

    with pytest.raises(cron_service_module.CronStoreUnavailableError, match="Failed to load cron store"):
        _run(service.start())

    assert store_path.read_text(encoding="utf-8") == "{not valid json"

    cron_service_module.stop_cron_service()
    with pytest.raises(cron_service_module.CronStoreUnavailableError, match="Failed to load cron store"):
        _run(cron_service_module.start_cron_service(store_path=store_path))
    assert cron_service_module.get_cron_service() is None


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


def test_add_job_api_returns_503_for_store_persistence_failure(monkeypatch, tmp_path: Path):
    service = CronService(store_path=_make_store_path(tmp_path))
    monkeypatch.setattr(cron_router_module, "get_cron_service", lambda: service)

    def fail_write(store):
        del store
        raise OSError("disk full")

    monkeypatch.setattr(service, "_write_store_to_disk", fail_write)

    with TestClient(_make_app()) as client:
        response = client.post(
            "/api/cron",
            json={
                "name": "Persist me",
                "schedule": {"kind": "every", "every_ms": 60_000},
                "payload": {"message": "Ping"},
            },
        )

    assert response.status_code == 503
    assert "Failed to save cron store" in response.json()["detail"]
    assert _run(service.get_jobs()) == []


def test_run_job_api_returns_ignored_status(monkeypatch):
    class FakeCronService:
        async def run_job(self, job_id: str, force: bool = True):
            del job_id, force
            return cron_service_module._ManualRunResult(status="ignored", result="already_running")

    monkeypatch.setattr(cron_router_module, "get_cron_service", lambda: FakeCronService())

    with TestClient(_make_app()) as client:
        response = client.post("/api/cron/job-1/run")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ignored",
        "job_id": "job-1",
        "result": "already_running",
    }


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


def test_external_store_corruption_preserves_last_known_jobs_and_recovers(tmp_path: Path):
    store_path = _make_store_path(tmp_path)
    writer = CronService(store_path=store_path)
    created = _run(
        writer.add_job(
            name="Heartbeat",
            schedule=CronSchedule(kind="every", every_ms=60_000),
            payload=CronPayload(message="Ping"),
        )
    )
    original_content = store_path.read_text(encoding="utf-8")

    service = CronService(store_path=store_path)

    async def run():
        await service.start()
        try:
            healthy_jobs = await service.list_jobs(include_disabled=True)

            store_path.write_text("{broken", encoding="utf-8")

            degraded_jobs = await service.list_jobs(include_disabled=True)
            degraded_status = await service.status()
            with pytest.raises(cron_service_module.CronStoreUnavailableError, match="Failed to load cron store"):
                await service.add_job(
                    name="Should fail",
                    schedule=CronSchedule(kind="every", every_ms=120_000),
                    payload=CronPayload(message="Nope"),
                )

            store_path.write_text(original_content, encoding="utf-8")

            recovered_jobs = await service.list_jobs(include_disabled=True)
            recovered_status = await service.status()
            return healthy_jobs, degraded_jobs, degraded_status, recovered_jobs, recovered_status
        finally:
            service.stop()

    healthy_jobs, degraded_jobs, degraded_status, recovered_jobs, recovered_status = asyncio.run(run())

    assert healthy_jobs[0]["id"] == created.id
    assert degraded_jobs == healthy_jobs
    assert degraded_status["store_available"] is False
    assert "Failed to load cron store" in degraded_status["store_error"]
    assert recovered_jobs[0]["id"] == created.id
    assert recovered_status["store_available"] is True
    assert recovered_status["store_error"] is None


def test_external_store_deletion_preserves_last_known_jobs_and_recovers(tmp_path: Path):
    store_path = _make_store_path(tmp_path)
    writer = CronService(store_path=store_path)
    created = _run(
        writer.add_job(
            name="Heartbeat",
            schedule=CronSchedule(kind="every", every_ms=60_000),
            payload=CronPayload(message="Ping"),
        )
    )
    original_content = store_path.read_text(encoding="utf-8")

    service = CronService(store_path=store_path)

    async def run():
        await service.start()
        try:
            healthy_jobs = await service.list_jobs(include_disabled=True)

            store_path.unlink()

            degraded_jobs = await service.list_jobs(include_disabled=True)
            degraded_status = await service.status()
            with pytest.raises(cron_service_module.CronStoreUnavailableError, match="Failed to load cron store"):
                await service.add_job(
                    name="Should fail",
                    schedule=CronSchedule(kind="every", every_ms=120_000),
                    payload=CronPayload(message="Nope"),
                )

            store_path.write_text(original_content, encoding="utf-8")

            recovered_jobs = await service.list_jobs(include_disabled=True)
            recovered_status = await service.status()
            return healthy_jobs, degraded_jobs, degraded_status, recovered_jobs, recovered_status
        finally:
            service.stop()

    healthy_jobs, degraded_jobs, degraded_status, recovered_jobs, recovered_status = asyncio.run(run())

    assert healthy_jobs[0]["id"] == created.id
    assert degraded_jobs == healthy_jobs
    assert degraded_status["store_available"] is False
    assert "Failed to load cron store" in degraded_status["store_error"]
    assert recovered_jobs[0]["id"] == created.id
    assert recovered_status["store_available"] is True
    assert recovered_status["store_error"] is None


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
    assert result.status == "executed"
    assert result.result == "ok"

def test_run_job_ignores_inflight_execution_without_polling(monkeypatch, tmp_path: Path):
    started = asyncio.Event()
    release = asyncio.Event()
    run_count = 0

    async def slow_job(job):
        nonlocal run_count
        del job
        run_count += 1
        started.set()
        await release.wait()
        return "done"

    service = CronService(
        store_path=_make_store_path(tmp_path),
        on_job=slow_job,
    )
    original_sleep = asyncio.sleep

    async def tracked_sleep(delay, *args, **kwargs):
        assert delay != 0.01
        return await original_sleep(delay, *args, **kwargs)

    monkeypatch.setattr(cron_service_module.asyncio, "sleep", tracked_sleep)

    async def run():
        job = await service.add_job(
            name="Serialized task",
            schedule=CronSchedule(kind="every", every_ms=60_000),
            payload=CronPayload(message="Run twice"),
        )

        first = asyncio.create_task(service.run_job(job.id))
        await asyncio.wait_for(started.wait(), timeout=1)

        second = asyncio.create_task(service.run_job(job.id))
        second_result = await asyncio.wait_for(second, timeout=0.5)

        release.set()
        first_result = await asyncio.wait_for(first, timeout=1)
        return first_result, second_result

    first_result, second_result = asyncio.run(run())

    assert first_result.status == "executed"
    assert first_result.result == "ok"
    assert second_result.status == "ignored"
    assert second_result.result == "already_running"
    assert run_count == 1


def test_timer_triggered_execution_causes_manual_run_to_be_ignored(tmp_path: Path):
    started = asyncio.Event()
    release = asyncio.Event()
    run_count = 0

    async def slow_job(job):
        nonlocal run_count
        del job
        run_count += 1
        started.set()
        await release.wait()
        return "done"

    service = CronService(
        store_path=_make_store_path(tmp_path),
        on_job=slow_job,
    )
    original_sleep = asyncio.sleep

    async def run():
        job = await service.add_job(
            name="Timer task",
            schedule=CronSchedule(kind="every", every_ms=60_000),
            payload=CronPayload(message="Wake manual run"),
        )

        async with service._store_lock:
            store = await service._load_store_locked()
            working_store = service._copy_store(store)
            working_store.jobs[0].state.next_run_at_ms = 1
            await service._commit_store_locked(working_store)

        timer_task = asyncio.create_task(service._on_timer())
        await asyncio.wait_for(started.wait(), timeout=1)

        manual_task = asyncio.create_task(service.run_job(job.id))
        manual_result = await asyncio.wait_for(manual_task, timeout=0.5)

        release.set()
        await asyncio.wait_for(timer_task, timeout=1)
        return manual_result

    manual_result = asyncio.run(run())

    assert manual_result.status == "ignored"
    assert manual_result.result == "already_running"
    assert run_count == 1


def test_timer_retries_pending_execution_persistence_without_rerunning_job(monkeypatch, tmp_path: Path):
    run_count = 0

    async def fast_job(job):
        nonlocal run_count
        del job
        run_count += 1
        return "done"

    service = CronService(
        store_path=_make_store_path(tmp_path),
        on_job=fast_job,
    )

    async def run():
        await service.start()
        try:
            job = await service.add_job(
                name="Retry persisted timer",
                schedule=CronSchedule(kind="every", every_ms=60_000),
                payload=CronPayload(message="Don't rerun"),
            )

            async with service._store_lock:
                store = await service._load_store_locked()
                working_store = service._copy_store(store)
                working_store.jobs[0].state.next_run_at_ms = 1
                await service._commit_store_locked(working_store)

            original_write = service._write_store_to_disk
            attempts = 0

            def flaky_write(store):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise OSError("disk full")
                return original_write(store)

            monkeypatch.setattr(service, "_write_store_to_disk", flaky_write)

            await service._on_timer()
            after_failure_status = await service.status()
            after_failure_jobs = await service.list_jobs(include_disabled=True)

            await service._on_timer()
            recovered_status = await service.status()
            recovered_jobs = await service.list_jobs(include_disabled=True)

            return job, after_failure_status, after_failure_jobs, recovered_status, recovered_jobs
        finally:
            service.stop()

    job, after_failure_status, after_failure_jobs, recovered_status, recovered_jobs = asyncio.run(run())

    assert run_count == 1
    assert after_failure_status["store_available"] is False
    assert "Failed to save cron store" in after_failure_status["store_error"]
    assert after_failure_jobs[0]["id"] == job.id
    assert after_failure_jobs[0]["state"]["last_status"] == "ok"
    assert after_failure_jobs[0]["state"]["last_run_at_ms"] is not None
    assert recovered_status["store_available"] is True
    assert recovered_status["store_error"] is None
    assert recovered_jobs[0]["id"] == job.id
    assert recovered_jobs[0]["state"]["last_status"] == "ok"
    assert recovered_jobs[0]["state"]["last_run_at_ms"] is not None

def test_auto_deleted_job_is_removed_after_manual_run(tmp_path: Path):
    service = CronService(store_path=_make_store_path(tmp_path))

    async def run():
        job = await service.add_job(
            name="Cleanup auto deleted job",
            schedule=CronSchedule(kind="at", at_ms=32_503_680_000_000),
            payload=CronPayload(message="Cleanup"),
            delete_after_run=True,
        )

        result = await service.run_job(job.id)
        jobs = await service.get_jobs()
        return job.id, result, jobs

    job_id, result, jobs = asyncio.run(run())

    assert result.status == "executed"
    assert result.result == "ok"
    assert jobs == []
    assert job_id is not None
