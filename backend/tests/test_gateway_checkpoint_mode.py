"""Dual-mode (full/delta) parity for the gateway thread-state endpoints.

Drives ``GET /api/threads/{id}``, ``GET /api/threads/{id}/state`` and
``POST /api/threads/{id}/history`` through the real route stack
(``build_thread_checkpoint_state_accessor`` -> factory-built graph ->
``CheckpointStateAccessor``) against a real ``InMemorySaver``, once per
checkpoint channel mode, and asserts the wire responses are identical apart
from checkpoint ids/timestamps. The delta storage layout must be invisible
to API consumers.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph
from langgraph.store.memory import InMemoryStore

from app.gateway import services as gateway_services
from app.gateway.routers import threads
from deerflow.agents.thread_state import get_thread_state_schema
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
from deerflow.runtime.checkpoint_mode import checkpoint_metadata_uses_delta, inject_checkpoint_mode

_THREAD_ID = "thread-gateway-parity"


@pytest.fixture
def _stub_app_config():
    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))
    yield
    reset_app_config()


def _build_reply_graph(mode: str, checkpointer: Any):
    async def _reply(state: dict[str, Any]) -> dict[str, Any]:
        n = len(state.get("messages") or [])
        return {"messages": [AIMessage(content=f"answer-{n}", id=f"a{n}")]}

    builder = StateGraph(get_thread_state_schema(mode))
    builder.add_node("reply", _reply)
    builder.set_entry_point("reply")
    builder.set_finish_point("reply")
    return builder.compile(checkpointer=checkpointer)


def _message_wire_shape(messages: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    return [(message.get("type"), message.get("content"), message.get("id")) for message in messages]


def _run_gateway_flow(mode: str, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    app = make_authed_test_app()
    store = InMemoryStore()
    checkpointer = InMemorySaver()
    app.state.store = store
    app.state.checkpointer = checkpointer
    app.state.thread_store = MemoryThreadMetaStore(store)
    app.state.checkpoint_channel_mode = mode
    app.state.run_event_store = SimpleNamespace()
    app.include_router(threads.router)

    graph = _build_reply_graph(mode, checkpointer)
    monkeypatch.setattr(
        gateway_services,
        "resolve_agent_factory",
        lambda assistant_id=None: lambda config: graph,
    )

    config: dict[str, Any] = {"configurable": {"thread_id": _THREAD_ID}}
    inject_checkpoint_mode(config, mode)
    for i in range(2):
        asyncio.run(graph.ainvoke({"messages": [HumanMessage(content=f"question-{i}", id=f"h{i}")]}, config))

    with TestClient(app) as client:
        thread_response = client.get(f"/api/threads/{_THREAD_ID}")
        state_response = client.get(f"/api/threads/{_THREAD_ID}/state")
        history_response = client.post(f"/api/threads/{_THREAD_ID}/history", json={"limit": 10})

    assert thread_response.status_code == 200, thread_response.text
    assert state_response.status_code == 200, state_response.text
    assert history_response.status_code == 200, history_response.text

    thread_payload = thread_response.json()
    state_payload = state_response.json()
    history_payload = history_response.json()

    return {
        "thread_status": thread_payload["status"],
        "thread_messages": _message_wire_shape(thread_payload["values"]["messages"]),
        "state_messages": _message_wire_shape(state_payload["values"]["messages"]),
        "history_messages": [_message_wire_shape(snapshot["values"].get("messages", [])) for snapshot in history_payload],
    }


def test_thread_state_endpoints_are_mode_invariant(_stub_app_config, monkeypatch: pytest.MonkeyPatch) -> None:
    full = _run_gateway_flow("full", monkeypatch)
    monkeypatch.undo()
    delta = _run_gateway_flow("delta", monkeypatch)
    assert full == delta
    # Guard against a vacuous pass: the flow must have observed real messages.
    assert full["thread_messages"], "expected seeded messages in the thread response"
    assert any(full["history_messages"]), "expected history snapshots with messages"


def test_full_mode_gateway_rejects_delta_thread_with_409(_stub_app_config, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail-closed gate at the HTTP boundary, against a real checkpointer.

    A full-mode process opening a delta thread must get a precise 409 naming
    the cause — not a generic 500 that forces operators to grep logs. Seeds a
    real delta checkpoint through the delta graph (marker + LangGraph delta
    counters land in checkpoint metadata), then exercises every state surface
    of the threads router in full mode.
    """
    app = make_authed_test_app()
    store = InMemoryStore()
    checkpointer = InMemorySaver()
    app.state.store = store
    app.state.checkpointer = checkpointer
    app.state.thread_store.get = AsyncMock(return_value=None)
    app.state.checkpoint_channel_mode = "full"
    app.state.run_event_store = SimpleNamespace()
    app.include_router(threads.router)

    full_graph = _build_reply_graph("full", checkpointer)
    monkeypatch.setattr(
        gateway_services,
        "resolve_agent_factory",
        lambda assistant_id=None: lambda config: full_graph,
    )

    # Seed through the delta graph so the checkpoint carries the delta marker.
    delta_graph = _build_reply_graph("delta", checkpointer)
    config: dict[str, Any] = {"configurable": {"thread_id": _THREAD_ID}}
    inject_checkpoint_mode(config, "delta")
    asyncio.run(delta_graph.ainvoke({"messages": [HumanMessage(content="question", id="h0")]}, config))
    latest = asyncio.run(checkpointer.aget_tuple({"configurable": {"thread_id": _THREAD_ID, "checkpoint_ns": ""}}))
    assert checkpoint_metadata_uses_delta(latest.metadata), "seed did not produce a delta checkpoint"

    with TestClient(app) as client:
        state_response = client.get(f"/api/threads/{_THREAD_ID}/state")
        assert state_response.status_code == 409, state_response.text
        assert "requires delta mode" in state_response.json()["detail"]
        assert _THREAD_ID in state_response.json()["detail"]

        update_response = client.post(f"/api/threads/{_THREAD_ID}/state", json={"values": {"title": "x"}})
        assert update_response.status_code == 409, update_response.text
        assert "requires delta mode" in update_response.json()["detail"]

        history_response = client.post(f"/api/threads/{_THREAD_ID}/history", json={"limit": 10})
        assert history_response.status_code == 409, history_response.text
        assert "requires delta mode" in history_response.json()["detail"]

        thread_response = client.get(f"/api/threads/{_THREAD_ID}")
        assert thread_response.status_code == 409, thread_response.text
        assert "requires delta mode" in thread_response.json()["detail"]


