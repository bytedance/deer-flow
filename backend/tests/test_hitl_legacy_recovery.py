"""Reject-only legacy approval recovery, identity fencing and serialization."""

from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import HTTPException
from langchain_core.messages import AIMessage
from langgraph.types import Interrupt

from deerflow.runtime import RunManager, RunStatus
from deerflow.runtime.approval_identity import InvalidApprovalIdentity, invalid_approval_identity
from deerflow.runtime.runs.store.memory import MemoryRunStore


def _payload(ids=None, *, request_id="pause-1"):
    ids = [None] if ids is None else ids
    return {
        "kind": "hitl_approval",
        "version": 1,
        "request_id": request_id,
        "pending_tool_call_ids": ids,
        "actions": [{"tool_call_id": call_id, "tool_name": "write_file", "request_id": f"{request_id}:{index}", "args_summary": {"path": f"/tmp/{index}"}} for index, call_id in enumerate(ids)],
    }


def _responses(payload):
    return [{"tool_call_id": action["tool_call_id"], "request_id": action["request_id"], "option_id": "reject"} for action in payload["actions"]]


@pytest.mark.parametrize("ids", [[None], ["same", "same"], [None, "valid"]])
def test_identity_binds_entire_invalid_pause_without_retaining_contents(ids):
    payload = _payload(ids)
    identity = invalid_approval_identity(payload)
    assert isinstance(identity, InvalidApprovalIdentity)
    assert identity == invalid_approval_identity(copy.deepcopy(payload))
    assert "/tmp/" not in repr(identity)
    payload["actions"][0]["args_summary"]["path"] = "/tmp/changed"
    assert invalid_approval_identity(payload) != identity


@pytest.mark.parametrize("change", ["valid", "missing-id", "missing-request", "bad-actions", "bad-version", "non-string", "oversized", "non-json"])
def test_identity_does_not_enable_recovery_for_other_damage(change):
    payload = _payload()
    if change == "valid":
        payload = _payload(["unique"])
    elif change == "missing-id":
        payload["actions"][0].pop("tool_call_id")
    elif change == "missing-request":
        payload.pop("request_id")
    elif change == "bad-actions":
        payload["actions"] = []
    elif change == "bad-version":
        payload["version"] = 2
    elif change == "non-string":
        payload["pending_tool_call_ids"] = [{}]
    elif change == "oversized":
        payload["extra"] = "x" * 32_001
    else:
        payload["extra"] = object()
    assert invalid_approval_identity(payload) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("ids", [[None], ["same", "same"]])
async def test_gateway_recovery_rejects_mixed_stale_and_partial_responses(monkeypatch, ids):
    from app.gateway import hitl_approval as gateway

    payload = _payload(ids)
    grouped = {"task": [Interrupt(value=payload, id="interrupt-1")]}
    monkeypatch.setattr(gateway, "find_pending_interrupts", AsyncMock(return_value=grouped))
    monkeypatch.setattr(gateway, "has_waiting_for_input_run", AsyncMock(return_value=True))
    monkeypatch.setattr(gateway, "has_any_pending_interrupt", AsyncMock(return_value=True))
    accessor = SimpleNamespace(aget=AsyncMock(return_value=SimpleNamespace(config={}, next=())))

    async def validate(responses):
        return await gateway.validate_resume_request(request=None, thread_id="thread", accessor=accessor, read_config={}, enabled=False, body=SimpleNamespace(command={"resume": {"responses": responses}}))

    assert await validate(_responses(payload)) == invalid_approval_identity(payload)
    assert await gateway.current_approval_request_ids(None, "thread", accessor=accessor, read_config={}) == invalid_approval_identity(payload)
    for mutate in ("approve", "stale", "partial", "missing-id", "empty"):
        responses = _responses(payload)
        if mutate == "approve":
            responses[0]["option_id"] = "approve"
        elif mutate == "stale":
            responses[0]["request_id"] = "earlier-pause"
        elif mutate == "missing-id":
            responses[0].pop("tool_call_id")
        elif mutate == "empty":
            responses = []
        else:
            responses = responses[:-1]
        with pytest.raises(HTTPException) as error:
            await validate(responses)
        assert error.value.status_code == 422


@pytest_asyncio.fixture(params=["memory", "sqlite"])
async def run_store(request, tmp_path):
    if request.param == "memory":
        yield MemoryRunStore()
        return
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.persistence.run import RunRepository

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}", sqlite_dir=str(tmp_path))
    try:
        yield RunRepository(get_session_factory())
    finally:
        await close_engine()


