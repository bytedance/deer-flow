"""A run that exhausts recursion_limit reports a plain stop, its unpresented outputs, and stands its goal down."""

import asyncio
import json
import socket
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import after_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from pydantic import ConfigDict

from deerflow.agents.thread_state import get_thread_state_schema
from deerflow.config.app_config import AppConfig
from deerflow.config.database_config import CheckpointChannelMode
from deerflow.config.paths import Paths
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.goal import build_goal_state, read_thread_goal, write_thread_goal
from deerflow.runtime.runs import worker
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.user_context import get_effective_user_id, reset_current_user, set_current_user


class _ToolLoopModel(BaseChatModel):
    """Calls the writer until the configured final response, or forever."""

    calls: list[int]
    finish_on_call: int | None = None
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def _llm_type(self) -> str:
        return "scripted-recursion-cap"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(len(self.calls) + 1)
        n = len(self.calls)
        if n == self.finish_on_call:
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="The report is ready."))])
        message = AIMessage(content=f"Working on part {n}.", tool_calls=[{"id": f"w-{n}", "name": "write_part", "args": {"n": n}}])
        return ChatResult(generations=[ChatGeneration(message=message)])


async def _run_at_limit(tmp_path: Path, *, with_goal: bool, checkpoint_mode: CheckpointChannelMode = "full", limit: int = 6, finish_on_call: int | None = None) -> dict[str, Any]:
    exit_calls = []
    evaluator_calls: list[Any] = []
    published: list[tuple[str, Any]] = []

    async def publish(run_id, event, data):
        published.append((event, data))

    bridge = SimpleNamespace(publish=publish, publish_end=lambda run_id: asyncio.sleep(0), cleanup=lambda run_id, delay=0: asyncio.sleep(0))
    saver = InMemorySaver()
    events = MemoryRunEventStore()
    manager = RunManager(store=MemoryRunStore())
    paths = Paths(base_dir=tmp_path)
    token = set_current_user(SimpleNamespace(id="recursion-cap-user", role="admin"))
    try:
        with (
            patch("deerflow.config.paths._paths", paths),
            patch.dict("os.environ", {"DEER_FLOW_HOME": str(tmp_path), "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"}),
            patch.object(worker, "create_goal_evaluator_model", lambda **kwargs: evaluator_calls.append(kwargs)),
        ):
            record = await manager.create("recursion-cap-thread", user_id="recursion-cap-user")
            outputs = paths.sandbox_outputs_dir(record.thread_id, user_id=get_effective_user_id())
            outputs.mkdir(parents=True, exist_ok=True)

            @tool
            def write_part(n: int) -> str:
                """Write one part of the report."""
                (outputs / f"part-{n}.md").write_text(f"part {n}\n", encoding="utf-8")
                return f"wrote part-{n}.md"

            model = _ToolLoopModel(calls=[], finish_on_call=finish_on_call)
            # Snapshot every delta write so the cap lands on a stored messages snapshot.
            state_schema = get_thread_state_schema(checkpoint_mode, snapshot_frequency=1)

            @after_agent
            def record_exit(state, runtime):
                exit_calls.append(True)

            graph = create_agent(model=model, tools=[write_part], middleware=[record_exit] if finish_on_call else [], state_schema=state_schema, context_schema=dict, checkpointer=saver)
            app_config = AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
            app_config.title.enabled = True
            app_config.memory.enabled = app_config.memory.injection_enabled = False
            if with_goal:
                await write_thread_goal(saver, record.thread_id, build_goal_state("Write the report.", max_continuations=2), create_if_missing=True)
            await worker.run_agent(
                bridge,
                manager,
                record,
                ctx=worker.RunContext(checkpointer=saver, event_store=events, app_config=app_config, checkpoint_channel_mode=checkpoint_mode),
                agent_factory=lambda config: graph,
                graph_input={"messages": [HumanMessage(content="Write the report in parts.")]},
                config={"configurable": {"thread_id": record.thread_id}, "recursion_limit": limit},
                stream_modes=["values"],
            )
            snapshot = await graph.aget_state({"configurable": {"thread_id": record.thread_id}})
            if record.status == RunStatus.error:
                assert snapshot.values["title"] == "Write the report in parts."
            goal = await read_thread_goal(saver, record.thread_id)
            recorded = await events.list_events(record.thread_id, record.run_id)
    finally:
        reset_current_user(token)
    return {
        "record": record,
        "exit_calls": exit_calls,
        "graph_outcomes": [event["event_type"] for event in recorded if event["event_type"] in {"run.end", "run.error"}],
        "goal": goal,
        "error_frames": [data for event, data in published if event == "error"],
        "deliveries": [event["content"] for event in recorded if event["event_type"] == "run.delivery"],
        "model_calls": len(model.calls),
        "evaluator_calls": len(evaluator_calls),
    }


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    connect = socket.socket.connect

    def deny(sock, address):
        # Windows asyncio uses a loopback socket pair to wake its event loop.
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return connect(sock, address)
        raise AssertionError("this regression must not use the network")

    monkeypatch.setattr(socket.socket, "connect", deny)


