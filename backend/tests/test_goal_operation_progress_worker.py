"""Goal operation observations at the real durable worker decision boundary.

Only completion verdicts are scripted. Checkpoint writes, continuation admission,
progress counting, and all existing worker guards execute production code.
"""

from __future__ import annotations

import os
import socket
from types import SimpleNamespace

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.prebuilt import ToolNode

from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware
from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
from deerflow.agents.middlewares.tool_receipt_middleware import ToolReceiptMiddleware
from deerflow.agents.thread_state import ThreadState
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor, build_state_mutation_graph
from deerflow.runtime.goal import (
    GoalEvaluation,
    attach_goal_evaluation,
    build_goal_state,
    latest_visible_assistant_signature,
    read_thread_goal,
    write_thread_goal,
)
from deerflow.runtime.runs import worker
from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping
from deerflow.sandbox.tools import bash_tool, read_file_tool, write_file_tool


class _Bridge:
    async def publish(self, *_args):
        pass


def _config(thread_id):
    return {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}


def _accessor(saver, mode):
    graph = build_state_mutation_graph("goal_evaluator", mode, snapshot_frequency=1000)
    return CheckpointStateAccessor.bind(graph, saver, mode=mode)


def _operations(indices, *, prefix="call", text="Work remains", status="success"):
    messages = []
    for index in indices:
        call = {"name": "read_file", "id": f"{prefix}-{index}", "args": {"path": f"/part-{index}.txt"}}
        messages.extend(
            [
                AIMessage(content="", tool_calls=[call], id=f"ai-{prefix}-{index}"),
                ToolMessage(
                    content=f"Observed part {index}",
                    tool_call_id=call["id"],
                    name=call["name"],
                    status=status,
                    id=f"tool-{prefix}-{index}",
                ),
            ]
        )
    messages.append(AIMessage(content=text, id=f"final-{prefix}"))
    return messages


@pytest.fixture(autouse=True)
def _no_models_or_network(monkeypatch):
    def denied(*_args, **_kwargs):
        raise AssertionError("Goal worker regression attempted a provider/network call")

    from deerflow import models
    from deerflow.runtime import goal

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(models, "create_chat_model", denied)
    monkeypatch.setattr(goal, "create_chat_model", denied)

    async def unresolved(_goal, _messages, **_kwargs):
        return GoalEvaluation(satisfied=False, blocker="goal_not_met_yet", reason="Fixed unresolved control", evidence_summary="")

    monkeypatch.setattr(worker, "evaluate_goal_completion", unresolved)


async def _seed(saver, mode, thread_id, messages):
    accessor = _accessor(saver, mode)
    await accessor.aupdate(_config(thread_id), {"messages": [HumanMessage(content="Finish all parts", id="user"), *messages]}, as_node="goal_evaluator")
    await write_thread_goal(saver, thread_id, build_goal_state("Finish all parts"))
    return accessor


async def _decide(saver, accessor, thread_id, **kwargs):
    result = await worker._prepare_goal_continuation_input(
        bridge=_Bridge(),
        accessor=accessor,
        checkpointer=saver,
        thread_id=thread_id,
        run_id="local-control",
        model_name=None,
        app_config=None,
        **kwargs,
    )
    return result, await read_thread_goal(saver, thread_id)


async def _append_turn(accessor, thread_id, messages, *, turn):
    await accessor.aupdate(_config(thread_id), {"messages": [HumanMessage(content="Continue", id=f"hidden-{turn}", additional_kwargs={"hide_from_ui": True, "deerflow_goal_continuation": True}), *messages]}, as_node="goal_evaluator")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "delta"])
async def test_worker_keeps_exact_seen_operations_above_64_without_fallback(mode):
    count = 65
    saver = InMemorySaver()
    thread_id = f"over-64-{mode}-{count}"
    accessor = await _seed(saver, mode, thread_id, _operations(range(count)))
    first, goal = await _decide(saver, accessor, thread_id)
    assert first is not None and goal["no_progress_count"] == 0
    keys = goal["last_evaluation"]["operation_progress"]["seen_keys"]
    assert len(keys) == count
    assert len(set(keys)) == count
    # Rotating and shrinking previously observed sets must not buy continuations.
    await _append_turn(accessor, thread_id, _operations(reversed(range(count)), prefix="rotated", text="Another wording"), turn=2)
    second, goal = await _decide(saver, accessor, thread_id)
    assert second is not None and goal["no_progress_count"] == 1
    assert goal["last_evaluation"]["operation_progress"]["seen_keys"] == keys
    await _append_turn(accessor, thread_id, _operations(range(1), prefix="subset", text="Yet another wording"), turn=3)
    third, goal = await _decide(saver, accessor, thread_id)
    assert third is None and goal["no_progress_count"] == 2
    assert goal["last_evaluation"]["stand_down_reason"] == "no_progress_detected"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "delta"])
