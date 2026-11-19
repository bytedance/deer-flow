"""Offline reproduction of Goal re-entry after the native loop guard stops."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ConfigDict

from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware
from deerflow.agents.thread_state import ThreadState
from deerflow.config.app_config import AppConfig
from deerflow.config.paths import Paths
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.goal import build_goal_state, read_thread_goal, write_thread_goal
from deerflow.runtime.runs import worker
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.user_context import reset_current_user, set_current_user


@dataclass
class Counts:
    model_calls: int = 0
    tool_executions: int = 0
    evaluator_calls: int = 0


class RepeatingModel(BaseChatModel):
    """Always request the same harmless tool, including after a hard stop."""

    counts: Counts
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def _llm_type(self) -> str:
        return "offline-loop-stop-reproduction"

    def bind_tools(self, tools: Any, **kwargs: Any) -> RepeatingModel:
        return self

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        self.counts.model_calls += 1
        message = AIMessage(
            content="",
            tool_calls=[{"id": f"inspect-{self.counts.model_calls}", "name": "inspect_marker", "args": {"marker": "fixed"}}],
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


class UnmetEvaluator:
    def __init__(self, counts: Counts) -> None:
        self.counts = counts

    async def ainvoke(self, messages: Any, config: Any = None) -> AIMessage:
        self.counts.evaluator_calls += 1
        return AIMessage(
            content=json.dumps({"satisfied": False, "blocker": "goal_not_met_yet", "reason": "The synthetic task remains unfinished.", "evidence_summary": "Only repeated marker inspections ran.", "relied_on_assumption": False})
        )


async def run_case(*, max_continuations: int = 1) -> dict[str, Any]:
    """Run a real graph and worker with scripted models and temporary storage.

    The sole provider replacement is the Goal evaluator factory. Goal decisions,
    loop detection, tool execution, checkpoints and finalization stay native.
    """
    counts = Counts()

    @tool
    def inspect_marker(marker: str) -> str:
        """Record a synthetic inspection without shell or network access."""
        counts.tool_executions += 1
        return f"Observed marker: {marker}"

    saver = InMemorySaver()
    events = MemoryRunEventStore()
    manager = RunManager(store=MemoryRunStore())
    graph = create_agent(
        model=RepeatingModel(counts=counts),
        tools=[inspect_marker],
        middleware=[LoopDetectionMiddleware(warn_threshold=3, hard_limit=5, window_size=20)],
        state_schema=ThreadState,
        context_schema=dict,
        checkpointer=saver,
    )
    cfg = AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
    cfg.title.enabled = cfg.memory.enabled = cfg.memory.injection_enabled = False
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    token = set_current_user(SimpleNamespace(id="goal-loop-probe", role="admin"))
    try:
        with tempfile.TemporaryDirectory(prefix="goal-loop-stop-") as folder:
            paths = Paths(base_dir=Path(folder))
            with (
                patch("deerflow.config.paths._paths", paths),
                patch.dict(os.environ, {"DEER_FLOW_HOME": folder, "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"}),
                patch.object(worker, "create_goal_evaluator_model", lambda **kwargs: UnmetEvaluator(counts)),
            ):
                record = await manager.create(f"loop-stop-{uuid4().hex}", user_id="goal-loop-probe")
                await write_thread_goal(saver, record.thread_id, build_goal_state("Finish the synthetic task.", max_continuations=max_continuations), create_if_missing=True)
                await worker.run_agent(
                    bridge,
                    manager,
                    record,
                    ctx=worker.RunContext(checkpointer=saver, event_store=events, app_config=cfg),
                    agent_factory=lambda config: graph,
                    graph_input={"messages": [HumanMessage(content="Inspect the marker until the synthetic task is complete.")]},
                    config={"configurable": {"thread_id": record.thread_id}, "recursion_limit": 100},
                    stream_modes=["values"],
                )
                goal = await read_thread_goal(saver, record.thread_id)
                if goal is None:
                    raise AssertionError("The unfinished goal was cleared")
                return {
                    "scenario": "native_loop_hard_stop_with_unmet_goal",
                    "fixture": "scripted models; real loop middleware, ToolNode, worker and in-memory checkpoints",
                    "guard_hard_limit": 5,
                    "max_goal_continuations": max_continuations,
                    "lead_model_calls": counts.model_calls,
                    "tool_executions": counts.tool_executions,
                    "goal_evaluator_calls": counts.evaluator_calls,
                    "goal_continuations": goal["continuation_count"],
                    "goal_status": goal["status"],
                    "stand_down_reason": goal.get("last_evaluation", {}).get("stand_down_reason"),
                    "run_status": record.status.value,
                    "run_stop_reason": record.stop_reason,
                    "run_error": record.error,
                    "provider_requests": 0,
                    "versions": {name: version(name) for name in ["langgraph", "langgraph-checkpoint", "langchain"]},
                }
    finally:
        reset_current_user(token)
