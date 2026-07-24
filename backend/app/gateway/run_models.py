"""Shared request models for the LangGraph-compatible run boundary."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator
from pydantic_core import PydanticCustomError

from deerflow.runtime.stream_modes import RunStreamMode, UnsupportedStreamModeError, normalize_stream_modes


class RunCreateRequest(BaseModel):
    """Validated run request used by both HTTP and internal launch paths."""

    model_config = ConfigDict(extra="forbid")

    assistant_id: str | None = Field(default=None, description="Agent / assistant to use")
    input: dict[str, Any] | None = Field(default=None, description="Graph input (e.g. {messages: [...]})")
    command: dict[str, Any] | None = Field(default=None, description="LangGraph Command")
    metadata: dict[str, Any] | None = Field(default=None, description="Run metadata")
    config: dict[str, Any] | None = Field(default=None, description="RunnableConfig overrides")
    context: dict[str, Any] | None = Field(default=None, description="DeerFlow context overrides (model_name, thinking_enabled, etc.)")
    webhook: None = Field(default=None, description="Compatibility placeholder; completion callbacks are not supported")
    checkpoint_id: str | None = Field(default=None, description="Resume from checkpoint")
    checkpoint: dict[str, Any] | None = Field(default=None, description="Full checkpoint object")
    interrupt_before: list[str] | Literal["*"] | None = Field(default=None, description="Nodes to interrupt before")
    interrupt_after: list[str] | Literal["*"] | None = Field(default=None, description="Nodes to interrupt after")
    stream_mode: list[RunStreamMode] | RunStreamMode | None = Field(default=None, description="Supported stream mode(s)")
    stream_subgraphs: bool = Field(default=False, description="Include subgraph events")
    stream_resumable: None = Field(default=None, description="Compatibility placeholder; resumable SSE is not supported")
    on_disconnect: Literal["cancel", "continue"] = Field(default="cancel", description="Behaviour on SSE disconnect")
    on_completion: None = Field(default=None, description="Compatibility placeholder; completion behavior is not supported")
    multitask_strategy: Literal["reject", "rollback", "interrupt"] = Field(default="reject", description="Concurrency strategy")
    after_seconds: None = Field(default=None, description="Compatibility placeholder; delayed execution is not supported")
    if_not_exists: Literal["create"] = Field(default="create", description="Compatibility default; missing threads are created")
    feedback_keys: None = Field(default=None, description="Compatibility placeholder; feedback key collection is not supported")

    @field_validator(
        "webhook",
        "stream_resumable",
        "on_completion",
        "multitask_strategy",
        "after_seconds",
        "if_not_exists",
        "feedback_keys",
        mode="before",
    )
    @classmethod
    def reject_unsupported_run_options(cls, value: Any, info: ValidationInfo) -> Any:
        if info.field_name in {"multitask_strategy", "if_not_exists"} and not isinstance(value, str):
            return value

        supported_defaults = {
            "webhook": None,
            "stream_resumable": None,
            "on_completion": None,
            "multitask_strategy": {"reject", "rollback", "interrupt"},
            "after_seconds": None,
            "if_not_exists": "create",
            "feedback_keys": None,
        }
        supported = supported_defaults[info.field_name]
        if isinstance(supported, set):
            is_supported = isinstance(value, str) and value in supported
        else:
            is_supported = value == supported
        if not is_supported:
            raise PydanticCustomError(
                "unsupported_run_option",
                "Run option '{option}' is not supported by DeerFlow",
                {"option": info.field_name},
            )
        return value

    @field_validator("stream_mode", mode="before")
    @classmethod
    def reject_unsupported_stream_modes(cls, value: Any) -> Any:
        if value is None:
            return value
        if not isinstance(value, str) and (not isinstance(value, list) or not all(isinstance(mode, str) for mode in value)):
            return value
        try:
            normalize_stream_modes(value)
        except UnsupportedStreamModeError as exc:
            modes = ", ".join(exc.modes)
            raise PydanticCustomError(
                "unsupported_stream_mode",
                "Unsupported stream mode(s): {modes}",
                {"modes": modes},
            ) from exc
        return value
