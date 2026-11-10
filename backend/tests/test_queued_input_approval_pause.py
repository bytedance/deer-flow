"""A Queue input survives a HITL approval pause and runs after the resumed work.

Queue/Steer (#7729) dispatches a Run's queued inputs after that Run finishes
successfully. An approval pause (#7979) ends the worker in the non-terminal
``waiting_for_input`` status, and the approved work then continues under a new
resume Run. The queued follow-up belongs to the paused Run, so it must wait
through the pause and be dispatched once the resumed work succeeds, instead of
being marked ``not_applied`` at the pause and never dispatched.
"""

from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from starlette.testclient import TestClient
from test_hitl_approval_api import (  # noqa: F401
    _MODEL_PATCH,
    _approval_request_id,
    _create_thread,
    _enable_approval,
    _register_user,
    _resume,
    _run,
    _run_body,
    _StateAwareModel,
    _TwoStepStateAwareModel,
    _wait_run_status,
    _wait_run_terminal,
    isolated_app,
    isolated_deer_flow_home,
)

pytestmark = pytest.mark.no_auto_user

USER_ID = "00000000-0000-0000-0000-000000000001"


@pytest_asyncio.fixture(params=["memory", "sqlite"])
async def chain_store(request, tmp_path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from deerflow.persistence.base import Base
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    if request.param == "memory":
        yield MemoryRunStore()
        return
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield RunRepository(async_sessionmaker(engine, expire_on_commit=False))
    await engine.dispose()


QUEUED_TEXT = "afterwards, reply with done"

# Model call number (1-based) -> gate the call waits on before answering.
_GATES: dict[int, threading.Event] = {}
_CALLS = {"count": 0}
_CALLS_LOCK = threading.Lock()


def _wait_gate() -> None:
    with _CALLS_LOCK:
        _CALLS["count"] += 1
        gate = _GATES.get(_CALLS["count"])
    if gate is not None:
        assert gate.wait(30), "test gate was never released"


class _GatedModel(_StateAwareModel):
    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any):
        _wait_gate()
        return super()._generate(messages, stop, run_manager, **kwargs)


class _GatedTwoStepModel(_TwoStepStateAwareModel):
    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any):
        _wait_gate()
        return super()._generate(messages, stop, run_manager, **kwargs)


@pytest.fixture(autouse=True)
def _reset_gates():
    _GATES.clear()
    _CALLS["count"] = 0
    yield
    for gate in _GATES.values():
        gate.set()


def _gated(*args, **kwargs):
    return _GatedModel(responses=[])


def _gated_two_step(*args, **kwargs):
    return _GatedTwoStepModel(responses=[])


def _thread_inputs(client, tid):
    return client.get(f"/api/threads/{tid}/inputs").json()["items"]


def _queued_item(client, tid):
    return next(item for item in _thread_inputs(client, tid) if item["id"] == "q1")


def _queue_while_running(client, csrf, tid, rid):
    """Submit the follow-up once the Run's input channel is open (first model call is gated)."""
    _wait_run_status(client, tid, rid, "running")
    deadline = time.monotonic() + 20
    response = None
    while time.monotonic() < deadline:
        response = client.post(
            f"/api/threads/{tid}/runs/{rid}/inputs",
            json={"request_id": "q1", "text": QUEUED_TEXT, "mode": "queue"},
            headers={"X-CSRF-Token": csrf},
        )
        if response.status_code == 200:
            return response.json()
        time.sleep(0.1)
    raise AssertionError(f"queued input was not accepted: {response.status_code if response else None} {response.text if response else ''}")


def _wait_queued_status(client, tid, wanted, timeout=20.0):
    deadline = time.monotonic() + timeout
    item = {}
    while time.monotonic() < deadline:
        item = _queued_item(client, tid)
        if item["status"] == wanted:
            return item
        time.sleep(0.2)
    raise AssertionError(f"queued input did not reach {wanted}: {item}")


def _human_texts(client, tid):
    messages = client.get(f"/api/threads/{tid}").json()["values"]["messages"]
    return [m["content"] for m in messages if m.get("type") == "human" and isinstance(m.get("content"), str)]