async def test_worker_novel_operation_beyond_64_resets_count(mode):
    saver = InMemorySaver()
    accessor = await _seed(saver, mode, "novel", _operations(range(65)))
    await _decide(saver, accessor, "novel")
    await _append_turn(accessor, "novel", _operations([0], prefix="repeat"), turn=2)
    _, goal = await _decide(saver, accessor, "novel")
    assert goal["no_progress_count"] == 1
    await _append_turn(accessor, "novel", _operations([65], prefix="new"), turn=3)
    continuation, goal = await _decide(saver, accessor, "novel")
    assert continuation is not None and goal["no_progress_count"] == 0
    assert len(goal["last_evaluation"]["operation_progress"]["seen_keys"]) == 66


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "delta"])
async def test_worker_text_only_turns_preserve_original_counter(mode):
    saver = InMemorySaver()
    accessor = await _seed(saver, mode, "text", [AIMessage(content="First explanation", id="text-1")])
    outcomes = [await _decide(saver, accessor, "text")]
    await _append_turn(accessor, "text", [AIMessage(content="Different explanation", id="text-2")], turn=2)
    outcomes.extend([await _decide(saver, accessor, "text") for _ in range(3)])
    assert [r is not None for r, _ in outcomes] == [True, True, True, False]
    assert [g["no_progress_count"] for _, g in outcomes] == [0, 0, 1, 2]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "delta"])
async def test_worker_sqlite_reopen_preserves_exact_history(tmp_path, mode):
    db = tmp_path / "goal.sqlite"
    for phase in range(3):
        async with AsyncSqliteSaver.from_conn_string(str(db)) as saver:
            await saver.setup()
            if phase == 0:
                accessor = await _seed(saver, mode, "restart", _operations(range(65)))
            else:
                accessor = _accessor(saver, mode)
            result, goal = await _decide(saver, accessor, "restart")
            assert (result is not None) == (phase < 2)
            assert goal["no_progress_count"] == phase
            assert len(goal["last_evaluation"]["operation_progress"]["seen_keys"]) == 65


def _summary_middleware(*, keep):
    return DeerFlowSummarizationMiddleware(
        model=FakeListChatModel(responses=["Earlier operations summarized. Work remains."]),
        trigger=("messages", 4),
        keep=("messages", keep),
        trim_tokens_to_summarize=2000,
        token_counter=lambda messages: sum(len(message.content) for message in messages),
        summary_prompt="{messages}",
        anchor_model_name="primary",
        run_model_name="primary",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "delta"])
async def test_worker_real_compaction_and_old_replay_do_not_reset_count(mode):
    saver = InMemorySaver()
    accessor = await _seed(saver, mode, "compact", _operations(range(65)))
    await _decide(saver, accessor, "compact")
    snapshot = await accessor.aget(_config("compact"))
    middleware = _summary_middleware(keep=1)
    compact = await middleware.acompact_state(dict(snapshot.values), SimpleNamespace(context={}), force=True, raise_on_failure=True)
    assert compact is not None and middleware.summary_call_count > 0
    await accessor.aupdate(_config("compact"), {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *compact.preserved_messages], "summary_text": compact.summary_text}, as_node="goal_evaluator")
    second, goal = await _decide(saver, accessor, "compact")
    assert second is not None and goal["no_progress_count"] == 1
    await _append_turn(accessor, "compact", _operations([0], prefix="replayed", text="Rephrased old work"), turn=3)
    third, goal = await _decide(saver, accessor, "compact")
    assert third is None and goal["no_progress_count"] == 2
    assert len(goal["last_evaluation"]["operation_progress"]["seen_keys"]) == 65


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "delta"])
async def test_worker_first_turn_compaction_counts_retained_successful_pairs(mode):
    saver = InMemorySaver()
    prefix = [AIMessage(content="Earlier context " * 50, id=f"prefix-{index}") for index in range(20)]
    accessor = await _seed(saver, mode, "first-compact", [*prefix, *_operations(range(65))])
    snapshot = await accessor.aget(_config("first-compact"))
    middleware = _summary_middleware(keep=131)
    compact = await middleware.acompact_state(dict(snapshot.values), SimpleNamespace(context={}), force=True, raise_on_failure=True)
    assert compact is not None and middleware.summary_call_count > 0
    assert sum(isinstance(message, ToolMessage) for message in compact.preserved_messages) == 65
    await accessor.aupdate(_config("first-compact"), {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *compact.preserved_messages], "summary_text": compact.summary_text}, as_node="goal_evaluator")
    continuation, goal = await _decide(saver, accessor, "first-compact")
    assert continuation is not None
    assert len(goal["last_evaluation"]["operation_progress"]["seen_keys"]) == 65


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "delta"])
@pytest.mark.parametrize("with_tool", [False, True])
async def test_worker_legacy_changed_reply_then_repeat_keeps_native_counter(mode, with_tool):
    saver = InMemorySaver()
    thread_id = f"legacy-changed-{mode}-{with_tool}"
    previous_messages = [AIMessage(content="Earlier reply", id="legacy-final")]
    accessor = await _seed(saver, mode, thread_id, previous_messages)
    goal = await read_thread_goal(saver, thread_id)
    evaluation = GoalEvaluation(satisfied=False, blocker="goal_not_met_yet", reason="Work remains", evidence_summary="")
    legacy = attach_goal_evaluation(goal, evaluation, run_id="old-version", no_progress_count=1, evidence_signature=latest_visible_assistant_signature(previous_messages))
    await write_thread_goal(saver, thread_id, legacy)
    for turn, expected_count in [(1, 0), (2, 1), (3, 2)]:
        messages = _operations([1], prefix=f"legacy-changed-{turn}", text="A genuinely changed reply") if with_tool else [AIMessage(content="A genuinely changed reply", id=f"changed-{turn}")]
        await _append_turn(accessor, thread_id, messages, turn=turn)
        continuation, current = await _decide(saver, accessor, thread_id)
        assert current["no_progress_count"] == expected_count
        assert (continuation is not None) is (expected_count < 2)


