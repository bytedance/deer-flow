"""Tests for DynamicContextMiddleware emitting a memory context snapshot.

Memory is frozen into a conversation on its first turn (per-thread snapshot
pattern). The middleware records that injection once, keyed by the run's thread,
via ``RunJournal.record_context_snapshot``. The snapshot is built from the same
memory load as the injected reminder (single source of truth) and carried out of
``_inject`` via ``_InjectResult``. These tests pin *when* the snapshot is emitted,
that recording uses a single memory read, and that the timed injection bound also
covers snapshot building.
"""

from __future__ import annotations

import hashlib
import threading
from types import SimpleNamespace
from unittest import mock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory import InjectedMemorySnapshot, format_memory_for_injection
from deerflow.agents.middlewares.dynamic_context_middleware import (
    _DYNAMIC_CONTEXT_REMINDER_KEY,
    DynamicContextMiddleware,
)
from deerflow.config.memory_config import MemoryConfig
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.journal import RunJournal

# The single-load seam the middleware uses to build the reminder + snapshot.
_CTX_SNAP_FN = "deerflow.agents.lead_agent.prompt._get_memory_context_with_snapshot"
_DATETIME = "deerflow.agents.middlewares.dynamic_context_middleware.datetime"


def _snapshot() -> InjectedMemorySnapshot:
    return InjectedMemorySnapshot(
        fact_ids=("f-high", "f-mid"),
        fact_count=2,
        total_facts=4,
        sections=("user_context", "facts"),
        token_count=120,
        max_tokens=2000,
        content_hash="sha256:abc123",
    )


def _runtime_with_journal(journal):
    return SimpleNamespace(context={"thread_id": "t-1", "__run_journal": journal})


def _reminder_msg(content: str, msg_id: str) -> HumanMessage:
    return HumanMessage(
        content=content,
        id=msg_id,
        additional_kwargs={"hide_from_ui": True, _DYNAMIC_CONTEXT_REMINDER_KEY: True},
    )


def test_records_snapshot_on_first_turn_when_journal_present():
    mw = DynamicContextMiddleware()
    state = {"messages": [HumanMessage(content="hi", id="msg-1")]}
    journal = mock.MagicMock()
    snap = _snapshot()

    with (
        mock.patch(_CTX_SNAP_FN, return_value=("<memory>\nx\n</memory>", snap)),
        mock.patch(_DATETIME) as mock_dt,
    ):
        mock_dt.now.return_value.strftime.return_value = "2026-06-13, Saturday"
        result = mw.before_agent(state, _runtime_with_journal(journal))

    assert result is not None  # injection still happens
    journal.record_context_snapshot.assert_called_once_with("memory", payload=snap.to_event_payload())


def test_no_snapshot_emitted_when_journal_absent():
    mw = DynamicContextMiddleware()
    state = {"messages": [HumanMessage(content="hi", id="msg-1")]}

    with (
        mock.patch(_CTX_SNAP_FN, return_value=("<memory>\nx\n</memory>", _snapshot())),
        mock.patch(_DATETIME) as mock_dt,
    ):
        mock_dt.now.return_value.strftime.return_value = "2026-06-13, Saturday"
        # context={} → no journal → emission is a graceful no-op (no error).
        result = mw.before_agent(state, SimpleNamespace(context={}))

    assert result is not None
    assert "<memory>" in result["messages"][0].content


def test_no_snapshot_on_second_turn_same_day():
    """The reminder is already present (frozen snapshot) — no re-injection, so no
    new memory snapshot is recorded."""
    mw = DynamicContextMiddleware()
    reminder = "<system-reminder>\n<current_date>2026-06-13, Saturday</current_date>\n</system-reminder>"
    state = {
        "messages": [
            _reminder_msg(reminder, "msg-1"),
            HumanMessage(content="hello", id="msg-1__user"),
            AIMessage(content="hi"),
            HumanMessage(content="follow-up", id="msg-2"),
        ]
    }
    journal = mock.MagicMock()

    with (
        mock.patch(_CTX_SNAP_FN, return_value=("<memory>\nx\n</memory>", _snapshot())) as ctx_fn,
        mock.patch(_DATETIME) as mock_dt,
    ):
        mock_dt.now.return_value.strftime.return_value = "2026-06-13, Saturday"
        result = mw.before_agent(state, _runtime_with_journal(journal))

    assert result is None
    ctx_fn.assert_not_called()  # second turn never rebuilds the reminder
    journal.record_context_snapshot.assert_not_called()


