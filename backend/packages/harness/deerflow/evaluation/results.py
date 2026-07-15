"""Result normalization and failure classification for eval attempts."""

from __future__ import annotations

from collections import defaultdict
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class FailureKind(StrEnum):
    CONFIG = "config_error"
    CHECK_FAILED = "deterministic_check_failed"
    CHECK_TIMEOUT = "deterministic_check_timeout"
    TRACE_GATE = "trace_gate_failed"
    PLATFORM_EVIDENCE_MISSING = "platform_evidence_missing"
    EXTERNAL_BLOCKED = "external_blocked"
    PLATFORM_DEFECT = "platform_defect"
    INFRASTRUCTURE = "infrastructure_error"
    INFRASTRUCTURE_TIMEOUT = "infrastructure_timeout"
    AGENT_ERROR = "agent_error"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


_EXTERNAL_BLOCKED_MARKERS = (
    "llm.error",
    "provider",
    "authentication_error",
    "unauthorized",
    "invalid api key",
    "insufficient quota",
    "provider config",
    "model config",
    "api key",
    "auth",
    "credential",
    "external service",
    "network",
    "connection",
    "dns",
    "name resolution",
    "unreachable",
    "refused",
    "ssl",
    "tls",
    "rate limit",
    "quota",
    "401",
    "403",
    "429",
)

_PLATFORM_DEFECT_MARKERS = (
    "eval platform",
    "evaluation platform",
    "evaluation service",
    "run_events provider",
    "run event provider",
    "report builder",
    "result normalization",
    "repository",
    "persistence",
    "database",
    "integrityerror",
    "unique constraint",
    "constraint failed",
    "eval_runs",
    "eval_run_items",
    "eval_item_attempts",
    "schema migration",
    "workspace seed",
    "internal evidence",
)

_FAILURE_KIND_PRIORITY = {
    FailureKind.UNKNOWN.value: 0,
    FailureKind.AGENT_ERROR.value: 10,
    FailureKind.CHECK_FAILED.value: 20,
    FailureKind.CHECK_TIMEOUT.value: 25,
    FailureKind.TRACE_GATE.value: 30,
    FailureKind.PLATFORM_EVIDENCE_MISSING.value: 40,
    FailureKind.CONFIG.value: 50,
    FailureKind.CANCELLED.value: 60,
    FailureKind.INFRASTRUCTURE.value: 70,
    FailureKind.INFRASTRUCTURE_TIMEOUT.value: 80,
    FailureKind.EXTERNAL_BLOCKED.value: 90,
    FailureKind.PLATFORM_DEFECT.value: 100,
}


class CheckResult(BaseModel):
    type: str
    passed: bool
    failure_kind: str | None = None
    message: str = ""
    duration_ms: int | None = None
    exit_code: int | None = None
    stdout: str | None = None
    stderr: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CostSummary(BaseModel):
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class AttemptResult(BaseModel):
    suite_item_id: str
    variant_id: str = "default"
    sample_index: int = 0
    attempt_index: int = 0
    status: Literal["passed", "failed", "error", "skipped", "cancelled"] = "failed"
    thread_id: str | None = None
    run_id: str | None = None
    workspace_path: str | None = None
    check_results: list[CheckResult] = Field(default_factory=list)
    trace_gate: dict[str, Any] | None = None
    run_event_summary: dict[str, Any] | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    cost: CostSummary = Field(default_factory=CostSummary)
    failure_kind: str | None = None
    error: str | None = None


def normalize_failure_kind(
    *,
    status: str | None = None,
    check_results: list[CheckResult] | None = None,
    trace_gate: dict[str, Any] | None = None,
    error: BaseException | str | None = None,
    run_event_summary: dict[str, Any] | None = None,
) -> str | None:
    if status == "passed":
        return None
    if status == "cancelled":
        return FailureKind.CANCELLED.value

    if trace_gate is not None and trace_gate.get("passed") is False:
        return FailureKind.TRACE_GATE.value

    blocking_failure = _blocking_failure_kind(error=error, run_event_summary=run_event_summary)
    if blocking_failure is not None:
        return blocking_failure

    for check_result in check_results or []:
        if check_result.passed:
            continue
        if check_result.failure_kind:
            return check_result.failure_kind
        return FailureKind.CHECK_FAILED.value

    if error is None:
        return FailureKind.UNKNOWN.value if status in {"failed", "error"} else None

    classified_error = _failure_kind_from_error(error)
    if classified_error is not None:
        return classified_error
    return FailureKind.AGENT_ERROR.value


