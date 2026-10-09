"""Tests for surfacing a parked run's approval payload over the REST API.

A run gated by ``interrupt_on`` parks with its payload on ``snapshot.tasks``
only — the checkpoint's channel values never carry ``__interrupt__`` (LangGraph
records it as a pending write). So every REST reader that wants to show the
pending approval has to project it from the snapshot's tasks, and all of them
must agree on one shape, or a client reconciling a resumed stream against a
refetched snapshot sees the same approval two different ways.
"""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from _router_auth_helpers import make_authed_test_app
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Interrupt

from app.gateway.routers import threads
from deerflow.persistence.thread_meta.memory import THREADS_NS, MemoryThreadMetaStore

_APPROVAL_PAYLOAD = {"action_requests": [{"name": "bash_tool", "args": {"command": "rm -rf build"}}]}
_TASK_ID = "task-parked"
_THREAD_ID = "thread-parked"


class _PermissiveThreadMetaStore(MemoryThreadMetaStore):
    """Skip owner filtering: the stub auth stamps a fresh user id per request."""

    async def _get_owned_record(self, thread_id, user_id, method_name):  # type: ignore[override]
        item = await self._store.aget(THREADS_NS, thread_id)
        return dict(item.value) if item is not None else None

    async def check_access(self, thread_id, user_id, *, require_existing=False):  # type: ignore[override]
        return True


class _StubRunManager:
    async def list_by_thread(self, _thread_id, *, user_id=None, limit=100):
        return []


class _StubAccessor:
    """Return one fixed snapshot for both the point read and the history walk."""

    def __init__(self, snapshot: SimpleNamespace):
        self.snapshot = snapshot

    async def aget(self, _config):
        return self.snapshot

    async def ahistory(self, _config, *, limit=None):
        return [self.snapshot][:limit]


def _parked_snapshot(*, interrupts: tuple[Interrupt, ...] = (Interrupt(value=_APPROVAL_PAYLOAD, id="int-1"),)) -> SimpleNamespace:
    """A snapshot shaped like the one a real parked graph produces.

    ``values`` deliberately omits ``__interrupt__``: a probe against a graph
    parked by ``interrupt()`` shows the channel absent from the checkpoint,
    with the payload reachable only through the task.
    """
    return SimpleNamespace(
        values={"messages": [AIMessage(id="a1", content="about to run a command")]},
        config={"configurable": {"thread_id": _THREAD_ID, "checkpoint_ns": "", "checkpoint_id": "ckpt-2"}},
        parent_config={"configurable": {"checkpoint_id": "ckpt-1"}},
        metadata={"step": 2, "created_at": "2026-09-11T00:00:00+00:00"},
        next=("tools",),
        tasks=(SimpleNamespace(id=_TASK_ID, name="tools", error=None, interrupts=interrupts),),
        created_at="2026-09-11T00:00:00+00:00",
    )


def _build_app() -> tuple[FastAPI, InMemorySaver]:
    app = make_authed_test_app()
    store = InMemoryStore()
    checkpointer = InMemorySaver()
    app.state.store = store
    app.state.checkpointer = checkpointer
    app.state.run_manager = _StubRunManager()
    app.state.thread_store = _PermissiveThreadMetaStore(store)
    app.state.run_event_store = SimpleNamespace(find_latest_ai_message_run_ids=AsyncMock(return_value={}))
    app.include_router(threads.router)

    async def _seed() -> None:
        await store.aput(
            THREADS_NS,
            _THREAD_ID,
            {
                "thread_id": _THREAD_ID,
                "status": "idle",
                "created_at": "2026-09-11T00:00:00+00:00",
                "updated_at": "2026-09-11T00:00:00+00:00",
                "metadata": {},
            },
        )
        await checkpointer.aput(
            {"configurable": {"thread_id": _THREAD_ID, "checkpoint_ns": ""}},
            empty_checkpoint(),
            {"step": 2, "source": "loop", "writes": {}, "parents": {}},
            {},
        )

    asyncio.run(_seed())
    return app, checkpointer


