"""A parked run's pending approval must survive the run-metadata checkpoint.

``interrupt()`` makes the graph exit *normally*: the stream ends cleanly, so the
worker stages ``RunStatus.success`` (``RunStatus.interrupted`` is only ever set
by the cancellation path). That success then reaches ``_persist_run_duration``,
which writes a new latest checkpoint parented on the parked one.

``pending_writes`` is not a field of the checkpoint — it is a separate record the
checkpointer keys by checkpoint id — so a plain ``aput`` does not carry it over.
The new latest checkpoint therefore has no pending task, and every later
``GET /threads/{id}`` or ``/state`` read loses the approval that the client just
saw on the stream.

Before this PR the branch was unreachable: every Gateway run was downgraded, so
an HTTP run never parked. Keeping approval on for HTTP *resumes* is what makes
"approve, then hit a second gated call" reachable.
"""

from typing import Annotated, Any, TypedDict

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from deerflow.runtime.runs.worker import _persist_run_duration


class _State(TypedDict):
    steps: Annotated[list[str], lambda left, right: [*left, *right]]


def _parking_graph(checkpointer: InMemorySaver, *, gates: int) -> Any:
    """A graph that parks on ``interrupt()`` once per gate, then finishes."""

    def gate(state: _State) -> dict:
        taken = len([step for step in state["steps"] if step.startswith("approved:")])
        if taken < gates:
            decision = interrupt({"gate": taken})
            return {"steps": [f"approved:{decision}"]}
        return {"steps": ["done"]}

    builder = StateGraph(_State)
    builder.add_node("gate", gate)
    builder.add_edge(START, "gate")
    # Re-enter so a resumed run can park again on its next gated call.
    builder.add_conditional_edges("gate", lambda state: END if "done" in state["steps"] else "gate")
    return builder.compile(checkpointer=checkpointer)


async def _park(graph: Any, config: dict, payload: Any) -> Any:
    """Drive the graph until it parks (or finishes) and return its snapshot."""
    async for _ in graph.astream(payload, config=config, stream_mode="values"):
        pass
    return await graph.aget_state(config)


def _pending_interrupts(snapshot: Any) -> list[Any]:
    return [pending for task in (snapshot.tasks or ()) for pending in (task.interrupts or ())]


@pytest.mark.anyio
async def test_a_first_park_survives_the_duration_checkpoint() -> None:
    checkpointer = InMemorySaver()
    thread_id = "park-duration-first"
    config = {"configurable": {"thread_id": thread_id}}
    graph = _parking_graph(checkpointer, gates=1)

    parked = await _park(graph, config, {"steps": []})
    assert _pending_interrupts(parked), "precondition: the graph must be parked"

    await _persist_run_duration(
        checkpointer=checkpointer,
        thread_id=thread_id,
        run_id="run-1",
        duration_seconds=3,
    )

    after = await graph.aget_state(config)
    assert _pending_interrupts(after), "the duration checkpoint dropped the pending approval"


@pytest.mark.anyio
async def test_a_second_park_after_an_approval_survives_it() -> None:
    """The reviewer's scenario: approve, then hit another gated call."""
    checkpointer = InMemorySaver()
    thread_id = "park-duration-second"
    config = {"configurable": {"thread_id": thread_id}}
    graph = _parking_graph(checkpointer, gates=2)

    await _park(graph, config, {"steps": []})
    reparked = await _park(graph, config, Command(resume="first"))
    assert _pending_interrupts(reparked), "precondition: the resumed run must park again"

    await _persist_run_duration(
        checkpointer=checkpointer,
        thread_id=thread_id,
        run_id="run-2",
        duration_seconds=5,
    )

    after = await graph.aget_state(config)
    assert _pending_interrupts(after), "the duration checkpoint dropped the second pending approval"


@pytest.mark.anyio
async def test_the_park_is_still_resumable_afterwards() -> None:
    """Losing the pending write would also make the thread unresumable."""
    checkpointer = InMemorySaver()
    thread_id = "park-duration-resumable"
    config = {"configurable": {"thread_id": thread_id}}
    graph = _parking_graph(checkpointer, gates=1)

    await _park(graph, config, {"steps": []})
    await _persist_run_duration(
        checkpointer=checkpointer,
        thread_id=thread_id,
        run_id="run-1",
        duration_seconds=3,
    )

    await _park(graph, config, Command(resume="yes"))

    final = await graph.aget_state(config)
    assert "approved:yes" in final.values["steps"]
    assert not _pending_interrupts(final)


@pytest.mark.anyio
async def test_an_unparked_thread_still_records_its_duration() -> None:
    """The ordinary path must keep working — this is not a blanket skip."""
    checkpointer = InMemorySaver()
    thread_id = "park-duration-plain"
    config = {"configurable": {"thread_id": thread_id}}
    graph = _parking_graph(checkpointer, gates=0)

    finished = await _park(graph, config, {"steps": []})
    assert not _pending_interrupts(finished), "precondition: this run must not park"

    await _persist_run_duration(
        checkpointer=checkpointer,
        thread_id=thread_id,
        run_id="run-1",
        duration_seconds=4,
    )

    latest = await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
    assert latest is not None
    assert latest.metadata["run_durations"] == {"run-1": 4}
