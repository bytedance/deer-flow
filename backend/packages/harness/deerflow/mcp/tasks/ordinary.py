"""Driver for ordinary MCP submit/status/cancel tool contracts."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from deerflow.constants import MCP_TASK_REMOTE_ID_MAX_LENGTH
from deerflow.mcp.tasks.models import (
    TaskReference,
    TaskSnapshot,
    TaskStatus,
    TaskSubmission,
    TaskSubmitRequest,
)

ORDINARY_MCP_TASK_DRIVER = "ordinary-tools"
_MAX_TOOL_ERROR_DETAIL_CHARS = 500


class McpTaskProtocolError(RuntimeError):
    """A remote task tool returned a deterministic contract violation."""


class McpTaskToolCaller(Protocol):
    async def call_tool(
        self,
        *,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        user_id: str,
        thread_id: str,
        request_scoped_headers: bool = False,
    ) -> Any: ...


class _SubmitPayload(BaseModel):
    task_id: str = Field(min_length=1)
    status: Literal["running"]
    model_config = ConfigDict(extra="ignore")


class _ResultArtifact(BaseModel):
    uri: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    model_config = ConfigDict(extra="ignore")


class _StatusPayload(BaseModel):
    task_id: str = Field(min_length=1, max_length=MCP_TASK_REMOTE_ID_MAX_LENGTH)
    status: Literal["running", "input_required", "completed", "failed", "cancelled"]
    result: Any | None = None
    result_artifact: _ResultArtifact | None = None
    error: str | None = None
    error_code: str | None = None
    input_required: dict[str, Any] | None = None
    poll_after_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    model_config = ConfigDict(extra="ignore")


class _CancelPayload(BaseModel):
    task_id: str = Field(min_length=1, max_length=MCP_TASK_REMOTE_ID_MAX_LENGTH)
    status: Literal["cancelled", "completed", "failed"]
    result: Any | None = None
    result_artifact: _ResultArtifact | None = None
    error: str | None = None
    model_config = ConfigDict(extra="ignore")


_REMOTE_TO_LOCAL_STATUS = {
    "running": TaskStatus.WORKING,
    "input_required": TaskStatus.INPUT_REQUIRED,
    "completed": TaskStatus.COMPLETED,
    "failed": TaskStatus.FAILED,
    "cancelled": TaskStatus.CANCELLED,
}


def _tool_name(data: dict[str, Any], role: str) -> str:
    value = data.get(role)
    if not isinstance(value, str) or not value:
        raise McpTaskProtocolError(f"Task driver_data is missing required {role!r}")
    return value


def _first_error_text(call_result: Any) -> str | None:
    content = getattr(call_result, "content", None)
    if not isinstance(content, (list, tuple)):
        return None
    for item in content:
        if isinstance(item, dict):
            if item.get("type") != "text":
                continue
            text = item.get("text")
        else:
            if getattr(item, "type", None) != "text":
                continue
            text = getattr(item, "text", None)
        if isinstance(text, str) and (text := text.strip()):
            return text[:_MAX_TOOL_ERROR_DETAIL_CHARS]
    return None


def _structured_content(call_result: Any, *, tool_name: str) -> Any:
    if bool(getattr(call_result, "isError", False)):
        message = f"MCP task tool {tool_name!r} returned an error"
        if detail := _first_error_text(call_result):
            message = f"{message}: {detail}"
        raise RuntimeError(message)
    value = getattr(call_result, "structuredContent", None)
    if value is None:
        raise McpTaskProtocolError(f"MCP task tool {tool_name!r} must return structuredContent; text content is not parsed")
    return value


def _parse(model_type: type[BaseModel], value: Any, *, tool_name: str) -> BaseModel:
    try:
        return model_type.model_validate(value)
    except ValidationError as exc:
        raise McpTaskProtocolError(f"Invalid structuredContent from MCP task tool {tool_name!r}: {exc}") from exc


def _artifact_dict(artifact: _ResultArtifact | None) -> dict[str, str] | None:
    return artifact.model_dump() if artifact is not None else None


def _snapshot_from_status(payload: _StatusPayload | _CancelPayload) -> TaskSnapshot:
    input_required = getattr(payload, "input_required", None)
    if getattr(payload, "error_code", None) == "task_not_found":
        return TaskSnapshot(
            status=TaskStatus.FAILED,
            error=payload.error or "Remote MCP task was not found",
        )
    if payload.status == "input_required" and input_required is None:
        raise McpTaskProtocolError("Invalid structuredContent: input_required status requires input_required")
    return TaskSnapshot(
        status=_REMOTE_TO_LOCAL_STATUS[payload.status],
        result=payload.result,
        result_artifact=_artifact_dict(payload.result_artifact),
        error=payload.error,
        input_required=input_required,
        poll_after_seconds=getattr(payload, "poll_after_seconds", None),
    )


class OrdinaryMcpTaskDriver:
    """Bind a configured ordinary three-tool contract to normalized task state."""

    def __init__(self, caller: McpTaskToolCaller) -> None:
        self._caller = caller

    async def submit(self, request: TaskSubmitRequest) -> TaskSubmission:
        tool_name = _tool_name(request.driver_data, "submit_tool")
        result = await self._caller.call_tool(
            server_name=request.server_name,
            tool_name=tool_name,
            arguments=request.arguments,
            user_id=request.user_id,
            thread_id=request.thread_id,
            # Submit alone is awaited inside the Agent run, so it is the one
            # durable-task call that can carry the run's request-scoped
            # credentials; status and cancel run after that run ended.
            request_scoped_headers=True,
        )
        payload = _parse(
            _SubmitPayload,
            _structured_content(result, tool_name=tool_name),
            tool_name=tool_name,
        )
        assert isinstance(payload, _SubmitPayload)
        return TaskSubmission(
            remote_task_id=payload.task_id,
            snapshot=TaskSnapshot(status=TaskStatus.SUBMITTED),
            driver_data=dict(request.driver_data),
        )

    async def get_status(self, task: TaskReference) -> TaskSnapshot:
        tool_name = _tool_name(task.driver_data, "status_tool")
        result = await self._caller.call_tool(
            server_name=task.server_name,
            tool_name=tool_name,
            arguments={"task_id": task.remote_task_id},
            user_id=task.user_id,
            thread_id=task.thread_id,
        )
        payload = _parse(
            _StatusPayload,
            _structured_content(result, tool_name=tool_name),
            tool_name=tool_name,
        )
        assert isinstance(payload, _StatusPayload)
        self._require_matching_task_id(payload.task_id, task.remote_task_id)
        return _snapshot_from_status(payload)

    async def cancel(self, task: TaskReference) -> TaskSnapshot:
        tool_name = _tool_name(task.driver_data, "cancel_tool")
        result = await self._caller.call_tool(
            server_name=task.server_name,
            tool_name=tool_name,
            arguments={"task_id": task.remote_task_id},
            user_id=task.user_id,
            thread_id=task.thread_id,
        )
        payload = _parse(
            _CancelPayload,
            _structured_content(result, tool_name=tool_name),
            tool_name=tool_name,
        )
        assert isinstance(payload, _CancelPayload)
        self._require_matching_task_id(payload.task_id, task.remote_task_id)
        return _snapshot_from_status(payload)

    @staticmethod
    def _require_matching_task_id(actual: str, expected: str) -> None:
        if actual != expected:
            raise McpTaskProtocolError(f"MCP task response task_id does not match the persisted remote task: expected {expected!r}, got {actual!r}")
