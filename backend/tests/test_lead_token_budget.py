"""Regression tests for subagent usage in the assembled lead budget chain."""

from typing import Annotated

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.agents.lead_agent.agent import build_middlewares
from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware
from deerflow.agents.middlewares.subagent_limit_middleware import SubagentLimitMiddleware
from deerflow.agents.middlewares.token_budget_middleware import TokenBudgetMiddleware
from deerflow.agents.middlewares.token_usage_middleware import TOKEN_USAGE_ATTRIBUTION_KEY, CompletedSubagentUsageMiddleware, TokenUsageMiddleware
from deerflow.agents.thread_state import ThreadState
from deerflow.config.app_config import AppConfig
from deerflow.config.loop_detection_config import LoopDetectionConfig
from deerflow.config.memory_config import MemoryConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.summarization_config import SummarizationConfig
from deerflow.config.token_budget_config import TokenBudgetConfig
from deerflow.config.token_usage_config import TokenUsageConfig
from deerflow.tools.builtins.task_tool import _task_result_command

_ACCOUNTING_MIDDLEWARE_TYPES = (TokenBudgetMiddleware, TokenUsageMiddleware, CompletedSubagentUsageMiddleware)


class _ToolCallingModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@pytest.mark.asyncio
@pytest.mark.parametrize("async_graph", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize(
    ("child_tokens", "usage_enabled"),
    [(200, True), (500, True), (500, False)],
    ids=["below-budget", "last-batch-exceeds-budget", "usage-disabled"],
)
async def test_lead_budget_counts_last_subagent_batch_across_same_run_continuation(async_graph, child_tokens, usage_enabled):
    app_config = AppConfig(
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        memory=MemoryConfig(enabled=False),
        summarization=SummarizationConfig(enabled=False),
        token_budget=TokenBudgetConfig(enabled=True, max_tokens=1000),
        token_usage=TokenUsageConfig(enabled=usage_enabled),
    )
    assembled = build_middlewares(
        {"configurable": {"subagent_enabled": True}},
        model_name=None,
        app_config=app_config,
        memory_enabled=False,
        available_skills=set(),
    )
    # Preserve the production factory's accounting order; unrelated middleware
    # and live child model execution are outside this offline regression.
    accounting = [middleware for middleware in assembled if isinstance(middleware, _ACCOUNTING_MIDDLEWARE_TYPES)]
    budget = next(middleware for middleware in accounting if isinstance(middleware, TokenBudgetMiddleware))

    @tool("task")
    def completed_task(tool_call_id: Annotated[str, InjectedToolCallId]):
        """Return controlled terminal usage through the production serializer."""
        return _task_result_command(
            tool_call_id=tool_call_id,
            status="completed",
            result="Completed synthetic task.",
            usage={"input_tokens": child_tokens, "output_tokens": 0, "total_tokens": child_tokens},
        )

    def response(message_id, content="", tool_calls=None):
        return AIMessage(
            id=message_id,
            content=content,
            tool_calls=tool_calls or [],
            usage_metadata={"input_tokens": 100, "output_tokens": 0, "total_tokens": 100},
        )

    graph = create_agent(
        model=_ToolCallingModel(
            responses=[
                response("dispatch", tool_calls=[{"name": "task", "id": f"child-{index}", "args": {}} for index in range(2)]),
                response("final", "Completed answer."),
                response("continuation", "Continued answer."),
                response("new-run", "New answer."),
            ]
        ),
        tools=[completed_task],
        middleware=accounting,
        state_schema=ThreadState,
        context_schema=dict,
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "budget-thread"}}

    async def invoke(text, run_id):
        arguments = {"config": config, "context": {"thread_id": "budget-thread", "run_id": run_id}}
        inputs = {"messages": [HumanMessage(content=text)]}
        return await graph.ainvoke(inputs, **arguments) if async_graph else graph.invoke(inputs, **arguments)

    expected = 200 + (2 * child_tokens if usage_enabled else 0)
    first = await invoke("Complete two tasks.", "run-1")
    assert budget._cumulative_usage["run-1"].total == expected
    assert ("TOKEN BUDGET EXCEEDED" in first["messages"][-1].content) == (expected >= 1000)

    # Rebuilding the seen-message baseline must neither discard the last child
    # batch nor count checkpointed usage a second time.
    await invoke("Continue within the same run.", "run-1")
    assert budget._cumulative_usage["run-1"].total == expected + 100
    assert budget.consume_stop_reason("run-1") == ("token_capped" if expected >= 1000 else None)

    await invoke("Start another user run.", "run-2")
    assert budget._cumulative_usage["run-2"].total == 100
    assert budget.consume_stop_reason("run-2") is None


