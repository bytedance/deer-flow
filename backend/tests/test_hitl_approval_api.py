"""Gateway E2E for HITL tool approval (real app, scripted model)."""

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from starlette.testclient import TestClient
from test_runtime_lifecycle_e2e import (  # noqa: F401
    _create_thread,
    _preserve_process_config_singletons,
    _register_user,
    _reset_process_singletons,
    _run_body,
    isolated_deer_flow_home,
)

from deerflow.config import get_app_config

pytestmark = pytest.mark.no_auto_user

_MODEL_PATCH = "deerflow.agents.lead_agent.agent.create_chat_model"


def _enable_approval():
    from deerflow.config.tool_config import ToolConfig

    cfg = get_app_config()
    cfg.hitl_approval.enabled = True
    cfg.hitl_approval.tools = ["write_file"]
    if not any(tool.name == "write_file" for tool in cfg.tools):
        cfg.tools.append(ToolConfig(name="write_file", use="deerflow.sandbox.tools:write_file_tool", group="file:write"))


class _StateAwareModel(FakeMessagesListChatModel):
    call_count: int = 1

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        if any(isinstance(m, ToolMessage) for m in messages):
            message = AIMessage(content="final answer")
        else:
            call_count = self.call_count
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "write_file",
                        "args": {"path": f"/mnt/user-data/workspace/hitl-test-{index}.txt", "content": "ok"},
                        "id": f"call_hitl_{index}",
                    }
                    for index in range(1, call_count + 1)
                ],
            )
        return ChatResult(generations=[ChatGeneration(message=message)])


class _TwoStepStateAwareModel(_StateAwareModel):
    reuse_tool_call_id: bool = False

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        tool_message_count = sum(isinstance(message, ToolMessage) for message in messages)
        if tool_message_count >= 2:
            message = AIMessage(content="final answer")
        else:
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "write_file",
                        "args": {"path": f"/mnt/user-data/workspace/hitl-test-{tool_message_count + 1}.txt", "content": "ok"},
                        "id": "call_hitl_1" if self.reuse_tool_call_id else f"call_hitl_{tool_message_count + 1}",
                    }
                ],
            )
        return ChatResult(generations=[ChatGeneration(message=message)])


def _fake_two_step_model(*args, **kwargs):
    return _TwoStepStateAwareModel(responses=[])


def _fake_reused_call_id_model(*args, **kwargs):
    return _TwoStepStateAwareModel(responses=[], reuse_tool_call_id=True)


def _fake_model(*args, **kwargs):
    return _StateAwareModel(responses=[])


def _fake_two_target_model(*args, **kwargs):
    return _StateAwareModel(responses=[], call_count=2)


@pytest.fixture(params=["full", "delta"])
def isolated_app(request, isolated_deer_flow_home, monkeypatch):  # noqa: F811
    if request.param == "delta":
        config_path = isolated_deer_flow_home.parent / "config.yaml"
        config_path.write_text(
            config_path.read_text(encoding="utf-8").replace(
                "database:\n  backend: sqlite\n",
                "database:\n  backend: sqlite\n  checkpoint_channel_mode: delta\n",
            ),
            encoding="utf-8",
        )
    _preserve_process_config_singletons(monkeypatch)
    _reset_process_singletons(monkeypatch)
    from deerflow.config import app_config as app_config_module

    cfg = app_config_module.get_app_config()
    cfg.database.sqlite_dir = str(isolated_deer_flow_home / "db")
    from app.gateway.app import create_app

    return create_app()


def _run(client, csrf, tid, body):
    return client.post(f"/api/threads/{tid}/runs", json=body, headers={"X-CSRF-Token": csrf})


def _wait_for_status(client, tid, wanted, timeout=20.0):
    deadline = time.monotonic() + timeout
    state = {}
    while time.monotonic() < deadline:
        state = client.get(f"/api/threads/{tid}").json()
        if state.get("status") == wanted:
            return state
        time.sleep(0.2)
    raise AssertionError(f"thread did not reach {wanted}: {state}")


