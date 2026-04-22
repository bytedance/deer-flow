"""Tests for model_feedback lifecycle dual-write bridge."""

from __future__ import annotations

import pytest

from deerflow.runtime.model_feedback.lifecycle import (
    record_model_feedback,
    reset_model_feedback_event_context,
    set_model_feedback_event_context,
)


class _FakeFeedbackStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def increment(self, model_name: str, **kwargs):
        self.calls.append((model_name, kwargs))


class _FakeEventStore:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def put(self, **kwargs):
        self.events.append(kwargs)
        return kwargs


@pytest.mark.anyio
async def test_record_model_feedback_dual_writes_success(monkeypatch):
    feedback_store = _FakeFeedbackStore()
    event_store = _FakeEventStore()
    monkeypatch.setattr(
        "deerflow.runtime.model_feedback.lifecycle.get_model_feedback_store",
        lambda: feedback_store,
    )

    token = set_model_feedback_event_context(
        thread_id="thread-1",
        run_id="run-1",
        user_id="alice",
        event_store=event_store,
    )
    try:
        await record_model_feedback("gpt-4o", success=True)
    finally:
        reset_model_feedback_event_context(token)

    assert feedback_store.calls == [("gpt-4o", {"call_count": 1, "success_count": 1})]
    assert len(event_store.events) == 1
    event = event_store.events[0]
    assert event["thread_id"] == "thread-1"
    assert event["run_id"] == "run-1"
    assert event["event_type"] == "model.call.succeeded"
    assert event["metadata"]["model_name"] == "gpt-4o"
    assert event["metadata"]["user_id"] == "alice"


@pytest.mark.anyio
async def test_record_model_feedback_dual_writes_failure(monkeypatch):
    feedback_store = _FakeFeedbackStore()
    event_store = _FakeEventStore()
    monkeypatch.setattr(
        "deerflow.runtime.model_feedback.lifecycle.get_model_feedback_store",
        lambda: feedback_store,
    )

    token = set_model_feedback_event_context(
        thread_id="thread-2",
        run_id="run-2",
        user_id=None,
        event_store=event_store,
    )
    try:
        await record_model_feedback("claude-3-7", success=False)
    finally:
        reset_model_feedback_event_context(token)

    assert feedback_store.calls == [("claude-3-7", {"call_count": 1, "failure_count": 1})]
    assert len(event_store.events) == 1
    event = event_store.events[0]
    assert event["event_type"] == "model.call.failed"
    assert "user_id" not in event["metadata"]


@pytest.mark.anyio
async def test_record_model_feedback_without_feedback_store_still_emits_event(monkeypatch):
    event_store = _FakeEventStore()
    monkeypatch.setattr(
        "deerflow.runtime.model_feedback.lifecycle.get_model_feedback_store",
        lambda: None,
    )

    token = set_model_feedback_event_context(
        thread_id="thread-3",
        run_id="run-3",
        user_id="bob",
        event_store=event_store,
    )
    try:
        await record_model_feedback("deepseek", success=True)
    finally:
        reset_model_feedback_event_context(token)

    assert len(event_store.events) == 1
    assert event_store.events[0]["event_type"] == "model.call.succeeded"