@pytest.mark.asyncio
@pytest.mark.parametrize("ids", [[None], ["same", "same"]])
async def test_recovery_has_one_winner_and_restores_exact_pause(run_store, ids):
    payload = _payload(ids)
    identity = invalid_approval_identity(payload)
    assert identity is not None
    owner = RunManager(store=run_store)
    peer = RunManager(store=run_store)
    record = await owner.create_or_reject("thread", metadata={"hitl_approval": payload, "retained": True})
    await owner.set_status(record.run_id, RunStatus.waiting_for_input)
    # Concurrent managers share only the actual store, not an in-process gate.
    answers = await asyncio.gather(owner.mark_approval_answered("thread", expected_request_ids=identity), peer.mark_approval_answered("thread", expected_request_ids=identity))
    assert sum(answer is not None for answer in answers) == 1
    winner = owner if answers[0] is not None else peer
    answer = next(answer for answer in answers if answer is not None)
    assert (await run_store.get(record.run_id))["metadata"] == {"retained": True}
    assert await winner.restore_approval_answer(answer)
    restored = await run_store.get(record.run_id)
    assert restored["status"] == "waiting_for_input"
    assert restored["metadata"] == {"hitl_approval": payload, "retained": True}
    assert not await winner.restore_approval_answer(answer)
    assert await winner.mark_approval_answered("thread", expected_request_ids=identity) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("next_ids", [["valid"], [None], ["duplicate", "duplicate"]])
async def test_old_recovery_identity_cannot_answer_a_new_pause(run_store, next_ids):
    owner = RunManager(store=run_store)
    peer = RunManager(store=run_store)
    first_payload = _payload()
    first_identity = invalid_approval_identity(first_payload)
    first = await owner.create_or_reject("thread", metadata={"hitl_approval": first_payload})
    await owner.set_status(first.run_id, RunStatus.waiting_for_input)
    assert await owner.mark_approval_answered("thread", expected_request_ids=first_identity) is not None
    second_payload = _payload(next_ids, request_id="pause-2")
    second = await owner.create_or_reject("thread", metadata={"hitl_approval": second_payload})
    await owner.set_status(second.run_id, RunStatus.waiting_for_input)
    assert await peer.mark_approval_answered("thread", expected_request_ids=first_identity) is None
    row = await run_store.get(second.run_id)
    assert row["status"] == "waiting_for_input"
    assert row["metadata"]["hitl_approval"] == second_payload


@pytest.mark.parametrize("ids", [[None], ["same", "same"]])
def test_replayed_rejection_removes_colliding_provider_surfaces(ids):
    from deerflow.agents.middlewares.hitl_approval_middleware import HitlApprovalMiddleware

    calls = [{"name": "write_file", "args": {}, "id": call_id} for call_id in ids]
    calls.append({"name": "echo", "args": {}, "id": ids[0]})
    calls.append({"name": "echo", "args": {}, "id": "healthy"})
    message = AIMessage(
        id="original-message",
        content=[{"type": "tool_use", "id": call["id"], "name": call["name"], "input": {}} for call in calls],
        tool_calls=calls,
        additional_kwargs={"tool_calls": [{"id": call["id"], "type": "function", "function": {"name": call["name"], "arguments": "{}"}} for call in calls]},
        invalid_tool_calls=[{"name": "write_file", "args": "{", "id": ids[0], "error": "invalid arguments"}],
    )
    middleware = HitlApprovalMiddleware(tool_names={"write_file"})
    result = middleware._process_responses(message, calls[:-2], {"responses": []})["messages"][0]
    assert result.id == message.id
    assert not result.invalid_tool_calls
    assert [call["id"] for call in result.tool_calls] == ["healthy"]
    assert [call["id"] for call in result.additional_kwargs["tool_calls"]] == ["healthy"]
    assert [block["id"] for block in result.content if block.get("type") == "tool_use"] == ["healthy"]
    assert any(block.get("type") == "text" and "rejected" in block["text"] for block in result.content)


@pytest.mark.asyncio
@pytest.mark.parametrize("ids", [[None], ["same", "same"]])
async def test_worker_recovers_legacy_names_only_for_bound_rejections(ids):
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import MessagesState, StateGraph
    from langgraph.types import Command, interrupt

    from deerflow.runtime.runs.worker import _is_all_reject_hitl_resume, _pending_hitl_resume_tool_names

    payload = _payload(ids)

    def pause(state):
        interrupt(payload)
        return {}

    saver = InMemorySaver()
    builder = StateGraph(MessagesState)
    builder.add_node("pause", pause)
    builder.set_entry_point("pause")
    builder.set_finish_point("pause")
    graph = builder.compile(checkpointer=saver)
    config = {"configurable": {"thread_id": "legacy-names"}}
    await graph.ainvoke({"messages": []}, config)
    responses = _responses(payload)
    command = Command(resume={"responses": responses})
    assert _is_all_reject_hitl_resume(command)
    assert await _pending_hitl_resume_tool_names(saver, config, command) == {"write_file"}
    responses[0]["request_id"] = "stale"
    assert await _pending_hitl_resume_tool_names(saver, config, command) == set()
    responses[0]["request_id"] = payload["actions"][0]["request_id"]
    responses[0]["option_id"] = "approve"
    assert await _pending_hitl_resume_tool_names(saver, config, command) == set()
