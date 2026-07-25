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

from typing import Annotated, Any, TypedDict

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
from deerflow.runtime.runs.worker import _linearize_delta_checkpoint_resume

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _DeltaChannelState(TypedDict):
    messages: Annotated[list[AnyMessage], DeltaChannel(merge_message_writes, snapshot_frequency=1000)]


class _FullChannelState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


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