def test_full_mode_state_reads_degrade_to_raw_checkpointer_when_factory_fails(_stub_app_config, monkeypatch: pytest.MonkeyPatch) -> None:
    """Full-mode read endpoints survive a broken agent factory.

    Full-mode checkpoints persist complete channel_values, so when the agent
    factory cannot build the graph (bad model config, MCP server down), state
    reads degrade to raw checkpointer reads instead of 500ing. The fail-closed
    delta gate must still apply on the degraded path.
    """
    app = make_authed_test_app()
    store = InMemoryStore()
    checkpointer = InMemorySaver()
    app.state.store = store
    app.state.checkpointer = checkpointer
    app.state.thread_store.get = AsyncMock(return_value=None)
    app.state.checkpoint_channel_mode = "full"
    app.state.run_event_store = SimpleNamespace()
    app.include_router(threads.router)

    full_graph = _build_reply_graph("full", checkpointer)
    config: dict[str, Any] = {"configurable": {"thread_id": _THREAD_ID}}
    inject_checkpoint_mode(config, "full")
    for i in range(2):
        asyncio.run(full_graph.ainvoke({"messages": [HumanMessage(content=f"question-{i}", id=f"h{i}")]}, config))
    latest = asyncio.run(checkpointer.aget_tuple(config))
    assert latest is not None
    latest_created_at = latest.checkpoint["ts"]

    def _broken_factory(assistant_id=None):
        def _factory(config):
            raise RuntimeError("model config broken")

        return _factory

    monkeypatch.setattr(gateway_services, "resolve_agent_factory", _broken_factory)

    with TestClient(app) as client:
        state_response = client.get(f"/api/threads/{_THREAD_ID}/state")
        assert state_response.status_code == 200, state_response.text
        values = state_response.json()["values"]
        assert state_response.json()["created_at"] == latest_created_at
        assert state_response.json()["checkpoint"]["ts"] == latest_created_at
        assert _message_wire_shape(values["messages"]) == [
            ("human", "question-0", "h0"),
            ("ai", "answer-1", "a1"),
            ("human", "question-1", "h1"),
            ("ai", "answer-3", "a3"),
        ]
        # next/tasks are not derivable without the compiled graph.
        assert state_response.json()["next"] == []

        history_response = client.post(f"/api/threads/{_THREAD_ID}/history", json={"limit": 10})
        assert history_response.status_code == 200, history_response.text
        entries = history_response.json()
        assert len(entries) >= 2
        assert all(entry["created_at"] for entry in entries)

        # History pagination: config.checkpoint_id is the *inclusive* anchor
        # (pregel semantics), so the degraded path must include it too.
        anchor_id = entries[1]["checkpoint_id"]
        paged_response = client.post(f"/api/threads/{_THREAD_ID}/history", json={"limit": 10, "before": anchor_id})
        assert paged_response.status_code == 200, paged_response.text
        assert paged_response.json()[0]["checkpoint_id"] == anchor_id

        app.state.thread_store.get = AsyncMock(
            return_value={
                "thread_id": _THREAD_ID,
                "assistant_id": None,
                "status": "interrupted",
                "created_at": latest_created_at,
                "updated_at": latest_created_at,
                "metadata": {},
            }
        )
        thread_response = client.get(f"/api/threads/{_THREAD_ID}")
        assert thread_response.status_code == 200, thread_response.text
        assert thread_response.json()["status"] == "interrupted"
        assert _message_wire_shape(thread_response.json()["values"]["messages"]) == [
            ("human", "question-0", "h0"),
            ("ai", "answer-1", "a1"),
            ("human", "question-1", "h1"),
            ("ai", "answer-3", "a3"),
        ]

        # The fail-closed gate still applies on the degraded path: a delta
        # checkpoint is a precise 409, never silently served as partial state.
        delta_graph = _build_reply_graph("delta", checkpointer)
        delta_config: dict[str, Any] = {"configurable": {"thread_id": "thread-degraded-delta"}}
        inject_checkpoint_mode(delta_config, "delta")
        asyncio.run(delta_graph.ainvoke({"messages": [HumanMessage(content="q", id="h0")]}, delta_config))
        delta_response = client.get("/api/threads/thread-degraded-delta/state")
        assert delta_response.status_code == 409, delta_response.text
        assert "requires delta mode" in delta_response.json()["detail"]


def test_mutation_accessor_fails_closed_when_thread_metadata_lookup_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    app = make_authed_test_app()
    app.state.thread_store.get = AsyncMock(side_effect=RuntimeError("metadata store unavailable"))
    resolve_factory = AsyncMock()
    monkeypatch.setattr(gateway_services, "resolve_agent_factory", resolve_factory)

    with pytest.raises(RuntimeError, match="metadata store unavailable"):
        asyncio.run(
            gateway_services.build_thread_checkpoint_state_mutation_accessor(
                SimpleNamespace(app=app),
                thread_id="custom-assistant-thread",
                as_node="manual_state_update",
            )
        )

    resolve_factory.assert_not_called()
