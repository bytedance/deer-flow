"""Regression for the thread-messages feedback attachment.

GET /api/threads/{thread_id}/messages attaches user feedback to the last AI
message of each run. AI messages are stored by RunJournal with event_type
"llm.ai.response"; the endpoint previously matched the non-existent
"ai_message", so feedback was never attached and the grouped-feedback query
ran on every request for nothing.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.routers import thread_runs


def _make_app(messages, feedback_grouped):
    app = make_authed_test_app()
    app.include_router(thread_runs.router)

    event_store = MagicMock()
    event_store.list_messages = AsyncMock(return_value=messages)
    app.state.run_event_store = event_store

    feedback_repo = MagicMock()
    feedback_repo.list_by_thread_grouped = AsyncMock(return_value=feedback_grouped)
    app.state.feedback_repo = feedback_repo

    # list_thread_messages also calls run_manager.list_by_thread to inject
    # turn durations; stub it to return no runs so that path stays inert.
    run_manager = MagicMock()
    run_manager.list_by_thread = AsyncMock(return_value=[])
    app.state.run_manager = run_manager

    return app, feedback_repo


def _ai(run_id: str, seq: int, content: str) -> dict:
    return {"seq": seq, "run_id": run_id, "event_type": "llm.ai.response", "category": "message", "content": content}


def _human(run_id: str, seq: int) -> dict:
    return {"seq": seq, "run_id": run_id, "event_type": "llm.human.input", "category": "message", "content": "hi"}


def test_feedback_attached_to_last_ai_message_per_run():
    messages = [
        _human("r1", 1),
        _ai("r1", 2, "first"),
        _ai("r1", 3, "final answer"),  # last AI of r1 -> should get feedback
        _ai("r2", 4, "other run"),  # last AI of r2 -> no feedback row
    ]
    grouped = {"r1": {"feedback_id": "fb-1", "rating": "up", "comment": "nice"}}
    app, feedback_repo = _make_app(messages, grouped)

    resp = TestClient(app).get("/api/threads/t1/messages")
    assert resp.status_code == 200
    data = resp.json()

    by_seq = {m["seq"]: m for m in data}
    # The bug: this used to be None for every message.
    assert by_seq[3]["feedback"] == {"feedback_id": "fb-1", "rating": "up", "comment": "nice"}
    # Earlier AI message of the same run and the human message get no feedback.
    assert by_seq[2]["feedback"] is None
    assert by_seq[1]["feedback"] is None
    # r2's last AI message has no feedback row.
    assert by_seq[4]["feedback"] is None
    feedback_repo.list_by_thread_grouped.assert_awaited_once()


def test_no_feedback_query_when_thread_has_no_ai_message():
    messages = [_human("r1", 1)]
    app, feedback_repo = _make_app(messages, {})

    resp = TestClient(app).get("/api/threads/t1/messages")
    assert resp.status_code == 200
    assert resp.json()[0]["feedback"] is None
    # No AI message -> the grouped feedback query must not run.
    feedback_repo.list_by_thread_grouped.assert_not_awaited()