def test_disabled_budget_preserves_attribution_after_subagent_call_limit():
    """Default tracking must describe the calls retained by the real limit."""
    app_config = AppConfig(
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        memory=MemoryConfig(enabled=False),
        summarization=SummarizationConfig(enabled=False),
        token_budget=TokenBudgetConfig(enabled=False),
    )
    assembled = build_middlewares(
        {"configurable": {"subagent_enabled": True, "max_concurrent_subagents": 1}},
        model_name=None,
        app_config=app_config,
        memory_enabled=False,
        available_skills=set(),
    )
    middlewares = [middleware for middleware in assembled if isinstance(middleware, (SubagentLimitMiddleware, TokenUsageMiddleware))]
    executed = []

    @tool("task")
    def completed_task(description: str) -> str:
        """Record the child calls actually executed after limiting."""
        executed.append(description)
        return "Completed."

    dispatch = AIMessage(id="dispatch", content="", tool_calls=[{"name": "task", "id": f"child-{index}", "args": {"description": str(index)}} for index in range(3)])
    graph = create_agent(
        model=_ToolCallingModel(responses=[dispatch, AIMessage(content="Done.")]),
        tools=[completed_task],
        middleware=middlewares,
        state_schema=ThreadState,
        context_schema=dict,
    )
    result = graph.invoke({"messages": [HumanMessage(content="Complete tasks.")]}, context={"run_id": "limited-run"})
    recorded_dispatch = next(message for message in result["messages"] if message.id == "dispatch")
    assert executed == ["0"]
    assert recorded_dispatch.additional_kwargs[TOKEN_USAGE_ATTRIBUTION_KEY]["tool_call_ids"] == ["child-0"]


@pytest.mark.asyncio
@pytest.mark.parametrize("async_graph", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("guard", ["concurrent", "total", "budget", "loop"])
async def test_enabled_budget_attribution_matches_calls_retained_by_guards(async_graph, guard):
    """Enabled budgeting must preserve attribution after actual call guards."""
    app_config = AppConfig(
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        memory=MemoryConfig(enabled=False),
        summarization=SummarizationConfig(enabled=False),
        token_budget=TokenBudgetConfig(enabled=True, max_tokens=1000 if guard == "budget" else 10000),
        loop_detection=LoopDetectionConfig(warn_threshold=1 if guard == "loop" else 100, hard_limit=1 if guard == "loop" else 100),
    )
    assembled = build_middlewares(
        {"configurable": {"subagent_enabled": True, "max_concurrent_subagents": 1, "max_total_subagents": 1}},
        model_name=None,
        app_config=app_config,
        memory_enabled=False,
        available_skills=set(),
    )
    guard_classes = _ACCOUNTING_MIDDLEWARE_TYPES + (SubagentLimitMiddleware, LoopDetectionMiddleware)
    middlewares = [middleware for middleware in assembled if isinstance(middleware, guard_classes)]
    executed = []

    @tool("task")
    def completed_task(description: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> str:
        """Record the task calls that survive the production guards."""
        executed.append(tool_call_id)
        return "Completed."

    tokens = 1000 if guard == "budget" else 100
    dispatch = AIMessage(
        id="dispatch",
        content="",
        tool_calls=[{"name": "task", "id": f"child-{index}", "args": {"description": str(index)}} for index in range(3)],
        usage_metadata={"input_tokens": tokens, "output_tokens": 0, "total_tokens": tokens},
    )
    graph = create_agent(
        model=_ToolCallingModel(responses=[dispatch, AIMessage(content="Done.")]),
        tools=[completed_task],
        middleware=middlewares,
        state_schema=ThreadState,
        context_schema=dict,
    )
    context = {"run_id": "guarded-run", "thread_id": "guarded-thread"}
    inputs = {"messages": [HumanMessage(content="Complete tasks.")]}
    if guard == "total":
        inputs["delegations"] = [
            {
                "id": "prior-child",
                "run_id": "guarded-run",
                "description": "Prior completed task.",
                "subagent_type": "general-purpose",
                "status": "completed",
                "created_at": "2026-01-01T00:00:00Z",
            }
        ]
    result = await graph.ainvoke(inputs, context=context) if async_graph else graph.invoke(inputs, context=context)
    recorded_dispatch = next(message for message in result["messages"] if message.id == "dispatch")
    expected_calls = ["child-0"] if guard == "concurrent" else []
    assert executed == expected_calls
    assert [call["id"] for call in recorded_dispatch.tool_calls] == expected_calls
    attribution = recorded_dispatch.additional_kwargs[TOKEN_USAGE_ATTRIBUTION_KEY]
    assert attribution["tool_call_ids"] == expected_calls
    assert [action["tool_call_id"] for action in attribution["actions"]] == expected_calls
    assert attribution["shared_attribution"] is False