@pytest.mark.asyncio
@pytest.mark.parametrize("checkpoint_mode", ["full", "delta"])
async def test_recursion_cap_reports_a_plain_stop_with_unpresented_outputs(tmp_path, checkpoint_mode):
    result = await _run_at_limit(tmp_path, with_goal=False, checkpoint_mode=checkpoint_mode)
    record = result["record"]

    assert record.status == RunStatus.error
    assert record.stop_reason == "recursion_capped"
    produced = [f"/mnt/user-data/outputs/part-{n}.md" for n in range(1, result["model_calls"] + 1)]
    assert result["model_calls"] >= 1
    assert record.error == (f"The run stopped at its step limit (recursion_limit=6) before finishing. Created but not presented: {', '.join(produced)}. Send a message to continue.")
    assert "config key" not in record.error and "troubleshooting" not in record.error
    assert result["error_frames"] == [{"message": record.error, "name": "GraphRecursionError"}]
    # One scan feeds both the message and the delivery receipt.
    assert len(result["deliveries"]) == 1
    assert result["deliveries"][0]["produced_paths"] == produced
    assert result["deliveries"][0]["satisfied"] is False
    assert result["deliveries"][0]["enforcement"] == "advisory"


@pytest.mark.asyncio
@pytest.mark.parametrize("checkpoint_mode", ["full", "delta"])
@pytest.mark.parametrize("limit", [5, 6])
async def test_final_answer_at_the_step_limit_waits_for_cleanup(tmp_path, checkpoint_mode, limit):
    result = await _run_at_limit(tmp_path, with_goal=False, checkpoint_mode=checkpoint_mode, limit=limit, finish_on_call=3)
    record = result["record"]
    assert result["model_calls"] == 3
    if limit == 5:
        assert result["graph_outcomes"] == ["run.error"]
        assert result["exit_calls"] == []
        assert record.status == RunStatus.error and record.stop_reason == "recursion_capped"
    else:
        assert result["graph_outcomes"] == ["run.end"]
        assert result["exit_calls"] == [True]
        assert record.status == RunStatus.success and record.stop_reason is None
        assert result["error_frames"] == []


@pytest.mark.asyncio
async def test_previous_idle_checkpoint_does_not_hide_a_new_cap():
    saver = InMemorySaver()
    builder = StateGraph(dict)
    builder.add_node("finish", lambda state: state)
    builder.add_edge(START, "finish")
    builder.add_edge("finish", END)
    graph = builder.compile(checkpointer=saver)
    accessor = worker.CheckpointStateAccessor.bind(graph, saver)
    config = {"configurable": {"thread_id": "same-thread"}, "metadata": {worker._GRAPH_INVOCATION_KEY: "earlier-invocation"}}
    await graph.ainvoke({"value": 1}, config)
    snapshot = await accessor.aget(config)
    assert snapshot.metadata["source"] == "loop" and not snapshot.next and not snapshot.tasks

    async def early_cap():
        yield "started"
        raise GraphRecursionError("new invocation stopped")

    with pytest.raises(GraphRecursionError, match="new invocation stopped"):
        async for _ in worker._graph_stream_events(early_cap(), accessor, "same-thread", "different-invocation"):
            pass


@pytest.mark.asyncio
async def test_recursion_cap_stands_the_goal_down_without_an_evaluator_call(tmp_path):
    result = await _run_at_limit(tmp_path, with_goal=True)
    record, goal = result["record"], result["goal"]

    assert result["evaluator_calls"] == 0
    assert goal is not None and goal["status"] == "active"
    evaluation = goal["last_evaluation"]
    assert evaluation["stand_down_reason"] == "recursion_capped"
    assert evaluation["blocker"] == "run_failed"
    assert evaluation["reason"] == "The run reached its step limit before finishing."
    assert goal["continuation_count"] == 0
    assert record.goal_verdict is not None
    assert record.goal_verdict["stand_down_reason"] == "recursion_capped"
    assert json.dumps(record.goal_verdict)  # stored as plain data on the run record
    # The receipt is built before the continuation call records the verdict;
    # it must be normalized to required for this goal run.
    assert len(result["deliveries"]) == 1
    assert result["deliveries"][0]["enforcement"] == "required"


def test_recursion_cap_message_without_outputs_or_limit():
    assert worker._recursion_capped_message(None, None) == "The run stopped at its step limit before finishing. Send a message to continue."
    presented = {"produced_paths": ["/mnt/user-data/outputs/a.md"], "matched_paths": ["/mnt/user-data/outputs/a.md"]}
    assert worker._recursion_capped_message(100, presented) == "The run stopped at its step limit (recursion_limit=100) before finishing. Send a message to continue."


def test_recursion_cap_message_lists_at_most_five_outputs():
    produced = [f"/mnt/user-data/outputs/{n}.md" for n in range(7)]
    message = worker._recursion_capped_message(1000, {"produced_paths": produced, "matched_paths": []})
    assert message.endswith(f"Created but not presented: {', '.join(produced[:5])} and 2 more. Send a message to continue.")
