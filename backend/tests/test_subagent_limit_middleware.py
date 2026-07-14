"""Tests for SubagentLimitMiddleware."""

import logging
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares.subagent_limit_middleware import (
    DEFAULT_MAX_TOTAL_SUBAGENTS,
    MAX_CONCURRENT_SUBAGENTS,
    MAX_SUBAGENT_LIMIT,
    MIN_SUBAGENT_LIMIT,
    SubagentLimitMiddleware,
    _clamp_subagent_limit,
)
from deerflow.agents.thread_state import DelegationEntry


def _make_runtime(run_id: str = "run-1"):
    runtime = MagicMock()
    runtime.context = {"thread_id": "test-thread", "run_id": run_id}
    return runtime


def _task_call(task_id="call_1"):
    return {"name": "task", "id": task_id, "args": {"prompt": "do something"}}


def _other_call(name="bash", call_id="call_other"):
    return {"name": name, "id": call_id, "args": {}}


def _delegation(entry_id: str, *, run_id: str | None = None) -> DelegationEntry:
    entry: DelegationEntry = {
        "id": entry_id,
        "description": "prior work",
        "subagent_type": "general-purpose",
        "status": "completed",
        "created_at": "2026-07-11T00:00:00Z",
    }
    if run_id is not None:
        entry["run_id"] = run_id
    return entry


def _raw_tool_call(call_id: str, name: str = "task") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": "{}"},
    }


class TestClampSubagentLimit:
    def test_below_min_clamped_to_min(self):
        assert _clamp_subagent_limit(0) == MIN_SUBAGENT_LIMIT
        assert _clamp_subagent_limit(1) == MIN_SUBAGENT_LIMIT

    def test_above_max_clamped_to_max(self):
        assert _clamp_subagent_limit(10) == MAX_SUBAGENT_LIMIT
        assert _clamp_subagent_limit(100) == MAX_SUBAGENT_LIMIT

    def test_within_range_unchanged(self):
        assert _clamp_subagent_limit(2) == 2
        assert _clamp_subagent_limit(3) == 3
        assert _clamp_subagent_limit(4) == 4


class TestSubagentLimitMiddlewareInit:
    def test_default_max_concurrent(self):
        mw = SubagentLimitMiddleware()
        assert mw.max_concurrent == MAX_CONCURRENT_SUBAGENTS
        assert mw.max_total == DEFAULT_MAX_TOTAL_SUBAGENTS

    def test_custom_max_concurrent_clamped(self):
        mw = SubagentLimitMiddleware(max_concurrent=1)
        assert mw.max_concurrent == MIN_SUBAGENT_LIMIT

        mw = SubagentLimitMiddleware(max_concurrent=10)
        assert mw.max_concurrent == MAX_SUBAGENT_LIMIT


