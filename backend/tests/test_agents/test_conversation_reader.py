"""Request-independent transcript reads share the HTTP history visibility rules."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

from app.gateway.conversation_reader import read_visible_message_page
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.manager import EditReplayVisibility


def _run_manager(*, superseded=(), hidden_sources=(), hidden_attempts=()):
    manager = AsyncMock()
    manager.list_successful_regenerate_sources.return_value = set(superseded)
    manager.list_edit_replay_visibility.return_value = EditReplayVisibility(
        hidden_source_run_ids=frozenset(hidden_sources),
        hidden_attempt_run_ids=frozenset(hidden_attempts),
    )
    return manager


async def _put(store, message_id, *, message_type="ai", run_id="run-1", caller="lead_agent", hidden=False):
    return await store.put(
        thread_id="source-thread",
        run_id=run_id,
        event_type="llm.human.input" if message_type == "human" else "llm.ai.response",
        category="message",
        content={"type": message_type, "id": message_id, "content": message_id, "additional_kwargs": {"hide_from_ui": hidden}},
        metadata={"caller": caller},
    )


def _plain_visible_text(row):
    message = row["content"]
    return message["type"] in {"human", "ai"} and not message["additional_kwargs"].get("hide_from_ui")


def test_reader_filters_before_paging_and_keeps_explicit_owner_on_every_query():
    store = MemoryRunEventStore()
    manager = _run_manager(superseded={"superseded"}, hidden_sources={"edited"}, hidden_attempts={"failed-edit"})

    async def exercise():
        await _put(store, "first", message_type="human")
        await _put(store, "replaced", run_id="superseded")
        await _put(store, "old-edit", run_id="edited")
        await _put(store, "failed-attempt", run_id="failed-edit")
        await _put(store, "second")
        await _put(store, "internal", caller="middleware:title")
        await _put(store, "child", caller="subagent:general-purpose")
        await _put(store, "tool-output", message_type="tool")
        await _put(store, "hidden-context", message_type="human", hidden=True)
        await _put(store, "third")
        store.list_messages = AsyncMock(wraps=store.list_messages)
        latest, has_more = await read_visible_message_page(
            event_store=store,
            run_manager=manager,
            thread_id="source-thread",
            user_id="source-owner",
            limit=2,
            message_filter=_plain_visible_text,
            batch_size=2,
        )
        older, older_has_more = await read_visible_message_page(
            event_store=store,
            run_manager=manager,
            thread_id="source-thread",
            user_id="source-owner",
            limit=2,
            before_seq=latest[0]["seq"],
            message_filter=_plain_visible_text,
            batch_size=2,
        )
        return latest, has_more, older, older_has_more

    latest, has_more, older, older_has_more = asyncio.run(exercise())

    assert [row["content"]["id"] for row in latest] == ["second", "third"]
    assert has_more is True
    assert [row["content"]["id"] for row in older] == ["first"]
    assert older_has_more is False
    assert len(store.list_messages.await_args_list) > 2
    for call in store.list_messages.await_args_list:
        assert call.args == ("source-thread",)
        assert call.kwargs["user_id"] == "source-owner"
    for query in (manager.list_successful_regenerate_sources, manager.list_edit_replay_visibility):
        assert query.await_count == 2
        for call in query.await_args_list:
            assert call.args == ("source-thread",)
            assert call.kwargs == {"user_id": "source-owner"}


def test_default_reader_keeps_parent_tool_results_and_does_not_mutate_source():
    store = MemoryRunEventStore()

    async def exercise():
        await _put(store, "prompt", message_type="human")
        await _put(store, "private-child-answer", caller="subagent:researcher")
        await _put(store, "parent-task-result", message_type="tool", caller="subagent:researcher")
        await _put(store, "answer")
        before = deepcopy(await store.list_messages("source-thread"))
        rows, has_more = await read_visible_message_page(
            event_store=store,
            run_manager=_run_manager(),
            thread_id="source-thread",
            user_id="owner",
            limit=10,
        )
        after = await store.list_messages("source-thread")
        return rows, has_more, before, after

    rows, has_more, before, after = asyncio.run(exercise())

    assert [row["content"]["id"] for row in rows] == ["prompt", "parent-task-result", "answer"]
    assert has_more is False
    assert after == before


def test_reader_reports_exhaustion_when_only_filtered_messages_remain():
    store = MemoryRunEventStore()

    async def exercise():
        for index in range(5):
            await _put(store, f"tool-{index}", message_type="tool")
        return await read_visible_message_page(
            event_store=store,
            run_manager=_run_manager(),
            thread_id="source-thread",
            user_id="owner",
            limit=2,
            message_filter=_plain_visible_text,
            batch_size=2,
        )

    assert asyncio.run(exercise()) == ([], False)
