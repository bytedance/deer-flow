from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import scheduled_tasks


def test_router_registers_list_endpoint():
    app = FastAPI()
    app.include_router(scheduled_tasks.router)
    client = TestClient(app)
    response = client.get("/api/scheduled-tasks")
    assert response.status_code != 404


def test_router_registers_trigger_route():
    app = FastAPI()
    app.include_router(scheduled_tasks.router)
    client = TestClient(app)
    response = client.post("/api/scheduled-tasks/task-1/trigger")
    assert response.status_code != 404


def test_router_registers_create_route():
    app = FastAPI()
    app.include_router(scheduled_tasks.router)
    client = TestClient(app)
    response = client.post(
        "/api/scheduled-tasks",
        json={
            "thread_id": "thread-1",
            "title": "Daily summary",
            "prompt": "Summarize thread",
            "schedule_type": "cron",
            "schedule_spec": {"cron": "0 9 * * *"},
            "timezone": "UTC",
        },
    )
    assert response.status_code != 404
