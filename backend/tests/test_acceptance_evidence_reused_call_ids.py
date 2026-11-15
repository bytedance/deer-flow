"""tests_passed evidence must follow each tool call, even when a provider reuses its id.

Tool-call ids are unique per assistant response, not per conversation: some
providers number calls per response, so two turns can both issue ``call_0``.
"""

import importlib.util
import sys
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool

from deerflow.config.app_config import AppConfig
from deerflow.subagents.acceptance_checks import check_acceptance_criteria
from deerflow.subagents.config import SubagentConfig

FAILED_RUN = "===== 1 failed, 2 passed in 0.10s =====\nExit Code: 1"
PASSED_RUN = "===== 3 passed in 0.10s ====="


@pytest.fixture
def executor_module(monkeypatch, tmp_path):
    # conftest installs an executor stub. Load the production module separately
    # so the real subagent graph streams, harvests and merges the evidence.
    path = Path(__file__).parents[1] / "packages/harness/deerflow/subagents/executor.py"
    spec = importlib.util.spec_from_file_location("_reused_call_id_executor", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    # The scripted bash tool has no sandbox; declare fresh-shell provenance so
    # the verdict depends only on which run the evidence attributes.
    monkeypatch.setattr(module, "_harvest_shell_persistence", lambda state: False)
    yield module
    module._shutdown_isolated_subagent_loop()


class ScriptedModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _bash_call(call_id: str, command: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": "bash", "id": call_id, "args": {"command": command}}])


@pytest.mark.asyncio
async def test_latest_failing_run_under_a_reused_call_id_fails_tests_passed(executor_module, monkeypatch):
    outputs = iter([FAILED_RUN, PASSED_RUN, FAILED_RUN])
    commands = []

    def bash(command: str) -> str:
        """Run a shell command."""
        commands.append(command)
        return next(outputs)

    # The provider numbers calls per response: the third run reuses call_0.
    responses = [
        _bash_call("call_0", "pytest tests"),
        _bash_call("call_1", "pytest tests -q"),
        _bash_call("call_0", "pytest tests"),
        AIMessage(content="Tests were run."),
    ]
    model = ScriptedModel(messages=iter(responses))
    monkeypatch.setattr(executor_module, "create_chat_model", lambda **kwargs: model)
    app_config = AppConfig.model_validate(
        {
            "models": [{"name": "offline", "use": "langchain_openai:ChatOpenAI", "model": "offline"}],
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "summarization": {"enabled": False},
        }
    )
    executor = executor_module.SubagentExecutor(
        config=SubagentConfig(name="tester", description="Offline test runner", skills=[]),
        tools=[StructuredTool.from_function(bash, name="bash")],
        parent_model="offline",
        app_config=app_config,
        thread_id="reused-call-id-thread",
        user_id="reused-call-id-user",
        acceptance_criteria=["tests_passed:pytest tests"],
    )

    result = await executor._aexecute("Run the test suite")

    assert result.status == executor_module.SubagentStatus.COMPLETED, result.error
    assert commands == ["pytest tests", "pytest tests -q", "pytest tests"]
    # Every run stays a separate entry, in execution order.
    assert [(entry["tool_call_id"], entry["status"]) for entry in result.bash_executions] == [("call_0", "error"), ("call_1", "success"), ("call_0", "error")]
    verdict = check_acceptance_criteria(["tests_passed:pytest tests"], bash_executions=result.bash_executions)
    # The decisive latest run failed, so the leaf is a checked negative.
    assert (verdict["leaves"][0]["checked"], verdict["all_hold"]) == (True, False), verdict


def test_reused_call_id_never_takes_another_commands_output(executor_module):
    # A cancelled or timed-out subagent leaves its last call unanswered. Its
    # reused id must not relabel the earlier subset run as the full suite.
    messages = [
        HumanMessage(content="Run the suite"),
        _bash_call("call_0", "pytest tests/unit"),
        ToolMessage(content=PASSED_RUN, tool_call_id="call_0"),
        _bash_call("call_0", "pytest tests"),
    ]

    executions = executor_module._harvest_bash_executions({"messages": messages})

    assert [entry["command"] for entry in executions] == ["pytest tests/unit"]
    verdict = check_acceptance_criteria(["tests_passed:pytest tests"], bash_executions=executions)
    assert verdict["all_hold"] is False, verdict


def test_merge_keeps_each_occurrence_of_a_reused_call_id(executor_module):
    first = executor_module._harvest_bash_executions({"messages": [_bash_call("call_0", "pytest tests"), ToolMessage(content=FAILED_RUN, tool_call_id="call_0", id="result-1")]})
    later = executor_module._harvest_bash_executions(
        {
            "messages": [
                _bash_call("call_0", "pytest tests"),
                ToolMessage(content=FAILED_RUN, tool_call_id="call_0", id="result-1"),
                _bash_call("call_1", "pytest tests -q"),
                ToolMessage(content=PASSED_RUN, tool_call_id="call_1", id="result-2"),
                _bash_call("call_0", "pytest tests"),
                ToolMessage(content=FAILED_RUN, tool_call_id="call_0", id="result-3"),
            ]
        }
    )
    result = executor_module.SubagentResult(task_id="task", trace_id="trace", status=executor_module.SubagentStatus.RUNNING)

    result.update_bash_executions(first)
    result.update_bash_executions(later)

    # The reused id's later run is appended, not written back over the first.
    assert [(entry["tool_call_id"], entry["status"]) for entry in result.bash_executions] == [("call_0", "error"), ("call_1", "success"), ("call_0", "error")]
    verdict = check_acceptance_criteria(["tests_passed:pytest tests"], bash_executions=result.bash_executions)
    assert (verdict["leaves"][0]["checked"], verdict["all_hold"]) == (True, False), verdict


def test_summary_cache_keeps_one_slot_per_run_of_a_reused_call_id(executor_module, monkeypatch):
    from unittest.mock import Mock

    from deerflow.subagents import acceptance_checks

    classify = Mock(wraps=acceptance_checks.summarize_test_output)
    monkeypatch.setattr(acceptance_checks, "summarize_test_output", classify)
    messages = [
        _bash_call("call_0", "pytest tests"),
        ToolMessage(content=FAILED_RUN, tool_call_id="call_0", id="result-1"),
        _bash_call("call_0", "pytest tests"),
        ToolMessage(content=PASSED_RUN, tool_call_id="call_0", id="result-2"),
    ]
    cache = {}

    for _ in range(3):
        executor_module._harvest_bash_executions({"messages": messages}, summary_cache=cache)

    # Each run is classified once; values chunks reuse both cached summaries.
    assert classify.call_count == 2
    assert list(cache) == [("result", "result-1"), ("result", "result-2")]


@pytest.mark.parametrize("call_id", [None, ""])
def test_a_call_without_an_id_records_no_evidence(executor_module, call_id):
    # Pairing needs a call id. Without one the owner of a result is unknown,
    # so the harvest records nothing and the leaf stays UNVERIFIED.
    messages = [
        AIMessage(content="", tool_calls=[{"name": "bash", "id": call_id, "args": {"command": "pytest tests"}}]),
        ToolMessage(content=PASSED_RUN, tool_call_id=call_id or ""),
    ]

    executions = executor_module._harvest_bash_executions({"messages": messages})

    assert executions == []
    verdict = check_acceptance_criteria(["tests_passed:pytest tests"], bash_executions=executions)
    assert (verdict["leaves"][0]["checked"], verdict["all_hold"]) == (False, False), verdict
