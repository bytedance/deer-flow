"""Unittest acceptance requires actual passing tests, including annotated OK summaries."""

import asyncio
import importlib.util
import os
import shlex
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping
from deerflow.subagents.acceptance_checks import check_acceptance_criteria, render_acceptance_section, render_acceptance_segment


def _summary(total=2, options="", newline="\n"):
    return newline.join([f"Ran {total} tests in 0.001s", "", f"OK{options}"])


def _verdict(output, **overrides):
    execution = {"command": "python -m unittest", "status": "success", "shell_persistent": False, "output_tail": output, **overrides}
    return check_acceptance_criteria(["tests_passed:python -m unittest"], bash_executions=[execution])


@pytest.mark.parametrize("options", ["", " (skipped=1)", " (expected failures=1)", " (skipped=1, expected failures=1)"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_passing_tests_survive_unittest_annotations(options, newline):
    verdict = _verdict(_summary(total=3, options=options, newline=newline))
    assert verdict["all_hold"] is True
    assert "[holds]" in render_acceptance_section(verdict)
    assert "acceptance:" in render_acceptance_segment(verdict)
    assert "execution evidence only" in render_acceptance_section(verdict)


@pytest.mark.parametrize(
    "output",
    [
        "OK",
        "OK (skipped=1)",
        "ok\nexample/package",
        _summary(0),
        _summary(2, " (skipped=2)"),
        _summary(2, " (expected failures=2)"),
        _summary(2, " (skipped=1, expected failures=1)"),
        _summary(2, " (skipped=3)"),
        _summary(2, " (skipped=1, skipped=0)"),
        _summary(2, " (unknown=1)"),
        _summary("9" * 100),
        _summary(2, " (skipped=" + "9" * 100 + ")"),
        "Ran 2 tests in\n\nOK",
        "Ran 2 tests in 0.001s\n\nOK (skipped=",
        "warning: " + _summary(),
    ],
)
def test_incomplete_empty_or_nonpassing_unittest_evidence_remains_unverified(output):
    verdict = _verdict(output)
    assert (verdict["leaves"][0]["checked"], verdict["all_hold"]) == (False, False)
    assert "[UNVERIFIED]" in render_acceptance_section(verdict)


@pytest.mark.parametrize("failure", ["FAILED (failures=1)", "FAILED (errors=1)", "FAILED (unexpected successes=1)"])
@pytest.mark.parametrize("reverse", [False, True])
def test_failure_records_still_win_over_a_passing_summary(failure, reverse):
    records = [_summary(2, " (skipped=1)"), failure]
    verdict = _verdict("\n".join(reversed(records) if reverse else records))
    assert (verdict["leaves"][0]["checked"], verdict["all_hold"]) == (True, False)


@pytest.mark.parametrize(
    "overrides",
    [
        {"shell_persistent": True},
        {"shell_persistent": None},
        {"command_truncated": True},
        {"command": "python -m unittest sample.OneTest"},
        {"command": "echo 'other'; python -m unittest"},
        {"command": 'cd "OK (skipped=1)" && python -m unittest'},
    ],
)
def test_annotations_do_not_bypass_evidence_admission(overrides):
    assert _verdict(_summary(2, " (skipped=1)"), **overrides)["leaves"][0]["checked"] is False


def test_recorded_error_status_still_overrides_positive_counts():
    verdict = _verdict(_summary(2, " (skipped=1)"), status="error")
    assert (verdict["leaves"][0]["checked"], verdict["all_hold"]) == (True, False)


@pytest.fixture
def executor_module(monkeypatch):
    # conftest substitutes the executor; use its actual harvest implementation.
    path = Path(__file__).parents[1] / "packages/harness/deerflow/subagents/executor.py"
    spec = importlib.util.spec_from_file_location("_unittest_evidence_executor", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


class SandboxMessages(MessagesState):
    sandbox: dict


@pytest.mark.skipif(os.name == "nt", reason="Real LocalSandbox command integration uses a POSIX Python executable")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "methods,expected",
    [
        (" def test_pass(self): pass\n", (True, True)),
        (' def test_pass(self): pass\n @unittest.skip("optional")\n def test_skip(self): pass\n', (True, True)),
        (' @unittest.skip("optional")\n def test_skip(self): pass\n', (False, False)),
        (" pass\n", (True, False)),
        (" @unittest.expectedFailure\n def test_xfail(self): self.fail()\n", (False, False)),
        (" def test_pass(self): pass\n @unittest.expectedFailure\n def test_xfail(self): self.fail()\n", (True, True)),
        (" def test_fail(self): self.fail()\n", (True, False)),
        (' def test_error(self): raise RuntimeError("fixture")\n', (True, False)),
        (" @unittest.expectedFailure\n def test_xpass(self): pass\n", (True, False)),
    ],
    ids=["pass", "pass-and-skip", "all-skipped", "empty", "all-expected-failure", "pass-and-expected-failure", "failure", "error", "unexpected-success"],
)
async def test_native_unittest_results_reach_parent_acceptance(tmp_path, monkeypatch, executor_module, methods, expected):
    (tmp_path / "test_sample.py").write_text("import unittest\nclass Sample(unittest.TestCase):\n" + methods, encoding="utf-8")
    sandbox = LocalSandbox("unittest-evidence", path_mappings=[PathMapping("/mnt/user-data/workspace", str(tmp_path))])
    monkeypatch.setattr("deerflow.sandbox.sandbox_provider.get_sandbox_provider", lambda: SimpleNamespace(get=lambda sandbox_id: sandbox if sandbox_id == sandbox.id else None))
    outputs = []

    async def bash(command: str) -> str:
        output = await asyncio.to_thread(sandbox.execute_command, command, timeout=30)
        outputs.append(output)
        return output

    tool = StructuredTool.from_function(coroutine=bash, name="bash", description="Execute the offline Python unittest fixture.")
    graph = StateGraph(SandboxMessages)
    graph.add_node("tools", ToolNode([tool], awrap_tool_call=ToolErrorHandlingMiddleware().awrap_tool_call))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    command = shlex.quote(sys.executable) + " -m unittest discover -s /mnt/user-data/workspace"
    state = await graph.compile().ainvoke(
        {
            "sandbox": {"sandbox_id": sandbox.id},
            "messages": [AIMessage(content="", tool_calls=[{"name": "bash", "id": "unittest-call", "type": "tool_call", "args": {"command": command}}])],
        }
    )
    assert len(outputs) == 1 and "Ran " in outputs[0], outputs
    executions = executor_module._harvest_bash_executions(state)
    assert len(executions) == 1 and executions[0]["tool_call_id"] == "unittest-call"
    assert executions[0]["shell_persistent"] is False
    verdict = check_acceptance_criteria([f"tests_passed:{command}"], bash_executions=executions)
    assert (verdict["leaves"][0]["checked"], verdict["all_hold"]) == expected, (outputs, verdict)
    if expected == (True, False):
        # Python 3.12+ exits 5 for an empty selection, 1 for test errors/failures.
        exit_code = 5 if methods == " pass\n" else 1
        assert f"Exit Code: {exit_code}" in outputs[0]
        assert executions[0]["status"] == "error"
