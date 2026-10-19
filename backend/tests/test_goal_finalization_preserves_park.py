"""Goal finalization must not run — or write — while a run is parked.

``interrupt()`` exits the graph *normally*, so a parked run reaches run
finalization staged as ``RunStatus.success``. Finalization then walks the goal
loop before it ever reaches the duration write:
``_stream_once`` → ``_prepare_goal_continuation_input`` → ... → ``_persist_run_duration``.

Every goal write below creates a *new head checkpoint*, and ``pending_writes`` is
not a checkpoint field — the checkpointer keys it by checkpoint id — so a fresh
head cannot carry the park's pending write. The approval the client already saw
on the stream disappears from every later ``/state`` read.

The trap is that the guard which *detects* the park is the very thing that
triggers the write: ``_has_durable_goal_turn_receipt`` returns false while
pending writes exist, which routes into ``_persist(stand_down_reason=
"no_durable_end_of_turn")`` → ``write_thread_goal``. So the park check has to come
*before* it.

Nothing is lost by skipping: that receipt reads the same ``pending_writes``, so
answering the park restores ordinary evaluation on the next turn. Compare
``_ends_on_human_input_request``, which stands the goal down for an unanswered
question — that path may persist, because it is not itself the destroyer.

Companion to ``test_run_duration_preserves_park.py``, which covers the duration
writer at the end of the same finalization sequence.
"""

from typing import Annotated, Any, TypedDict

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt

from deerflow.runtime.checkpoint_state import CheckpointStateAccessor, build_state_mutation_graph
from deerflow.runtime.goal import GoalEvaluation, build_goal_state, read_thread_goal, write_thread_goal
from deerflow.runtime.runs import worker


class _State(TypedDict):
    messages: Annotated[list, add_messages]
    goal: Any


class _CollectingBridge:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    async def publish(self, _run_id: str, event: str, payload: object) -> None:
        self.events.append((event, payload))


def _gated_graph(checkpointer: InMemorySaver, *, gates: int) -> Any:
    """A graph that parks on tool approval ``gates`` times, then answers."""

    def agent(state: _State) -> dict:
        approved = len([m for m in state["messages"] if isinstance(m, AIMessage) and m.content.startswith("approved")])
        if approved < gates:
            decision = interrupt({"action_requests": [{"name": "bash_tool", "args": {"command": "ls"}}]})
            return {"messages": [AIMessage(content=f"approved {decision}")]}
        return {"messages": [AIMessage(content="All done — the goal is met.")]}

    builder = StateGraph(_State)
    builder.add_node("agent", agent)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", lambda state: END if state["messages"][-1].content.startswith("All done") else "agent")
    return builder.compile(checkpointer=checkpointer)


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}


def _accessor(checkpointer: InMemorySaver) -> CheckpointStateAccessor:
    return CheckpointStateAccessor.bind(build_state_mutation_graph("goal_evaluator", "full"), checkpointer, mode="full")


async def _drive(graph: Any, thread_id: str, payload: Any) -> None:
    async for _ in graph.astream(payload, config=_config(thread_id), stream_mode="values"):
        pass


async def _pending_interrupts(graph: Any, thread_id: str) -> list[Any]:
    snapshot = await graph.aget_state(_config(thread_id))
    return [pending for task in (snapshot.tasks or ()) for pending in (task.interrupts or ())]


async def _park_with_active_goal(checkpointer: InMemorySaver, thread_id: str, *, gates: int) -> Any:
    """Park a thread that carries an active goal, mirroring the HTTP flow."""
    graph = _gated_graph(checkpointer, gates=gates)
    goal = build_goal_state("Finish the migration", max_continuations=2)
    await _drive(graph, thread_id, {"messages": [HumanMessage(content="Do the migration.")], "goal": goal})
    return graph


def _never_called_evaluator(monkeypatch) -> list[Any]:
    """Record evaluator invocations — a parked turn must not be evaluated."""
    calls: list[Any] = []

    async def fake_evaluate_goal_completion(goal, messages, **kwargs):
        calls.append(goal)
        return GoalEvaluation(satisfied=False, blocker="goal_not_met_yet", reason="unused", evidence_summary="")

    monkeypatch.setattr(worker, "evaluate_goal_completion", fake_evaluate_goal_completion)
    return calls


async def _prepare(checkpointer: InMemorySaver, thread_id: str, run_id: str) -> Any:
    return await worker._prepare_goal_continuation_input(
        accessor=_accessor(checkpointer),
        bridge=_CollectingBridge(),
        checkpointer=checkpointer,
        thread_id=thread_id,
        run_id=run_id,
        model_name="test-model",
        app_config=None,
    )


