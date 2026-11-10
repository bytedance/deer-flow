"""A resumed HITL decision reaches the persisted history feed.

The approval pause and its resolution run as two Runs. A rejected call never
executes, so HITL answers it in ``after_model`` of the resume run and no
``on_tool_end`` fires. The resume run's journal must still own that call, or the
rejection exists only in checkpoint state and disappears from
``/messages`` (and from the reloaded conversation once compaction drops it).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from starlette.testclient import TestClient
from test_hitl_approval_api import (  # noqa: F401
    _MODEL_PATCH,
    _approval_request_id,
    _create_thread,
    _enable_approval,
    _fake_model,
    _fake_two_target_model,
    _register_user,
    _resume,
    _run,
    _run_body,
    _run_tool_result_call_ids,
    _wait_for_approval,
    _wait_run_status,
    _wait_run_terminal,
    isolated_app,
    isolated_deer_flow_home,
)

from deerflow.runtime.runs.worker import _hitl_action_calls, _hitl_action_tool_names

pytestmark = pytest.mark.no_auto_user


def _feed_tool_results(client, tid):
    rows = client.get(f"/api/threads/{tid}/messages").json()
    return [row["content"] for row in rows if row.get("event_type") == "llm.tool.result"]


def _state_tool_messages(client, tid):
    state = client.get(f"/api/threads/{tid}").json()
    return [message for message in state["values"]["messages"] if message.get("type") == "tool"]


@pytest.mark.parametrize("decision", ["reject", "approve"])
def test_resolved_call_reaches_the_history_feed_once(isolated_app, decision):  # noqa: F811
    _enable_approval()
    with patch(_MODEL_PATCH, new=_fake_model), TestClient(isolated_app) as client:
        csrf = _register_user(client)
        tid = _create_thread(client, csrf)
        _run(client, csrf, tid, _run_body(input={"messages": [{"role": "user", "content": "write"}]}))
        _wait_for_approval(client, tid)
        resumed = _resume(client, csrf, tid, decision, value="do not write" if decision == "reject" else None)
        assert resumed.status_code == 200, resumed.text
        resume_run_id = resumed.json()["run_id"]
        _wait_run_terminal(client, tid, resume_run_id)

        state_results = _state_tool_messages(client, tid)
        feed_results = _feed_tool_results(client, tid)
        assert [message["id"] for message in feed_results] == [message["id"] for message in state_results]
        assert [message["tool_call_id"] for message in feed_results] == ["call_hitl_1"]
        if decision == "reject":
            assert "do not write" in feed_results[0]["content"]
            run_rows = client.get(f"/api/threads/{tid}/runs/{resume_run_id}/messages").json()
            run_rows = run_rows["data"] if isinstance(run_rows, dict) else run_rows
            assert any(row.get("event_type") == "llm.tool.result" for row in run_rows)


def test_mixed_decision_keeps_both_results_in_the_history_feed(isolated_app):  # noqa: F811
    _enable_approval()
    with patch(_MODEL_PATCH, new=_fake_two_target_model), TestClient(isolated_app) as client:
        csrf = _register_user(client)
        tid = _create_thread(client, csrf)
        rid = _run(client, csrf, tid, _run_body(input={"messages": [{"role": "user", "content": "write twice"}]})).json()["run_id"]
        _wait_run_status(client, tid, rid, "waiting_for_input")
        responses = [
            {"option_id": "approve", "tool_call_id": "call_hitl_1", "request_id": _approval_request_id(client, tid, "call_hitl_1")},
            {"option_id": "reject", "tool_call_id": "call_hitl_2", "request_id": _approval_request_id(client, tid, "call_hitl_2"), "value": "skip the second"},
        ]
        resumed = _run(client, csrf, tid, {"command": {"resume": {"responses": responses}}})
        assert resumed.status_code == 200, resumed.text
        resume_run_id = resumed.json()["run_id"]
        _wait_run_terminal(client, tid, resume_run_id)

        state_ids = sorted(message["id"] for message in _state_tool_messages(client, tid))
        feed_results = _feed_tool_results(client, tid)
        assert sorted(message["id"] for message in feed_results) == state_ids
        assert sorted(message["tool_call_id"] for message in feed_results) == ["call_hitl_1", "call_hitl_2"]
        assert sorted(_run_tool_result_call_ids(client, tid, resume_run_id)) == ["call_hitl_1", "call_hitl_2"]


def test_replay_gate_names_do_not_depend_on_an_adoptable_call_id():
    actions = [
        {"tool_call_id": "call_1", "tool_name": "write_file"},
        {"tool_name": "bash"},
        {"tool_call_id": "", "tool_name": "str_replace"},
    ]

    assert _hitl_action_tool_names(actions) == {"write_file", "bash", "str_replace"}
    assert _hitl_action_calls(actions) == {"call_1": "write_file"}