def _blocking_failure_kind(*, error: BaseException | str | None, run_event_summary: dict[str, Any] | None) -> str | None:
    if _run_event_summary_has_llm_error(run_event_summary):
        return FailureKind.EXTERNAL_BLOCKED.value

    classified_error = _failure_kind_from_error(error)
    if classified_error in {
        FailureKind.PLATFORM_DEFECT.value,
        FailureKind.EXTERNAL_BLOCKED.value,
        FailureKind.INFRASTRUCTURE.value,
        FailureKind.INFRASTRUCTURE_TIMEOUT.value,
    }:
        return classified_error
    return None


def _failure_kind_from_error(error: BaseException | str | None) -> str | None:
    if error is None:
        return None
    if isinstance(error, TimeoutError):
        return FailureKind.INFRASTRUCTURE_TIMEOUT.value
    text = str(error).lower()
    if any(marker in text for marker in _PLATFORM_DEFECT_MARKERS):
        return FailureKind.PLATFORM_DEFECT.value
    if any(marker in text for marker in _EXTERNAL_BLOCKED_MARKERS):
        return FailureKind.EXTERNAL_BLOCKED.value
    if "timeout" in text or "timed out" in text:
        return FailureKind.INFRASTRUCTURE_TIMEOUT.value
    if any(marker in text for marker in ("5xx", "connection", "gateway", "sandbox")):
        return FailureKind.INFRASTRUCTURE.value
    return None


def _run_event_summary_has_llm_error(run_event_summary: dict[str, Any] | None) -> bool:
    if not isinstance(run_event_summary, dict):
        return False
    event_types = run_event_summary.get("event_types") or {}
    if isinstance(event_types, dict):
        return int(event_types.get("llm.error") or 0) > 0
    return False


def _higher_priority_failure_kind(current: str | None, candidate: str | None) -> str | None:
    if candidate is None:
        return current
    if current is None:
        return candidate
    if _FAILURE_KIND_PRIORITY.get(candidate, 0) > _FAILURE_KIND_PRIORITY.get(current, 0):
        return candidate
    return current


def normalize_attempt_result(**kwargs: Any) -> AttemptResult:
    check_results = [result if isinstance(result, CheckResult) else CheckResult.model_validate(result) for result in kwargs.get("check_results", [])]
    trace_gate = kwargs.get("trace_gate")
    status = kwargs.get("status")
    failure_kind = kwargs.get("failure_kind")
    normalized_failure_kind = normalize_failure_kind(
        status=status,
        check_results=check_results,
        trace_gate=trace_gate,
        error=kwargs.get("error"),
        run_event_summary=kwargs.get("run_event_summary"),
    )
    failure_kind = _higher_priority_failure_kind(failure_kind, normalized_failure_kind)
    kwargs = {**kwargs, "check_results": check_results, "failure_kind": failure_kind}
    return AttemptResult.model_validate(kwargs)


def selected_attempt_for_sample(attempts: list[AttemptResult]) -> AttemptResult:
    if not attempts:
        raise ValueError("attempts must be non-empty")
    ordered = sorted(attempts, key=lambda item: item.attempt_index)
    passed = [attempt for attempt in ordered if attempt.status == "passed"]
    return passed[-1] if passed else ordered[-1]


def selected_attempts(attempts: list[AttemptResult]) -> list[AttemptResult]:
    grouped: dict[tuple[str, str, int], list[AttemptResult]] = defaultdict(list)
    for attempt in attempts:
        grouped[(attempt.suite_item_id, attempt.variant_id, attempt.sample_index)].append(attempt)
    return [selected_attempt_for_sample(group) for group in grouped.values()]
