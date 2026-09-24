from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RequestAdmissionConfig(BaseModel):
    """Optional per-process pacing of model requests, shared by quota group."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    requests_per_minute: int = Field(gt=0, strict=True)
    group: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    max_wait_seconds: float = Field(default=300, gt=0, allow_inf_nan=False)
    max_queue_size: int = Field(default=256, gt=0, strict=True)


_EFFORT_TOKEN_PATTERN = r"^[A-Za-z0-9_.-]{1,32}$"
# Dotted identifiers only: the factory writes the effort value at this path by
# creating nested dicts, so it must never be able to address arbitrary keys.
_EFFORT_PATH_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$"
# Single-segment paths that would replace a whole dict-valued provider setting
# with the effort string (``path: extra_body`` would clobber ``extra_body``).
_EFFORT_PATH_RESERVED_ROOTS = frozenset({"extra_body", "thinking", "model_kwargs", "default_headers", "default_query"})


def _lookup_dotted(mapping: object, path: str) -> object | None:
    """Return the value at a dotted *path* inside nested dicts, or ``None``."""
    cursor = mapping
    for part in path.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            return None
        cursor = cursor[part]
    return cursor


class ReasoningEffortCapabilities(BaseModel):
    """Effort vocabulary one model accepts (issue #5073).

    ``values`` is the provider's own vocabulary in display order. ``aliases``
    map DeerFlow's generic values (``minimal``/``low``/``medium``/``high``) onto
    that vocabulary so a UI preset or a per-agent default never reaches the
    provider unmapped. ``path`` is where the value is serialized: the default
    ``reasoning_effort`` constructor keyword, or a dotted path such as
    ``extra_body.thinking.effort`` for providers that nest it.
    """

    model_config = ConfigDict(extra="forbid")
    values: list[str] = Field(..., min_length=1, description="Accepted effort values, in display order")
    default: str | None = Field(default=None, description="Effort used when the caller does not choose one")
    aliases: dict[str, str] = Field(default_factory=dict, description="Generic DeerFlow value -> provider value")
    path: str = Field(default="reasoning_effort", pattern=_EFFORT_PATH_PATTERN, description="Dotted model-settings path the value is written to")

    @field_validator("path")
    @classmethod
    def _path_must_not_shadow_a_container(cls, path: str) -> str:
        if path in _EFFORT_PATH_RESERVED_ROOTS:
            raise ValueError(f"effort path {path!r} would replace the whole {path!r} mapping; address a key inside it instead (e.g. {path}.effort)")
        return path

    @field_validator("values")
    @classmethod
    def _values_are_unique_tokens(cls, values: list[str]) -> list[str]:
        import re

        for value in values:
            if not re.fullmatch(_EFFORT_TOKEN_PATTERN, value):
                raise ValueError(f"effort value {value!r} is not a valid token")
        if len(set(values)) != len(values):
            raise ValueError("effort values must be unique")
        return values

    @model_validator(mode="after")
    def _default_and_aliases_point_at_values(self) -> "ReasoningEffortCapabilities":
        if self.default is not None and self.default not in self.values:
            raise ValueError(f"effort default {self.default!r} is not one of the declared values {self.values}")
        for generic, provider in self.aliases.items():
            if generic in self.values:
                raise ValueError(f"effort alias {generic!r} is already a declared value; aliases may only map generic values onto the provider vocabulary")
            if provider not in self.values:
                raise ValueError(f"effort alias {generic!r} -> {provider!r} does not target a declared value")
        return self


class ReasoningCapabilities(BaseModel):
    """Declarative reasoning contract for one model (issue #5073).

    Declared beside the legacy ``supports_thinking`` / ``supports_reasoning_effort``
    booleans; when present, those booleans are derived from it. See
    ``deerflow.models.reasoning`` for the normalized runtime view.
    """

    model_config = ConfigDict(extra="forbid")
    thinking: Literal["unsupported", "optional", "required"] = Field(default="unsupported", description="Whether thinking can be toggled, is always on, or is unavailable")
    on_disable_request: Literal["keep_enabled", "reject"] = Field(
        default="keep_enabled",
        description="Required-thinking models only: silently keep thinking on when a caller asks for it to be off, or fail the request",
    )
    dialect: Literal["auto", "openai_extra_body", "anthropic", "vllm_chat_template", "ollama", "none"] = Field(
        default="auto",
        description="Payload dialect used to serialize thinking on/off; auto infers it from when_thinking_enabled",
    )
    history: Literal["preserve", "clear"] | None = Field(default=None, description="Whether reasoning history must be preserved or cleared across turns")
    effort: ReasoningEffortCapabilities | None = Field(default=None, description="Effort control; omitted means the model exposes none")

    @model_validator(mode="after")
    def _reject_only_applies_to_required_thinking(self) -> "ReasoningCapabilities":
        if self.on_disable_request == "reject" and self.thinking != "required":
            raise ValueError("on_disable_request: reject is only meaningful when thinking is required")
        return self


class ModelConfig(BaseModel):
    """Config section for a model"""

    name: str = Field(..., description="Unique name for the model")
    request_admission: RequestAdmissionConfig | None = Field(default=None, description="Opt-in process-local RPM pacing. Changing an active group's policy requires a process restart.")
    display_name: str | None = Field(..., default_factory=lambda: None, description="Display name for the model")
    description: str | None = Field(..., default_factory=lambda: None, description="Description for the model")
    use: str = Field(
        ...,
        description="Class path of the model provider(e.g. langchain_openai.ChatOpenAI)",
    )
    model: str = Field(..., description="Model name")
    model_config = ConfigDict(extra="allow")
    use_responses_api: bool | None = Field(
        default=None,
        description="Whether to route OpenAI ChatOpenAI calls through the /v1/responses API",
    )
    output_version: str | None = Field(
        default=None,
        description="Structured output version for OpenAI responses content, e.g. responses/v1",
    )
    supports_thinking: bool = Field(default_factory=lambda: False, description="Whether the model supports thinking")
    supports_reasoning_effort: bool = Field(default_factory=lambda: False, description="Whether the model supports reasoning effort")
    reasoning: ReasoningCapabilities | bool | str | None = Field(
        default=None,
        description=(
            "Declarative reasoning capability contract (thinking availability, accepted effort values, "
            "payload dialect, reasoning-history requirement). A boolean or a string preserves the legacy native "
            "provider setting (e.g. ChatOllama reasoning: true, or reasoning: high for gpt-oss levels); "
            "only a contract derives supports_thinking / supports_reasoning_effort."
        ),
    )
    when_thinking_enabled: dict | None = Field(
        default_factory=lambda: None,
        description="Extra settings to be passed to the model when thinking is enabled",
    )
    when_thinking_disabled: dict | None = Field(
        default_factory=lambda: None,
        description="Extra settings to be passed to the model when thinking is disabled",
    )
    supports_vision: bool = Field(default_factory=lambda: False, description="Whether the model supports vision/image inputs")
    context_window: int | None = Field(
        default=None,
        gt=0,
        description=(
            "Positive total context window size in tokens (prompt + completion). Used to compute the real-time "
            "context usage percentage displayed in the chat UI, and attached to the model's langchain profile "
            "(`max_input_tokens`) so fraction-based summarization triggers can resolve their thresholds for "
            "third-party OpenAI-compatible models that carry no built-in profile. Distinct from `max_tokens`, "
            "which is the per-call output cap passed to the provider. Leave unset if unknown; the UI will hide "
            "the percentage and fraction summarization clauses will degrade with a warning."
        ),
    )
    stream_chunk_timeout: float | None = Field(
        default=None,
        description=(
            "Maximum seconds to wait between successive streaming chunks before "
            "langchain-openai raises StreamChunkTimeoutError. None means use the "
            "factory default (240s for OpenAI-compatible clients). Tune higher for "
            "reasoning models with long thinking pauses; lower for latency-sensitive "
            "interactive endpoints. Has no effect on non-OpenAI-compatible providers."
        ),
    )
    thinking: dict | None = Field(
        default_factory=lambda: None,
        description=(
            "Thinking settings for the model. If provided, these settings will be passed to the model when thinking is enabled. "
            "This is a shortcut for `when_thinking_enabled` and will be merged with `when_thinking_enabled` if both are provided."
        ),
    )

    @model_validator(mode="after")
    def _validate_reasoning_contract(self) -> "ModelConfig":
        """Fail early on combinations the contract cannot honor, then project the legacy booleans."""
        contract = self.reasoning
        if not isinstance(contract, ReasoningCapabilities):
            return self

        if contract.thinking == "required" and self.when_thinking_disabled is not None:
            raise ValueError("reasoning.thinking: required cannot be combined with when_thinking_disabled")
        if contract.thinking == "unsupported":
            if self.when_thinking_enabled is not None:
                raise ValueError("reasoning.thinking: unsupported cannot be combined with when_thinking_enabled")
            if self.thinking is not None:
                raise ValueError("reasoning.thinking: unsupported cannot be combined with the thinking shortcut")

        derived_thinking = contract.thinking != "unsupported"
        derived_effort = contract.effort is not None
        if "supports_thinking" in self.model_fields_set and self.supports_thinking != derived_thinking:
            raise ValueError(f"supports_thinking={self.supports_thinking} contradicts reasoning.thinking: {contract.thinking}; drop the legacy flag or fix the contract")
        if "supports_reasoning_effort" in self.model_fields_set and self.supports_reasoning_effort != derived_effort:
            raise ValueError(f"supports_reasoning_effort={self.supports_reasoning_effort} contradicts the reasoning.effort contract; drop the legacy flag or fix the contract")

        # Operator-supplied effort values — the profile itself and the thinking
        # templates — are forwarded when the caller chooses nothing, so they
        # must satisfy the contract too; otherwise an out-of-vocabulary value
        # could still reach the provider despite the contract.
        effort_path = contract.effort.path if contract.effort is not None else "reasoning_effort"
        sources: list[tuple[str, object]] = [
            ("profile-level", self.model_extra or {}),
            ("when_thinking_enabled", self.when_thinking_enabled),
            ("when_thinking_disabled", self.when_thinking_disabled),
            ("thinking", {"thinking": self.thinking} if self.thinking is not None else None),
        ]
        for source, mapping in sources:
            if mapping is None:
                continue
            # The thinking shortcut becomes the nested ``thinking`` payload;
            # the other sources are merged at the constructor-settings root.
            generic_path = "thinking.reasoning_effort" if source == "thinking" else "reasoning_effort"
            generic_mapping = self.thinking if source == "thinking" else mapping
            if effort_path != generic_path and isinstance(generic_mapping, dict) and "reasoning_effort" in generic_mapping:
                if contract.effort is None:
                    raise ValueError(f"{source} reasoning_effort is set, but the reasoning contract declares no effort control")
                raise ValueError(f"{source} reasoning_effort conflicts with reasoning.effort.path={effort_path!r}; remove the legacy key")
            value = _lookup_dotted(mapping, effort_path)
            if value is None:
                continue
            if contract.effort is None:
                raise ValueError(f"{source} {effort_path} is set, but the reasoning contract declares no effort control")
            if value not in contract.effort.values:
                raise ValueError(f"{source} {effort_path} {value!r} is not one of the contract's accepted values {contract.effort.values}")

        # Deprecation-window projection: readers that still consult the booleans
        # (wizard, older clients, the /api/models legacy fields) stay correct.
        self.supports_thinking = derived_thinking
        self.supports_reasoning_effort = derived_effort
        return self
