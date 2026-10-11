"""Goal writes reject unusable objectives before state or run admission."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi import HTTPException
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from app.gateway import services
from app.gateway.auth.models import User
from app.gateway.routers import runs, thread_runs, threads
from deerflow.utils.goal_objective import MAX_GOAL_OBJECTIVE_CHARS


@pytest.mark.parametrize("boundary", [services.normalize_input, services.strip_server_owned_state_metadata])
@pytest.mark.parametrize(
    "goal",
    [
        {"status": "active"},
        {"objective": None},
        {"objective": 42},
        {"objective": ""},
        {"objective": " \n\t "},
        {"objective": "x" * (MAX_GOAL_OBJECTIVE_CHARS + 1)},
        "finish",
        [],
    ],
)
def test_external_goal_requires_a_usable_objective(boundary, goal):
    with pytest.raises(HTTPException) as rejected:
        boundary({"goal": goal})
    assert rejected.value.status_code == 400
    assert "goal" in rejected.value.detail.lower()
    assert "x" * 100 not in rejected.value.detail


@pytest.mark.parametrize("boundary", [services.normalize_input, services.strip_server_owned_state_metadata])
def test_valid_sparse_goals_are_normalized_without_building_fresh_state(boundary):
    sparse = {"objective": "  finish\n the report  "}
    source = {"goal": sparse}
    admitted = boundary(source)

    assert admitted["goal"] == {"objective": "finish the report"}
    assert source == {"goal": {"objective": "  finish\n the report  "}}
    assert set(admitted["goal"]) == {"objective"}
    assert boundary({"goal": None}) == {"goal": None}
    assert boundary({"title": "unrelated update"}) == {"title": "unrelated update"}


def test_goal_replacement_preserves_supplied_counters_and_clears_previous_outcome():
    goal = {"objective": "finish", "status": "active", "continuation_count": 7, "max_continuations": 8}
    assert services.normalize_input({"goal": goal}) == {"goal": goal, "goal_outcome": None}
    assert services.normalize_input({"goal": None}) == {"goal": None}
    assert services.normalize_input({"goal": goal}, trusted_internal=True) == {"goal": goal}


class _StateRunManager:
    def __init__(self):
        self.reservations = 0

    @asynccontextmanager
    async def reserve_thread_operation(self, *_args, **_kwargs):
        self.reservations += 1
        yield


@pytest.mark.parametrize("mode", ["full", "delta"])
def test_state_route_rejects_missing_objective_without_changing_checkpoint(monkeypatch, mode):
    user = User(email="goal-input@example.com", password_hash="x", id=UUID("00000000-0000-0000-0000-000000000001"))
    app = make_authed_test_app(user_factory=lambda: user, bind_current_user=True)
    app.include_router(threads.router)
    app.state.checkpointer = checkpointer = InMemorySaver()
    app.state.checkpoint_channel_mode = mode
    app.state.run_manager = manager = _StateRunManager()
    config = {"configurable": {"thread_id": "goal-input-http", "checkpoint_ns": ""}}

    # Keep the real state mutation graph and saver; assistant-schema resolution
    # is unrelated to goal admission, so use the base schema here.
    async def build_accessor(request, *, thread_id, as_node, checkpoint_id=None):
        return services.build_checkpoint_state_mutation_accessor(request, thread_id=thread_id, as_node=as_node, checkpoint_id=checkpoint_id)

    builder = AsyncMock(side_effect=build_accessor)
    monkeypatch.setattr(threads, "build_thread_checkpoint_state_mutation_accessor", builder)

    with TestClient(app) as client:
        valid = client.post("/api/threads/goal-input-http/state", json={"values": {"goal": {"objective": "finish", "status": "active"}}})
        assert valid.status_code == 200, valid.text
        assert valid.json()["values"]["goal"] == {"objective": "finish", "status": "active"}
        before = asyncio.run(checkpointer.aget_tuple(config))
        assert before is not None
        builder.reset_mock()
        reservations = manager.reservations

        rejected = client.post("/api/threads/goal-input-http/state", json={"values": {"goal": {"status": "active"}, "title": "must not write"}})
        assert rejected.status_code == 400, rejected.text
        builder.assert_not_awaited()
        assert manager.reservations == reservations
        after = asyncio.run(checkpointer.aget_tuple(config))
        assert after is not None
        assert after.config == before.config
        assert after.checkpoint == before.checkpoint

        cleared = client.post("/api/threads/goal-input-http/state", json={"values": {"goal": None}})
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["values"].get("goal") is None


@pytest.mark.parametrize(
    "path",
    [
        "/api/threads/goal-input-http/runs",
        "/api/threads/goal-input-http/runs/stream",
        "/api/threads/goal-input-http/runs/wait",
        "/api/runs/stream",
        "/api/runs/wait",
    ],
)
def test_run_routes_reject_missing_objective_before_admission(monkeypatch, path):
    app = make_authed_test_app()
    app.include_router(runs.router)
    app.include_router(thread_runs.router)
    app.state.stream_bridge = SimpleNamespace()
    app.state.run_manager = SimpleNamespace(create_or_reject=AsyncMock())
    monkeypatch.setattr(services, "get_run_context", lambda _request: SimpleNamespace(thread_store=app.state.thread_store))
    factory = Mock(side_effect=AssertionError("invalid goal reached graph assembly"))
    monkeypatch.setattr(services, "resolve_agent_factory", factory)
    worker = AsyncMock()
    monkeypatch.setattr(services, "run_agent", worker)

    with TestClient(app, raise_server_exceptions=False) as client:
        rejected = client.post(path, json={"input": {"goal": {"status": "active"}}})

    assert rejected.status_code == 400, rejected.text
    factory.assert_not_called()
    app.state.run_manager.create_or_reject.assert_not_awaited()
    worker.assert_not_awaited()
