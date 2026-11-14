"""A stateless run without ``thread_id`` auto-creates a thread, so the project-context
resolution at admission must not log a "thread row does not exist yet" failure for it.
A caller-supplied ``thread_id`` whose row is missing keeps the existing warning."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient
from langgraph.store.memory import InMemoryStore

from app.gateway.auth.models import User
from app.gateway.routers import runs
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
from deerflow.runtime import ConflictError

USER = User(email="owner@example.com", password_hash="x", system_role="user", id=uuid4())
MARKER = "Failed to resolve project context"
CAUSE = "thread row does not exist yet"


@pytest.fixture(autouse=True)
def _stub_app_config():
    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))
    yield
    reset_app_config()


def _post(body: dict, caplog, path: str = "/api/runs/stream"):
    app = make_authed_test_app(user_factory=lambda: USER)
    app.include_router(runs.router)
    app.state.thread_store = MemoryThreadMetaStore(InMemoryStore())
    app.state.project_repo = MagicMock()
    app.state.stream_bridge = MagicMock()
    app.state.checkpointer = MagicMock()
    app.state.checkpointer.aget_tuple = AsyncMock(return_value=None)
    app.state.store = MagicMock()
    app.state.run_events_config = None
    app.state.run_event_store = MagicMock()
    app.state.run_event_store.list_messages = AsyncMock(return_value=[])
    run_manager = MagicMock()
    run_manager.create_or_reject = AsyncMock(side_effect=ConflictError("sentinel"))
    app.state.run_manager = run_manager
    with caplog.at_level(logging.WARNING), TestClient(app) as client:
        response = client.post(path, json=body)
    return response


def _hits(caplog) -> int:
    return sum(1 for r in caplog.records if MARKER in r.getMessage() and r.exc_info and CAUSE in str(r.exc_info[1]))


@pytest.mark.parametrize("path", ["/api/runs/stream", "/api/runs/wait"])
def test_new_thread_without_thread_id_logs_no_resolution_failure(caplog, path):
    response = _post({}, caplog, path)
    assert response.status_code == 409
    assert _hits(caplog) == 0


@pytest.mark.parametrize("path", ["/api/runs/stream", "/api/runs/wait"])
def test_caller_supplied_missing_thread_still_warns(caplog, path):
    response = _post({"config": {"configurable": {"thread_id": "never-created-thread"}}}, caplog, path)
    assert response.status_code == 409
    assert _hits(caplog) == 1
