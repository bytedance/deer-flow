from .diff import compare_snapshots, get_changed_output_paths, get_changed_paths
from .recorder import capture_workspace_snapshot, record_workspace_changes
from .scanner import scan_workspace_roots
from .types import (
    WORKSPACE_CHANGES_EVENT_TYPE,
    WORKSPACE_CHANGES_METADATA_KEY,
    FileSnapshot,
    WorkspaceChangeLimits,
    WorkspaceChangeResult,
    WorkspaceChangeSummary,
    WorkspaceFileChange,
    WorkspaceRoot,
    WorkspaceSnapshot,
)

__all__ = [
    "WORKSPACE_CHANGES_EVENT_TYPE",
    "WORKSPACE_CHANGES_METADATA_KEY",
    "FileSnapshot",
    "WorkspaceChangeLimits",
    "WorkspaceChangeResult",
    "WorkspaceChangeSummary",
    "WorkspaceFileChange",
    "WorkspaceRoot",
    "WorkspaceSnapshot",
    "capture_workspace_snapshot",
    "compare_snapshots",
    "get_changed_output_paths",
    "get_changed_paths",
    "get_workspace_changes_response",
    "record_workspace_changes",
    "scan_workspace_roots",
]


def __getattr__(name: str):
    # `.api` reads `deerflow.runtime.user_context` for the AUTO sentinel, and
    # importing that package runs `deerflow.runtime`'s init, which imports
    # `.runs` -> `worker` -> this package. Resolving it lazily keeps this
    # package importable as a process's first import instead of failing with
    # ImportError while its own names are still unbound.
    if name == "get_workspace_changes_response":
        from .api import get_workspace_changes_response

        globals()[name] = get_workspace_changes_response
        return get_workspace_changes_response
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
