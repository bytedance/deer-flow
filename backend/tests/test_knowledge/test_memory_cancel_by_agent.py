"""Regression for #5037: scoped cancellation of buffered memory extraction."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.backends.deermem.deermem.core.queue import ConversationContext
from deerflow.agents.memory.manager import MemoryManager, get_memory_manager, reset_memory_manager
from deerflow.config.memory_config import MemoryConfig, get_memory_config, set_memory_config


def test_deermem_cancel_by_agent_uses_canonical_bucket(tmp_path) -> None:
    mem = DeerMem(backend_config={"storage_path": str(tmp_path)})
    with patch.object(mem._queue, "_schedule_timer"):
        mem._queue.add(thread_id="t1", messages=["m"], agent_name="research-agent", user_id="u1")
        mem._queue.add(thread_id="t2", messages=["m"], agent_name="other", user_id="u1")

    removed = mem.cancel_by_agent("Research-Agent", user_id="u1")

    assert removed == 1
    assert mem._queue.pending_count == 1
    assert mem._queue._items[0].agent_name == "other"


def test_deermem_clear_memory_cancels_before_and_after_clear(tmp_path) -> None:
    mem = DeerMem(backend_config={"storage_path": str(tmp_path)})
    mem._queue._items = [
        ConversationContext(thread_id="t1", messages=["m"], agent_name="research-agent", user_id="u1"),
        ConversationContext(thread_id="t2", messages=["m"], agent_name="other", user_id="u1"),
    ]
    mem._updater = MagicMock()

    def _clear(**kwargs):
        mem._queue._items.append(ConversationContext(thread_id="t-mid", messages=["m"], agent_name="research-agent", user_id="u1"))
        return {"facts": []}

    mem._updater.clear_memory_data.side_effect = _clear

    mem.clear_memory(agent_name="research-agent", user_id="u1")

    assert [c.agent_name for c in mem._queue._items] == ["other"]
    mem._updater.clear_memory_data.assert_called_once_with(agent_name="research-agent", user_id="u1")


def test_deermem_clear_all_cancels_all_pending_for_user(tmp_path) -> None:
    mem = DeerMem(backend_config={"storage_path": str(tmp_path)})
    mem._queue._items = [
        ConversationContext(thread_id="t1", messages=["m"], agent_name="a", user_id="u1"),
        ConversationContext(thread_id="t2", messages=["m"], agent_name="b", user_id="u1"),
        ConversationContext(thread_id="t3", messages=["m"], agent_name="a", user_id="u2"),
    ]
    mem._updater = MagicMock()
    mem._updater.clear_all_memory_data.return_value = {"facts": []}

    mem.clear_memory(user_id="u1")

    assert mem._queue.pending_count == 1
    assert mem._queue._items[0].user_id == "u2"
    mem._updater.clear_all_memory_data.assert_called_once_with(user_id="u1")


def test_base_memory_manager_cancel_by_agent_defaults_to_zero() -> None:
    class _Bare(MemoryManager):
        def add(self, thread_id, messages, *, agent_name=None, user_id=None, trace_id=None) -> None:
            return None

        def get_context(self, user_id, *, agent_name=None, thread_id=None) -> str:
            return ""

        @classmethod
        def from_config(cls, backend_config, *, mode="middleware", **host_hooks):
            return cls(backend_config=backend_config or {}, mode=mode)

    assert _Bare().cancel_by_agent("x", user_id="u") == 0


def test_deermem_cancel_by_agent_forwards_scoped_queue_kwargs(tmp_path) -> None:
    """Manager mapping: None agent → all_agents; named agent → canonical bucket."""
    mem = DeerMem(backend_config={"storage_path": str(tmp_path)})
    queue = MagicMock()
    queue.cancel_by_agent.return_value = 0
    mem._queue = queue

    mem.cancel_by_agent(None, user_id=None)
    queue.cancel_by_agent.assert_called_with(user_id=None, all_agents=True)

    mem.cancel_by_agent("Research-Agent", user_id="u1")
    queue.cancel_by_agent.assert_called_with("research-agent", user_id="u1", all_agents=False)


def test_delete_agent_cancels_before_and_after_successful_delete(tmp_path) -> None:
    """Cancel must run before store.delete so a timer cannot resurrect mid-rmtree."""
    from app.gateway.routers import agents as agents_router

    orig = get_memory_config()
    reset_memory_manager()
    set_memory_config(
        MemoryConfig(
            enabled=True,
            manager_class="deermem",
            backend_config={"storage_path": str(tmp_path / "memory")},
        )
    )
    try:
        manager = get_memory_manager()
        with patch.object(manager._queue, "_schedule_timer"):
            manager._queue.add(thread_id="t1", messages=["m"], agent_name="gone", user_id="user-1")
            manager._queue.add(thread_id="t2", messages=["m"], agent_name="keep", user_id="user-1")

        store = MagicMock()
        order: list[str] = []

        def _delete(name, *, user_id=None):
            order.append("delete")
            manager._queue._items.append(ConversationContext(thread_id="t-mid", messages=["m"], agent_name="gone", user_id="user-1"))
            return "deleted"

        store.delete.side_effect = _delete
        real_cancel = agents_router._cancel_pending_memory_for_agent

        def tracked_cancel(name, user_id):
            order.append("cancel")
            return real_cancel(name, user_id)

        with (
            patch.object(agents_router, "_require_agents_api_enabled"),
            patch.object(agents_router, "_validate_agent_name"),
            patch.object(agents_router, "_normalize_agent_name", side_effect=lambda n: n.lower()),
            patch.object(agents_router, "get_effective_user_id", return_value="user-1"),
            patch.object(agents_router, "get_agent_store", return_value=store),
            patch.object(agents_router, "_cancel_pending_memory_for_agent", side_effect=tracked_cancel),
        ):
            asyncio.run(agents_router.delete_agent("Gone"))

        assert order == ["cancel", "delete", "cancel"]
        assert manager._queue.pending_count == 1
        assert manager._queue._items[0].agent_name == "keep"
        store.delete.assert_called_once_with("gone", user_id="user-1")
    finally:
        set_memory_config(orig)
        reset_memory_manager()


def test_delete_agent_still_cancels_when_memory_disabled(tmp_path) -> None:
    """Disabling memory must not skip cancel of an already-live queue."""
    from app.gateway.routers import agents as agents_router

    orig = get_memory_config()
    reset_memory_manager()
    set_memory_config(
        MemoryConfig(
            enabled=True,
            manager_class="deermem",
            backend_config={"storage_path": str(tmp_path / "memory")},
        )
    )
    try:
        manager = get_memory_manager()
        with patch.object(manager._queue, "_schedule_timer"):
            manager._queue.add(thread_id="t1", messages=["m"], agent_name="gone", user_id="user-1")

        # Hot-disable after work was queued; delete must still cancel.
        set_memory_config(MemoryConfig(enabled=False, manager_class="deermem"))

        store = MagicMock()
        store.delete.return_value = "deleted"

        with (
            patch.object(agents_router, "_require_agents_api_enabled"),
            patch.object(agents_router, "_validate_agent_name"),
            patch.object(agents_router, "_normalize_agent_name", side_effect=lambda n: n.lower()),
            patch.object(agents_router, "get_effective_user_id", return_value="user-1"),
            patch.object(agents_router, "get_agent_store", return_value=store),
        ):
            asyncio.run(agents_router.delete_agent("Gone"))

        assert manager._queue.pending_count == 0
    finally:
        set_memory_config(orig)
        reset_memory_manager()


def test_delete_agent_still_cancels_before_rejected_delete() -> None:
    """Pre-delete cancel is intentional even when delete later 404s."""
    from app.gateway.routers import agents as agents_router

    store = MagicMock()
    store.delete.return_value = "missing"
    manager = MagicMock()

    with (
        patch.object(agents_router, "_require_agents_api_enabled"),
        patch.object(agents_router, "_validate_agent_name"),
        patch.object(agents_router, "_normalize_agent_name", side_effect=lambda n: n.lower()),
        patch.object(agents_router, "get_effective_user_id", return_value="user-1"),
        patch.object(agents_router, "get_agent_store", return_value=store),
        patch.object(agents_router, "get_memory_manager", return_value=manager),
    ):
        try:
            asyncio.run(agents_router.delete_agent("ghost"))
            raise AssertionError("expected 404")
        except HTTPException as exc:
            assert exc.status_code == 404

    manager.cancel_by_agent.assert_called_once_with("ghost", user_id="user-1")
