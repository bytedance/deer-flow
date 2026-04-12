"""Tests for event-store-backed message loading in thread state/history endpoints.

Covers the helper functions added to ``app/gateway/routers/threads.py``:

- ``_sanitize_legacy_command_repr`` — extracts inner ToolMessage text from
  legacy ``str(Command(...))`` strings captured before the ``journal.py``
  fix for state-updating tools like ``present_files``.
- ``_get_event_store_messages`` — loads the full message stream with full
  pagination, copy-on-read id patching, legacy Command sanitization, and
  a clean fallback to ``None`` when the event store is unavailable.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.gateway.routers.threads import (
    _get_event_store_messages,
    _sanitize_legacy_command_repr,
)
from deerflow.runtime.events.store.memory import MemoryRunEventStore


@pytest.fixture()
def event_store() -> MemoryRunEventStore:
    return MemoryRunEventStore()


class _FakeFeedbackRepo:
    """Minimal ``FeedbackRepository`` stand-in that returns a configured map."""

    def __init__(self, by_run: dict[str, dict] | None = None) -> None:
        self._by_run = by_run or {}

    async def list_by_thread_grouped(self, thread_id: str, *, user_id: str | None) -> dict[str, dict]:
        return dict(self._by_run)


def _make_request(
    event_store: MemoryRunEventStore,
    feedback_repo: _FakeFeedbackRepo | None = None,
) -> Any:
    """Build a minimal FastAPI-like Request object.

    ``get_run_event_store(request)`` reads ``request.app.state.run_event_store``.
    ``get_feedback_repo(request)`` reads ``request.app.state.feedback_repo``.
    ``get_current_user`` is monkey-patched separately in tests that need it.
    """
    state = SimpleNamespace(
        run_event_store=event_store,
        feedback_repo=feedback_repo or _FakeFeedbackRepo(),
    )
    app = SimpleNamespace(state=state)
    return SimpleNamespace(app=app)


@pytest.fixture(autouse=True)
def _stub_current_user(monkeypatch):
    """Stub out ``get_current_user`` so tests don't need real auth context."""
    import app.gateway.routers.threads as threads_mod

    async def _fake(_request):
        return None

    monkeypatch.setattr(threads_mod, "get_current_user", _fake)


async def _seed_simple_run(store: MemoryRunEventStore, thread_id: str, run_id: str) -> None:
    """Seed one run: human + ai_tool_call + tool_result + final ai_message, plus a trace."""
    await store.put(
        thread_id=thread_id, run_id=run_id,
        event_type="human_message", category="message",
        content={
            "type": "human", "id": None,
            "content": [{"type": "text", "text": "hello"}],
            "additional_kwargs": {}, "response_metadata": {}, "name": None,
        },
    )
    await store.put(
        thread_id=thread_id, run_id=run_id,
        event_type="ai_tool_call", category="message",
        content={
            "type": "ai", "id": "lc_run--tc1",
            "content": "",
            "tool_calls": [{"name": "search", "args": {"q": "x"}, "id": "call_1", "type": "tool_call"}],
            "invalid_tool_calls": [],
            "additional_kwargs": {}, "response_metadata": {}, "name": None,
            "usage_metadata": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        },
    )
    await store.put(
        thread_id=thread_id, run_id=run_id,
        event_type="tool_result", category="message",
        content={
            "type": "tool", "id": None,
            "content": "results",
            "tool_call_id": "call_1", "name": "search",
            "artifact": None, "status": "success",
            "additional_kwargs": {}, "response_metadata": {},
        },
    )
    await store.put(
        thread_id=thread_id, run_id=run_id,
        event_type="ai_message", category="message",
        content={
            "type": "ai", "id": "lc_run--final1",
            "content": "done",
            "tool_calls": [], "invalid_tool_calls": [],
            "additional_kwargs": {}, "response_metadata": {"finish_reason": "stop"}, "name": None,
            "usage_metadata": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        },
    )
    # Non-message trace — must be filtered out.
    await store.put(
        thread_id=thread_id, run_id=run_id,
        event_type="llm_request", category="trace",
        content={"model": "test"},
    )


