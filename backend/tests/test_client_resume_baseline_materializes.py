"""The resume baseline must materialize in both checkpoint channel modes.

A resume passes ``Command(resume=...)`` and appends no ``HumanMessage``, so the
``run_id`` marker that normally separates this turn from history never appears.
``_resume_baseline_messages`` supplies that separation by reading the checkpoint
the resume continues from — without it the whole prior turn is re-emitted as new
deltas and its ``usage_metadata`` is counted again.

Reading ``checkpoint["channel_values"]["messages"]`` off the raw saver only works
in ``full`` mode. In ``delta`` mode neither persisted shape yields messages:

* a non-snapshot checkpoint omits ``messages`` from ``channel_values`` entirely
  (the writes live on ancestors), and
* a snapshot checkpoint stores a ``_DeltaSnapshot`` — a single-field NamedTuple
  wrapping the accumulated value, not a message sequence. It *is* a ``Sequence``,
  so a bare isinstance check lets it through as a one-element "baseline".

``CheckpointStateAccessor`` materializes through the graph's channel table, so it
answers the same question in either mode. See
``test_delta_channel_checkpointers.py::test_delta_storage_shape_and_snapshot_cadence``
for the persisted-shape contract this relies on.
"""

from typing import Annotated, Any, TypedDict
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.channels.delta import DeltaChannel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.types import _DeltaSnapshot
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages

from deerflow.agents.thread_state import merge_message_writes
from deerflow.client import DeerFlowClient

# Small enough that the suite can cross it deliberately, unlike the production
# default — the point is to exercise both sides of the snapshot cadence.
_SNAPSHOT_FREQUENCY = 2


class _FullState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


class _DeltaState(TypedDict):
    messages: Annotated[list[AnyMessage], DeltaChannel(merge_message_writes, snapshot_frequency=_SNAPSHOT_FREQUENCY)]


def _turn(index: int) -> list[Any]:
    """One completed exchange, carrying usage that must not be counted twice."""
    return [
        HumanMessage(content=f"question {index}", id=f"h-{index}", additional_kwargs={"run_id": f"run-{index}"}),
        AIMessage(content=f"answer {index}", id=f"ai-{index}", usage_metadata={"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}),
    ]


def _graph(schema: Any, checkpointer: Any) -> Any:
    builder = StateGraph(schema)
    builder.add_node("append", lambda state: {})
    builder.set_entry_point("append")
    builder.set_finish_point("append")
    return builder.compile(checkpointer=checkpointer)


def _client(agent: Any, checkpointer: Any, mode: str) -> DeerFlowClient:
    """A client wired for baseline reads only — no run, no model."""
    client = DeerFlowClient.__new__(DeerFlowClient)
    client._agent = agent
    client._checkpointer = checkpointer
    client._checkpoint_channel_mode = mode
    return client


async def _seed(schema: Any, checkpointer: Any, mode: str, *, turns: int) -> tuple[Any, dict[str, Any], list[Any]]:
    """Drive real turns through a real graph so the persisted shape is genuine."""
    thread_id = f"resume-baseline-{mode}-{uuid4().hex}"
    config = {"configurable": {"thread_id": thread_id}}
    graph = _graph(schema, checkpointer)

    expected: list[Any] = []
    for index in range(turns):
        messages = _turn(index)
        expected.extend(messages)
        await graph.ainvoke({"messages": messages}, config=config)

    return graph, config, expected


def _ids(messages: list[Any]) -> list[str | None]:
    return [getattr(message, "id", None) for message in messages]


@pytest.mark.asyncio
async def test_a_full_mode_baseline_is_materialized() -> None:
    checkpointer = InMemorySaver()
    graph, config, expected = await _seed(_FullState, checkpointer, "full", turns=2)
    client = _client(graph, checkpointer, "full")

    baseline = client._resume_baseline_messages(checkpointer, config)

    assert _ids(baseline) == _ids(expected)


@pytest.mark.asyncio
async def test_a_delta_baseline_between_snapshots_is_materialized() -> None:
    """One turn: below the cadence, so the head has no ``messages`` channel value."""
    checkpointer = InMemorySaver()
    graph, config, expected = await _seed(_DeltaState, checkpointer, "delta", turns=1)

    head = await checkpointer.aget_tuple(config)
    assert head is not None
    assert "messages" not in head.checkpoint["channel_values"], "precondition: a non-snapshot checkpoint omits the channel"

    client = _client(graph, checkpointer, "delta")
    baseline = client._resume_baseline_messages(checkpointer, config)

    assert _ids(baseline) == _ids(expected)


@pytest.mark.asyncio
async def test_a_delta_baseline_at_a_snapshot_is_materialized() -> None:
    """Enough turns to cross the cadence, so a ``_DeltaSnapshot`` is persisted."""
    checkpointer = InMemorySaver()
    graph, config, expected = await _seed(_DeltaState, checkpointer, "delta", turns=_SNAPSHOT_FREQUENCY + 1)

    snapshot_found = False
    async for chain_tuple in checkpointer.alist(config):
        if isinstance(chain_tuple.checkpoint["channel_values"].get("messages"), _DeltaSnapshot):
            snapshot_found = True
            break
    assert snapshot_found, "precondition: the cadence must have written a _DeltaSnapshot"

    client = _client(graph, checkpointer, "delta")
    baseline = client._resume_baseline_messages(checkpointer, config)

    assert _ids(baseline) == _ids(expected)


@pytest.mark.asyncio
async def test_a_delta_baseline_is_never_a_snapshot_wrapper() -> None:
    """The failure mode a bare ``Sequence`` check admits.

    ``_DeltaSnapshot`` is a NamedTuple, so ``isinstance(x, Sequence)`` is true and
    ``list(x)`` yields ``[value]`` — a one-element baseline of a non-message. That
    would seed a bogus id into the history set and skip nothing real.
    """
    checkpointer = InMemorySaver()
    graph, config, _ = await _seed(_DeltaState, checkpointer, "delta", turns=_SNAPSHOT_FREQUENCY + 1)
    client = _client(graph, checkpointer, "delta")

    baseline = client._resume_baseline_messages(checkpointer, config)

    assert not any(isinstance(message, _DeltaSnapshot) for message in baseline)
    assert all(hasattr(message, "content") for message in baseline)


@pytest.mark.asyncio
async def test_an_unreadable_baseline_does_not_fail_the_resume() -> None:
    """Best effort: a noisy stream beats a resume that cannot run at all."""
    checkpointer = InMemorySaver()
    graph, config, _ = await _seed(_FullState, checkpointer, "full", turns=1)

    class _Exploding:
        def __getattr__(self, name: str) -> Any:
            raise RuntimeError("checkpointer is unavailable")

    client = _client(graph, _Exploding(), "full")

    assert client._resume_baseline_messages(_Exploding(), config) == []


def test_no_checkpointer_means_no_baseline() -> None:
    client = _client(None, None, "full")

    assert client._resume_baseline_messages(None, {"configurable": {"thread_id": "t-1"}}) == []