def test_no_snapshot_when_memory_empty():
    """When memory injection yields nothing, the snapshot is None even on the
    first turn, so no event is recorded (only the date reminder is injected)."""
    mw = DynamicContextMiddleware()
    state = {"messages": [HumanMessage(content="hi", id="msg-1")]}
    journal = mock.MagicMock()

    with (
        mock.patch(_CTX_SNAP_FN, return_value=("", None)),
        mock.patch(_DATETIME) as mock_dt,
    ):
        mock_dt.now.return_value.strftime.return_value = "2026-06-13, Saturday"
        result = mw.before_agent(state, _runtime_with_journal(journal))

    assert result is not None  # date reminder still injected
    journal.record_context_snapshot.assert_not_called()


def test_no_loader_call_or_snapshot_when_injection_disabled():
    """When ``memory.injection_enabled`` is False, ``_build_full_reminder`` must
    short-circuit to ("", None) WITHOUT loading memory and WITHOUT recording a
    snapshot — only the date reminder is injected."""
    app_config = SimpleNamespace(memory=SimpleNamespace(injection_enabled=False))
    mw = DynamicContextMiddleware(app_config=app_config)
    state = {"messages": [HumanMessage(content="hi", id="msg-1")]}
    journal = mock.MagicMock()

    with (
        mock.patch(_CTX_SNAP_FN) as ctx_fn,
        mock.patch(_DATETIME) as mock_dt,
    ):
        mock_dt.now.return_value.strftime.return_value = "2026-06-13, Saturday"
        result = mw.before_agent(state, _runtime_with_journal(journal))

    assert result is not None  # date reminder still injected
    assert "<memory>" not in result["messages"][0].content
    ctx_fn.assert_not_called()  # injection disabled → memory never loaded
    journal.record_context_snapshot.assert_not_called()


def test_emit_swallows_journal_errors_and_still_injects():
    """A failure inside ``record_context_snapshot`` must not break the run:
    ``_emit_memory_snapshot`` swallows it, and injection still succeeds."""
    mw = DynamicContextMiddleware()
    state = {"messages": [HumanMessage(content="hi", id="msg-1")]}
    journal = mock.MagicMock()
    journal.record_context_snapshot.side_effect = RuntimeError("event store down")
    snap = _snapshot()

    with (
        mock.patch(_CTX_SNAP_FN, return_value=("<memory>\nx\n</memory>", snap)),
        mock.patch(_DATETIME) as mock_dt,
    ):
        mock_dt.now.return_value.strftime.return_value = "2026-06-13, Saturday"
        # Must not raise despite the journal error.
        result = mw.before_agent(state, _runtime_with_journal(journal))

    assert result is not None
    assert "<memory>" in result["messages"][0].content  # injection still happened
    journal.record_context_snapshot.assert_called_once()


@pytest.mark.asyncio
async def test_async_path_records_snapshot_on_first_turn():
    mw = DynamicContextMiddleware()
    state = {"messages": [HumanMessage(content="hi", id="msg-1")]}
    journal = mock.MagicMock()
    snap = _snapshot()

    with (
        mock.patch(_CTX_SNAP_FN, return_value=("<memory>\nx\n</memory>", snap)),
        mock.patch(_DATETIME) as mock_dt,
    ):
        mock_dt.now.return_value.strftime.return_value = "2026-06-13, Saturday"
        result = await mw.abefore_agent(state, _runtime_with_journal(journal))

    assert result is not None
    journal.record_context_snapshot.assert_called_once_with("memory", payload=snap.to_event_payload())


@pytest.mark.asyncio
async def test_async_timeout_with_journal_records_nothing():
    """Codex #2 guard: snapshot building is inside the timed ``_inject`` pass.

    If ``_inject`` exceeds the timeout, ``abefore_agent`` returns None and records
    nothing — the snapshot path cannot hold the request open after injection.
    """
    mw = DynamicContextMiddleware()
    journal = mock.MagicMock()

    # Gate the offloaded thread on an Event rather than a hard sleep: it must
    # outlast the 0.1s timeout, but the test releases it the moment the timeout
    # has been observed so the dangling thread doesn't block event-loop teardown
    # (a fixed multi-second tax on every run otherwise).
    release = threading.Event()

    def blocking_inject(state):
        release.wait(10)  # exceeds the patched timeout; released by the test below
        return None

    with (
        mock.patch.object(mw, "_inject", blocking_inject),
        mock.patch("deerflow.agents.middlewares.dynamic_context_middleware._INJECT_TIMEOUT_SECONDS", 0.1),
    ):
        state = {"messages": [HumanMessage(content="hi", id="msg-1")]}
        result = await mw.abefore_agent(state, _runtime_with_journal(journal))
        release.set()  # let the offloaded thread return promptly

    assert result is None
    journal.record_context_snapshot.assert_not_called()


_E2E_MEMORY = {
    "user": {"workContext": {"summary": "Maintainer on DeerFlow"}},
    "facts": [
        {"id": "f-high", "content": "Prefers deterministic fixes", "category": "preference", "confidence": 0.95},
        {"id": "f-low", "content": "Uses make targets for checks", "category": "knowledge", "confidence": 0.72},
    ],
}