def _wait_for_approval(client, tid, timeout=20.0):
    deadline = time.monotonic() + timeout
    state = {}
    while time.monotonic() < deadline:
        state = client.get(f"/api/threads/{tid}").json()
        payloads = [item for group in state.get("interrupts", {}).values() for item in group]
        if payloads and payloads[0].get("value", {}).get("kind") == "hitl_approval":
            return state
        time.sleep(0.2)
    raise AssertionError(f"thread did not expose a HITL approval: {state}")


def _wait_run_status(client, tid, rid, wanted, timeout=20.0):
    deadline = time.monotonic() + timeout
    run = {}
    while time.monotonic() < deadline and run.get("status") != wanted:
        run = client.get(f"/api/threads/{tid}/runs/{rid}").json()
        time.sleep(0.2)
    return run


def _wait_run_terminal(client, tid, rid, timeout=20.0):
    deadline = time.monotonic() + timeout
    run = {}
    while time.monotonic() < deadline:
        run = client.get(f"/api/threads/{tid}/runs/{rid}").json()
        if run.get("status") not in ("running", "pending", "queued"):
            return run
        time.sleep(0.2)
    raise AssertionError(f"run did not finish: {run}")


def _approval_request_id(client, tid, tool_call_id):
    state = _wait_for_approval(client, tid)
    payload = next(item for group in state["interrupts"].values() for item in group)["value"]
    return next(action["request_id"] for action in payload["actions"] if action["tool_call_id"] == tool_call_id)


def _resume(client, csrf, tid, option_id, value=None, *, tool_call_id="call_hitl_1", request_id=None):
    response = {
        "option_id": option_id,
        "tool_call_id": tool_call_id,
        "request_id": request_id or _approval_request_id(client, tid, tool_call_id),
    }
    if value is not None:
        response["value"] = value
    return _run(client, csrf, tid, {"command": {"resume": {"responses": [response]}}})


def _feed_tool_result_ids(client, tid):
    rows = client.get(f"/api/threads/{tid}/messages").json()
    return [row["content"]["id"] for row in rows if row.get("event_type") == "llm.tool.result"]


def _run_tool_result_call_ids(client, tid, run_id):
    rows = client.get(f"/api/threads/{tid}/runs/{run_id}/messages").json()
    rows = rows["data"] if isinstance(rows, dict) else rows
    return [row["content"]["tool_call_id"] for row in rows if row.get("event_type") == "llm.tool.result"]


def test_approval_pause_then_approve_executes(isolated_app):
    _enable_approval()
    with patch(_MODEL_PATCH, new=_fake_model), TestClient(isolated_app) as client:
        csrf = _register_user(client)
        tid = _create_thread(client, csrf)
        rid = _run(client, csrf, tid, _run_body(input={"messages": [{"role": "user", "content": "write"}]})).json()["run_id"]
        state = _wait_for_approval(client, tid)
        deadline = time.monotonic() + 20.0
        run = {}
        while time.monotonic() < deadline and run.get("status") != "waiting_for_input":
            run = client.get(f"/api/threads/{tid}/runs/{rid}").json()
            time.sleep(0.2)
        assert run["status"] == "waiting_for_input"
        payloads = [i for group in state["interrupts"].values() for i in group]
        assert payloads and payloads[0]["value"]["kind"] == "hitl_approval"
        assert payloads[0]["value"]["pending_tool_call_ids"] == ["call_hitl_1"]

        conflict = _run(client, csrf, tid, _run_body(input={"messages": [{"role": "user", "content": "other"}]}))
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "approval_pending"

        approved = _resume(client, csrf, tid, "approve")
        assert approved.status_code == 200, approved.text
        _ = _wait_run_terminal(client, tid, approved.json()["run_id"])
        state = client.get(f"/api/threads/{tid}").json()
        contents = [m.get("content") for m in state["values"]["messages"] if m.get("type") == "tool"]
        assert "OK" in contents
        assert state["status"] == "idle"

        duplicate = _resume(client, csrf, tid, "approve", request_id=payloads[0]["value"]["request_id"])
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"]["code"] == "no_pending_approval"


