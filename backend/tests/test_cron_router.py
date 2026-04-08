"""Tests for app.gateway.routers.cron."""

from __future__ import annotations

from types import SimpleNamespace

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
