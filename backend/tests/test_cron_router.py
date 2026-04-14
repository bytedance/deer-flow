"""Tests for app.gateway.routers.cron."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.store.memory import InMemoryStore

from app.gateway.routers import cron


class FakeScheduler:
    def __init__(self, *, trigger_result=None):
        self.wake_calls = 0
        self.trigger_result = trigger_result

    def wake(self) -> None:
        self.wake_calls += 1

    async def trigger_job(self, job_id: str):
        if self.trigger_result is None:
            raise KeyError(job_id)
        return self.trigger_result


def _make_app(*, scheduler=None) -> FastAPI:
    app = FastAPI()
    app.include_router(cron.router)
    app.state.store = InMemoryStore()
    app.state.cron_scheduler = scheduler
    return app


def test_create_job_endpoint_persists_record_and_wakes_scheduler():
    scheduler = FakeScheduler()
    app = _make_app(scheduler=scheduler)

    with TestClient(app) as client:
        response = client.post(
            "/api/cron/jobs",
            json={
                "thread_id": "thread-1",
                "cron": "*/15 * * * *",
                "timezone": "UTC",
                "input": {"messages": [{"role": "user", "content": "hello"}]},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["thread_id"] == "thread-1"
    assert body["cron"] == "*/15 * * * *"
    assert body["next_fire_at"] is not None
    assert scheduler.wake_calls == 1


def test_patch_and_delete_job_wake_scheduler():
    scheduler = FakeScheduler()
    app = _make_app(scheduler=scheduler)

    with TestClient(app) as client:
        created = client.post(
            "/api/cron/jobs",
            json={"thread_id": "thread-1", "cron": "0 * * * *", "timezone": "UTC"},
        )
        job_id = created.json()["job_id"]

        patched = client.patch(
            f"/api/cron/jobs/{job_id}",
            json={"enabled": False},
        )
        deleted = client.delete(f"/api/cron/jobs/{job_id}")

    assert patched.status_code == 200
    assert patched.json()["enabled"] is False
    assert deleted.status_code == 204
    assert scheduler.wake_calls == 3


def test_trigger_job_endpoint_returns_run_metadata():
    scheduler = FakeScheduler(
        trigger_result=SimpleNamespace(
            run_id="run-123",
            thread_id="thread-1",
            status=SimpleNamespace(value="pending"),
            metadata={"scheduler": {"job_id": "job-1"}},
        )
    )
    app = _make_app(scheduler=scheduler)

    with TestClient(app) as client:
        response = client.post("/api/cron/jobs/job-1/trigger")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": "run-123",
        "thread_id": "thread-1",
        "status": "pending",
        "metadata": {"scheduler": {"job_id": "job-1"}},
    }


def test_trigger_job_endpoint_uses_request_scoped_scheduler_fallback(monkeypatch: pytest.MonkeyPatch):
    from deerflow.runtime import CronJobCreate, create_cron_job, get_cron_job

    app = _make_app(scheduler=None)
    app.state.stream_bridge = object()
    app.state.run_manager = object()
    app.state.checkpointer = object()

    async def fake_start_run_with_deps(payload, thread_id, **kwargs):
        return SimpleNamespace(
            run_id="run-fallback",
            thread_id=thread_id,
            status=SimpleNamespace(value="pending"),
            metadata=payload.metadata,
        )

    monkeypatch.setattr("app.gateway.cron_scheduler.start_run_with_deps", fake_start_run_with_deps)

    async def seed_job():
        return await create_cron_job(
            app.state.store,
            CronJobCreate(
                thread_id="thread-1",
                cron="*/15 * * * *",
                timezone="UTC",
                input={"messages": [{"role": "user", "content": "fallback"}]},
            ),
            job_id="job-1",
        )

    with TestClient(app) as client:
        client.portal.call(seed_job)
        before = client.portal.call(get_cron_job, app.state.store, "job-1")

        response = client.post("/api/cron/jobs/job-1/trigger")
        after = client.portal.call(get_cron_job, app.state.store, "job-1")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": "run-fallback",
        "thread_id": "thread-1",
        "status": "pending",
        "metadata": {
            "scheduler": {
                "job_id": "job-1",
                "cron": "*/15 * * * *",
                "timezone": "UTC",
            }
        },
    }
    assert before is not None
    assert after is not None
    assert after.next_fire_at == before.next_fire_at
    assert after.last_fire_at == before.last_fire_at


def test_trigger_job_endpoint_returns_404_for_missing_job(monkeypatch: pytest.MonkeyPatch):
    from deerflow.runtime import CronJobNotFoundError

    app = _make_app(scheduler=None)

    class MissingScheduler:
        async def trigger_job(self, job_id: str):
            raise CronJobNotFoundError(job_id)

    monkeypatch.setattr("app.gateway.routers.cron.build_request_cron_scheduler", lambda request: MissingScheduler())

    with TestClient(app) as client:
        response = client.post("/api/cron/jobs/job-missing/trigger")

    assert response.status_code == 404
    assert response.json() == {"detail": "Cron job job-missing not found"}