def test_fresh_run_rechecks_pending_approval_at_durable_admission(isolated_app):
    """A pause created after the early guard still blocks fresh admission."""
    _enable_approval()
    model_started = threading.Event()
    release_model = threading.Event()
    admission_started = threading.Event()
    release_admission = threading.Event()

    class _GatedModel(_StateAwareModel):
        def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
            model_started.set()
            if not release_model.wait(20):
                raise TimeoutError("test did not release the model")
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    def _gated_model(*args, **kwargs):
        return _GatedModel(responses=[])

    from app.gateway import services

    original_resolve = services.resolve_project_context

    async def _gate_fresh_admission(*args, **kwargs):
        if model_started.is_set() and not admission_started.is_set():
            admission_started.set()
            if not await asyncio.to_thread(release_admission.wait, 20):
                raise TimeoutError("test did not release fresh admission")
        return await original_resolve(*args, **kwargs)

    with (
        patch(_MODEL_PATCH, new=_gated_model),
        patch("app.gateway.services.resolve_project_context", new=_gate_fresh_admission),
        TestClient(isolated_app) as client,
    ):
        csrf = _register_user(client)
        tid = _create_thread(client, csrf)
        initial = _run(client, csrf, tid, _run_body(input={"messages": [{"role": "user", "content": "write"}]}))
        assert initial.status_code == 200, initial.text
        assert model_started.wait(20)

        with ThreadPoolExecutor(max_workers=1) as pool:
            fresh = pool.submit(_run, client, csrf, tid, _run_body(input={"messages": [{"role": "user", "content": "replace"}]}))
            try:
                # The fresh request has passed its early check but not durable
                # admission. Only now let the other run expose its pause.
                assert admission_started.wait(20)
                release_model.set()
                _wait_for_approval(client, tid)
                release_admission.set()
                conflict = fresh.result(timeout=20)
            finally:
                release_model.set()
                release_admission.set()

        assert conflict.status_code == 409, conflict.text
        assert conflict.json()["detail"]["code"] == "approval_pending"
        assert _wait_run_status(client, tid, initial.json()["run_id"], "waiting_for_input")["status"] == "waiting_for_input"

        cleanup = _resume(client, csrf, tid, "reject")
        assert cleanup.status_code == 200, cleanup.text
        _wait_run_terminal(client, tid, cleanup.json()["run_id"])


def test_approval_reject_returns_reason_without_execution(isolated_app):
    _enable_approval()
    with patch(_MODEL_PATCH, new=_fake_model), TestClient(isolated_app) as client:
        csrf = _register_user(client)
        tid = _create_thread(client, csrf)
        _run(client, csrf, tid, _run_body(input={"messages": [{"role": "user", "content": "write"}]}))
        _wait_for_approval(client, tid)
        rejected = _resume(client, csrf, tid, "reject", value="do not write")
        assert rejected.status_code == 200, rejected.text
        _wait_run_terminal(client, tid, rejected.json()["run_id"])
        state = client.get(f"/api/threads/{tid}").json()
        contents = [m.get("content") for m in state["values"]["messages"] if m.get("type") == "tool"]
        assert any("do not write" in str(c) for c in contents)
        assert "OK" not in contents


def test_invalid_resume_is_422_and_does_not_create_run(isolated_app):
    _enable_approval()
    with patch(_MODEL_PATCH, new=_fake_model), TestClient(isolated_app) as client:
        csrf = _register_user(client)
        tid = _create_thread(client, csrf)
        rid = _run(client, csrf, tid, _run_body(input={"messages": [{"role": "user", "content": "write"}]})).json()["run_id"]
        _wait_run_status(client, tid, rid, "waiting_for_input")
        # Wrong id → 422 without admitting a run; a valid approval still works.
        bad = _run(client, csrf, tid, {"command": {"resume": {"responses": [{"option_id": "approve", "tool_call_id": "wrong", "request_id": "unused"}]}}})
        assert bad.status_code == 422, bad.text
        assert bad.json()["detail"]["code"] == "invalid_approval_response"
        assert {run["run_id"] for run in client.get(f"/api/threads/{tid}/runs").json()} == {rid}
        good = _resume(client, csrf, tid, "approve")
        assert good.status_code == 200, good.text


