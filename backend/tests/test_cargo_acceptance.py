"""Cargo's empty test targets must not invalidate completed sibling tests."""

import asyncio
import importlib.util
import os
import shutil
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


def _summary(passed=0, failed=0, ignored=0):
    return f"test result: {'FAILED' if failed else 'ok'}. {passed} passed; {failed} failed; {ignored} ignored; 0 measured; 0 filtered out; finished in 0.00s"


def _verdict(output, **overrides):
    execution = {"command": "cargo test", "output_tail": output, "status": "success", "shell_persistent": False, **overrides}
    return check_acceptance_criteria(["tests_passed:cargo test"], bash_executions=[execution])


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("ignored", [0, 2])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_successful_tests_survive_complete_empty_target_summaries(reverse, ignored, newline):
    records = [_summary(passed=2), _summary(ignored=ignored)]
    if reverse:
        records.reverse()
    verdict = _verdict(newline.join(records))
    assert verdict["all_hold"] is True
    assert verdict["unchecked"] == []
    assert "[holds]" in render_acceptance_section(verdict)
    assert "execution evidence only" in render_acceptance_section(verdict)
    assert "acceptance:" in render_acceptance_segment(verdict)


@pytest.mark.parametrize("output", [_summary(), _summary(ignored=3), _summary() + "\n" + _summary(ignored=1)])
def test_only_empty_or_ignored_targets_remain_unverified(output):
    verdict = _verdict(output)
    assert (verdict["leaves"][0]["checked"], verdict["all_hold"]) == (False, False)
    assert "[UNVERIFIED]" in render_acceptance_section(verdict)


@pytest.mark.parametrize("output", ["test result: ok", "test result: ok. 0", _summary() + "\ntest result: ok"])
def test_bare_cargo_success_banner_cannot_supply_test_count_evidence(output):
    verdict = _verdict(output)
    assert (verdict["leaves"][0]["checked"], verdict["all_hold"]) == (False, False)


@pytest.mark.parametrize("banner", ["OK", "all tests passed", "test result: ok. 2 passed; 0 failed"])
def test_zero_target_records_need_a_complete_positive_cargo_sibling(banner):
    verdict = _verdict(_summary() + "\n" + banner)
    assert (verdict["leaves"][0]["checked"], verdict["all_hold"]) == (False, False)


def test_positive_counts_do_not_bypass_output_attribution():
    verdict = _verdict(_summary(passed=2) + "\n" + _summary(), command="echo 'unrelated'; cargo test")
    assert verdict["leaves"][0]["checked"] is False


@pytest.mark.parametrize(
    "zero",
    [
        _summary().split("; 0 filtered out")[0],
        "warning: " + _summary(),
        _summary().replace("finished in 0.00s", "finished in"),
        _summary().replace("0 ignored", "9" * 100 + " ignored"),
        "0 passed in 0.1s",
        "Ran 0 tests\nOK",
    ],
)
def test_incomplete_or_other_runner_zero_evidence_is_not_silenced(zero):
    verdict = _verdict(_summary(passed=2) + "\n" + zero)
    assert (verdict["leaves"][0]["checked"], verdict["all_hold"]) == (False, False)


@pytest.mark.parametrize("failure", [_summary(failed=1), _summary(failed=1).replace("FAILED", "ok"), "error: doctest failed"])
@pytest.mark.parametrize("reverse", [False, True])
def test_failure_in_a_sibling_target_still_wins(failure, reverse):
    # Cargo normally exits nonzero; the terminal FAILED/count summary must
    # also prevent a positive verdict if a surrounding runner swallows it.
    records = [_summary(passed=2), _summary(), failure]
    output = "\n".join(reversed(records) if reverse else records)
    if failure.startswith("error:"):
        verdict = _verdict(output, status="error")
    else:
        verdict = _verdict(output)
    assert (verdict["leaves"][0]["checked"], verdict["all_hold"]) == (True, False)
    assert "[does not hold]" in render_acceptance_section(verdict)