@pytest.mark.asyncio
async def test_a_first_park_survives_goal_finalization(monkeypatch) -> None:
    checkpointer = InMemorySaver()
    thread_id = "goal-park-first"
    graph = await _park_with_active_goal(checkpointer, thread_id, gates=1)
    assert await _pending_interrupts(graph, thread_id), "precondition: the run must be parked"
    evaluator_calls = _never_called_evaluator(monkeypatch)

    continuation = await _prepare(checkpointer, thread_id, "run-1")

    assert continuation is None
    assert evaluator_calls == [], "a parked turn is not a finished turn to evaluate"
    assert await _pending_interrupts(graph, thread_id), "goal finalization dropped the pending approval"


@pytest.mark.asyncio
async def test_a_second_park_after_an_approval_survives_it(monkeypatch) -> None:
    """The reviewer's scenario: approve over HTTP, then hit another gated call."""
    checkpointer = InMemorySaver()
    thread_id = "goal-park-second"
    graph = await _park_with_active_goal(checkpointer, thread_id, gates=2)
    await _drive(graph, thread_id, Command(resume="yes"))
    assert await _pending_interrupts(graph, thread_id), "precondition: the resumed run must park again"
    _never_called_evaluator(monkeypatch)

    await _prepare(checkpointer, thread_id, "run-2")

    assert await _pending_interrupts(graph, thread_id), "goal finalization dropped the second pending approval"


@pytest.mark.asyncio
async def test_the_goal_is_left_untouched_while_parked(monkeypatch) -> None:
    """Skipping must not stand the goal down — the turn simply has not ended.

    A ``stand_down_reason`` write is exactly what destroys the park, so the goal
    has to come through byte-identical.
    """
    checkpointer = InMemorySaver()
    thread_id = "goal-park-untouched"
    graph = await _park_with_active_goal(checkpointer, thread_id, gates=1)
    before = await read_thread_goal(checkpointer, thread_id)
    _never_called_evaluator(monkeypatch)

    await _prepare(checkpointer, thread_id, "run-1")

    after = await read_thread_goal(checkpointer, thread_id)
    assert after == before
    assert after is not None and after["status"] == "active"
    assert await _pending_interrupts(graph, thread_id)


@pytest.mark.asyncio
async def test_the_park_is_still_resumable_afterwards(monkeypatch) -> None:
    """Losing the pending write would also make the thread unresumable."""
    checkpointer = InMemorySaver()
    thread_id = "goal-park-resumable"
    graph = await _park_with_active_goal(checkpointer, thread_id, gates=1)
    _never_called_evaluator(monkeypatch)

    await _prepare(checkpointer, thread_id, "run-1")
    await _drive(graph, thread_id, Command(resume="approved by hand"))

    final = await graph.aget_state(_config(thread_id))
    assert any(m.content == "approved approved by hand" for m in final.values["messages"])
    assert not await _pending_interrupts(graph, thread_id)


@pytest.mark.asyncio
async def test_goal_evaluation_resumes_once_the_park_is_answered(monkeypatch) -> None:
    """The skip needs no compensation: the receipt reads the same pending writes.

    Answering the park empties ``pending_writes``, so
    ``_has_durable_goal_turn_receipt`` passes again and the next turn evaluates
    the goal normally. Without this the guard would trade a lost approval for a
    goal that never advances.
    """
    checkpointer = InMemorySaver()
    thread_id = "goal-park-unstuck"
    graph = await _park_with_active_goal(checkpointer, thread_id, gates=1)
    evaluator_calls = _never_called_evaluator(monkeypatch)

    await _prepare(checkpointer, thread_id, "run-parked")
    assert evaluator_calls == []

    await _drive(graph, thread_id, Command(resume="yes"))
    assert not await _pending_interrupts(graph, thread_id), "precondition: the park is answered"

    await _prepare(checkpointer, thread_id, "run-answered")

    assert len(evaluator_calls) == 1, "the goal must be evaluated again once nothing is pending"


@pytest.mark.asyncio
async def test_an_unparked_thread_still_finalizes_its_goal(monkeypatch) -> None:
    """The ordinary path must keep working — this is not a blanket skip."""
    checkpointer = InMemorySaver()
    thread_id = "goal-park-plain"
    graph = _gated_graph(checkpointer, gates=0)
    await write_thread_goal(checkpointer, thread_id, build_goal_state("Finish the migration", max_continuations=2), create_if_missing=True)
    await _drive(graph, thread_id, {"messages": [HumanMessage(content="Do the migration.")], "goal": await read_thread_goal(checkpointer, thread_id)})
    assert not await _pending_interrupts(graph, thread_id), "precondition: this run must not park"
    evaluator_calls = _never_called_evaluator(monkeypatch)

    await _prepare(checkpointer, thread_id, "run-1")

    assert len(evaluator_calls) == 1, "an unparked turn must still be evaluated"