def test_stale_request_id_cannot_approve_reused_tool_call(isolated_app):
    _enable_approval()
    with patch(_MODEL_PATCH, new=_fake_reused_call_id_model), TestClient(isolated_app) as client:
        csrf = _register_user(client)
        tid = _create_thread(client, csrf)
        first_run_id = _run(client, csrf, tid, _run_body(input={"messages": [{"role": "user", "content": "write twice"}]})).json()["run_id"]
        first_pause = _wait_for_approval(client, tid)
        first_payload = next(item for group in first_pause["interrupts"].values() for item in group)["value"]
        first_request_id = first_payload["request_id"]
        _wait_run_status(client, tid, first_run_id, "waiting_for_input")

        rejected = _resume(client, csrf, tid, "reject", value="reject the first arguments")
        assert rejected.status_code == 200, rejected.text
        second_run_id = rejected.json()["run_id"]
        _wait_run_status(client, tid, second_run_id, "waiting_for_input")
        second_pause = _wait_for_approval(client, tid)
        second_payload = next(item for group in second_pause["interrupts"].values() for item in group)["value"]
        assert second_payload["pending_tool_call_ids"] == first_payload["pending_tool_call_ids"] == ["call_hitl_1"]
        assert second_payload["request_id"] != first_request_id

        stale = _run(
            client,
            csrf,
            tid,
            {"command": {"resume": {"responses": [{"option_id": "approve", "tool_call_id": "call_hitl_1", "request_id": first_request_id}]}}},
        )
        assert stale.status_code == 422, stale.text
        assert stale.json()["detail"]["code"] == "invalid_approval_response"
        assert {run["run_id"] for run in client.get(f"/api/threads/{tid}/runs").json()} == {first_run_id, second_run_id}
        state = client.get(f"/api/threads/{tid}").json()
        tool_messages = [message for message in state["values"]["messages"] if message.get("type") == "tool"]
        assert len(tool_messages) == 1
        assert "OK" not in [message.get("content") for message in tool_messages]

        approved = _resume(client, csrf, tid, "approve")
        assert approved.status_code == 200, approved.text
        terminal = _wait_run_terminal(client, tid, approved.json()["run_id"])
        assert terminal["status"] == "success"
        state = client.get(f"/api/threads/{tid}").json()
        tool_messages = [message for message in state["values"]["messages"] if message.get("type") == "tool"]
        assert len(tool_messages) == 2
        assert sum(message.get("content") == "OK" for message in tool_messages) == 1