def _start_paused_run_with_queued_input(client, csrf, tid):
    _GATES[1] = threading.Event()
    rid = _run(client, csrf, tid, _run_body(input={"messages": [{"role": "user", "content": "write"}]})).json()["run_id"]
    _queue_while_running(client, csrf, tid, rid)
    _GATES[1].set()
    paused = _wait_run_status(client, tid, rid, "waiting_for_input")
    assert paused["status"] == "waiting_for_input"
    return rid


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_queued_input_runs_after_the_resumed_work(isolated_app, decision):  # noqa: F811
    _enable_approval()
    with patch(_MODEL_PATCH, new=_gated), TestClient(isolated_app) as client:
        csrf = _register_user(client)
        tid = _create_thread(client, csrf)
        paused_run_id = _start_paused_run_with_queued_input(client, csrf, tid)

        # The pause is not a failure: the follow-up still waits for the work.
        assert _queued_item(client, tid)["status"] == "pending"
        from deerflow.runtime.runs.inputs import PAUSED_KEY, RunInputs

        paused_inputs = RunInputs(isolated_app.state.run_manager.input_store, paused_run_id, None)
        # Written by the worker before the pause became visible.
        assert client.portal.call(paused_inputs.read)[PAUSED_KEY] is True

        resumed = _resume(client, csrf, tid, decision, value="no" if decision == "reject" else None)
        assert resumed.status_code == 200, resumed.text
        resume_run_id = resumed.json()["run_id"]
        assert _wait_run_terminal(client, tid, resume_run_id)["status"] == "success"
        # The paused row now reads success, yet stays recognisable as an answered pause.
        assert client.portal.call(paused_inputs.read)[PAUSED_KEY] is True

        applied = _wait_queued_status(client, tid, "applied")
        assert applied["target_run_id"] == paused_run_id
        follow_up_run_id = applied["run_id"]
        assert follow_up_run_id not in (paused_run_id, resume_run_id)
        assert _wait_run_terminal(client, tid, follow_up_run_id)["status"] == "success"
        assert any(QUEUED_TEXT in text for text in _human_texts(client, tid))


def test_queued_input_waits_through_consecutive_approvals(isolated_app):  # noqa: F811
    _enable_approval()
    with patch(_MODEL_PATCH, new=_gated_two_step), TestClient(isolated_app) as client:
        csrf = _register_user(client)
        tid = _create_thread(client, csrf)
        _start_paused_run_with_queued_input(client, csrf, tid)

        first = _resume(client, csrf, tid, "approve")
        assert first.status_code == 200, first.text
        # The resumed work asks for a second approval before it can finish.
        assert _wait_run_status(client, tid, first.json()["run_id"], "waiting_for_input")["status"] == "waiting_for_input"
        assert _queued_item(client, tid)["status"] == "pending"

        second = _resume(client, csrf, tid, "approve", request_id=_approval_request_id(client, tid, "call_hitl_2"), tool_call_id="call_hitl_2")
        assert second.status_code == 200, second.text
        assert _wait_run_terminal(client, tid, second.json()["run_id"])["status"] == "success"

        applied = _wait_queued_status(client, tid, "applied")
        assert _wait_run_terminal(client, tid, applied["run_id"])["status"] == "success"
        assert sum(QUEUED_TEXT in text for text in _human_texts(client, tid)) == 1


def test_queued_input_is_retryable_when_the_resumed_work_stops(isolated_app):  # noqa: F811
    _enable_approval()
    with patch(_MODEL_PATCH, new=_gated), TestClient(isolated_app) as client:
        csrf = _register_user(client)
        tid = _create_thread(client, csrf)
        _start_paused_run_with_queued_input(client, csrf, tid)

        # Hold the resumed model call so the resume Run can be cancelled mid-work.
        _GATES[2] = threading.Event()
        resumed = _resume(client, csrf, tid, "approve")
        assert resumed.status_code == 200, resumed.text
        resume_run_id = resumed.json()["run_id"]
        _wait_run_status(client, tid, resume_run_id, "running")
        cancelled = client.post(f"/api/threads/{tid}/runs/{resume_run_id}/cancel", headers={"X-CSRF-Token": csrf})
        assert cancelled.status_code in (200, 202, 204), cancelled.text
        _GATES[2].set()
        assert _wait_run_terminal(client, tid, resume_run_id)["status"] != "success"

        # Not dispatched automatically, but left for an explicit retry.
        item = _wait_queued_status(client, tid, "not_applied")
        assert "run_id" not in item
        assert not any(QUEUED_TEXT in text for text in _human_texts(client, tid))


def _chain_agent_runs(store, outcomes: dict[str, str], dispatched: list[str]):
    """Ordinary-admission double: claim from the source row, then report the scripted outcome."""
    from types import SimpleNamespace

    from deerflow.runtime.runs.inputs import RunInputs

    async def dispatch_input(*, thread_id, run_id, input_id):
        source = RunInputs(store, run_id, USER_ID)
        await source.claim(input_id)
        child = f"child-{input_id}"
        await store.put(child, thread_id="thread", user_id=USER_ID, status="running")
        if outcomes.get(child) == "answered":
            # Paused for approval and answered before the dispatcher's first poll.
            await RunInputs(store, child, USER_ID).mark_paused()
        await store.update_status(child, _row_status(outcomes.get(child, "success")))
        await source.dispatched(input_id, child)
        dispatched.append(input_id)
        return SimpleNamespace(run_id=child, status="running", stop_reason=None)

    async def wait(*, thread_id, run_id, timeout):
        return SimpleNamespace(run_id=run_id, status=_row_status(outcomes.get(run_id, "success")), stop_reason=None)

    return SimpleNamespace(dispatch_input=dispatch_input, wait=wait)


