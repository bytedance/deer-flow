"""Goal writes reject unusable objectives and counters before admission."""

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
from langgraph.graph import StateGraph
from langgraph.types import Overwrite

from app.gateway import services
from app.gateway.auth.models import User
from app.gateway.routers import runs, thread_runs, threads
from deerflow.agents.thread_state import get_thread_state_schema
from deerflow.utils.goal_objective import MAX_GOAL_OBJECTIVE_CHARS

_JSON_OVERWRITE_GOAL = {
    "objective": "outer objective",
    "type": "__overwrite__",
    "value": {"status": "active", "continuation_count": "many"},
}
_KEYED_OVERWRITE_GOAL = {"objective": "outer objective", "__overwrite__": {"status": "active", "continuation_count": "many"}}


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
@pytest.mark.parametrize("field", ["continuation_count", "max_continuations", "no_progress_count", "max_no_progress_continuations"])
@pytest.mark.parametrize(
    "value",
    [
        pytest.param("many", id="text"),
        pytest.param("2", id="numeric-string"),
        pytest.param(-1, id="negative"),
        pytest.param(1.5, id="float"),
        pytest.param(True, id="boolean"),
        pytest.param(None, id="null"),
    ],
)
def test_external_goal_rejects_invalid_present_counters(boundary, field, value):
    source = {"goal": {"objective": "finish", field: value}}
    with pytest.raises(HTTPException) as rejected:
        boundary(source)
    assert rejected.value.status_code == 400
    assert f"goal.{field}" in rejected.value.detail
    assert "many" not in rejected.value.detail
    assert source == {"goal": {"objective": "finish", field: value}}


@pytest.mark.parametrize("boundary", [services.normalize_input, services.strip_server_owned_state_metadata])
@pytest.mark.parametrize(
    "goal",
    [
        pytest.param(_JSON_OVERWRITE_GOAL, id="json-overwrite"),
        pytest.param(_KEYED_OVERWRITE_GOAL, id="reserved-key"),
        pytest.param({"objective": "finish", "type": "__overwrite__"}, id="marker-without-value"),
        pytest.param({"objective": "finish", "type": "__overwrite__", "value": None}, id="overwrite-clear"),
    ],
)
def test_external_goal_rejects_reducer_control_markers(boundary, goal):
    with pytest.raises(HTTPException) as rejected:
        boundary({"goal": goal})
    assert rejected.value.status_code == 400
    assert "goal" in rejected.value.detail
    assert "outer objective" not in rejected.value.detail
    assert "many" not in rejected.value.detail


@pytest.mark.parametrize("boundary", [services.normalize_input, services.strip_server_owned_state_metadata])
def test_external_goal_keeps_ordinary_type_and_value_fields(boundary):
    goal = {"objective": "finish", "continuation_count": 7, "max_continuations": 8, "type": "business", "value": {"continuation_count": "many"}}
    assert boundary({"goal": goal})["goal"] == goal


def test_trusted_internal_goal_input_preserves_typed_overwrite():
    overwrite = Overwrite({"objective": "finish", "continuation_count": 7, "max_continuations": 8})
    assert services.normalize_input({"goal": overwrite}, trusted_internal=True)["goal"] is overwrite


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "delta"])
@pytest.mark.parametrize("initial_goal", [None, {"objective": "previous", "status": "active", "continuation_count": 7, "max_continuations": 8}], ids=["cleared", "active"])
async def test_run_input_rejects_overwrite_before_mutating_existing_goal(mode, initial_goal):
    checkpointer = InMemorySaver()
    builder = StateGraph(get_thread_state_schema(mode))
    builder.add_node("finish", lambda _state: {})
    builder.set_entry_point("finish")
    builder.set_finish_point("finish")
    graph = builder.compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "goal-overwrite-input", "checkpoint_ns": ""}}
    # An initialized goal channel is required to exercise LangGraph's sentinel
    # unpacking; the first write into an unset channel keeps the outer mapping.
    await graph.ainvoke({"goal": initial_goal}, config)
    before = await checkpointer.aget_tuple(config)
    assert before is not None

    with pytest.raises(HTTPException) as rejected:
        await graph.ainvoke(services.normalize_input({"goal": _JSON_OVERWRITE_GOAL}), config)
    assert rejected.value.status_code == 400
    after = await checkpointer.aget_tuple(config)
    assert after is not None
    assert after.config == before.config
    assert after.checkpoint == before.checkpoint
    assert (await graph.aget_state(config)).values["goal"] == initial_goal


@pytest.mark.parametrize("boundary", [services.normalize_input, services.strip_server_owned_state_metadata])
@pytest.mark.parametrize(
    "counters",
    [
        {"continuation_count": 0, "max_continuations": 0, "no_progress_count": 0, "max_no_progress_continuations": 0},
        {"continuation_count": 7, "max_continuations": 8, "no_progress_count": 1, "max_no_progress_continuations": 2},
        {"continuation_count": 9, "max_continuations": 8, "no_progress_count": 3, "max_no_progress_continuations": 2},
    ],
    ids=["zero", "remaining-budget", "used-budget"],
)
def test_external_goal_preserves_valid_counters_without_resetting_budget(boundary, counters):
    goal = {"objective": "finish", **counters}
    assert boundary({"goal": goal})["goal"] == goal


def test_trusted_internal_goal_input_keeps_existing_restore_protocol():
    source = {"goal": {"objective": "finish", "continuation_count": "many"}}
    assert services.normalize_input(source, trusted_internal=True) == source


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
@pytest.mark.parametrize(
    "invalid_goal",
    [
        pytest.param({"status": "active"}, id="missing-objective"),
        pytest.param({"objective": "finish", "continuation_count": "many"}, id="invalid-count"),
        pytest.param({"objective": "finish", "max_continuations": True}, id="boolean-limit"),
        pytest.param({"objective": "finish", "no_progress_count": -1}, id="negative-count"),
        pytest.param({"objective": "finish", "max_no_progress_continuations": None}, id="null-limit"),
        pytest.param(_JSON_OVERWRITE_GOAL, id="json-overwrite"),
        pytest.param(_KEYED_OVERWRITE_GOAL, id="reserved-key"),
    ],
)
def test_state_route_rejects_invalid_goal_without_changing_checkpoint(monkeypatch, mode, invalid_goal):
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

        rejected = client.post("/api/threads/goal-input-http/state", json={"values": {"goal": invalid_goal, "title": "must not write"}})
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
@pytest.mark.parametrize(
    "invalid_goal",
    [
        pytest.param({"status": "active"}, id="missing-objective"),
        pytest.param({"objective": "finish", "continuation_count": "many"}, id="invalid-counter"),
        pytest.param(_JSON_OVERWRITE_GOAL, id="json-overwrite"),
        pytest.param(_KEYED_OVERWRITE_GOAL, id="reserved-key"),
    ],
)
def test_run_routes_reject_invalid_goal_before_admission(monkeypatch, path, invalid_goal):
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
        rejected = client.post(path, json={"input": {"goal": invalid_goal}})

    assert rejected.status_code == 400, rejected.text
    factory.assert_not_called()
    app.state.run_manager.create_or_reject.assert_not_awaited()
    worker.assert_not_awaited()
