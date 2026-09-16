"""Shared request models for the LangGraph-compatible run boundary."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, ValidationInfo, field_validator, model_validator
from pydantic_core import PydanticCustomError

from deerflow.runtime.stream_modes import RunStreamMode, UnsupportedStreamModeError, normalize_stream_modes
from deerflow.utils.thread_id import validate_thread_id

# Upper bound on explicit conversation references per run; ``/api/features``
# reports it so a UI can cap its selection to the same number.
MAX_CONVERSATION_REFERENCES = 3

# One reference as the field accepts it; the conflict guard probes with the
# same annotation so its acceptance set is exactly the field's, now and after
# a pydantic upgrade (lax mode also coerces tuples, sets, generators, ...).
ConversationReference = Annotated[str, Field(strict=True, min_length=1, max_length=2048)]
_REFERENCES_ADAPTER = TypeAdapter(list[ConversationReference])


class RunCreateRequest(BaseModel):
    """Validated run request used by both HTTP and internal launch paths."""

    model_config = ConfigDict(extra="forbid")

    assistant_id: str | None = Field(default=None, description="Agent / assistant to use")
    input: dict[str, Any] | None = Field(default=None, description="Graph input (e.g. {messages: [...]})")
    command: dict[str, Any] | None = Field(default=None, description="LangGraph Command")
    metadata: dict[str, Any] | None = Field(default=None, description="Run metadata")
    config: dict[str, Any] | None = Field(default=None, description="RunnableConfig overrides")
    context: dict[str, Any] | None = Field(default=None, description="DeerFlow context overrides (model_name, thinking_enabled, etc.)")
    conversation_references: list[ConversationReference] = Field(
        default_factory=list,
        max_length=MAX_CONVERSATION_REFERENCES,
        description="Explicit thread IDs or same-origin chat URLs readable only during this run (opt-in read_conversation tool); SDK clients may send the same list as context.conversation_references",
    )
    webhook: None = Field(default=None, description="Compatibility placeholder; completion callbacks are not supported")
    checkpoint_id: str | None = Field(default=None, description="Resume from checkpoint")
    checkpoint: dict[str, Any] | None = Field(default=None, description="Full checkpoint object")
    interrupt_before: list[str] | Literal["*"] | None = Field(default=None, description="Nodes to interrupt before")
    interrupt_after: list[str] | Literal["*"] | None = Field(default=None, description="Nodes to interrupt after")
    stream_mode: list[RunStreamMode] | RunStreamMode | None = Field(default=None, description="Supported stream mode(s)")
    stream_subgraphs: bool = Field(default=False, description="Include subgraph events")
    stream_resumable: Literal[False] | None = Field(default=None, description="Compatibility placeholder; only the SDK's non-resumable default (null/false) is accepted")
    on_disconnect: Literal["cancel", "continue"] = Field(default="cancel", description="Behaviour on SSE disconnect")
    on_completion: None = Field(default=None, description="Compatibility placeholder; completion behavior is not supported")
    multitask_strategy: Literal["reject", "rollback", "interrupt"] = Field(default="reject", description="Concurrency strategy")
    after_seconds: None = Field(default=None, description="Compatibility placeholder; delayed execution is not supported")
    if_not_exists: Literal["create"] = Field(default="create", description="Compatibility default; missing threads are created")
    feedback_keys: None = Field(default=None, description="Compatibility placeholder; feedback key collection is not supported")

    @model_validator(mode="before")
    @classmethod
    def lift_context_conversation_references(cls, data: Any) -> Any:
        """Accept ``context.conversation_references`` as the same explicit grant.

        LangGraph SDK clients build a fixed run body and drop unknown top-level
        fields, so the web UI can only reach ``conversation_references`` through
        ``context``. The key is moved to the top level before field validation,
        so it keeps the same bounds and error locations, and it is removed from
        ``context`` so run-context merging never sees it. Sending both is an
        error rather than a silent merge.
        """
        if not isinstance(data, dict):
            return data
        context = data.get("context")
        if not isinstance(context, dict) or "conversation_references" not in context:
            return data
        references = context["conversation_references"]
        top_level = data.get("conversation_references")
        if isinstance(top_level, Iterator):
            # A one-shot iterator can be read only once. Materialise it so the
            # probe below and the field validate the same items, instead of the
            # field seeing an exhausted iterator that coerces to [].
            top_level = list(top_level)
            data = {**data, "conversation_references": top_level}
        lifted = {**data, "context": {key: value for key, value in context.items() if key != "conversation_references"}}
        if references is None:
            return lifted
        if top_level is not None:
            try:
                top_level = _REFERENCES_ADAPTER.validate_python(top_level)
            except ValidationError:
                # Let the field report its own error instead of a misleading conflict.
                return data
        if top_level:
            raise PydanticCustomError("conversation_references_conflict", "Pass conversation_references at the top level or in context, not both")
        lifted["conversation_references"] = references
        return lifted

    @model_validator(mode="after")
    def validate_configurable_thread_id(self) -> RunCreateRequest:
        """Validate the stateless-run thread selector inside RunnableConfig."""
        if not isinstance(self.config, dict):
            return self
        configurable = self.config.get("configurable")
        if not isinstance(configurable, dict) or "thread_id" not in configurable:
            return self
        thread_id = configurable["thread_id"]
        if thread_id is not None:
            validate_thread_id(thread_id)
        return self

    @field_validator(
        "webhook",
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

    @field_validator("stream_resumable", mode="before")
    @classmethod
    def reject_resumable_streams(cls, value: Any) -> Any:
        # LangGraph SDK clients always send this field (its default is ``False``, which the
        # payload's ``None`` filter keeps). ``False`` asks for the non-resumable stream
        # DeerFlow already serves, so only an explicit ``True`` requests the unsupported feature.
        if value is None or value is False:
            return value
        raise PydanticCustomError(
            "unsupported_run_option",
            "Run option '{option}' is not supported by DeerFlow",
            {"option": "stream_resumable"},
        )

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