class TestTruncateTaskCalls:
    def test_no_messages_returns_none(self):
        mw = SubagentLimitMiddleware()
        assert mw._truncate_task_calls({"messages": []}) is None

    def test_missing_messages_returns_none(self):
        mw = SubagentLimitMiddleware()
        assert mw._truncate_task_calls({}) is None

    def test_last_message_not_ai_returns_none(self):
        mw = SubagentLimitMiddleware()
        state = {"messages": [HumanMessage(content="hello")]}
        assert mw._truncate_task_calls(state) is None

    def test_ai_no_tool_calls_returns_none(self):
        mw = SubagentLimitMiddleware()
        state = {"messages": [AIMessage(content="thinking...")]}
        assert mw._truncate_task_calls(state) is None

    def test_task_calls_within_limit_returns_none(self):
        mw = SubagentLimitMiddleware(max_concurrent=3)
        msg = AIMessage(
            content="",
            tool_calls=[_task_call("t1"), _task_call("t2"), _task_call("t3")],
        )
        assert mw._truncate_task_calls({"messages": [msg]}) is None

    def test_task_calls_exceeding_limit_truncated(self):
        mw = SubagentLimitMiddleware(max_concurrent=2)
        msg = AIMessage(
            content="",
            tool_calls=[_task_call("t1"), _task_call("t2"), _task_call("t3"), _task_call("t4")],
        )
        result = mw._truncate_task_calls({"messages": [msg]})
        assert result is not None
        updated_msg = result["messages"][0]
        task_calls = [tc for tc in updated_msg.tool_calls if tc["name"] == "task"]
        assert len(task_calls) == 2
        assert task_calls[0]["id"] == "t1"
        assert task_calls[1]["id"] == "t2"

    def test_non_task_calls_preserved(self):
        mw = SubagentLimitMiddleware(max_concurrent=2)
        msg = AIMessage(
            content="",
            tool_calls=[
                _other_call("bash", "b1"),
                _task_call("t1"),
                _task_call("t2"),
                _task_call("t3"),
                _other_call("read", "r1"),
            ],
        )
        result = mw._truncate_task_calls({"messages": [msg]})
        assert result is not None
        updated_msg = result["messages"][0]
        names = [tc["name"] for tc in updated_msg.tool_calls]
        assert "bash" in names
        assert "read" in names
        task_calls = [tc for tc in updated_msg.tool_calls if tc["name"] == "task"]
        assert len(task_calls) == 2

    def test_truncation_syncs_raw_provider_tool_calls(self):
        mw = SubagentLimitMiddleware(max_concurrent=2)
        msg = AIMessage(
            content="",
            tool_calls=[_task_call("t1"), _task_call("t2"), _task_call("t3"), _task_call("t4")],
            additional_kwargs={"tool_calls": [_raw_tool_call("t1"), _raw_tool_call("t2"), _raw_tool_call("t3"), _raw_tool_call("t4")]},
            response_metadata={"finish_reason": "tool_calls"},
        )

        result = mw._truncate_task_calls({"messages": [msg]})

        assert result is not None
        updated_msg = result["messages"][0]
        assert [tc["id"] for tc in updated_msg.tool_calls] == ["t1", "t2"]
        assert [tc["id"] for tc in updated_msg.additional_kwargs["tool_calls"]] == ["t1", "t2"]
        assert updated_msg.response_metadata["finish_reason"] == "tool_calls"

    def test_total_limit_counts_prior_delegations(self):
        mw = SubagentLimitMiddleware(max_concurrent=3, max_total=4)
        msg = AIMessage(
            content="",
            tool_calls=[_task_call("t4"), _task_call("t5"), _task_call("t6")],
            additional_kwargs={"tool_calls": [_raw_tool_call("t4"), _raw_tool_call("t5"), _raw_tool_call("t6")]},
            response_metadata={"finish_reason": "tool_calls"},
        )
        state = {
            "messages": [msg],
            "delegations": [_delegation("t1"), _delegation("t2"), _delegation("t3")],
        }

        result = mw._truncate_task_calls(state)

        assert result is not None
        updated_msg = result["messages"][0]
        assert [tc["id"] for tc in updated_msg.tool_calls] == ["t4"]
        assert [tc["id"] for tc in updated_msg.additional_kwargs["tool_calls"]] == ["t4"]
        assert "subagent delegation limit" not in updated_msg.content

    def test_missing_run_id_logs_fail_restrictive_fallback(self, caplog):
        mw = SubagentLimitMiddleware(max_concurrent=3, max_total=1)
        msg = AIMessage(content="", tool_calls=[_task_call("t2")])
        state = {"messages": [msg], "delegations": [_delegation("t1")]}

        with caplog.at_level(logging.WARNING, logger="deerflow.agents.middlewares.subagent_limit_middleware"):
            result = mw._truncate_task_calls(state)

        assert result is not None
        assert result["messages"][0].tool_calls == []
        assert "received no run_id" in caplog.text
        assert "counting all thread delegations" in caplog.text

    def test_total_limit_reached_forces_terminal_message(self):
        mw = SubagentLimitMiddleware(max_concurrent=3, max_total=3)
        msg = AIMessage(
            content="",
            tool_calls=[_task_call("t4")],
            additional_kwargs={"tool_calls": [_raw_tool_call("t4")]},
            response_metadata={"finish_reason": "tool_calls"},
        )
        state = {
            "messages": [msg],
            "delegations": [_delegation("t1"), _delegation("t2"), _delegation("t3")],
        }

        result = mw._truncate_task_calls(state)

        assert result is not None
        updated_msg = result["messages"][0]
        assert updated_msg.tool_calls == []
        assert "tool_calls" not in updated_msg.additional_kwargs
        assert updated_msg.response_metadata["finish_reason"] == "stop"
        assert "subagent delegation limit" in updated_msg.content

    def test_total_limit_ignores_previous_thread_delegations_for_new_run(self):
        mw = SubagentLimitMiddleware(max_concurrent=3, max_total=3)
        msg = AIMessage(
            content="",
            tool_calls=[_task_call("new-run-task")],
            additional_kwargs={"tool_calls": [_raw_tool_call("new-run-task")]},
            response_metadata={"finish_reason": "tool_calls"},
        )
        state = {
            "messages": [HumanMessage(content="new request"), msg],
            "delegations": [_delegation("old-1"), _delegation("old-2"), _delegation("old-3")],
        }

        assert mw.after_model(state, _make_runtime(run_id="run-2")) is None

    def test_total_limit_counts_only_current_run_delegations(self):
        mw = SubagentLimitMiddleware(max_concurrent=3, max_total=3)
        msg = AIMessage(
            content="",
            tool_calls=[_task_call("current-t3"), _task_call("current-t4")],
            additional_kwargs={"tool_calls": [_raw_tool_call("current-t3"), _raw_tool_call("current-t4")]},
            response_metadata={"finish_reason": "tool_calls"},
        )
        state = {
            "messages": [HumanMessage(content="continue"), msg],
            "delegations": [
                _delegation("old-t1", run_id="run-old"),
                _delegation("current-t1", run_id="run-current"),
                _delegation("current-t2", run_id="run-current"),
            ],
        }

        result = mw.after_model(state, _make_runtime(run_id="run-current"))

        assert result is not None
        updated_msg = result["messages"][0]
        assert [tc["id"] for tc in updated_msg.tool_calls] == ["current-t3"]
        assert [tc["id"] for tc in updated_msg.additional_kwargs["tool_calls"]] == ["current-t3"]

    def test_total_limit_reached_with_non_task_calls_still_adds_visible_notice(self):
        mw = SubagentLimitMiddleware(max_concurrent=3, max_total=1)
        msg = AIMessage(
            content="",
            tool_calls=[_task_call("blocked-task"), _other_call("bash", "allowed-bash")],
            additional_kwargs={"tool_calls": [_raw_tool_call("blocked-task"), _raw_tool_call("allowed-bash", name="bash")]},
            response_metadata={"finish_reason": "tool_calls"},
        )
        state = {
            "messages": [msg],
            "delegations": [_delegation("already-used", run_id="run-1")],
        }

        result = mw.after_model(state, _make_runtime(run_id="run-1"))

        assert result is not None
        updated_msg = result["messages"][0]
        assert [tc["id"] for tc in updated_msg.tool_calls] == ["allowed-bash"]
        assert [tc["id"] for tc in updated_msg.additional_kwargs["tool_calls"]] == ["allowed-bash"]
        assert "subagent delegation limit" in updated_msg.content

    def test_only_non_task_calls_returns_none(self):
        mw = SubagentLimitMiddleware()
        msg = AIMessage(
            content="",
            tool_calls=[_other_call("bash", "b1"), _other_call("read", "r1")],
        )
        assert mw._truncate_task_calls({"messages": [msg]}) is None


class TestAfterModel:
    def test_delegates_to_truncate(self):
        mw = SubagentLimitMiddleware(max_concurrent=2)
        runtime = _make_runtime()
        msg = AIMessage(
            content="",
            tool_calls=[_task_call("t1"), _task_call("t2"), _task_call("t3")],
        )
        result = mw.after_model({"messages": [msg]}, runtime)
        assert result is not None
        task_calls = [tc for tc in result["messages"][0].tool_calls if tc["name"] == "task"]
        assert len(task_calls) == 2
