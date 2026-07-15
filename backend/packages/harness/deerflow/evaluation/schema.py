"""Pydantic schema for DeerFlow evaluation suites."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

StableId = Annotated[str, Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
MetricTag = Literal["task_success", "preference", "cross_thread", "isolation", "correction", "cost"]
VariantProfile = Literal["default", "baseline", "candidate", "custom"]


def _validate_workspace_relative_path(value: str) -> str:
    if not value or not value.strip():
        raise ValueError("path must be non-empty")
    normalized = value.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    if normalized.startswith("/") or any(part == ".." for part in parts):
        raise ValueError("path must be relative to the item workspace")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SuiteRequires(StrictModel):
    run_events_backend: Literal["persistent", "db", "jsonl", "any"] = "persistent"
    trace_export: Literal["disabled", "optional", "langsmith"] = "optional"
    required_capabilities: list[str] = Field(default_factory=list)


class Variant(StrictModel):
    id: StableId
    label: str | None = None
    profile: VariantProfile | None = None
    runtime: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def infer_profile(self) -> Variant:
        if self.profile is None:
            if self.id in {"baseline", "candidate", "default"}:
                self.profile = self.id  # type: ignore[assignment]
            else:
                self.profile = "custom"
        return self


class SuiteInput(StrictModel):
    prompt: str = Field(min_length=1)


class EvalStep(StrictModel):
    user: str = Field(min_length=1)
    session_id: StableId | None = None
    barrier: Literal["run_complete"] | None = None
    barrier_after: bool = False


class EvalSession(StrictModel):
    id: StableId
    steps: list[EvalStep] = Field(min_length=1)

    @model_validator(mode="after")
    def normalize_steps(self) -> EvalSession:
        for step in self.steps:
            if step.session_id is not None and step.session_id != self.id:
                raise ValueError("session step session_id must match the enclosing session id")
            step.session_id = self.id
        return self


class WorkspaceSeed(StrictModel):
    provider: Literal["local_fixture"]
    path: str = Field(min_length=1)


class WorkspaceFileExistsCheck(StrictModel):
    type: Literal["workspace_file_exists"]
    path: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _validate_workspace_relative_path(value)


class WorkspaceFileContainsCheck(StrictModel):
    type: Literal["workspace_file_contains"]
    path: str
    contains: list[str] = Field(default_factory=list)
    not_contains: list[str] = Field(default_factory=list)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _validate_workspace_relative_path(value)

    @field_validator("contains", "not_contains", mode="before")
    @classmethod
    def normalize_needles(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return value

    @model_validator(mode="after")
    def require_needle(self) -> WorkspaceFileContainsCheck:
        if not self.contains and not self.not_contains:
            raise ValueError("workspace_file_contains requires contains or not_contains")
        return self


class CommandExitZeroCheck(StrictModel):
    type: Literal["command_exit_zero"]
    command: list[str] = Field(min_length=1)
    timeout_seconds: int = Field(default=60, ge=1, le=3600)
    env: dict[str, str] = Field(default_factory=dict)
    env_allowlist: list[str] = Field(default_factory=lambda: ["PATH", "LANG", "LC_ALL", "PYTHONPATH", "VIRTUAL_ENV"])
    stdout_limit: int = Field(default=4000, ge=0, le=20000)
    stderr_limit: int = Field(default=4000, ge=0, le=20000)

    @field_validator("command")
    @classmethod
    def validate_argv(cls, value: list[str]) -> list[str]:
        if any(not isinstance(part, str) or part == "" for part in value):
            raise ValueError("command must be a non-empty argv array of strings")
        return value


class RunEventExistsCheck(StrictModel):
    type: Literal["run_event_exists"]
    event_type: str = Field(min_length=1)
    min_count: int = Field(default=1, ge=1)
    metadata: dict[str, Any] | None = None


CheckSpec = Annotated[
    WorkspaceFileExistsCheck | WorkspaceFileContainsCheck | CommandExitZeroCheck | RunEventExistsCheck,
    Field(discriminator="type"),
]


class MetricSpec(StrictModel):
    type: Literal["behavior_assertion", "cost", "check_result"]
    name: str | None = None
    source: str | None = None
    fields: list[str] = Field(default_factory=list)


class CompareSpec(StrictModel):
    baseline: StableId = "baseline"
    candidate: StableId = "candidate"
    method: Literal["threshold_delta"] = "threshold_delta"
    thresholds: dict[str, float] = Field(default_factory=dict)


class SuiteItem(StrictModel):
    id: StableId
    type: str = Field(min_length=1)
    repeat: int = Field(default=1, ge=1, le=100)
    metric_tags: list[MetricTag] = Field(default_factory=list)
    variants: list[StableId] | None = None
    input: SuiteInput | None = None
    turns: list[EvalStep] | None = None
    sessions: list[EvalSession] | None = None
    workspace_seed: WorkspaceSeed | None = None
    checks: list[CheckSpec] = Field(default_factory=list)
    metrics: list[MetricSpec] = Field(default_factory=list)
    expected: dict[str, Any] = Field(default_factory=dict)
    compare: CompareSpec | None = None

    @model_validator(mode="after")
    def validate_execution_shape(self) -> SuiteItem:
        shapes = [self.input is not None, bool(self.turns), bool(self.sessions)]
        if sum(1 for enabled in shapes if enabled) != 1:
            raise ValueError("each item must define exactly one of input, turns, or sessions")
        if self.turns:
            session_ids = [step.session_id for step in self.turns if step.session_id is not None]
            if session_ids and len(session_ids) != len(self.turns):
                raise ValueError("turns must either all set session_id or all omit it")
        if self.sessions:
            seen: set[str] = set()
            for session in self.sessions:
                if session.id in seen:
                    raise ValueError(f"duplicate session id: {session.id}")
                seen.add(session.id)
        return self


class EvalSuite(StrictModel):
    name: StableId
    version: str | int | None = None
    requires: SuiteRequires = Field(default_factory=SuiteRequires)
    variants: list[Variant] = Field(default_factory=list)
    langsmith: dict[str, Any] = Field(default_factory=dict)
    items: list[SuiteItem] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def apply_default_variant(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data.get("variants"):
            data = {**data, "variants": [{"id": "default", "label": "Default", "profile": "default"}]}
        return data

    @model_validator(mode="after")
    def validate_cross_references(self) -> EvalSuite:
        item_ids: set[str] = set()
        for item in self.items:
            if item.id in item_ids:
                raise ValueError(f"duplicate item id: {item.id}")
            item_ids.add(item.id)

        variant_ids: set[str] = set()
        for variant in self.variants:
            if variant.id in variant_ids:
                raise ValueError(f"duplicate variant id: {variant.id}")
            variant_ids.add(variant.id)

        for item in self.items:
            if item.variants:
                unknown = sorted(set(item.variants) - variant_ids)
                if unknown:
                    raise ValueError(f"item {item.id} references unknown variants: {', '.join(unknown)}")
            if item.compare is not None:
                missing = [variant_id for variant_id in (item.compare.baseline, item.compare.candidate) if variant_id not in variant_ids]
                if missing:
                    raise ValueError(f"item {item.id} compare references unknown variants: {', '.join(missing)}")
        return self

    def normalized_snapshot(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)