@pytest.mark.asyncio
async def test_end_to_end_records_real_context_event_in_store():
    """End-to-end teeth: drive the real middleware → snapshot → journal → store
    path, substituting only the two leaf data sources (memory data + config).

    Everything else is real: ``_get_memory_context_with_snapshot``,
    ``build_injected_memory_snapshot``, the ``RunJournal``, and the event store.
    Proves a real ``context:memory`` row lands on the run spine, and that the
    recorded ``content_hash`` matches the memory text actually injected into the
    message — not a parallel re-derivation.
    """
    store = MemoryRunEventStore()
    journal = RunJournal(run_id="run-e2e", thread_id="thread-e2e", event_store=store)
    runtime = SimpleNamespace(context={"thread_id": "thread-e2e", "__run_journal": journal})

    mw = DynamicContextMiddleware()
    state = {"messages": [HumanMessage(content="hello", id="msg-1")]}
    config = MemoryConfig(enabled=True, injection_enabled=True, max_injection_tokens=2000, token_counting="char")

    with (
        mock.patch("deerflow.agents.memory.get_memory_data", return_value=_E2E_MEMORY),
        mock.patch("deerflow.config.memory_config.get_memory_config", return_value=config),
        mock.patch(_DATETIME) as mock_dt,
    ):
        mock_dt.now.return_value.strftime.return_value = "2026-06-13, Saturday"
        result = mw.before_agent(state, runtime)

    # The injected reminder carries the real memory text.
    expected_memory_text = format_memory_for_injection(_E2E_MEMORY, max_tokens=2000, use_tiktoken=False)
    assert expected_memory_text  # sanity: non-empty
    assert expected_memory_text in result["messages"][0].content

    await journal.flush()

    events = store._events["thread-e2e"]
    context_events = [e for e in events if e["category"] == "context"]
    assert len(context_events) == 1
    event = context_events[0]
    assert event["event_type"] == "context:memory"
    assert event["run_id"] == "run-e2e"

    payload = event["content"]
    assert payload["schema_version"] == 1
    assert payload["fact_ids"] == ["f-high", "f-low"]
    assert payload["fact_count"] == 2
    assert payload["sections"] == ["user_context", "facts"]
    # The recorded hash is the hash of the text that was actually injected.
    assert payload["content_hash"] == "sha256:" + hashlib.sha256(expected_memory_text.encode("utf-8")).hexdigest()


@pytest.mark.asyncio
async def test_snapshot_uses_single_memory_read_not_a_second_one():
    """Regression for the two-read divergence (Codex #1): the reminder and the
    recorded snapshot must come from ONE memory load.

    ``get_memory_data`` returns A then B. With a single read, both the prompt and
    the ledger reflect A. A regression to a second read would record B's facts
    and hash while the prompt shows A.
    """
    memory_a = {"facts": [{"id": "fa", "content": "fact A", "category": "context", "confidence": 0.9}]}
    memory_b = {"facts": [{"id": "fb", "content": "fact B is different", "category": "context", "confidence": 0.9}]}
    reads = [memory_a, memory_b]

    def fake_get_memory_data(agent_name=None, *, user_id=None):
        return reads.pop(0) if reads else memory_b

    store = MemoryRunEventStore()
    journal = RunJournal(run_id="run-1read", thread_id="thread-1read", event_store=store)
    runtime = SimpleNamespace(context={"__run_journal": journal})
    mw = DynamicContextMiddleware()
    state = {"messages": [HumanMessage(content="hello", id="msg-1")]}
    config = MemoryConfig(enabled=True, injection_enabled=True, max_injection_tokens=2000, token_counting="char")

    with (
        mock.patch("deerflow.agents.memory.get_memory_data", side_effect=fake_get_memory_data),
        mock.patch("deerflow.config.memory_config.get_memory_config", return_value=config),
        mock.patch(_DATETIME) as mock_dt,
    ):
        mock_dt.now.return_value.strftime.return_value = "2026-06-13, Saturday"
        result = mw.before_agent(state, runtime)

    text_a = format_memory_for_injection(memory_a, max_tokens=2000, use_tiktoken=False)
    assert "fact A" in result["messages"][0].content
    assert text_a in result["messages"][0].content

    await journal.flush()
    event = next(e for e in store._events["thread-1read"] if e["category"] == "context")
    # Snapshot reflects the SAME single read that built the prompt — A, not B.
    assert event["content"]["fact_ids"] == ["fa"]
    assert event["content"]["content_hash"] == "sha256:" + hashlib.sha256(text_a.encode("utf-8")).hexdigest()
    # Exactly one memory read was consumed (B remains).
    assert reads == [memory_b]