def _client(snapshot: SimpleNamespace):
    """Drive the routers with a fixed snapshot, patching only the accessor boundary.

    ``get_thread`` resolves the accessor through the run-scoped boundary while
    ``/state`` and ``/history`` go through the thread-scoped one, so both entry
    points have to be stubbed for one snapshot to reach all three readers.
    """
    app, _checkpointer = _build_app()
    accessor = _StubAccessor(snapshot)
    config = {"configurable": {"thread_id": _THREAD_ID, "checkpoint_ns": ""}}
    patchers = ExitStack()
    patchers.enter_context(
        patch(
            "app.gateway.routers.threads.abuild_checkpoint_state_accessor",
            new=AsyncMock(return_value=(accessor, config)),
        )
    )
    patchers.enter_context(
        patch(
            "app.gateway.routers.threads.build_thread_checkpoint_state_accessor",
            new=AsyncMock(return_value=(accessor, config)),
        )
    )
    return patchers, app


def test_get_thread_maps_pending_interrupts_by_task_id() -> None:
    """``interrupts`` was hardcoded empty, so a parked thread looked idle."""
    patcher, app = _client(_parked_snapshot())

    with patcher, TestClient(app) as client:
        response = client.get(f"/api/threads/{_THREAD_ID}")

    assert response.status_code == 200, response.text
    body = response.json()
    # The LangGraph SDK's ``Thread.interrupts`` is a task-id -> interrupts mapping.
    assert body["interrupts"] == {_TASK_ID: [{"id": "int-1", "value": _APPROVAL_PAYLOAD}]}
    assert body["status"] == "interrupted"


def test_get_thread_reports_no_interrupts_for_a_task_without_one() -> None:
    """An ordinary in-flight task must not appear in the mapping at all."""
    patcher, app = _client(_parked_snapshot(interrupts=()))

    with patcher, TestClient(app) as client:
        response = client.get(f"/api/threads/{_THREAD_ID}")

    assert response.status_code == 200, response.text
    assert response.json()["interrupts"] == {}


def test_thread_state_keeps_the_interrupt_payload_on_its_task() -> None:
    """``/state`` projected only ``{id, name}``, dropping the approval payload."""
    patcher, app = _client(_parked_snapshot())

    with patcher, TestClient(app) as client:
        response = client.get(f"/api/threads/{_THREAD_ID}/state")

    assert response.status_code == 200, response.text
    assert response.json()["tasks"] == [{"id": _TASK_ID, "name": "tools", "interrupts": [{"id": "int-1", "value": _APPROVAL_PAYLOAD}]}]


def test_thread_state_omits_interrupts_for_an_ordinary_task() -> None:
    """Older clients parse ``{id, name}``; don't grow an empty key on them."""
    patcher, app = _client(_parked_snapshot(interrupts=()))

    with patcher, TestClient(app) as client:
        response = client.get(f"/api/threads/{_THREAD_ID}/state")

    assert response.status_code == 200, response.text
    assert response.json()["tasks"] == [{"id": _TASK_ID, "name": "tools"}]


def test_thread_history_carries_pending_tasks() -> None:
    """``HistoryEntry`` had no ``tasks`` field, so history hid parked approvals.

    A client that reloads a thread reads history, not just ``/state``; without
    this it cannot tell a finished turn from one waiting on the user.
    """
    patcher, app = _client(_parked_snapshot())

    with patcher, TestClient(app) as client:
        response = client.post(f"/api/threads/{_THREAD_ID}/history", json={"limit": 10})

    assert response.status_code == 200, response.text
    entries = response.json()
    assert entries, "expected at least one history entry"
    assert entries[0]["tasks"] == [{"id": _TASK_ID, "name": "tools", "interrupts": [{"id": "int-1", "value": _APPROVAL_PAYLOAD}]}]


def test_thread_history_reports_no_tasks_for_a_settled_checkpoint() -> None:
    snapshot = _parked_snapshot()
    snapshot.tasks = ()
    snapshot.next = ()
    patcher, app = _client(snapshot)

    with patcher, TestClient(app) as client:
        response = client.post(f"/api/threads/{_THREAD_ID}/history", json={"limit": 10})

    assert response.status_code == 200, response.text
    assert response.json()[0]["tasks"] == []


def test_state_and_thread_reads_agree_on_the_interrupt_payload() -> None:
    """Both surfaces share one projection, so a client can reconcile them."""
    patcher, app = _client(_parked_snapshot())

    with patcher, TestClient(app) as client:
        thread_body = client.get(f"/api/threads/{_THREAD_ID}").json()
        state_body = client.get(f"/api/threads/{_THREAD_ID}/state").json()

    assert thread_body["interrupts"][_TASK_ID] == state_body["tasks"][0]["interrupts"]