@pytest.mark.parametrize("overrides", [{"shell_persistent": True}, {"shell_persistent": None}, {"command_truncated": True}])
def test_empty_target_handling_does_not_bypass_execution_provenance(overrides):
    verdict = _verdict(_summary(passed=2) + "\n" + _summary(), **overrides)
    assert verdict["leaves"][0]["checked"] is False


@pytest.fixture
def executor_module(monkeypatch):
    # conftest preloads an executor stub; harvest from the production module.
    path = Path(__file__).parents[1] / "packages/harness/deerflow/subagents/executor.py"
    spec = importlib.util.spec_from_file_location("_cargo_evidence_executor", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


class SandboxMessages(MessagesState):
    sandbox: dict


@pytest.mark.skipif(os.name == "nt" or shutil.which("cargo") is None, reason="POSIX Cargo integration requires an installed Rust toolchain")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source,selection,expected",
    [
        ("#[test] fn unit() { assert_eq!(2 + 2, 4); }", "", (True, True)),
        ("/// ```\n/// assert_eq!(2 + 2, 4);\n/// ```\npub fn documented() {}", "", (True, True)),
        ("#[test] #[ignore] fn ignored() {}", "", (False, False)),
        ('#[test] fn broken() { panic!("broken"); }', "", (True, False)),
        ("/// ```\n/// assert_eq!(1, 2);\n/// ```\npub fn documented() {}\n#[test] fn unit() {}", "", (True, False)),
        ("#[test] fn unit() {}", " no_test_matches", (False, False)),
    ],
    ids=["unit-with-empty-doc", "doc-with-empty-unit", "ignored", "failed-unit", "failed-doc", "filtered"],
)
async def test_native_cargo_output_reaches_parent_acceptance_through_tool_node(tmp_path, monkeypatch, executor_module, source, selection, expected):
    (tmp_path / "src").mkdir()
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "acceptance_fixture"\nversion = "0.1.0"\nedition = "2021"\n', encoding="utf-8")
    (tmp_path / "src/lib.rs").write_text(source, encoding="utf-8")
    sandbox = LocalSandbox("cargo-evidence", path_mappings=[PathMapping("/mnt/user-data/workspace", str(tmp_path))], environment={"CARGO_TERM_COLOR": "never"})
    monkeypatch.setattr("deerflow.sandbox.sandbox_provider.get_sandbox_provider", lambda: SimpleNamespace(get=lambda sandbox_id: sandbox if sandbox_id == sandbox.id else None))
    outputs = []

    async def bash(command: str) -> str:
        output = await asyncio.to_thread(sandbox.execute_command, command, timeout=60)
        outputs.append(output)
        return output

    tool = StructuredTool.from_function(coroutine=bash, name="bash", description="Execute the offline Rust fixture.")
    graph = StateGraph(SandboxMessages)
    graph.add_node("tools", ToolNode([tool], awrap_tool_call=ToolErrorHandlingMiddleware().awrap_tool_call))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    command = "cargo test --offline --manifest-path /mnt/user-data/workspace/Cargo.toml" + selection
    state = await graph.compile().ainvoke(
        {
            "sandbox": {"sandbox_id": sandbox.id},
            "messages": [AIMessage(content="", tool_calls=[{"name": "bash", "id": "cargo-call", "type": "tool_call", "args": {"command": command}}])],
        }
    )
    assert len(outputs) == 1
    assert "test result:" in outputs[0], outputs[0]
    message = state["messages"][-1]
    assert (message.name, message.tool_call_id) == ("bash", "cargo-call")
    executions = executor_module._harvest_bash_executions(state)
    assert len(executions) == 1
    assert executions[0]["shell_persistent"] is False
    assert executions[0]["tool_call_id"] == "cargo-call"
    verdict = check_acceptance_criteria([f"tests_passed:{command}"], bash_executions=executions)
    assert (verdict["leaves"][0]["checked"], verdict["all_hold"]) == expected, verdict
    if expected == (True, True):
        assert "1 passed" in outputs[0] and "0 passed" in outputs[0]
        assert "[holds]" in render_acceptance_section(verdict)
    elif expected == (True, False):
        assert "Exit Code: 101" in outputs[0]
        assert executions[0]["status"] == "error"
    else:
        assert "[UNVERIFIED]" in render_acceptance_section(verdict)
