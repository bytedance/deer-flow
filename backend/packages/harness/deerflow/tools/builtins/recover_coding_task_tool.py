from collections.abc import Mapping, Sequence
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from deerflow.agents.human_input import read_human_input_response
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.task_graph.factory import create_task_graph
from deerflow.tools.types import Runtime

RETRY_OPTION_VALUE = "Retry failed task"
RECOVERY_CONTEXT_PREFIX = "coding_task_recovery:"


def _runtime_messages(runtime: Runtime) -> Sequence[BaseMessage]:
    state = runtime.state
    if isinstance(state, Mapping):
        messages = state.get("messages", [])
    else:
        messages = getattr(state, "messages", [])
    return messages if isinstance(messages, Sequence) and not isinstance(messages, (str, bytes)) else []


def _read_human_input_request(message: ToolMessage) -> Mapping[str, Any] | None:
    if message.name != "ask_clarification" or not isinstance(message.artifact, Mapping):
        return None
    payload = message.artifact.get("human_input")
    if not isinstance(payload, Mapping):
        return None
    if payload.get("kind") != "human_input_request" or payload.get("source") != "ask_clarification":
        return None
    return payload


def _request_offered_retry(payload: Mapping[str, Any], *, option_id: str) -> bool:
    options = payload.get("options")
    if not isinstance(options, list):
        return False
    return any(isinstance(option, Mapping) and option.get("id") == option_id and option.get("value") == RETRY_OPTION_VALUE for option in options)


def _has_matching_retry_approval(messages: Sequence[BaseMessage], coding_task_id: str) -> bool:
    requests: dict[str, Mapping[str, Any]] = {}
    expected_context = f"{RECOVERY_CONTEXT_PREFIX}{coding_task_id}"

    for message in messages:
        if isinstance(message, ToolMessage):
            payload = _read_human_input_request(message)
            if payload is not None and isinstance(payload.get("request_id"), str):
                requests[payload["request_id"]] = payload
            continue

        if not isinstance(message, HumanMessage):
            continue
        response = read_human_input_response(message.additional_kwargs)
        if response is None or response["source"] != "ask_clarification":
            continue
        if response["response_kind"] != "option" or response["value"] != RETRY_OPTION_VALUE:
            continue

        request = requests.get(response["request_id"])
        if request is None:
            continue
        if request.get("clarification_type") != "risk_confirmation" or request.get("context") != expected_context:
            continue
        if _request_offered_retry(request, option_id=response["option_id"]):
            return True

    return False


@tool("recover_coding_task", parse_docstring=True)
def recover_coding_task(coding_task_id: str, runtime: Runtime) -> str:
    """在用户明确确认后，把当前线程中的失败编码任务恢复为待执行。

    Args:
        coding_task_id: 需要恢复的失败任务 ID。必须与人工确认请求中的任务 ID 一致。
    """
    context = runtime.context or {}
    thread_id = context.get("thread_id")
    if thread_id is None:
        thread_id = runtime.config.get("configurable", {}).get("thread_id")
    if thread_id is None:
        raise ValueError("thread_id is required")

    # 不接受模型自行声明“已批准”，只读取消息历史中的结构化人工回复。
    if not _has_matching_retry_approval(_runtime_messages(runtime), coding_task_id):
        raise ValueError("matching retry approval is required")

    user_id = resolve_runtime_user_id(runtime)
    graph = create_task_graph(thread_id, user_id=user_id)
    task = graph.recover(coding_task_id)
    return f"Recovered coding task {task.id} to {task.status.value}"