@pytest.mark.asyncio
async def test_replacing_or_clearing_goal_drops_its_operation_history():
    saver = InMemorySaver()
    accessor = await _seed(saver, "full", "replacement", _operations(range(65)))
    await _decide(saver, accessor, "replacement")
    await write_thread_goal(saver, "replacement", None)
    assert await read_thread_goal(saver, "replacement") is None
    await write_thread_goal(saver, "replacement", build_goal_state("A new goal"))
    await _append_turn(accessor, "replacement", _operations([0], prefix="replacement"), turn=2)
    continuation, goal = await _decide(saver, accessor, "replacement")
    assert continuation is not None and goal["no_progress_count"] == 0
    assert len(goal["last_evaluation"]["operation_progress"]["seen_keys"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "delta"])
async def test_worker_existing_goal_migration_does_not_reset_count(mode):
    saver = InMemorySaver()
    messages = _operations([0])
    accessor = await _seed(saver, mode, "migration", messages)
    goal = await read_thread_goal(saver, "migration")
    evaluation = GoalEvaluation(satisfied=False, blocker="goal_not_met_yet", reason="Work remains", evidence_summary="")
    legacy = attach_goal_evaluation(goal, evaluation, run_id="old-version", no_progress_count=1, evidence_signature=latest_visible_assistant_signature(messages))
    legacy["last_evaluation"].pop("operation_progress", None)
    await write_thread_goal(saver, "migration", legacy)
    result, goal = await _decide(saver, accessor, "migration")
    assert result is None and goal["no_progress_count"] == 2
    assert goal["last_evaluation"]["stand_down_reason"] == "no_progress_detected"


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_reason", ["loop_capped", "token_capped"])
async def test_new_successful_work_cannot_override_existing_hard_stop(stop_reason):
    saver = InMemorySaver()
    accessor = await _seed(saver, "full", "hard-stop", _operations(range(65)))
    result, goal = await _decide(saver, accessor, "hard-stop", run_stop_reason=stop_reason)
    assert result is None
    assert goal["continuation_count"] == 0
    assert goal["last_evaluation"]["stand_down_reason"] == stop_reason


def _native_tool_graph(tmp_path, monkeypatch, *, receipts):
    (tmp_path / "workspace").mkdir()
    (tmp_path / "workspace/input.txt").write_text("Stable input contents.\n", encoding="utf-8")
    sandbox = LocalSandbox("local", path_mappings=[PathMapping("/mnt/user-data/workspace", str(tmp_path / "workspace"))])
    monkeypatch.setattr("deerflow.sandbox.local.local_sandbox.build_sandbox_env", lambda _injected: {"PATH": os.defpath})
    # Bind only execution policy and the test-owned sandbox; tools, their real
    # results, normalization, receipt stamping and worker decisions stay native.
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)

    async def initialized(_runtime):
        return sandbox

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized_async", initialized)
    monkeypatch.setattr("deerflow.sandbox.tools.is_host_bash_allowed", lambda: True)
    errors = ToolErrorHandlingMiddleware()
    receipt = ToolReceiptMiddleware() if receipts else None

    async def wrap(request, handler):
        async def normalized(current):
            return await errors.awrap_tool_call(current, handler)

        return await receipt.awrap_tool_call(request, normalized) if receipt else await normalized(request)

    builder = StateGraph(ThreadState)
    builder.add_node("tools", ToolNode([bash_tool, read_file_tool, write_file_tool], awrap_tool_call=wrap, handle_tool_errors=False))
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    return builder.compile()


