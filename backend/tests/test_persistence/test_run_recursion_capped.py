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
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ConfigDict

from deerflow.agents.thread_state import ThreadState
from deerflow.config.app_config import AppConfig
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
    """Calls the writer on every turn, so the graph only stops at its recursion limit."""

    calls: list[int]
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def _llm_type(self) -> str:
        return "scripted-recursion-cap"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(len(self.calls) + 1)
        n = len(self.calls)
        message = AIMessage(content=f"Working on part {n}.", tool_calls=[{"id": f"w-{n}", "name": "write_part", "args": {"n": n}}])
        return ChatResult(generations=[ChatGeneration(message=message)])


async def _run_until_recursion_cap(tmp_path: Path, *, with_goal: bool) -> dict[str, Any]:
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

            model = _ToolLoopModel(calls=[])
            graph = create_agent(model=model, tools=[write_part], state_schema=ThreadState, context_schema=dict, checkpointer=saver)
            app_config = AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
            app_config.title.enabled = app_config.memory.enabled = app_config.memory.injection_enabled = False
            if with_goal:
                await write_thread_goal(saver, record.thread_id, build_goal_state("Write the report.", max_continuations=2), create_if_missing=True)
            await worker.run_agent(
                bridge,
                manager,
                record,
                ctx=worker.RunContext(checkpointer=saver, event_store=events, app_config=app_config),
                agent_factory=lambda config: graph,
                graph_input={"messages": [HumanMessage(content="Write the report in parts.")]},
                config={"configurable": {"thread_id": record.thread_id}, "recursion_limit": 6},
                stream_modes=["values"],
            )
            goal = await read_thread_goal(saver, record.thread_id)
            recorded = await events.list_events(record.thread_id, record.run_id)
    finally:
        reset_current_user(token)
    return {
        "record": record,
        "goal": goal,
        "error_frames": [data for event, data in published if event == "error"],
        "deliveries": [event["content"] for event in recorded if event["event_type"] == "run.delivery"],
        "model_calls": len(model.calls),
        "evaluator_calls": len(evaluator_calls),
    }


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("this regression must not use the network")

    monkeypatch.setattr(socket.socket, "connect", deny)


@pytest.mark.asyncio
async def test_recursion_cap_reports_a_plain_stop_with_unpresented_outputs(tmp_path):
    result = await _run_until_recursion_cap(tmp_path, with_goal=False)
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


@pytest.mark.asyncio
async def test_recursion_cap_stands_the_goal_down_without_an_evaluator_call(tmp_path):
    result = await _run_until_recursion_cap(tmp_path, with_goal=True)
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


def test_recursion_cap_message_without_outputs_or_limit():
    assert worker._recursion_capped_message(None, None) == "The run stopped at its step limit before finishing. Send a message to continue."
    presented = {"produced_paths": ["/mnt/user-data/outputs/a.md"], "matched_paths": ["/mnt/user-data/outputs/a.md"]}
    assert worker._recursion_capped_message(100, presented) == "The run stopped at its step limit (recursion_limit=100) before finishing. Send a message to continue."


def test_recursion_cap_message_lists_at_most_five_outputs():
    produced = [f"/mnt/user-data/outputs/{n}.md" for n in range(7)]
    message = worker._recursion_capped_message(1000, {"produced_paths": produced, "matched_paths": []})
    assert message.endswith(f"Created but not presented: {', '.join(produced[:5])} and 2 more. Send a message to continue.")
