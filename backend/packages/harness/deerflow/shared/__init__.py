"""Shared domain types — canonical enums and models used across layers.

ISSUE-02: Central module for shared type definitions.
"""

from deerflow.shared.status import (
    ArtifactStatus,
    FailedLayer,
    RunFailureCategory,
    RunStatus,
    ThreadStatus,
    UploadStatus,
    canonical_run_status,
)

__all__ = [
    "ArtifactStatus",
    "FailedLayer",
    "RunFailureCategory",
    "RunStatus",
    "ThreadStatus",
    "UploadStatus",
    "canonical_run_status",
]