def test_duplicate_resume_ids_are_422_without_creating_a_run(isolated_app):
    _enable_approval()
    with patch(_MODEL_PATCH, new=_fake_two_target_model), TestClient(isolated_app) as client:
        csrf = _register_user(client)
        tid = _create_thread(client, csrf)
        rid = _run(client, csrf, tid, _run_body(input={"messages": [{"role": "user", "content": "write twice"}]})).json()["run_id"]
        _wait_run_status(client, tid, rid, "waiting_for_input")
        duplicate = _run(
            client,
            csrf,
            tid,
            {
                "command": {
                    "resume": {
                        "responses": [
                            {"option_id": "reject", "tool_call_id": "call_hitl_1", "request_id": _approval_request_id(client, tid, "call_hitl_1")},
                            {"option_id": "reject", "tool_call_id": "call_hitl_1", "request_id": _approval_request_id(client, tid, "call_hitl_1")},
                        ]
                    }
                }
            },
        )
        assert duplicate.status_code == 422, duplicate.text
        assert duplicate.json()["detail"]["code"] == "invalid_approval_response"
        assert {run["run_id"] for run in client.get(f"/api/threads/{tid}/runs").json()} == {rid}

        mixed = _run(
            client,
            csrf,
            tid,
            {
                "command": {
                    "resume": {
                        "responses": [
                            {"option_id": "approve", "tool_call_id": "call_hitl_1", "request_id": _approval_request_id(client, tid, "call_hitl_1")},
                            {"option_id": "reject", "tool_call_id": "call_hitl_2", "value": "second rejected", "request_id": _approval_request_id(client, tid, "call_hitl_2")},
                        ]
                    }
                }
            },
        )
        assert mixed.status_code == 200, mixed.text
        terminal = _wait_run_terminal(client, tid, mixed.json()["run_id"])
        assert terminal["status"] == "success"
        state = client.get(f"/api/threads/{tid}").json()
        tool_messages = [message for message in state["values"]["messages"] if message.get("type") == "tool"]
        assert sum(message.get("content") == "OK" for message in tool_messages) == 1
        assert any("second rejected" in str(message.get("content")) for message in tool_messages)


def test_disabled_resume_409_and_all_reject_escape(isolated_app):
    _enable_approval()
    with patch(_MODEL_PATCH, new=_fake_two_step_model), TestClient(isolated_app) as client:
        csrf = _register_user(client)
        tid = _create_thread(client, csrf)
        _run(client, csrf, tid, _run_body(input={"messages": [{"role": "user", "content": "write"}]}))
        _wait_for_approval(client, tid)
        get_app_config().hitl_approval.enabled = False
        disabled = _resume(client, csrf, tid, "approve")
        assert disabled.status_code == 409
        assert disabled.json()["detail"]["code"] == "hitl_approval_disabled"
        escape = _resume(client, csrf, tid, "reject")
        assert escape.status_code == 200, escape.text
        terminal = _wait_run_terminal(client, tid, escape.json()["run_id"])
        assert terminal["status"] == "success"
        assert _wait_for_status(client, tid, "idle")["status"] == "idle"
        state_tools = [m for m in client.get(f"/api/threads/{tid}").json()["values"]["messages"] if m.get("type") == "tool"]
        contents = [m.get("content") for m in state_tools]
        assert "OK" not in contents
        assert len(contents) == 2
        # The escape run adopts the paused call, so its denial reaches the history feed.
        assert _feed_tool_result_ids(client, tid) == [m["id"] for m in state_tools]
        assert "call_hitl_1" in _run_tool_result_call_ids(client, tid, escape.json()["run_id"])


@pytest.mark.parametrize("current_tools", [["bash"], []], ids=["changed", "cleared"])
def test_changed_tools_all_reject_escape_preserves_later_gate(isolated_app, current_tools):
    _enable_approval()
    with patch(_MODEL_PATCH, new=_fake_two_step_model), TestClient(isolated_app) as client:
        csrf = _register_user(client)
        tid = _create_thread(client, csrf)
        _run(client, csrf, tid, _run_body(input={"messages": [{"role": "user", "content": "write"}]}))
        _wait_for_approval(client, tid)
        get_app_config().hitl_approval.tools = current_tools

        escape = _resume(client, csrf, tid, "reject")
        assert escape.status_code == 200, escape.text
        second_run_id = escape.json()["run_id"]
        second_pause = _wait_run_status(client, tid, second_run_id, "waiting_for_input")
        assert second_pause["status"] == "waiting_for_input"
        state = _wait_for_approval(client, tid)
        payloads = [item for group in state["interrupts"].values() for item in group]
        assert payloads[0]["value"]["pending_tool_call_ids"] == ["call_hitl_2"]
        tool_messages = [message for message in state["values"]["messages"] if message.get("type") == "tool"]
        assert len(tool_messages) == 1
        assert tool_messages[0]["tool_call_id"] == "call_hitl_1"
        assert tool_messages[0]["status"] == "error"
        assert "OK" not in [message.get("content") for message in tool_messages]
        assert _run_tool_result_call_ids(client, tid, second_run_id) == ["call_hitl_1"]

        second_escape = _resume(client, csrf, tid, "reject", tool_call_id="call_hitl_2")
        assert second_escape.status_code == 200, second_escape.text
        terminal = _wait_run_terminal(client, tid, second_escape.json()["run_id"])
        assert terminal["status"] == "success"
        assert _wait_for_status(client, tid, "idle")["status"] == "idle"
        tool_messages = [message for message in client.get(f"/api/threads/{tid}").json()["values"]["messages"] if message.get("type") == "tool"]
        assert len(tool_messages) == 2
        assert all(message.get("status") == "error" for message in tool_messages)
        assert "OK" not in [message.get("content") for message in tool_messages]
        assert _feed_tool_result_ids(client, tid) == [message["id"] for message in tool_messages]
        assert _run_tool_result_call_ids(client, tid, second_escape.json()["run_id"]) == ["call_hitl_2"]


