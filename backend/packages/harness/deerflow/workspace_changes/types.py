from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

WORKSPACE_CHANGES_EVENT_TYPE = "workspace_changes"
WORKSPACE_CHANGES_METADATA_KEY = "workspace_changes"

WorkspaceChangeStatus = Literal["created", "modified", "deleted"]
DiffUnavailableReason = Literal["binary", "large", "sensitive", "truncated"]


@dataclass(frozen=True)
class WorkspaceChangeLimits:
    max_files: int = 200
    max_scanned_files: int = 2000
    max_file_bytes_for_diff: int = 256 * 1024
    max_total_diff_bytes: int = 1024 * 1024

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class WorkspaceRoot:
    name: str
    host_path: Path
    virtual_prefix: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "host_path", Path(self.host_path))
        object.__setattr__(self, "virtual_prefix", self.virtual_prefix.rstrip("/"))


@dataclass(frozen=True)
class FileSnapshot:
    path: str
    root: str
    size: int
    mtime_ns: int
    sha256: str | None
    binary: bool = False
    sensitive: bool = False
    text: str | None = None
    text_path: str | None = None
    content_unavailable_reason: DiffUnavailableReason | None = None


@dataclass(frozen=True)
class WorkspaceSnapshot:
    files: dict[str, FileSnapshot] = field(default_factory=dict)
    truncated: bool = False
    text_cache_dir: str | None = None


@dataclass(frozen=True)
class WorkspaceFileChange:
    path: str
    root: str
    status: WorkspaceChangeStatus
    binary: bool
    sensitive: bool
    size_before: int | None
    size_after: int | None
    sha256_before: str | None
    sha256_after: str | None
    diff: str = ""
    diff_truncated: bool = False
    diff_unavailable_reason: DiffUnavailableReason | None = None
    additions: int = 0
    deletions: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class WorkspaceChangeSummary:
    created: int = 0
    modified: int = 0
    deleted: int = 0
    additions: int = 0
    deletions: int = 0
    truncated: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class WorkspaceChangeResult:
    summary: WorkspaceChangeSummary
    files: list[WorkspaceFileChange]
    limits: WorkspaceChangeLimits = field(default_factory=WorkspaceChangeLimits)
    version: int = 1

    def has_changes(self) -> bool:
        return bool(self.summary.created or self.summary.modified or self.summary.deleted or self.summary.additions or self.summary.deletions)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "summary": self.summary.to_dict(),
            "files": [change.to_dict() for change in self.files],
            "limits": self.limits.to_dict(),
        }