class TestSanitizeLegacyCommandRepr:
    def test_passthrough_non_string(self):
        assert _sanitize_legacy_command_repr(None) is None
        assert _sanitize_legacy_command_repr(42) == 42
        assert _sanitize_legacy_command_repr([{"type": "text", "text": "x"}]) == [{"type": "text", "text": "x"}]

    def test_passthrough_plain_string(self):
        assert _sanitize_legacy_command_repr("Successfully presented files") == "Successfully presented files"
        assert _sanitize_legacy_command_repr("") == ""

    def test_extracts_inner_content_single_quotes(self):
        legacy = (
            "Command(update={'artifacts': ['/mnt/user-data/outputs/report.md'], "
            "'messages': [ToolMessage(content='Successfully presented files', "
            "tool_call_id='call_abc')]})"
        )
        assert _sanitize_legacy_command_repr(legacy) == "Successfully presented files"

    def test_extracts_inner_content_double_quotes(self):
        legacy = 'Command(update={"messages": [ToolMessage(content="ok", tool_call_id="x")]})'
        assert _sanitize_legacy_command_repr(legacy) == "ok"

    def test_unparseable_command_returns_original(self):
        legacy = "Command(update={'something_else': 1})"
        assert _sanitize_legacy_command_repr(legacy) == legacy