def test_stale_all_reject_cannot_dismiss_newer_pause(isolated_app):
    """Checkpoint-only recovery is limited to the pause that was validated."""
    _enable_approval()
    with patch(_MODEL_PATCH, new=_fake_two_step_model), TestClient(isolated_app) as client:
        csrf = _register_user(client)
        tid = _create_thread(client, csrf)
        initial = _run(client, csrf, tid, _run_body(input={"messages": [{"role": "user", "content": "write twice"}]}))
        assert initial.status_code == 200, initial.text
        _wait_for_approval(client, tid)
        first_request_id = _approval_request_id(client, tid, "call_hitl_1")

        reject_validated = threading.Event()
        release_reject = threading.Event()
        from app.gateway import services

        original_resolve = services.resolve_project_context

        async def _queue_reject_before_admission(*args, **kwargs):
            if not reject_validated.is_set():
                # resolve_project_context runs after resume validation but before
                # the per-thread admission lock, so P1 can still be approved.
                reject_validated.set()
                if not await asyncio.to_thread(release_reject.wait, 20):
                    raise TimeoutError("test did not release stale rejection")
            return await original_resolve(*args, **kwargs)

        with (
            patch("app.gateway.services.resolve_project_context", new=_queue_reject_before_admission),
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            stale_reject = pool.submit(_resume, client, csrf, tid, "reject", tool_call_id="call_hitl_1", request_id=first_request_id)
            try:
                assert reject_validated.wait(20)
                approved = _resume(client, csrf, tid, "approve", request_id=first_request_id)
                assert approved.status_code == 200, approved.text
                second_run_id = approved.json()["run_id"]
                assert _wait_run_status(client, tid, second_run_id, "waiting_for_input")["status"] == "waiting_for_input"
                second_request_id = _approval_request_id(client, tid, "call_hitl_2")
                assert second_request_id != first_request_id

                release_reject.set()
                conflict = stale_reject.result(timeout=20)
            finally:
                release_reject.set()

        assert conflict.status_code == 409, conflict.text
        assert conflict.json()["detail"]["code"] == "no_pending_approval"
        assert client.get(f"/api/threads/{tid}/runs/{second_run_id}").json()["status"] == "waiting_for_input"
        state = _wait_for_approval(client, tid)
        payloads = [item for group in state["interrupts"].values() for item in group]
        assert payloads[0]["value"]["pending_tool_call_ids"] == ["call_hitl_2"]

        cleanup = _resume(client, csrf, tid, "reject", tool_call_id="call_hitl_2", request_id=second_request_id)
        assert cleanup.status_code == 200, cleanup.text
        _wait_run_terminal(client, tid, cleanup.json()["run_id"])


@pytest.mark.asyncio
async def test_generic_interrupt_resume_admission_survives_head_moving_state_update(monkeypatch):
    from langchain_core.messages import AIMessage, HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import MessagesState, StateGraph
    from langgraph.types import interrupt

    from app.gateway.hitl_approval import validate_resume_request

    class EmptyRunStore:
        async def list_by_thread(self, thread_id, limit):
            return []

    monkeypatch.setattr("app.gateway.deps.get_run_store", lambda request: EmptyRunStore())

    def answer(state):
        value = interrupt({"question": "Continue?"})
        return {"messages": [AIMessage(content=f"answer:{value}")]}

    builder = StateGraph(MessagesState)
    builder.add_node("answer", answer)
    builder.set_entry_point("answer")
    builder.set_finish_point("answer")
    saver = InMemorySaver()
    graph = builder.compile(checkpointer=saver)
    config = {"configurable": {"thread_id": "generic-head-move"}}
    await graph.ainvoke({"messages": [HumanMessage(content="go")]}, config)
    await graph.aupdate_state(config, {"messages": [AIMessage(content="head move")]}, as_node="answer")
    accessor = SimpleNamespace(aget=graph.aget_state, checkpointer=saver)
    assert not (await graph.aget_state(config)).next

    body = SimpleNamespace(command={"resume": "yes"})
    await validate_resume_request(
        request=SimpleNamespace(),
        thread_id="generic-head-move",
        accessor=accessor,
        read_config=config,
        enabled=False,
        body=body,
    )


@pytest.mark.asyncio
async def test_mark_approval_answered_preserves_idempotency_fields(monkeypatch):
    from app.gateway.hitl_approval import mark_approval_answered
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    identity = {"version": 1, "kind": "resume", "sha256": "a" * 64}
    store = MemoryRunStore()
    await store.put(
        "paused-run",
        thread_id="thread-1",
        status="waiting_for_input",
        metadata={"hitl_approval": {"kind": "hitl_approval", "request_id": "approval-1"}, "retained": True},
        idempotency_key="http-run:key",
        idempotency_request=identity,
    )
    monkeypatch.setattr("app.gateway.deps.get_run_store", lambda request: store)

    await mark_approval_answered(SimpleNamespace(), "thread-1")

    answered = await store.get("paused-run")
    assert answered is not None
    assert answered["status"] == "success"
    assert answered["idempotency_key"] == "http-run:key"
    assert answered["idempotency_request"] == identity
    assert answered["metadata"] == {"retained": True}


@pytest.mark.asyncio
async def test_run_store_fallback_uses_original_langgraph_task_id(monkeypatch):
    from langchain_core.messages import AIMessage, HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import MessagesState, StateGraph
    from langgraph.types import interrupt

    from app.gateway.hitl_approval import find_pending_interrupts

    payload = {
        "kind": "hitl_approval",
        "version": 1,
        "request_id": "approval-1",
        "actions": [],
        "allowed_decisions": ["approve", "reject"],
        "pending_tool_call_ids": ["call-1"],
    }

    class WaitingRunStore:
        async def list_by_thread(self, thread_id, limit):
            return [{"run_id": "paused-run", "status": "waiting_for_input", "metadata": {"hitl_approval": payload}}]

    monkeypatch.setattr("app.gateway.deps.get_run_store", lambda request: WaitingRunStore())

    def approval(state):
        value = interrupt(payload)
        return {"messages": [AIMessage(content=f"answer:{value}")]}

    builder = StateGraph(MessagesState)
    builder.add_node("approval", approval)
    builder.set_entry_point("approval")
    builder.set_finish_point("approval")
    saver = InMemorySaver()
    graph = builder.compile(checkpointer=saver)
    config = {"configurable": {"thread_id": "approval-head-move"}}
    await graph.ainvoke({"messages": [HumanMessage(content="go")]}, config)
    paused = await graph.aget_state(config)
    paused_task = next(task for task in paused.tasks if task.interrupts)
    original_interrupt = paused_task.interrupts[0]
    await graph.aupdate_state(config, {"messages": [AIMessage(content="head move")]}, as_node="approval")
    accessor = SimpleNamespace(aget=graph.aget_state, checkpointer=saver)
    assert not (await graph.aget_state(config)).next

    pending = await find_pending_interrupts(SimpleNamespace(), "approval-head-move", accessor=accessor, read_config=config)

    assert set(pending) == {paused_task.id}
    assert pending[paused_task.id][0].value == payload
    assert pending[paused_task.id][0].id == original_interrupt.id


@pytest.mark.asyncio
async def test_run_store_fallback_reconstructs_interrupt_without_checkpoint(monkeypatch):
    from app.gateway.hitl_approval import find_pending_interrupts
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    payload = {
        "kind": "hitl_approval",
        "request_id": "approval-store-only",
        "pending_tool_call_ids": ["call-1"],
    }
    store = MemoryRunStore()
    await store.put(
        "paused-run",
        thread_id="thread-store-only",
        status="waiting_for_input",
        metadata={"hitl_approval": payload},
    )
    monkeypatch.setattr("app.gateway.deps.get_run_store", lambda request: store)

    pending = await find_pending_interrupts(SimpleNamespace(), "thread-store-only")

    assert set(pending) == {"paused-run"}
    assert len(pending["paused-run"]) == 1
    assert pending["paused-run"][0].value == payload
    assert pending["paused-run"][0].id == "approval-store-only"


@pytest.mark.asyncio
async def test_newest_resume_write_subtracts_answered_checkpoint_pause():
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import MessagesState, StateGraph
    from langgraph.types import Command, interrupt

    from app.gateway.hitl_approval import has_any_pending_interrupt

    def answer(state):
        value = interrupt({"question": "Continue?"})
        return {"messages": [AIMessage(content=f"answer:{value}")]}

    builder = StateGraph(MessagesState)
    builder.add_node("answer", answer)
    builder.set_entry_point("answer")
    builder.set_finish_point("answer")
    saver = InMemorySaver()
    graph = builder.compile(checkpointer=saver)
    config = {"configurable": {"thread_id": "answered-pause"}}
    await graph.ainvoke({"messages": [HumanMessage(content="go")]}, config)
    accessor = SimpleNamespace(checkpointer=saver)

    assert await has_any_pending_interrupt(accessor, config) is True
    await graph.ainvoke(Command(resume="yes"), config)
    assert not (await graph.aget_state(config)).next
    assert await has_any_pending_interrupt(accessor, config) is False


@pytest.mark.asyncio
async def test_pending_interrupts_fall_back_to_sync_saver_history():
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import MessagesState, StateGraph
    from langgraph.types import interrupt

    from app.gateway.hitl_approval import _interrupt_from_checkpoint_history, _pending_interrupts_from_checkpoint_history, has_any_pending_interrupt

    class SyncOnlySaver(InMemorySaver):
        def alist(self, *args, **kwargs):
            raise NotImplementedError

    payload = {"question": "Continue?"}

    def answer(state):
        value = interrupt(payload)
        return {"messages": [AIMessage(content=f"answer:{value}")]}

    builder = StateGraph(MessagesState)
    builder.add_node("answer", answer)
    builder.set_entry_point("answer")
    builder.set_finish_point("answer")
    saver = SyncOnlySaver()
    graph = builder.compile(checkpointer=saver)
    config = {"configurable": {"thread_id": "sync-saver-pause"}}
    await graph.ainvoke({"messages": [HumanMessage(content="go")]}, config)

    pending = await _pending_interrupts_from_checkpoint_history(saver, config)
    recovered = await _interrupt_from_checkpoint_history(SimpleNamespace(checkpointer=saver), config, payload)

    assert len(pending) == 1
    assert next(iter(pending.values()))[0].value["question"] == "Continue?"
    assert recovered is not None
    recovered_task_id, recovered_interrupt = recovered
    assert recovered_task_id in pending
    assert recovered_interrupt.value == payload
    assert await has_any_pending_interrupt(SimpleNamespace(checkpointer=saver), config) is True