def _row_status(outcome: str) -> str:
    return "success" if outcome == "answered" else outcome


async def _queued_run(store, run_id, *input_ids, status="success"):
    from deerflow.runtime.runs.inputs import RunInputs

    await store.put(run_id, thread_id="thread", user_id=USER_ID, status="running")
    inputs = RunInputs(store, run_id, USER_ID)
    for input_id in input_ids:
        await inputs.submit(input_id, f"then {input_id}", "queue")
    await store.update_status(run_id, status)
    return inputs


def _statuses(state):
    return {item["id"]: item["status"] for item in state["items"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["waiting_for_input", "answered"])
async def test_follow_up_that_pauses_holds_the_rest_until_its_resumed_work(chain_store, outcome):
    from app.gateway.run_inputs import dispatch_queued_inputs
    from deerflow.runtime.runs.inputs import QUEUED_FROM_KEY, RunInputs

    source = await _queued_run(chain_store, "source", "A", "B")
    dispatched: list[str] = []
    agent_runs = _chain_agent_runs(chain_store, {"child-A": outcome}, dispatched)

    await dispatch_queued_inputs(source, agent_runs=agent_runs, thread_id="thread")
    # A paused for approval itself: B waits for A's resumed work, not a failure.
    assert dispatched == ["A"]
    assert _statuses(await source.read()) == {"A": "applied", "B": "pending"}
    assert (await RunInputs(chain_store, "child-A", USER_ID).read())[QUEUED_FROM_KEY] == "source"

    resume = await _queued_run(chain_store, "resume-A")
    await dispatch_queued_inputs(resume, agent_runs=agent_runs, thread_id="thread", continues_run_id="child-A")
    assert dispatched == ["A", "B"]
    assert _statuses(await source.read()) == {"A": "applied", "B": "applied"}


@pytest.mark.asyncio
async def test_unfinished_resumed_work_lapses_every_held_run(chain_store):
    from app.gateway.run_inputs import dispatch_queued_inputs

    paused = await _queued_run(chain_store, "paused", "A")
    resume = await _queued_run(chain_store, "resume", "C", status="error")
    dispatched: list[str] = []

    await dispatch_queued_inputs(resume, agent_runs=_chain_agent_runs(chain_store, {}, dispatched), thread_id="thread", continues_run_id="paused")
    assert dispatched == []
    assert _statuses(await paused.read()) == {"A": "not_applied"}


@pytest.mark.asyncio
async def test_failed_follow_up_lapses_later_held_runs(chain_store):
    from app.gateway.run_inputs import dispatch_queued_inputs

    paused = await _queued_run(chain_store, "paused", "A", "B")
    resume = await _queued_run(chain_store, "resume", "C")
    dispatched: list[str] = []

    await dispatch_queued_inputs(resume, agent_runs=_chain_agent_runs(chain_store, {"child-A": "error"}, dispatched), thread_id="thread", continues_run_id="paused")
    assert dispatched == ["A"]
    assert _statuses(await paused.read()) == {"A": "applied", "B": "not_applied"}
    assert _statuses(await resume.read()) == {"C": "not_applied"}


def test_steer_still_lapses_at_an_approval_pause():
    """Only queued follow-ups wait through a pause; an undelivered steer targeted the frozen work."""
    import asyncio

    from deerflow.runtime.runs.inputs import RunInputs
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    async def scenario():
        store = MemoryRunStore()
        await store.put("run", thread_id="thread", user_id="user", status="running")
        inputs = RunInputs(store, "run", "user")
        await inputs.submit("q", "later", "queue")
        await inputs.submit("s", "change course", "steer")
        await store.update_status("run", "waiting_for_input")
        await inputs.hold()
        state = await inputs.read()
        assert state["closed"] is True
        assert {item["id"]: item["status"] for item in state["items"]} == {"q": "pending", "s": "not_applied"}

    asyncio.run(scenario())


def test_paused_run_lists_its_queued_input_as_pending(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from app.gateway import run_inputs as gateway_run_inputs

    rows = [{"run_id": "paused", "status": "waiting_for_input", "run_inputs": {"closed": True, "items": [{"id": "q", "text": "later", "mode": "queue", "status": "pending"}]}}]

    class _Store:
        async def list_input_runs(self, thread_id, *, user_id=None):
            return rows

        async def active_input_run(self, thread_id, *, user_id=None):
            return None

    async def _user(_request):
        return "user"

    monkeypatch.setattr(gateway_run_inputs, "get_current_user", _user)
    monkeypatch.setattr(gateway_run_inputs, "_store", lambda _request: _Store())
    items = asyncio.run(gateway_run_inputs.list_thread_inputs("thread", SimpleNamespace()))["items"]
    assert [item["status"] for item in items] == ["pending"]


@pytest.mark.asyncio
async def test_follow_up_that_finishes_does_not_dispatch_its_source_queue(chain_store):
    """The queued-from link is followed only from a resume Run's predecessors."""
    from app.gateway.run_inputs import dispatch_queued_inputs
    from deerflow.runtime.runs.inputs import RunInputs

    source = await _queued_run(chain_store, "source", "A", "B")
    dispatched: list[str] = []
    agent_runs = _chain_agent_runs(chain_store, {}, dispatched)
    await dispatch_queued_inputs(source, agent_runs=agent_runs, thread_id="thread")
    assert dispatched == ["A", "B"]

    # child-A carries the queued-from link, but its own finalize dispatches nothing.
    await dispatch_queued_inputs(RunInputs(chain_store, "child-A", USER_ID), agent_runs=agent_runs, thread_id="thread")
    assert dispatched == ["A", "B"]


@pytest.mark.asyncio
async def test_answered_pause_leaves_dispatch_to_its_resume_run(chain_store):
    """A pause answered before this Run's own finalize reads success, yet its work is not done."""
    from app.gateway.run_inputs import dispatch_queued_inputs

    earlier = await _queued_run(chain_store, "earlier", "A")
    paused = await _queued_run(chain_store, "paused", "B", status="running")
    await paused.mark_paused()
    await chain_store.update_status("paused", "success")
    dispatched: list[str] = []
    agent_runs = _chain_agent_runs(chain_store, {}, dispatched)

    await dispatch_queued_inputs(paused, agent_runs=agent_runs, thread_id="thread", continues_run_id="earlier")
    assert dispatched == []
    assert _statuses(await earlier.read()) == {"A": "pending"}

    resume = await _queued_run(chain_store, "resume")
    await dispatch_queued_inputs(resume, agent_runs=agent_runs, thread_id="thread", continues_run_id="paused")
    assert dispatched == ["A", "B"]


@pytest.mark.asyncio
async def test_chain_beyond_the_hop_bound_lapses_its_oldest_runs(chain_store, monkeypatch, caplog):
    from app.gateway import run_inputs as gateway_run_inputs
    from deerflow.runtime.runs import inputs as runs_inputs

    monkeypatch.setattr(runs_inputs, "MAX_CONTINUATION_HOPS", 2)
    monkeypatch.setattr(gateway_run_inputs, "MAX_CONTINUATION_HOPS", 2)
    previous = None
    runs = []
    for index in range(4):
        run = await _queued_run(chain_store, f"pause-{index}", f"Q{index}")
        if previous is not None:
            await run.link_continuation(previous)
        runs.append(run)
        previous = run.run_id
    resume = await _queued_run(chain_store, "resume")
    dispatched: list[str] = []

    with caplog.at_level("WARNING", logger=gateway_run_inputs.logger.name):
        await gateway_run_inputs.dispatch_queued_inputs(resume, agent_runs=_chain_agent_runs(chain_store, {}, dispatched), thread_id="thread", continues_run_id=previous)
    # The two nearest pauses dispatch in order; the two oldest lapse for an explicit retry.
    assert dispatched == ["Q2", "Q3"]
    assert [_statuses(await run.read()) for run in runs[:2]] == [{"Q0": "not_applied"}, {"Q1": "not_applied"}]
    assert "pause-0" in caplog.text and "pause-1" in caplog.text


@pytest.mark.asyncio
async def test_recovered_resume_finds_the_consumed_pause(chain_store):
    """Checkpoint-only recovery has no answer handle; the consumed row still holds its queue."""
    from app.gateway.run_inputs import answered_pause_run_id

    await _queued_run(chain_store, "finished", "A")
    consumed = await _queued_run(chain_store, "consumed", "B", status="running")
    await consumed.mark_paused()
    await consumed.hold()
    await chain_store.update_status("consumed", "success")
    await _queued_run(chain_store, "crashed-resume", "C", status="error")
    await chain_store.put("recovery", thread_id="thread", user_id=USER_ID, status="pending")

    assert await answered_pause_run_id(chain_store, "thread", user_id=USER_ID, exclude_run_id="recovery") == "consumed"

    # Once the held queue is resolved there is nothing to continue.
    await consumed.pause()
    assert await answered_pause_run_id(chain_store, "thread", user_id=USER_ID, exclude_run_id="recovery") is None
