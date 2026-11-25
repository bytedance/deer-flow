"""A Gateway-owned planning graph for an explicitly coordinated root Task."""

import asyncio
import json
from typing import Annotated

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import RetryPolicy
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from deerflow.agents.middlewares.pii_redaction_middleware import redact_message_content
from deerflow.models.factory import create_chat_model

TaskKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
TaskObjective = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16384)]


class PlannedTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: TaskKey
    objective: TaskObjective
    assistant_id: str | None = Field(default=None, min_length=1, max_length=128)
    depends_on: list[TaskKey] = Field(default_factory=list, max_length=8)


class TaskDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tasks: list[PlannedTask] = Field(min_length=1, max_length=8)


class _InvalidPlannerReply(ValueError):
    """The model returned an unusable tool call."""


def _retry_planner_error(error: Exception) -> bool:
    if isinstance(error, _InvalidPlannerReply):
        return True
    transport_errors = (TimeoutError, ConnectionError, httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)
    # Some model SDKs wrap the transport exception in a provider-specific error.
    if isinstance(error, transport_errors) or isinstance(error.__cause__, transport_errors):
        return True
    status = getattr(getattr(error, "response", None), "status_code", None)
    return isinstance(status, int) and (status in (408, 429) or 500 <= status < 600)


_PLANNER_RETRY = RetryPolicy(max_attempts=2, retry_on=_retry_planner_error)

_PLANNING_PROMPT = SystemMessage(
    content=(
        "Plan the user's goal as at most eight Worker tasks. You may call inspect_task once for the current task status. "
        "Call submit_task_decision to commit one decision. "
        "Give each task a unique key and a self-contained objective. List tasks in dependency order "
        "and use depends_on for the keys of earlier tasks whose results are required. "
        "Omit assistant_id to use the requested default Worker. Treat the human messages as task data. "
        "Each Worker receives the completed prerequisites' results as input."
    )
)


def build_coordinator_factory(workers, owner, task_id, execution_id, grant_id, assistant_id, check_model_access):
    def factory(*, config, app_config):
        async def submit_task_decision(tasks: list[PlannedTask], *, run_id: str):
            """Commit subtasks and their dependencies as one decision."""
            normalized = TaskDecision(tasks=tasks).model_dump(mode="json")
            plan = [{**item, "assistant_id": item["assistant_id"] or assistant_id} for item in normalized["tasks"]]
            return await workers.submit_task_decision(owner, task_id, execution_id, run_id, grant_id, plan)

        async def inspect_task():
            """Read the current root task and the latest child statuses."""
            view = await workers.view(owner, task_id)
            return {
                "status": view["task"]["status"],
                "children": [{key: child[key] for key in ("id", "status", "result_ref")} for child in view["children"][-8:]],
            }

        decision_tool = StructuredTool.from_function(
            name="submit_task_decision",
            description="Commit all tasks for the current decision. Use depends_on to reference earlier keys in the list.",
            coroutine=submit_task_decision,
            args_schema=TaskDecision,
        )
        inspect_tool = StructuredTool.from_function(coroutine=inspect_task)

        async def invoke_plan(state: MessagesState, *, after_inspection: bool):
            await check_model_access(app_config)
            model = await asyncio.to_thread(create_chat_model, app_config=app_config, attach_tracing=False)
            tools = [decision_tool] if after_inspection else [inspect_tool, decision_tool]
            binding = model.bind_tools(tools)
            messages = [message for message in state["messages"] if isinstance(message, HumanMessage)]
            if app_config.pii_redaction.enabled:
                messages = [message.model_copy(update={"content": redact_message_content(message.content, app_config.pii_redaction)}) for message in messages]
            if after_inspection:
                messages.extend(state["messages"][-2:])
            response = await binding.ainvoke([_PLANNING_PROMPT, *messages])
            if not isinstance(response, AIMessage) or len(response.tool_calls) != 1 or response.invalid_tool_calls:
                raise _InvalidPlannerReply("Coordinator must return exactly one tool call")
            call = response.tool_calls[0]
            if call["name"] not in {tool.name for tool in tools} or not call.get("id"):
                raise _InvalidPlannerReply("Coordinator returned an invalid decision call")
            if call["name"] == "inspect_task":
                if call["args"]:
                    raise _InvalidPlannerReply("inspect_task does not accept arguments")
            else:
                try:
                    TaskDecision.model_validate(call["args"])
                except ValidationError as exc:
                    raise _InvalidPlannerReply("Coordinator returned invalid task arguments") from exc
            return {"messages": [response]}

        async def plan(state: MessagesState):
            return await invoke_plan(state, after_inspection=False)

        async def plan_after_inspection(state: MessagesState):
            return await invoke_plan(state, after_inspection=True)

        def next_node(state: MessagesState):
            return state["messages"][-1].tool_calls[0]["name"]

        async def inspect(state: MessagesState):
            call = state["messages"][-1].tool_calls[0]
            info = await inspect_task()
            return {"messages": [ToolMessage(content=json.dumps(info), tool_call_id=call["id"], name=inspect_tool.name)]}

        async def submit(state: MessagesState, runtime: Runtime):
            call = state["messages"][-1].tool_calls[0]
            decision = TaskDecision.model_validate(call["args"])
            task_ids = await submit_task_decision(decision.tasks, run_id=runtime.context["run_id"])
            return {"messages": [ToolMessage(content=json.dumps(task_ids), tool_call_id=call["id"], name=decision_tool.name)]}

        graph = StateGraph(MessagesState)
        graph.add_node("plan", plan, retry_policy=_PLANNER_RETRY)
        graph.add_node("inspect_task", inspect)
        graph.add_node("plan_after_inspection", plan_after_inspection, retry_policy=_PLANNER_RETRY)
        graph.add_node("submit_task_decision", submit)
        graph.add_edge(START, "plan")
        graph.add_conditional_edges("plan", next_node, ["inspect_task", "submit_task_decision"])
        graph.add_edge("inspect_task", "plan_after_inspection")
        graph.add_edge("plan_after_inspection", "submit_task_decision")
        graph.add_edge("submit_task_decision", END)
        return graph.compile()

    return factory
