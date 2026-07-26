"""Delta-mode checkpoint resume linearization (#4458).

Resuming a run from an older checkpoint forks the lineage. In ``delta`` mode
that fork cannot be materialized correctly — the delta history walk replays
every ``pending_writes`` entry stored on each on-path ancestor, including the
writes of the sibling child that was abandoned — so the run starts from a
message list that still contains the answer it was meant to replace. These
tests pin the worker's linearization: the requested state is written onto the
current head (which has no siblings) and the run proceeds linearly.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Annotated, Any, TypedDict
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.channels.delta import DeltaChannel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Overwrite

from deerflow.agents.thread_state import merge_message_writes
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor, build_state_mutation_graph
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.worker import RunContext, _checkpoint_thread_lock, _linearize_delta_checkpoint_resume, run_agent

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _DeltaChannelState(TypedDict):
    messages: Annotated[list[AnyMessage], DeltaChannel(merge_message_writes, snapshot_frequency=1000)]


class _FullChannelState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def _replace_optional_state(existing: dict[str, str] | None, new: dict[str, str] | None) -> dict[str, str] | None:
    return existing if new is None else new


class _ExtendedDeltaChannelState(_DeltaChannelState):
    notes: Annotated[list[AnyMessage], add_messages]
    marker: str | None
    head_only: Annotated[dict[str, str] | None, _replace_optional_state]
    head_last_only: str | None


def _build_answer_graph(state_schema: type, checkpointer: Any, answer_id: str):
    async def _answer(state: dict[str, Any]) -> dict[str, Any]:
        return {"messages": [AIMessage(content=f"answer for {answer_id}", id=answer_id)]}

    builder = StateGraph(state_schema)
    builder.add_node("answer", _answer)
    builder.set_entry_point("answer")
    builder.set_finish_point("answer")
    return builder.compile(checkpointer=checkpointer)


def _ids(snapshot: Any) -> list[str]:
    return [message.id for message in (snapshot.values or {}).get("messages", [])]


def _run_config(thread_id: str, checkpoint_id: str | None = None) -> dict[str, Any]:
    configurable: dict[str, Any] = {"thread_id": thread_id, "checkpoint_ns": ""}
    if checkpoint_id is not None:
        configurable["checkpoint_id"] = checkpoint_id
    return {"configurable": configurable}


async def _seed_two_turns(checkpointer: Any, state_schema: type, thread_id: str):
    """h1 -> a1, h2 -> a2, returning (accessor, head, pre-h2 snapshot)."""
    config = _run_config(thread_id)
    await _build_answer_graph(state_schema, checkpointer, "a1").ainvoke({"messages": [HumanMessage(content="q1", id="h1")]}, config)
    graph = _build_answer_graph(state_schema, checkpointer, "a2")
    await graph.ainvoke({"messages": [HumanMessage(content="q2", id="h2")]}, config)

    mode = "delta" if state_schema is _DeltaChannelState else "full"
    accessor = CheckpointStateAccessor.bind(graph, checkpointer, mode=mode)
    head = await accessor.aget(config)
    history = await accessor.ahistory(config, limit=20)
    pre_turn = next(snapshot for snapshot in history if "h2" not in _ids(snapshot))
    return accessor, head, pre_turn


async def test_linearizes_a_delta_resume_onto_the_head():
    checkpointer = InMemorySaver()
    accessor, head, pre_turn = await _seed_two_turns(checkpointer, _DeltaChannelState, "thread-1")
    base_id = pre_turn.config["configurable"]["checkpoint_id"]
    config = _run_config("thread-1", base_id)

    resumed = await _linearize_delta_checkpoint_resume(
        accessor=accessor,
        checkpointer=checkpointer,
        config=config,
        thread_id="thread-1",
        run_id="run-1",
    )

    assert [message.id for message in resumed] == ["h1", "a1"]
    # The selector is consumed: the run continues on the (rewritten) head.
    assert "checkpoint_id" not in config["configurable"]
    new_head = await accessor.aget(_run_config("thread-1"))
    assert _ids(new_head) == ["h1", "a1"]
    assert new_head.config["configurable"]["checkpoint_id"] != head.config["configurable"]["checkpoint_id"]


async def test_linearization_restores_all_selected_state_and_clears_newer_channels():
    checkpointer = InMemorySaver()
    config = _run_config("thread-state")

    first_graph = _build_answer_graph(_ExtendedDeltaChannelState, checkpointer, "a1")
    await first_graph.ainvoke(
        {
            "messages": [HumanMessage(content="q1", id="h1")],
            "notes": [HumanMessage(content="selected", id="note-selected")],
            "marker": "selected",
        },
        config,
    )
    accessor = CheckpointStateAccessor.bind(first_graph, checkpointer, mode="delta")
    selected = await accessor.aget(config)

    second_graph = _build_answer_graph(_ExtendedDeltaChannelState, checkpointer, "a2")
    await second_graph.ainvoke(
        {
            "messages": [HumanMessage(content="q2", id="h2")],
            "notes": [HumanMessage(content="newer", id="note-newer")],
            "marker": "newer",
            "head_only": {"value": "must-not-leak"},
            "head_last_only": "must-not-leak",
        },
        config,
    )
    accessor = CheckpointStateAccessor.bind(second_graph, checkpointer, mode="delta")
    selected_id = selected.config["configurable"]["checkpoint_id"]

    await _linearize_delta_checkpoint_resume(
        accessor=accessor,
        checkpointer=checkpointer,
        config=_run_config("thread-state", selected_id),
        thread_id="thread-state",
        run_id="run-state",
    )

    rewritten = await accessor.aget(config)
    assert _ids(rewritten) == ["h1", "a1"]
    assert [message.id for message in rewritten.values["notes"]] == ["note-selected"]
    assert rewritten.values["marker"] == "selected"
    assert rewritten.values.get("head_only") is None
    assert rewritten.values.get("head_last_only") is None


async def test_regenerating_in_a_branched_thread_does_not_resurrect_the_old_answer(tmp_path):
    """The #4458 shape end-to-end on a persistent saver.

    A branch writes two synthetic checkpoints (replay base + visible head);
    regenerating the inherited answer resumes from the replay base. Without
    linearization the delta walk replays the branch head's own ``Overwrite``
    — which is stored on that shared parent — and the superseded assistant
    message comes back alongside the new one.
    """
    db_path = tmp_path / "branch.sqlite3"
    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as checkpointer:
        await checkpointer.setup()
        _, source_head, source_pre_turn = await _seed_two_turns(checkpointer, _DeltaChannelState, "parent")

        mutation_graph = build_state_mutation_graph("branch", "delta", _DeltaChannelState)
        branch_writer = CheckpointStateAccessor.bind(mutation_graph, checkpointer, mode="delta")
        replay_base_config = await branch_writer.aupdate(
            _run_config("branch"),
            {"messages": Overwrite(list(source_pre_turn.values["messages"]))},
            as_node="branch",
        )
        await branch_writer.aupdate(
            replay_base_config,
            {"messages": Overwrite(list(source_head.values["messages"]))},
            as_node="branch",
        )

        graph = _build_answer_graph(_DeltaChannelState, checkpointer, "a2-new")
        accessor = CheckpointStateAccessor.bind(graph, checkpointer, mode="delta")
        branch_history = await accessor.ahistory(_run_config("branch"), limit=20)
        base = next(snapshot for snapshot in branch_history if "h2" not in _ids(snapshot))
        config = _run_config("branch", base.config["configurable"]["checkpoint_id"])

        await _linearize_delta_checkpoint_resume(
            accessor=accessor,
            checkpointer=checkpointer,
            config=config,
            thread_id="branch",
            run_id="run-regen",
        )
        # The regenerate run replays the same human message and answers again.
        await graph.ainvoke({"messages": [HumanMessage(content="q2", id="h2")]}, config)

        final = await accessor.aget(_run_config("branch"))
        assert _ids(final) == ["h1", "a1", "h2", "a2-new"]


async def test_run_agent_streams_from_the_linearized_delta_resume(tmp_path):
    """Pin selector removal through ``run_agent`` and its stream config.

    Helper-level tests would still pass if the worker later streamed from the
    stale ``RunnableConfig`` built before linearization. This exercises the
    production boundary that hands the rewritten config to ``agent.astream``.
    """
    db_path = tmp_path / "worker-branch.sqlite3"
    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as checkpointer:
        await checkpointer.setup()
        _, source_head, source_pre_turn = await _seed_two_turns(checkpointer, _DeltaChannelState, "worker-parent")

        mutation_graph = build_state_mutation_graph("branch", "delta", _DeltaChannelState)
        branch_writer = CheckpointStateAccessor.bind(mutation_graph, checkpointer, mode="delta")
        replay_base_config = await branch_writer.aupdate(
            _run_config("worker-branch"),
            {"messages": Overwrite(list(source_pre_turn.values["messages"]))},
            as_node="branch",
        )
        await branch_writer.aupdate(
            replay_base_config,
            {"messages": Overwrite(list(source_head.values["messages"]))},
            as_node="branch",
        )

        read_graph = _build_answer_graph(_DeltaChannelState, checkpointer, "unused")
        read_accessor = CheckpointStateAccessor.bind(read_graph, checkpointer, mode="delta")
        branch_history = await read_accessor.ahistory(_run_config("worker-branch"), limit=20)
        base = next(snapshot for snapshot in branch_history if "h2" not in _ids(snapshot))

        run_manager = RunManager()
        record = await run_manager.create("worker-branch")
        bridge = SimpleNamespace(
            publish=AsyncMock(),
            publish_end=AsyncMock(),
            cleanup=AsyncMock(),
        )
        created_graphs: list[Any] = []

        def agent_factory(*, config):
            del config
            graph = _build_answer_graph(_DeltaChannelState, checkpointer, "a2-new")
            created_graphs.append(graph)
            return graph

        await asyncio.wait_for(
            run_agent(
                bridge,
                run_manager,
                record,
                ctx=RunContext(checkpointer=checkpointer, checkpoint_channel_mode="delta"),
                agent_factory=agent_factory,
                graph_input={"messages": [HumanMessage(content="q2", id="h2")]},
                config=_run_config("worker-branch", base.config["configurable"]["checkpoint_id"]),
                stream_modes=["values"],
            ),
            timeout=5,
        )

        assert record.status == RunStatus.success
        final_accessor = CheckpointStateAccessor.bind(created_graphs[-1], checkpointer, mode="delta")
        final = await final_accessor.aget(_run_config("worker-branch"))
        assert _ids(final) == ["h1", "a1", "h2", "a2-new"]


async def test_run_agent_serializes_resume_preparation_with_checkpoint_writes(monkeypatch):
    """Rollback capture and resume linearization share the checkpoint lock.

    A prior successful run can still be persisting duration metadata after its
    active run slot is released. Resume preparation must wait for that writer
    so its head snapshot and linear rewrite cannot interleave with the
    metadata checkpoint's compare-and-write sequence.
    """
    checkpointer = InMemorySaver()
    graph = _build_answer_graph(_DeltaChannelState, checkpointer, "a1")
    run_manager = RunManager()
    record = await run_manager.create("worker-lock")
    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )
    factory_called = asyncio.Event()
    startup_calls: list[str] = []

    def agent_factory(*, config):
        del config
        factory_called.set()
        return graph

    async def capture_rollback_point(*args, **kwargs):
        del args, kwargs
        startup_calls.append("capture")
        return None

    async def linearize_resume(**kwargs):
        del kwargs
        startup_calls.append("linearize")
        return None

    monkeypatch.setattr("deerflow.runtime.runs.worker._capture_rollback_point", capture_rollback_point)
    monkeypatch.setattr("deerflow.runtime.runs.worker._linearize_delta_checkpoint_resume", linearize_resume)

    async with _checkpoint_thread_lock("worker-lock"):
        run_task = asyncio.create_task(
            run_agent(
                bridge,
                run_manager,
                record,
                ctx=RunContext(checkpointer=checkpointer, checkpoint_channel_mode="delta"),
                agent_factory=agent_factory,
                graph_input={"messages": [HumanMessage(content="q1", id="h1")]},
                config=_run_config("worker-lock"),
                stream_modes=["values"],
            )
        )
        await asyncio.wait_for(factory_called.wait(), timeout=1)
        await asyncio.sleep(0)
        assert startup_calls == []

    await run_task
    assert startup_calls == ["capture", "linearize"]


async def test_cancelled_delta_resume_rolls_back_to_pre_linearization_head(tmp_path):
    """Rollback must restore the head captured before resume linearization.

    The worker deliberately captures its rollback point before rewriting a
    selected delta checkpoint onto the head. If that ordering is reversed,
    cancelling the resumed run would restore the selected historical state
    and silently discard the abandoned turn that was present before the run.
    """
    db_path = tmp_path / "worker-rollback-branch.sqlite3"
    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as checkpointer:
        await checkpointer.setup()
        _, source_head, source_pre_turn = await _seed_two_turns(checkpointer, _DeltaChannelState, "worker-rollback-parent")

        mutation_graph = build_state_mutation_graph("branch", "delta", _DeltaChannelState)
        branch_writer = CheckpointStateAccessor.bind(mutation_graph, checkpointer, mode="delta")
        replay_base_config = await branch_writer.aupdate(
            _run_config("worker-rollback-branch"),
            {"messages": Overwrite(list(source_pre_turn.values["messages"]))},
            as_node="branch",
        )
        await branch_writer.aupdate(
            replay_base_config,
            {"messages": Overwrite(list(source_head.values["messages"]))},
            as_node="branch",
        )

        read_graph = _build_answer_graph(_DeltaChannelState, checkpointer, "unused")
        read_accessor = CheckpointStateAccessor.bind(read_graph, checkpointer, mode="delta")
        pre_run_head = await read_accessor.aget(_run_config("worker-rollback-branch"))
        assert _ids(pre_run_head) == ["h1", "a1", "h2", "a2"]
        branch_history = await read_accessor.ahistory(_run_config("worker-rollback-branch"), limit=20)
        base = next(snapshot for snapshot in branch_history if "h2" not in _ids(snapshot))

        run_manager = RunManager()
        record = await run_manager.create("worker-rollback-branch")
        bridge = SimpleNamespace(
            publish=AsyncMock(),
            publish_end=AsyncMock(),
            cleanup=AsyncMock(),
        )
        created_graphs: list[Any] = []

        def agent_factory(*, config):
            del config

            async def _answer_then_abort(state: dict[str, Any]) -> dict[str, Any]:
                del state
                record.abort_action = "rollback"
                record.abort_event.set()
                return {"messages": [AIMessage(content="answer for a2-new", id="a2-new")]}

            builder = StateGraph(_DeltaChannelState)
            builder.add_node("answer", _answer_then_abort)
            builder.set_entry_point("answer")
            builder.set_finish_point("answer")
            graph = builder.compile(checkpointer=checkpointer)
            created_graphs.append(graph)
            return graph

        await run_agent(
            bridge,
            run_manager,
            record,
            ctx=RunContext(checkpointer=checkpointer, checkpoint_channel_mode="delta"),
            agent_factory=agent_factory,
            graph_input={"messages": [HumanMessage(content="q2", id="h2")]},
            config=_run_config("worker-rollback-branch", base.config["configurable"]["checkpoint_id"]),
            stream_modes=["values"],
        )

        assert record.status == RunStatus.error
        final_accessor = CheckpointStateAccessor.bind(created_graphs[-1], checkpointer, mode="delta")
        final = await final_accessor.aget(_run_config("worker-rollback-branch"))
        assert _ids(final) == ["h1", "a1", "h2", "a2"]


async def test_full_mode_keeps_the_fork():
    """Full checkpoints carry complete channel values, so the fork materializes
    correctly and LangGraph's branching semantics stay untouched."""
    checkpointer = InMemorySaver()
    accessor, _, pre_turn = await _seed_two_turns(checkpointer, _FullChannelState, "thread-1")
    config = _run_config("thread-1", pre_turn.config["configurable"]["checkpoint_id"])

    resumed = await _linearize_delta_checkpoint_resume(
        accessor=accessor,
        checkpointer=checkpointer,
        config=config,
        thread_id="thread-1",
        run_id="run-1",
    )

    assert resumed is None
    assert config["configurable"]["checkpoint_id"] == pre_turn.config["configurable"]["checkpoint_id"]


