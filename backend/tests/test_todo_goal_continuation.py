"""Todo completion reminders in Goal continuation turns after an earlier response cap.

The worker keeps the first cap reason in ``runtime.context["stop_reason"]`` across
hidden Goal turns so the run record reports it, and an unmet Goal keeps going after
a provider length or safety cap. Those turns are new model responses: a cap that
ended an earlier response must not switch off Todo reminders for them.
"""

import json
import os
import socket
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ConfigDict

from deerflow.agents.middlewares.model_length_finish_reason_middleware import ModelLengthFinishReasonMiddleware
from deerflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware
from deerflow.agents.middlewares.todo_middleware import TodoMiddleware
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

_UNFINISHED_TODOS = [
    {"content": "Draft the report", "status": "completed"},
    {"content": "Add the appendix", "status": "in_progress"},
]


class _ScriptedModel(BaseChatModel):
    """Return scripted responses in order and record every request."""

    responses: list[AIMessage]
    requests: list[list[BaseMessage]]
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def _llm_type(self) -> str:
        return "offline-todo-goal-continuation"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_ScriptedModel":
        return self

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        self.requests.append(list(messages))
        if not self.responses:
            raise AssertionError("The lead model was called more often than scripted")
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])


class _UnmetEvaluator:
    async def ainvoke(self, messages: Any, config: Any = None) -> AIMessage:
        return AIMessage(content=json.dumps({"satisfied": False, "blocker": "goal_not_met_yet", "reason": "The appendix is missing.", "evidence_summary": "Only the draft exists.", "relied_on_assumption": False}))


def _has_completion_reminder(request: list[BaseMessage]) -> bool:
    return any(isinstance(message, HumanMessage) and message.name == "todo_completion_reminder" for message in request)


async def _run_goal_with_capped_user_turn(model: _ScriptedModel, guard: Any):
    saver = InMemorySaver()
    manager = RunManager(store=MemoryRunStore())
    graph = create_agent(
        model=model,
        tools=[],
        middleware=[TodoMiddleware(), guard],
        state_schema=ThreadState,
        context_schema=dict,
        checkpointer=saver,
    )
    cfg = AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
    cfg.title.enabled = cfg.memory.enabled = cfg.memory.injection_enabled = False
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    token = set_current_user(SimpleNamespace(id="todo-goal-continuation", role="admin"))
    try:
        with tempfile.TemporaryDirectory(prefix="todo-goal-continuation-") as folder:
            with (
                patch("deerflow.config.paths._paths", Paths(base_dir=Path(folder))),
                patch.dict(os.environ, {"DEER_FLOW_HOME": folder, "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"}),
                patch.object(worker, "create_goal_evaluator_model", lambda **kwargs: _UnmetEvaluator()),
            ):
                record = await manager.create(f"todo-goal-{uuid4().hex}", user_id="todo-goal-continuation")
                await write_thread_goal(saver, record.thread_id, build_goal_state("Write the report with its appendix.", max_continuations=1), create_if_missing=True)
                await worker.run_agent(
                    bridge,
                    manager,
                    record,
                    ctx=worker.RunContext(checkpointer=saver, event_store=MemoryRunEventStore(), app_config=cfg),
                    agent_factory=lambda config: graph,
                    graph_input={"messages": [HumanMessage(content="Write the report with its appendix.")], "todos": _UNFINISHED_TODOS},
                    config={"configurable": {"thread_id": record.thread_id}, "recursion_limit": 100},
                    stream_modes=["values"],
                )
                goal = await read_thread_goal(saver, record.thread_id)
                return record, goal
    finally:
        reset_current_user(token)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("guard", "finish_reason", "stop_reason"),
    [
        # ModelLength keeps the first cap reason already in the context.
        pytest.param(ModelLengthFinishReasonMiddleware, "length", "model_length_capped", id="length"),
        # Safety overwrites the context's stop_reason unconditionally.
        pytest.param(SafetyFinishReasonMiddleware, "content_filter", "safety_capped", id="safety"),
    ],
)
async def test_goal_continuation_after_a_provider_stop_still_gets_todo_reminders(monkeypatch, guard, finish_reason, stop_reason):
    def deny_network(*args, **kwargs):
        raise AssertionError("This controlled regression must not use the network")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    model = _ScriptedModel(
        responses=[
            # User turn: the provider stops the answer early.
            AIMessage(content="Here is the first half of the report", response_metadata={"finish_reason": finish_reason}),
            # Hidden Goal turn: a complete response that tries to stop with the appendix unfinished.
            AIMessage(content="The report is done."),
            AIMessage(content="Adding the appendix now."),
            AIMessage(content="Appendix added."),
        ],
        requests=[],
    )

    record, goal = await _run_goal_with_capped_user_turn(model, guard())

    assert record.error is None
    # The run still reports the stop from the user turn.
    assert record.stop_reason == stop_reason
    assert goal is not None and goal["continuation_count"] == 1
    # The stopped user turn ends without a reminder ...
    assert not _has_completion_reminder(model.requests[0])
    # ... but the continuation's premature exit is reminded twice, up to the usual cap.
    assert len(model.requests) == 4
    assert [_has_completion_reminder(request) for request in model.requests[1:]] == [False, True, True]
