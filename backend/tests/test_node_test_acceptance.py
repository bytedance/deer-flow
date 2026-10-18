"""Node's native reporters must prove executed tests, not TAP point labels."""

import asyncio
import importlib.util
import os
import shlex
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping
from deerflow.subagents.acceptance_checks import _carries_summary_shape, check_acceptance_criteria, render_acceptance_section


def _summary(prefix="#", *, passed=1, failed=0, cancelled=0, skipped=0, todo=0, total=None):
    counters = {"tests": passed + failed + cancelled + skipped + todo if total is None else total, "suites": 0, "pass": passed, "fail": failed, "cancelled": cancelled, "skipped": skipped, "todo": todo}
    return "\n".join(f"{prefix} {key} {value}" for key, value in counters.items()) + f"\n{prefix} duration_ms 12.5"


def _verdict(output, **overrides):
    execution = {"command": "node --test", "status": "success", "shell_persistent": False, "output_tail": output, **overrides}
    return check_acceptance_criteria(["tests_passed:node --test"], bash_executions=[execution])


@pytest.mark.parametrize("prefix", ["#", "ℹ"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_native_reporters_accept_nonempty_passes(prefix, newline):
    verdict = _verdict(_summary(prefix, skipped=1, todo=1).replace("\n", newline))
    assert verdict["all_hold"] is True
    assert "[holds]" in render_acceptance_section(verdict)


@pytest.mark.parametrize("prefix", ["#", "ℹ"])
@pytest.mark.parametrize("counts", [{"failed": 1}, {"cancelled": 1}])
def test_native_failures_override_incidental_pass_text(prefix, counts):
    verdict = _verdict("ok 1 - all tests passed\n" + _summary(prefix, **counts))
    assert (verdict["leaves"][0]["checked"], verdict["all_hold"]) == (True, False)


@pytest.mark.parametrize("prefix", ["#", "ℹ"])
@pytest.mark.parametrize("counts", [{}, {"skipped": 2}, {"todo": 2}, {"skipped": 1, "todo": 1}])
def test_empty_skipped_and_todo_summaries_supply_no_proof(prefix, counts):
    verdict = _verdict("ok 1 - all tests passed # SKIP\n" + _summary(prefix, passed=0, **counts))
    assert (verdict["leaves"][0]["checked"], verdict["all_hold"]) == (False, False)


@pytest.mark.parametrize(
    "output",
    [
        "ok 1 - sample",
        "ok 12 # SKIP",
        _summary(total=4),
        _summary(passed="9" * 100, total=1),
        _summary().replace("# fail 0\n", ""),
        _summary().replace("# fail 0", "ℹ fail 0"),
        _summary().replace("# pass 1", "# pass -1"),
        _summary().split("# todo")[0],
    ],
)
def test_tap_points_and_incomplete_or_inconsistent_counts_remain_unverified(output):
    assert _verdict(output)["leaves"][0]["checked"] is False


@pytest.mark.parametrize("reverse", [False, True])
def test_failing_summary_wins_over_successful_sibling(reverse):
    summaries = [_summary(), _summary(failed=1)]
    verdict = _verdict("\n".join(reversed(summaries) if reverse else summaries))
    assert (verdict["leaves"][0]["checked"], verdict["all_hold"]) == (True, False)


@pytest.mark.parametrize(
    "overrides",
    [{"shell_persistent": True}, {"shell_persistent": None}, {"command_truncated": True}, {"command": "node --test sample.test.cjs"}, {"command": "echo other; node --test"}],
)
def test_node_counts_do_not_bypass_execution_admission(overrides):
    assert _verdict(_summary(), **overrides)["leaves"][0]["checked"] is False


def test_go_package_and_pytest_controls_still_pass():
    assert _verdict("ok\texample.org/project\t0.005s")["all_hold"] is True
    assert _verdict("ok\t123\t0.005s")["all_hold"] is True
    assert _verdict("2 passed in 0.01s")["all_hold"] is True


@pytest.mark.parametrize(
    "point",
    [
        "ok 1 - all tests passed # SKIP",
        "ok 12 # all tests passed",
        "✔ all tests passed (1ms)",
        "﹣ all tests passed (1ms)",
        "▶ all tests passed",
        "⚠ all tests passed",
        "    ok 1 - all tests passed # SKIP",
        "# Subtest: all tests passed\nok 1 - all tests passed # SKIP",
    ],
)
@pytest.mark.parametrize("tail", ["", _summary(passed=0, skipped=1).split("# todo")[0]])
def test_point_labels_cannot_supply_pass_evidence(point, tail):
    verdict = _verdict(point + "\n" + tail)
    assert (verdict["leaves"][0]["checked"], verdict["all_hold"]) == (False, False)


def test_recorded_exit_error_overrides_node_positive_counts():
    verdict = _verdict(_summary(), status="error")
    assert (verdict["leaves"][0]["checked"], verdict["all_hold"]) == (True, False)


def test_newest_matching_execution_is_decisive():
    first = {"command": "node --test", "status": "success", "shell_persistent": False, "output_tail": _summary(failed=1)}
    second = {**first, "output_tail": _summary()}
    assert check_acceptance_criteria(["tests_passed:node --test"], bash_executions=[first, second])["all_hold"] is True
    assert check_acceptance_criteria(["tests_passed:node --test"], bash_executions=[second, first])["all_hold"] is False


def test_empty_node_sibling_does_not_veto_another_runner():
    output = "2 passed in 0.01s\n" + _summary(passed=0)
    execution = {"command": "make test", "status": "success", "shell_persistent": False, "output_tail": output}
    assert check_acceptance_criteria(["tests_passed:make test"], bash_executions=[execution])["all_hold"] is True


@pytest.mark.parametrize("label", ["0 passed", "1 failed", "1 error"])
@pytest.mark.parametrize("point", ["# Subtest: {label}\n    ok 1 - {label}", "⚠ {label} # TODO"])
def test_test_names_cannot_supply_failure_or_zero_evidence(label, point):
    verdict = _verdict(point.format(label=label) + "\n" + _summary())
    assert verdict["all_hold"] is True


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_todo_diagnostic_location_cannot_supply_error_count(newline):
    output = "⚠ 1 failed # TODO\n" + _summary("ℹ", todo=1) + "\ntest at sample.test.cjs:1:57\n\n  Error: fixture"
    assert _verdict(output.replace("\n", newline))["all_hold"] is True


def test_color_codes_are_normalized_for_counts_and_output_admission():
    output = "\x1b[90m﹣ all tests passed\x1b[39m\n" + "\n".join(f"\x1b[34m{line}\x1b[39m" for line in _summary("ℹ", passed=0, skipped=1).splitlines())
    assert _verdict(output)["leaves"][0]["checked"] is False
    assert _carries_summary_shape(output) is True


@pytest.fixture
def executor_module(monkeypatch):
    path = Path(__file__).parents[1] / "packages/harness/deerflow/subagents/executor.py"
    spec = importlib.util.spec_from_file_location("_node_evidence_executor", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


class SandboxMessages(MessagesState):
    sandbox: dict


@pytest.mark.parametrize("label", ["all tests passed", "1 failed", "0 passed"])
def test_harvest_drops_a_partial_label_before_interpreting_counts(executor_module, monkeypatch, label):
    output = "ok 1 - " + "x" * 1500 + " " + label + " # SKIP\n" + _summary(passed=0, skipped=1)
    messages = [AIMessage(content="", tool_calls=[{"name": "bash", "id": "long-name", "args": {"command": "node --test"}}]), ToolMessage(content=output, tool_call_id="long-name")]
    monkeypatch.setattr(executor_module, "_harvest_shell_persistence", lambda state: False)
    executions = executor_module._harvest_bash_executions({"messages": messages})
    assert executions[0]["output_tail"] == _summary(passed=0, skipped=1)
    assert messages[-1].content == output
    verdict = check_acceptance_criteria(["tests_passed:node --test"], bash_executions=executions)
    assert (verdict["leaves"][0]["checked"], verdict["all_hold"]) == (False, False)


@pytest.mark.skipif(os.name == "nt" or shutil.which("node") is None, reason="Requires POSIX LocalSandbox and Node.js")
@pytest.mark.asyncio
@pytest.mark.parametrize("reporter", ["tap", "spec", "color-spec"])
@pytest.mark.parametrize(
    "body,expected",
    [
        ("test('sample', () => {});", (True, True)),
        ("test('0 passed', () => {}); test('1 failed', () => {});", (True, True)),
        ("test('sample', () => {}); test.skip('optional', () => {});", (True, True)),
        ("test.skip('all tests passed', () => {});", (False, False)),
        ("test.skip('x'.repeat(1500) + ' all tests passed', () => {});", (False, False)),
        ("test('x'.repeat(1500) + ' 1 failed', () => {});", (True, True)),
        ("test('x'.repeat(1500) + ' 0 passed', () => {});", (True, True)),
        ("test.todo('pending');", (False, False)),
        ("test('all tests passed', { todo: true }, () => { throw Error('fixture'); });", (False, False)),
        ("test('sample', () => {}); test('1 failed', { todo: true }, () => { throw Error('fixture'); });", (True, True)),
        ("describe('empty suite', () => {});", (False, False)),
        ("describe('all tests passed', () => { test.skip('optional', () => {}); });", (False, False)),
        ("describe('all tests passed', () => { test.todo('pending'); });", (False, False)),
        ("describe('1 failed', () => { test('sample', () => {}); });", (True, True)),
        ("test('sample', () => { throw Error('fixture'); });", (True, False)),
        ("test('pending', { timeout: 20 }, () => new Promise(() => {}));", (True, False)),
    ],
    ids=[
        "pass",
        "summary-like-names",
        "pass-and-skip",
        "all-skipped",
        "long-skipped",
        "long-failure-name",
        "long-zero-name",
        "all-todo",
        "failing-todo-pass-name",
        "failing-todo-failure-name",
        "empty-suite",
        "skipped-suite",
        "todo-suite",
        "summary-like-suite",
        "failure",
        "cancelled",
    ],
)
async def test_real_node_results_reach_parent_acceptance(tmp_path, monkeypatch, executor_module, reporter, body, expected):
    (tmp_path / "sample.test.cjs").write_text("const { test, describe } = require('node:test');\n" + body, encoding="utf-8")
    sandbox = LocalSandbox("node-evidence", path_mappings=[PathMapping("/mnt/user-data/workspace", str(tmp_path))])
    monkeypatch.setattr("deerflow.sandbox.sandbox_provider.get_sandbox_provider", lambda: SimpleNamespace(get=lambda sandbox_id: sandbox if sandbox_id == sandbox.id else None))
    outputs = []

    async def bash(command: str) -> str:
        output = await asyncio.to_thread(sandbox.execute_command, command, timeout=30)
        outputs.append(output)
        return output

    tool = StructuredTool.from_function(coroutine=bash, name="bash", description="Run offline native Node tests.")
    graph = StateGraph(SandboxMessages)
    graph.add_node("tools", ToolNode([tool], awrap_tool_call=ToolErrorHandlingMiddleware().awrap_tool_call))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    color = "FORCE_COLOR=1 " if reporter == "color-spec" else ""
    reporter = reporter.removeprefix("color-")
    command = f"{color}{shlex.quote(shutil.which('node'))} --test --test-reporter={reporter} /mnt/user-data/workspace/sample.test.cjs"
    state = await graph.compile().ainvoke({"sandbox": {"sandbox_id": sandbox.id}, "messages": [AIMessage(content="", tool_calls=[{"name": "bash", "id": "node-call", "args": {"command": command}}])]})
    assert len(outputs) == 1 and "duration_ms" in outputs[0], outputs
    executions = executor_module._harvest_bash_executions(state)
    assert len(executions) == 1 and executions[0]["shell_persistent"] is False
    verdict = check_acceptance_criteria([f"tests_passed:{command}"], bash_executions=executions)
    assert (verdict["leaves"][0]["checked"], verdict["all_hold"]) == expected, (outputs, verdict)