async def _native_tool_turn(graph, tmp_path, *, thread_id, turn, kind):
    args = (
        {"command": f"env -i /bin/sh -c 'exit 2' # attempt-{turn}", "description": "Controlled failing command"}
        if kind == "failed-bash"
        else {"path": "/mnt/user-data/workspace/input.txt", "description": f"Read attempt {turn}"}
        if kind == "same-read"
        else {"path": "/mnt/user-data/workspace/result.txt", "content": "The same file contents.\n", "description": f"Write attempt {turn}"}
    )
    tool_name = {"failed-bash": "bash", "same-read": "read_file", "same-write": "write_file"}[kind]
    state = await graph.ainvoke(
        {
            "sandbox": {"sandbox_id": "local"},
            "thread_data": {f"{name}_path": str(tmp_path / name) for name in ("workspace", "uploads", "outputs")},
            "messages": [AIMessage(content="", tool_calls=[{"id": f"native-{turn}", "name": tool_name, "args": args}])],
        },
        context={"thread_id": thread_id},
    )
    result = next(message for message in state["messages"] if isinstance(message, ToolMessage))
    return [*state["messages"], AIMessage(content="Work remains.", id=f"native-final-{turn}")], result


@pytest.mark.skipif(os.name == "nt", reason="Controlled native LocalSandbox commands use a POSIX shell")
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "delta"])
@pytest.mark.parametrize("receipts", [False, True], ids=["receipts-off", "receipts-on"])
@pytest.mark.parametrize("kind", ["failed-bash", "same-read"])
async def test_native_tool_results_cannot_buy_goal_continuations(tmp_path, monkeypatch, mode, receipts, kind):
    graph = _native_tool_graph(tmp_path, monkeypatch, receipts=receipts)
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "goal.sqlite")) as saver:
        await saver.setup()
        accessor = await _seed(saver, mode, "native-progress", [])
        counts, decisions, results = [], [], []
        for turn in range(3):
            messages, result = await _native_tool_turn(graph, tmp_path, thread_id="native-progress", turn=turn, kind=kind)
            assert ("deerflow_tool_receipt" in result.additional_kwargs) is receipts
            if kind == "failed-bash":
                assert str(result.content).endswith("Exit Code: 2")
            else:
                assert "Stable input contents." in str(result.content)
            await _append_turn(accessor, "native-progress", messages, turn=turn)
            continuation, goal = await _decide(saver, accessor, "native-progress")
            counts.append(goal["no_progress_count"])
            decisions.append(continuation is not None)
            results.append(result)
        assert counts == [0, 1, 2]
        assert decisions == [True, True, False]
        assert goal["last_evaluation"]["stand_down_reason"] == "no_progress_detected"
        assert len(goal["last_evaluation"]["operation_progress"]["seen_keys"]) == (0 if kind == "failed-bash" else 1)
        assert all(result.additional_kwargs["deerflow_tool_meta"]["status"] == ("error" if kind == "failed-bash" else "success") for result in results)
        assert (tmp_path / "workspace/input.txt").read_text(encoding="utf-8") == "Stable input contents.\n"


@pytest.mark.skipif(os.name == "nt", reason="Controlled native LocalSandbox commands use a POSIX shell")
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "delta"])
@pytest.mark.parametrize("receipts", [False, True], ids=["receipts-off", "receipts-on"])
async def test_native_success_after_failed_tools_resets_goal_stall(tmp_path, monkeypatch, mode, receipts):
    graph = _native_tool_graph(tmp_path, monkeypatch, receipts=receipts)
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "goal.sqlite")) as saver:
        await saver.setup()
        accessor = await _seed(saver, mode, "native-recovery", [])
        counts = []
        for turn, kind in enumerate(["failed-bash", "failed-bash", "same-write"]):
            messages, result = await _native_tool_turn(graph, tmp_path, thread_id="native-recovery", turn=turn, kind=kind)
            assert result.additional_kwargs["deerflow_tool_meta"]["status"] == ("error" if kind == "failed-bash" else "success")
            await _append_turn(accessor, "native-recovery", messages, turn=turn)
            continuation, goal = await _decide(saver, accessor, "native-recovery")
            assert continuation is not None
            counts.append(goal["no_progress_count"])
        assert counts == [0, 1, 0]
        assert len(goal["last_evaluation"]["operation_progress"]["seen_keys"]) == 1
        assert (tmp_path / "workspace/result.txt").read_text(encoding="utf-8") == "The same file contents.\n"