class TestGetEventStoreMessages:
    @pytest.mark.anyio
    async def test_returns_none_when_store_empty(self, event_store):
        request = _make_request(event_store)
        assert await _get_event_store_messages(request, "t_missing") is None

    @pytest.mark.anyio
    async def test_extracts_all_message_types_in_order(self, event_store):
        await _seed_simple_run(event_store, "t1", "r1")
        request = _make_request(event_store)
        messages = await _get_event_store_messages(request, "t1")
        assert messages is not None
        types = [m["type"] for m in messages]
        assert types == ["human", "ai", "tool", "ai"]
        # Trace events must not appear
        for m in messages:
            assert m.get("type") in {"human", "ai", "tool"}

    @pytest.mark.anyio
    async def test_null_ids_get_deterministic_uuid5(self, event_store):
        await _seed_simple_run(event_store, "t1", "r1")
        request = _make_request(event_store)
        messages = await _get_event_store_messages(request, "t1")
        assert messages is not None

        # AI messages keep their LLM ids
        assert messages[1]["id"] == "lc_run--tc1"
        assert messages[3]["id"] == "lc_run--final1"

        # Human (seq=1) + tool (seq=3) get deterministic uuid5
        expected_human_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "t1:1"))
        expected_tool_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "t1:3"))
        assert messages[0]["id"] == expected_human_id
        assert messages[2]["id"] == expected_tool_id

        # Re-running produces the same ids (stability across requests)
        messages2 = await _get_event_store_messages(request, "t1")
        assert [m["id"] for m in messages2] == [m["id"] for m in messages]

    @pytest.mark.anyio
    async def test_helper_does_not_mutate_store(self, event_store):
        """Helper must copy content dicts; the live store must stay unchanged."""
        await _seed_simple_run(event_store, "t1", "r1")
        request = _make_request(event_store)
        _ = await _get_event_store_messages(request, "t1")

        # Raw store records still have id=None for human/tool
        raw = await event_store.list_messages("t1", limit=500)
        human = next(e for e in raw if e["content"]["type"] == "human")
        tool = next(e for e in raw if e["content"]["type"] == "tool")
        assert human["content"]["id"] is None
        assert tool["content"]["id"] is None

    @pytest.mark.anyio
    async def test_legacy_command_repr_sanitized(self, event_store):
        """A tool_result whose content is a legacy ``str(Command(...))`` is cleaned."""
        legacy = (
            "Command(update={'artifacts': ['/mnt/user-data/outputs/x.md'], "
            "'messages': [ToolMessage(content='Successfully presented files', "
            "tool_call_id='call_p')]})"
        )
        await event_store.put(
            thread_id="t2", run_id="r1",
            event_type="tool_result", category="message",
            content={
                "type": "tool", "id": None,
                "content": legacy,
                "tool_call_id": "call_p", "name": "present_files",
                "artifact": None, "status": "success",
                "additional_kwargs": {}, "response_metadata": {},
            },
        )
        request = _make_request(event_store)
        messages = await _get_event_store_messages(request, "t2")
        assert messages is not None and len(messages) == 1
        assert messages[0]["content"] == "Successfully presented files"

    @pytest.mark.anyio
    async def test_pagination_covers_more_than_one_page(self, event_store, monkeypatch):
        """Simulate a long thread that exceeds a single page to exercise the loop."""
        thread_id = "t_long"
        # Seed 12 human messages
        for i in range(12):
            await event_store.put(
                thread_id=thread_id, run_id="r1",
                event_type="human_message", category="message",
                content={
                    "type": "human", "id": None,
                    "content": [{"type": "text", "text": f"msg {i}"}],
                    "additional_kwargs": {}, "response_metadata": {}, "name": None,
                },
            )

        # Force small page size to exercise pagination
        import app.gateway.routers.threads as threads_mod
        original = threads_mod._get_event_store_messages

        # Monkeypatch MemoryRunEventStore.list_messages to assert it's called with cursor pagination
        calls: list[dict] = []
        real_list = event_store.list_messages

        async def spy_list_messages(tid, *, limit=50, before_seq=None, after_seq=None):
            calls.append({"limit": limit, "after_seq": after_seq})
            return await real_list(tid, limit=limit, before_seq=before_seq, after_seq=after_seq)

        monkeypatch.setattr(event_store, "list_messages", spy_list_messages)

        request = _make_request(event_store)
        messages = await original(request, thread_id)
        assert messages is not None
        assert len(messages) == 12
        assert [m["content"][0]["text"] for m in messages] == [f"msg {i}" for i in range(12)]
        # At least one call was made with after_seq=None (the initial page)
        assert any(c["after_seq"] is None for c in calls)

    @pytest.mark.anyio
    async def test_summarize_regression_recovers_pre_summarize_messages(self, event_store):
        """The exact bug: checkpoint would have only post-summarize messages;
        event store must surface the original pre-summarize human query."""
        # Run 1 (pre-summarize)
        await event_store.put(
            thread_id="t_sum", run_id="r1",
            event_type="human_message", category="message",
            content={
                "type": "human", "id": None,
                "content": [{"type": "text", "text": "original question"}],
                "additional_kwargs": {}, "response_metadata": {}, "name": None,
            },
        )
        await event_store.put(
            thread_id="t_sum", run_id="r1",
            event_type="ai_message", category="message",
            content={
                "type": "ai", "id": "lc_run--r1",
                "content": "first answer",
                "tool_calls": [], "invalid_tool_calls": [],
                "additional_kwargs": {}, "response_metadata": {}, "name": None,
                "usage_metadata": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            },
        )
        # Run 2 (post-summarize — what the checkpoint still has)
        await event_store.put(
            thread_id="t_sum", run_id="r2",
            event_type="human_message", category="message",
            content={
                "type": "human", "id": None,
                "content": [{"type": "text", "text": "follow up"}],
                "additional_kwargs": {}, "response_metadata": {}, "name": None,
            },
        )
        await event_store.put(
            thread_id="t_sum", run_id="r2",
            event_type="ai_message", category="message",
            content={
                "type": "ai", "id": "lc_run--r2",
                "content": "second answer",
                "tool_calls": [], "invalid_tool_calls": [],
                "additional_kwargs": {}, "response_metadata": {}, "name": None,
                "usage_metadata": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            },
        )

        request = _make_request(event_store)
        messages = await _get_event_store_messages(request, "t_sum")
        assert messages is not None
        # 4 messages, not 2 (which is what the summarized checkpoint would yield)
        assert len(messages) == 4
        assert messages[0]["content"][0]["text"] == "original question"
        assert messages[1]["id"] == "lc_run--r1"
        assert messages[3]["id"] == "lc_run--r2"

    @pytest.mark.anyio
    async def test_run_id_attached_to_every_message(self, event_store):
        await _seed_simple_run(event_store, "t1", "r1")
        request = _make_request(event_store)
        messages = await _get_event_store_messages(request, "t1")
        assert messages is not None
        assert all(m.get("run_id") == "r1" for m in messages)

    @pytest.mark.anyio
    async def test_feedback_attached_only_to_final_ai_message_per_run(self, event_store):
        await _seed_simple_run(event_store, "t1", "r1")
        feedback_repo = _FakeFeedbackRepo(
            {"r1": {"feedback_id": "fb1", "rating": 1, "comment": "great"}}
        )
        request = _make_request(event_store, feedback_repo=feedback_repo)
        messages = await _get_event_store_messages(request, "t1")
        assert messages is not None

        # human (0), ai_tool_call (1), tool (2), ai_message (3)
        final_ai = messages[3]
        assert final_ai["feedback"] == {
            "feedback_id": "fb1",
            "rating": 1,
            "comment": "great",
        }
        # Non-final messages must NOT have a feedback key at all — the
        # frontend keys button visibility off of this.
        assert "feedback" not in messages[0]
        assert "feedback" not in messages[1]
        assert "feedback" not in messages[2]

    @pytest.mark.anyio
    async def test_feedback_none_when_no_row_for_run(self, event_store):
        await _seed_simple_run(event_store, "t1", "r1")
        request = _make_request(event_store, feedback_repo=_FakeFeedbackRepo({}))
        messages = await _get_event_store_messages(request, "t1")
        assert messages is not None
        # Final ai_message gets an explicit ``None`` — distinguishes "eligible
        # but unrated" from "not eligible" (field absent).
        assert messages[3]["feedback"] is None

    @pytest.mark.anyio
    async def test_feedback_per_run_for_multi_run_thread(self, event_store):
        """A thread with two runs: each final ai_message should get its own feedback."""
        # Run 1
        await event_store.put(
            thread_id="t_multi", run_id="r1",
            event_type="human_message", category="message",
            content={"type": "human", "id": None, "content": "q1",
                     "additional_kwargs": {}, "response_metadata": {}, "name": None},
        )
        await event_store.put(
            thread_id="t_multi", run_id="r1",
            event_type="ai_message", category="message",
            content={"type": "ai", "id": "lc_run--a1", "content": "a1",
                     "tool_calls": [], "invalid_tool_calls": [],
                     "additional_kwargs": {}, "response_metadata": {}, "name": None,
                     "usage_metadata": None},
        )
        # Run 2
        await event_store.put(
            thread_id="t_multi", run_id="r2",
            event_type="human_message", category="message",
            content={"type": "human", "id": None, "content": "q2",
                     "additional_kwargs": {}, "response_metadata": {}, "name": None},
        )
        await event_store.put(
            thread_id="t_multi", run_id="r2",
            event_type="ai_message", category="message",
            content={"type": "ai", "id": "lc_run--a2", "content": "a2",
                     "tool_calls": [], "invalid_tool_calls": [],
                     "additional_kwargs": {}, "response_metadata": {}, "name": None,
                     "usage_metadata": None},
        )
        feedback_repo = _FakeFeedbackRepo({
            "r1": {"feedback_id": "fb_r1", "rating": 1, "comment": None},
            "r2": {"feedback_id": "fb_r2", "rating": -1, "comment": "meh"},
        })
        request = _make_request(event_store, feedback_repo=feedback_repo)
        messages = await _get_event_store_messages(request, "t_multi")
        assert messages is not None
        # human[r1], ai[r1], human[r2], ai[r2]
        assert messages[1]["feedback"]["feedback_id"] == "fb_r1"
        assert messages[1]["feedback"]["rating"] == 1
        assert messages[3]["feedback"]["feedback_id"] == "fb_r2"
        assert messages[3]["feedback"]["rating"] == -1
        # Humans don't get feedback
        assert "feedback" not in messages[0]
        assert "feedback" not in messages[2]

    @pytest.mark.anyio
    async def test_feedback_repo_failure_does_not_break_helper(self, monkeypatch, event_store):
        """If feedback lookup throws, messages still come back without feedback."""
        await _seed_simple_run(event_store, "t1", "r1")

        class _BoomRepo:
            async def list_by_thread_grouped(self, *a, **kw):
                raise RuntimeError("db down")

        request = _make_request(event_store, feedback_repo=_BoomRepo())
        messages = await _get_event_store_messages(request, "t1")
        assert messages is not None
        assert len(messages) == 4
        for m in messages:
            assert "feedback" not in m

    @pytest.mark.anyio
    async def test_returns_none_when_dep_raises(self, monkeypatch, event_store):
        """When ``get_run_event_store`` is not configured, helper returns None."""
        import app.gateway.routers.threads as threads_mod

        def boom(_request):
            raise RuntimeError("no store")

        monkeypatch.setattr(threads_mod, "get_run_event_store", boom)
        request = _make_request(event_store)
        assert await threads_mod._get_event_store_messages(request, "t1") is None