async def test_ordinary_run_without_a_checkpoint_selector_is_untouched():
    checkpointer = InMemorySaver()
    accessor, _, _ = await _seed_two_turns(checkpointer, _DeltaChannelState, "thread-1")
    config = _run_config("thread-1")

    assert (
        await _linearize_delta_checkpoint_resume(
            accessor=accessor,
            checkpointer=checkpointer,
            config=config,
            thread_id="thread-1",
            run_id="run-1",
        )
        is None
    )


async def test_selecting_the_head_is_already_linear():
    """No sibling can exist under the head yet, so there is nothing to rewrite
    and the thread keeps its checkpoint count."""
    checkpointer = InMemorySaver()
    accessor, head, _ = await _seed_two_turns(checkpointer, _DeltaChannelState, "thread-1")
    head_id = head.config["configurable"]["checkpoint_id"]
    before = len(await accessor.ahistory(_run_config("thread-1"), limit=50))

    assert (
        await _linearize_delta_checkpoint_resume(
            accessor=accessor,
            checkpointer=checkpointer,
            config=_run_config("thread-1", head_id),
            thread_id="thread-1",
            run_id="run-1",
        )
        is None
    )
    assert len(await accessor.ahistory(_run_config("thread-1"), limit=50)) == before


async def test_unmaterializable_resume_state_fails_closed():
    """Falling back to the fork would persist the corrupted history this
    exists to prevent, so an unreadable resume checkpoint raises."""
    checkpointer = InMemorySaver()
    accessor, _, pre_turn = await _seed_two_turns(checkpointer, _DeltaChannelState, "thread-1")

    class _NoMessages:
        def __init__(self, inner):
            self._inner = inner
            self.mode = inner.mode
            self.graph = inner.graph

        async def aget(self, config):
            snapshot = await self._inner.aget(config)
            if config.get("configurable", {}).get("checkpoint_id"):
                return type(snapshot)(**{**snapshot._asdict(), "values": {}})
            return snapshot

    with pytest.raises(RuntimeError, match="could not materialize resume checkpoint"):
        await _linearize_delta_checkpoint_resume(
            accessor=_NoMessages(accessor),
            checkpointer=checkpointer,
            config=_run_config("thread-1", pre_turn.config["configurable"]["checkpoint_id"]),
            thread_id="thread-1",
            run_id="run-1",
        )
