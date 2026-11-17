"""POST /api/threads/{id}/goal/from-chat — goal synthesis route contract.

Pins the design decisions from the first-PR discussion on #7050:

* busy pre-check happens **before** the synthesis LLM call and returns the
  same 409 detail as ``PUT /goal`` (so the IM manager's in-flight matcher
  recognizes it); a pre-check failure degrades to synthesis, never blocks;
* a thread without a checkpoint (or without visible context) is a 422
  ``no_context`` — the route never creates a thread for from-chat;
* an unclear synthesis is a 422 ``unclear``; the model's reason never appears
  in the response body and is not logged verbatim either;
* a failed synthesis is a 502 ``synthesis_failed``;
* model admission runs **before** the synthesis call: a role denied the
  deployment default model gets the suggestions route's 403 and the
  conversation is never sent to it;
* success saves through the same reservation path as ``PUT /goal``
  (``reserve_checkpoint_write`` + ``write_thread_goal``), and a save-time
  race is a 409, not a silent overwrite — including a checkpoint that
  advanced during the model call, which the compare-and-swap against the
  synthesis source head rejects as 409 ``goal_changed``.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from _router_auth_helpers import make_authed_test_app
from _thread_checkpoint_helpers import put_thread
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from app.gateway.routers import threads
from deerflow.runtime.goal_synthesis import GoalSynthesisError, GoalSynthesisUnclear
from deerflow.runtime.runs.manager import ConflictError

_PUT_BUSY_DETAIL = "Thread has a run in flight. Set the goal after the run finishes."

# ``checkpoint_id`` sentinel for _make_app: the fake accessor reports the real
# head of the seeded checkpointer, so the route's compare-and-swap save sees
# the same id a production snapshot would carry.
_SEEDED_HEAD = "__seeded_head__"

_MESSAGES = [
    {"type": "user", "content": "Reconcile the invoices: vendor A 12,400 CNY, vendor B 8,900 CNY."},
    {"type": "assistant", "content": "Understood. Vendor C is excluded until its invoice arrives."},
    {"type": "user", "content": "List every discrepancy and explain each one when done."},
]

_PENDING_CLARIFICATION = [
    {"type": "human", "content": "Reconcile the invoices: vendor A 12,400 CNY, vendor B 8,900 CNY."},
    {"type": "ai", "content": "", "tool_calls": [{"name": "ask_clarification", "args": {"question": "What baseline should I compare against?"}, "id": "call-clarify"}]},
    {
        "type": "tool",
        "name": "ask_clarification",
        "tool_call_id": "call-clarify",
        "content": "❓ What baseline should I compare against?",
        "artifact": {
            "human_input": {
                "version": 1,
                "kind": "human_input_request",
                "source": "ask_clarification",
                "request_id": "clarification:call-clarify",
                "question": "What baseline should I compare against?",
            }
        },
    },
]


class _FromChatRunManager:
    """Stand-in exposing the two surfaces the route uses."""

    def __init__(self, *, busy: bool = False, precheck_error: Exception | None = None, conflict_on_reserve: bool = False):
        self.busy = busy
        self.precheck_error = precheck_error
        self.conflict_on_reserve = conflict_on_reserve
        self.precheck_calls: list[str] = []
        self.reservations = 0

    async def has_inflight(self, thread_id: str) -> bool:
        self.precheck_calls.append(thread_id)
        if self.precheck_error is not None:
            raise self.precheck_error
        return self.busy

    @asynccontextmanager
    async def reserve_thread_operation(self, thread_id: str, *, kind, user_id: str | None = None):
        if self.conflict_on_reserve:
            raise ConflictError(f"Thread {thread_id} is busy")
        self.reservations += 1
        yield SimpleNamespace(run_id="reservation-1")


class _FakeAccessor:
    def __init__(self, values: dict, *, checkpoint_id: str | None = "cp-1"):
        configurable = {"checkpoint_id": checkpoint_id} if checkpoint_id else {}
        self._snapshot = SimpleNamespace(values=values, config={"configurable": configurable})

    async def aget(self, config):
        return self._snapshot


def _make_app(
    monkeypatch,
    *,
    values: dict | None = None,
    checkpoint_id: str | None = _SEEDED_HEAD,
    run_manager: _FromChatRunManager | None = None,
    owner_check_passes: bool = True,
    seed_checkpoint: bool = False,
    accessor_error: Exception | None = None,
    stub_model_authz: bool = True,
):
    app = make_authed_test_app(owner_check_passes=owner_check_passes)
    app.include_router(threads.router)
    checkpointer = InMemorySaver()
    app.state.checkpointer = checkpointer
    app.state.run_manager = run_manager or _FromChatRunManager()
    app.dependency_overrides[threads.get_config] = lambda: SimpleNamespace(pii_redaction=None)
    if stub_model_authz:
        # The route enforces model:use on the deployment default before the
        # synthesis call; authz wiring itself is covered by the RBAC tests
        # below and by test_suggestions_model_authorization.
        monkeypatch.setattr(threads, "get_current_user_from_request", AsyncMock(return_value=SimpleNamespace(id="user-1")))
        monkeypatch.setattr(threads, "authorize_model_use", lambda *_args, **_kwargs: None)

    seeded_ids: list[str] = []
    if seed_checkpoint:
        seeded_ids = put_thread(checkpointer, "t-fc", ["2026-11-09T00:00:00+00:00"])
    effective_checkpoint_id = seeded_ids[-1] if checkpoint_id == _SEEDED_HEAD and seeded_ids else (None if checkpoint_id == _SEEDED_HEAD else checkpoint_id)

    async def build_accessor(request, *, thread_id, **kwargs):
        if accessor_error is not None:
            raise accessor_error
        return _FakeAccessor(dict(values or {}), checkpoint_id=effective_checkpoint_id), {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}

    monkeypatch.setattr(threads, "build_thread_checkpoint_state_accessor", AsyncMock(side_effect=build_accessor))
    return app, checkpointer


def _mock_synthesis(monkeypatch, *, objective: str = "Reconcile vendors A and B, excluding C, until every discrepancy is explained.", error: Exception | None = None) -> AsyncMock:
    async def _side_effect(**kwargs):
        if error is not None:
            raise error
        return objective

    mock = AsyncMock(side_effect=_side_effect)
    monkeypatch.setattr(threads, "synthesize_goal_objective", mock)
    return mock


@pytest.fixture(autouse=True)
def _stable_now(monkeypatch):
    monkeypatch.setattr(threads, "now_iso", lambda: "2026-11-09T00:00:00+00:00")
    # build_goal_state stamps the goal through the harness module, not the router.
    monkeypatch.setattr("deerflow.runtime.goal.now_iso", lambda: "2026-11-09T00:00:00+00:00")


def test_from_chat_busy_precheck_409s_before_any_llm_call(monkeypatch):
    run_manager = _FromChatRunManager(busy=True)
    synthesis = _mock_synthesis(monkeypatch)
    app, checkpointer = _make_app(monkeypatch, values={"messages": _MESSAGES}, run_manager=run_manager, seed_checkpoint=True)

    with TestClient(app) as client:
        response = client.post("/api/threads/t-fc/goal/from-chat", json={})

    assert response.status_code == 409
    # Same detail as PUT /goal so the IM manager's matcher recognizes it.
    assert response.json()["detail"] == _PUT_BUSY_DETAIL
    assert run_manager.precheck_calls == ["t-fc"]
    synthesis.assert_not_awaited()
    assert run_manager.reservations == 0
    # Nothing was saved.
    assert asyncio.run(threads.read_thread_goal(checkpointer, "t-fc")) is None


def test_from_chat_precheck_failure_degrades_to_synthesis(monkeypatch):
    run_manager = _FromChatRunManager(precheck_error=RuntimeError("registry down"))
    _mock_synthesis(monkeypatch)
    app, checkpointer = _make_app(monkeypatch, values={"messages": _MESSAGES}, run_manager=run_manager, seed_checkpoint=True)

    with TestClient(app) as client:
        response = client.post("/api/threads/t-fc/goal/from-chat", json={})

    assert response.status_code == 200, response.text
    assert run_manager.reservations == 1


@pytest.mark.parametrize(
    ("values", "checkpoint_id"),
    [
        pytest.param({"messages": _MESSAGES}, None, id="no-checkpoint"),
        pytest.param({}, "cp-1", id="empty-values"),
        pytest.param({"messages": [], "summary_text": None}, "cp-1", id="no-visible-context"),
    ],
)
def test_from_chat_without_context_422s_and_never_creates_a_thread(monkeypatch, values, checkpoint_id):
    synthesis = _mock_synthesis(monkeypatch)
    run_manager = _FromChatRunManager()
    app, checkpointer = _make_app(monkeypatch, values=values, checkpoint_id=checkpoint_id, run_manager=run_manager)

    with TestClient(app) as client:
        response = client.post("/api/threads/t-fc/goal/from-chat", json={})

    assert response.status_code == 422
    assert response.json()["detail"] == {"code": "no_context"}
    synthesis.assert_not_awaited()
    assert run_manager.reservations == 0
    # from-chat never mints a checkpoint the way PUT /goal does for /chats/new.
    config = {"configurable": {"thread_id": "t-fc", "checkpoint_ns": ""}}
    assert asyncio.run(checkpointer.aget_tuple(config)) is None


def test_from_chat_state_read_failure_is_a_server_error_not_no_context(monkeypatch):
    # A checkpointer outage is not "the conversation has no content": reporting
    # it as 422 no_context would tell the user to keep discussing instead of
    # retrying later.
    synthesis = _mock_synthesis(monkeypatch)
    run_manager = _FromChatRunManager()
    app, _ = _make_app(monkeypatch, values={"messages": _MESSAGES}, run_manager=run_manager, accessor_error=RuntimeError("checkpointer down"))

    with TestClient(app) as client:
        response = client.post("/api/threads/t-fc/goal/from-chat", json={})

    assert response.status_code == 500
    synthesis.assert_not_awaited()
    assert run_manager.reservations == 0


def test_from_chat_pending_clarification_422s_before_synthesis(monkeypatch):
    # A conversation waiting on the assistant's question has no agreed goal
    # yet; synthesizing and starting a run would let the model invent the
    # missing decision (the live Feishu run did exactly that).
    synthesis = _mock_synthesis(monkeypatch)
    run_manager = _FromChatRunManager()
    app, checkpointer = _make_app(monkeypatch, values={"messages": _PENDING_CLARIFICATION}, run_manager=run_manager, seed_checkpoint=True)

    with TestClient(app) as client:
        response = client.post("/api/threads/t-fc/goal/from-chat", json={})

    assert response.status_code == 422
    assert response.json()["detail"] == {"code": "pending_clarification"}
    synthesis.assert_not_awaited()
    assert run_manager.reservations == 0
    assert asyncio.run(threads.read_thread_goal(checkpointer, "t-fc")) is None


def test_from_chat_rejects_pending_tool_approval(monkeypatch):
    # PUT/DELETE /goal reject while a tool approval is pending so a new input
    # cannot silently discard it; from-chat writes the same goal state and must
    # share that gate.
    synthesis = _mock_synthesis(monkeypatch)
    run_manager = _FromChatRunManager()
    app, checkpointer = _make_app(monkeypatch, values={"messages": _MESSAGES}, run_manager=run_manager, seed_checkpoint=True)

    async def _pending(request, thread_id, *, accessor=None, read_config=None, snapshot=None):
        return {"task-approval": [SimpleNamespace(value={"kind": "hitl_approval"})]}

    monkeypatch.setattr("app.gateway.hitl_approval.find_pending_interrupts", _pending)

    with TestClient(app) as client:
        response = client.post("/api/threads/t-fc/goal/from-chat", json={})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "approval_pending"
    synthesis.assert_not_awaited()
    assert run_manager.reservations == 0
    assert asyncio.run(threads.read_thread_goal(checkpointer, "t-fc")) is None


def test_from_chat_answered_clarification_is_not_pending(monkeypatch):
    objective = "Reconcile A and B against the purchase orders, excluding C."
    synthesis = _mock_synthesis(monkeypatch, objective=objective)
    messages = [
        *_PENDING_CLARIFICATION,
        {
            "type": "human",
            "content": "",
            "additional_kwargs": {
                "hide_from_ui": True,
                "human_input_response": {
                    "version": 1,
                    "kind": "human_input_response",
                    "source": "ask_clarification",
                    "request_id": "clarification:call-clarify",
                    "response_kind": "text",
                    "value": "Use the purchase orders.",
                },
            },
        },
    ]
    app, _ = _make_app(monkeypatch, values={"messages": messages}, seed_checkpoint=True)

    with TestClient(app) as client:
        response = client.post("/api/threads/t-fc/goal/from-chat", json={})

    assert response.status_code == 200, response.text
    context = synthesis.await_args.kwargs["context"]
    # Both halves of the exchange reach the synthesizer: the question and the
    # card answer that resolved it.
    assert "Assistant (waiting for input): What baseline should I compare against?" in context
    assert "User (Human Input Card answer): Use the purchase orders." in context


def test_from_chat_passes_context_and_guidance_to_synthesis(monkeypatch):
    synthesis = _mock_synthesis(monkeypatch)
    app, _ = _make_app(monkeypatch, values={"messages": _MESSAGES, "summary_text": "Earlier the user described the batch."}, seed_checkpoint=True)

    with TestClient(app) as client:
        response = client.post("/api/threads/t-fc/goal/from-chat", json={"guidance": "focus on the vendor total"})

    assert response.status_code == 200, response.text
    kwargs = synthesis.await_args.kwargs
    assert "Earlier the user described the batch." in kwargs["context"]
    assert "vendor A 12,400" in kwargs["context"]
    assert kwargs["guidance"] == "focus on the vendor total"
    assert kwargs["thread_id"] == "t-fc"


def test_from_chat_unclear_422s_without_leaking_the_model_reason(monkeypatch):
    secret_reason = "provider-side note with token sk-secret and raw conversation quotes"
    _mock_synthesis(monkeypatch, error=GoalSynthesisUnclear(secret_reason))
    run_manager = _FromChatRunManager()
    app, checkpointer = _make_app(monkeypatch, values={"messages": _MESSAGES}, run_manager=run_manager, seed_checkpoint=True)

    with TestClient(app) as client:
        response = client.post("/api/threads/t-fc/goal/from-chat", json={})

    assert response.status_code == 422
    body = response.text
    assert response.json()["detail"] == {"code": "unclear"}
    assert "sk-secret" not in body and "provider-side note" not in body
    assert run_manager.reservations == 0
    assert asyncio.run(threads.read_thread_goal(checkpointer, "t-fc")) is None


def test_from_chat_synthesis_failure_502s(monkeypatch):
    _mock_synthesis(monkeypatch, error=GoalSynthesisError("provider down"))
    app, checkpointer = _make_app(monkeypatch, values={"messages": _MESSAGES}, seed_checkpoint=True)

    with TestClient(app) as client:
        response = client.post("/api/threads/t-fc/goal/from-chat", json={})

    assert response.status_code == 502
    assert response.json()["detail"] == {"code": "synthesis_failed"}
    assert asyncio.run(threads.read_thread_goal(checkpointer, "t-fc")) is None


def test_from_chat_success_saves_goal_through_the_reservation_path(monkeypatch):
    objective = "Reconcile vendors A and B, excluding C, until every discrepancy is explained."
    _mock_synthesis(monkeypatch, objective=objective)
    run_manager = _FromChatRunManager()
    app, checkpointer = _make_app(monkeypatch, values={"messages": _MESSAGES}, run_manager=run_manager, seed_checkpoint=True)

    with TestClient(app) as client:
        response = client.post("/api/threads/t-fc/goal/from-chat", json={})

    assert response.status_code == 200, response.text
    goal = response.json()["goal"]
    assert goal["objective"] == objective
    assert goal["status"] == "active"
    assert run_manager.reservations == 1
    saved = asyncio.run(threads.read_thread_goal(checkpointer, "t-fc"))
    assert saved is not None and saved["objective"] == objective


class _FakeBatchRepo:
    def __init__(self):
        self.suppressed: list[str] = []

    async def suppress_thread_continuations(self, thread_id: str) -> None:
        self.suppressed.append(thread_id)


def test_from_chat_suppresses_queued_continuations(monkeypatch):
    # A new goal supersedes subagent-batch continuations queued under the old
    # one; PUT/DELETE /goal already do this after the write.
    _mock_synthesis(monkeypatch)
    app, _ = _make_app(monkeypatch, values={"messages": _MESSAGES}, seed_checkpoint=True)
    repo = _FakeBatchRepo()
    app.state.subagent_batch_repo = repo

    with TestClient(app) as client:
        response = client.post("/api/threads/t-fc/goal/from-chat", json={})

    assert response.status_code == 200, response.text
    assert repo.suppressed == ["t-fc"]


def test_from_chat_save_conflict_409s_like_put(monkeypatch):
    _mock_synthesis(monkeypatch)
    run_manager = _FromChatRunManager(conflict_on_reserve=True)
    app, checkpointer = _make_app(monkeypatch, values={"messages": _MESSAGES}, run_manager=run_manager, seed_checkpoint=True)

    with TestClient(app) as client:
        response = client.post("/api/threads/t-fc/goal/from-chat", json={})

    assert response.status_code == 409
    assert response.json()["detail"] == _PUT_BUSY_DETAIL
    assert asyncio.run(threads.read_thread_goal(checkpointer, "t-fc")) is None


def test_from_chat_denied_model_is_rejected_before_synthesis(monkeypatch):
    # The synthesis call sends thread context to the deployment default model.
    # A role denied that model must get the same 403 the suggestions route
    # returns — before the model call, so the conversation never reaches the
    # denied profile even transiently.
    from fastapi import HTTPException as _HTTPException

    synthesis = _mock_synthesis(monkeypatch)
    run_manager = _FromChatRunManager()
    app, checkpointer = _make_app(monkeypatch, values={"messages": _MESSAGES}, run_manager=run_manager, seed_checkpoint=True, stub_model_authz=False)
    monkeypatch.setattr(threads, "get_current_user_from_request", AsyncMock(return_value=SimpleNamespace(id="user-1", system_role="user")))
    seen: list = []

    def _deny(user, model_name, *, is_internal, app_config):
        seen.append((model_name, is_internal))
        raise _HTTPException(status_code=403, detail="Model 'restricted' is not available for your role")

    monkeypatch.setattr(threads, "authorize_model_use", _deny)

    with TestClient(app) as client:
        response = client.post("/api/threads/t-fc/goal/from-chat", json={})

    assert response.status_code == 403
    # The check is for the factory default (model_name None), same as the
    # suggestions route's default-model admission.
    assert seen == [(None, False)]
    synthesis.assert_not_awaited()
    assert run_manager.reservations == 0
    assert asyncio.run(threads.read_thread_goal(checkpointer, "t-fc")) is None


def test_from_chat_allowed_model_reaches_synthesis(monkeypatch):
    # The admission check must not block the ordinary allowed path.
    synthesis = _mock_synthesis(monkeypatch)
    app, _ = _make_app(monkeypatch, values={"messages": _MESSAGES}, seed_checkpoint=True, stub_model_authz=False)
    monkeypatch.setattr(threads, "get_current_user_from_request", AsyncMock(return_value=SimpleNamespace(id="user-1", system_role="user")))
    monkeypatch.setattr(threads, "authorize_model_use", lambda *_args, **_kwargs: None)

    with TestClient(app) as client:
        response = client.post("/api/threads/t-fc/goal/from-chat", json={})

    assert response.status_code == 200, response.text
    synthesis.assert_awaited_once()


def test_from_chat_checkpoint_moved_during_synthesis_409s_goal_changed(monkeypatch):
    # The reviewer's repro: a goal (or any checkpoint write) lands while the
    # model call is in flight, moving the head. The save is a compare-and-swap
    # against the head the synthesis read, so the stale objective is rejected
    # instead of clobbering the newer state.
    run_manager = _FromChatRunManager()
    app, checkpointer = _make_app(monkeypatch, values={"messages": _MESSAGES}, run_manager=run_manager, seed_checkpoint=True)

    newer_goal_objective = "The user set a newer goal mid-synthesis."

    async def _synthesis_side_effect(**kwargs):
        # Simulate PUT /goal landing during the model call: the real head
        # advances past what the route read, and a newer goal exists.
        await threads.write_thread_goal(checkpointer, "t-fc", threads.build_goal_state(newer_goal_objective), as_node="goal")
        return "The stale synthesized objective."

    monkeypatch.setattr(threads, "synthesize_goal_objective", AsyncMock(side_effect=_synthesis_side_effect))

    with TestClient(app) as client:
        response = client.post("/api/threads/t-fc/goal/from-chat", json={})

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "goal_changed"}
    # The user's newer goal survived: the stale objective was never written.
    saved = asyncio.run(threads.read_thread_goal(checkpointer, "t-fc"))
    assert saved is not None and saved["objective"] == newer_goal_objective


def test_from_chat_owner_check_denies(monkeypatch):
    synthesis = _mock_synthesis(monkeypatch)
    app, _ = _make_app(monkeypatch, values={"messages": _MESSAGES}, owner_check_passes=False)

    with TestClient(app) as client:
        response = client.post("/api/threads/t-fc/goal/from-chat", json={})

    # require_permission(owner_check=True) denies with 404 so a non-owner
    # cannot distinguish "exists but not mine" from "does not exist".
    assert response.status_code == 404
    synthesis.assert_not_awaited()


def test_from_chat_rejects_overlong_guidance(monkeypatch):
    _mock_synthesis(monkeypatch)
    app, _ = _make_app(monkeypatch, values={"messages": _MESSAGES}, seed_checkpoint=True)

    with TestClient(app) as client:
        response = client.post("/api/threads/t-fc/goal/from-chat", json={"guidance": "x" * 501})

    assert response.status_code == 422  # FastAPI body validation
    assert "guidance" in response.text
