"""Canonical lifecycle status enums — single source of truth for all DeerFlow objects.

ISSUE-02: Unify execution lifecycle and state semantics.
Aligned with ISSUE-01 primary flow and object model baseline.

These enums replace ad-hoc Literal/StrEnum definitions scattered across
persistence, runtime, and report_templates modules.
"""

from __future__ import annotations

import warnings
from enum import StrEnum


# =============================================================================
# Thread — conversation thread
# =============================================================================


class ThreadStatus(StrEnum):
    """Aggregated from subordinate Run statuses, not set manually."""

    idle = "idle"
    active = "active"
    archived = "archived"


# =============================================================================
# Run — agent execution run
# =============================================================================


class RunStatus(StrEnum):
    """Unified execution lifecycle for agent and report runs.

    Canonical values: pending / running / success / failed / cancelled.

    ``error`` / ``timeout`` / ``interrupted`` are DEPRECATED — use ``failed``
    with ``failure_category`` instead.  They remain as enum members for one
    version of backward compatibility; ``canonical_run_status()`` maps them
    automatically and emits a ``DeprecationWarning``.
    """

    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    cancelled = "cancelled"

    # ── deprecated (backward compat, one version) ──
    error = "error"
    timeout = "timeout"
    interrupted = "interrupted"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            for member in cls:
                if member.value == value:
                    return member
        return None


# Map old status values to their canonical equivalents
_RUN_STATUS_DEPRECATED_MAP: dict[str, RunStatus] = {
    "error": RunStatus.failed,
    "timeout": RunStatus.failed,
    "interrupted": RunStatus.failed,
}


def canonical_run_status(raw: str) -> RunStatus:
    """Convert any historical run status string to its canonical form.

    Emits a ``DeprecationWarning`` when an old value is encountered.
    """
    if raw in _RUN_STATUS_DEPRECATED_MAP:
        warnings.warn(
            f"Run status {raw!r} is deprecated, use 'failed' with failure_category instead",
            DeprecationWarning,
            stacklevel=2,
        )
        return _RUN_STATUS_DEPRECATED_MAP[raw]
    return RunStatus(raw)


class RunFailureCategory(StrEnum):
    """Sub-classification when RunStatus is ``failed``."""

    execution_failed = "execution_failed"
    upload_failed = "upload_failed"
    external_dependency_unavailable = "external_dependency_unavailable"


class FailedLayer(StrEnum):
    """Which architectural layer caused the failure."""

    runtime = "runtime"
    gateway = "gateway"
    external = "external"


# =============================================================================
# Upload — file upload
# =============================================================================


class UploadStatus(StrEnum):
    """Lifecycle of a user-uploaded file."""

    uploading = "uploading"
    converting = "converting"
    ready = "ready"
    failed = "failed"


# =============================================================================
# Artifact — agent-generated output file
# =============================================================================


class ArtifactStatus(StrEnum):
    """Lifecycle of an agent-produced artifact."""

    generating = "generating"
    ready = "ready"
    failed = "failed"


# =============================================================================
# User-facing messages for failure categories
# =============================================================================

# Maps (failure_category, lang) -> user-visible message
FAILURE_MESSAGES: dict[str, dict[str, str]] = {
    "execution_failed": {
        "en": "An internal error occurred while processing your request. Please try again or contact support.",
        "zh": "处理请求时发生内部错误，请重试或联系技术支持。",
    },
    "upload_failed": {
        "en": "File upload failed. Please check the file format and size, then re-upload.",
        "zh": "文件上传失败，请检查文件格式和大小后重新上传。",
    },
    "external_dependency_unavailable": {
        "en": "An external service (AI model or data source) is temporarily unavailable. Please wait a moment and try again.",
        "zh": "外部服务（AI 模型或数据源）暂时不可用，请稍后重试。",
    },
}

# Maps (failure_category) -> recoverable action hint
RECOVERABLE_ACTIONS: dict[str, dict[str, str]] = {
    "execution_failed": {
        "en": "Retry",
        "zh": "重试",
    },
    "upload_failed": {
        "en": "Re-upload",
        "zh": "重新上传",
    },
    "external_dependency_unavailable": {
        "en": "Wait and retry",
        "zh": "等待后重试",
    },
}


def get_failure_message(category: str, lang: str = "en") -> str:
    """Return a user-facing message for a failure category."""
    return FAILURE_MESSAGES.get(category, {}).get(lang, FAILURE_MESSAGES.get(category, {}).get("en", category))


def get_recoverable_action(category: str, lang: str = "en") -> str:
    """Return the suggested recoverable action for a failure category."""
    return RECOVERABLE_ACTIONS.get(category, {}).get(lang, RECOVERABLE_ACTIONS.get(category, {}).get("en", ""))
