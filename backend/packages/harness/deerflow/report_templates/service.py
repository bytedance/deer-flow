"""Service-level helpers that bind tools and HTTP routers to repository state.

The 6 lifecycle tools in ``tools/builtins/report_template_*.py`` each need:

  - A ready-to-use ``FileSystemReportTemplateRepository`` rooted at the right
    directory (under ``DEER_FLOW_HOME``);
  - A ``Principal`` reflecting the current LLM caller's user/tenant identity
    + admin role flags.

This module centralises those concerns so each tool stays a ≤50-line thin shell
(see §3.4 of the design document).

Repository singleton
--------------------
``get_repository()`` lazily builds one ``FileSystemReportTemplateRepository``
per process and caches it. The runtime root resolves from ``deerflow.config.paths``;
the builtin root resolves from the repo's ``agents/builtin/report-templates/``
checked-in directory (read-only).

Principal resolution
--------------------
``principal_from_runnable_config(config)`` reads ``config["configurable"]`` and
falls back to the request-scoped ``user_context`` / ``tenant`` contextvars
already used by other built-in tools. The harness never imports anything from
the gateway — admin flags must be passed explicitly via ``configurable`` by the
Gateway authentication middleware that creates the runtime config.

The contract:

    config["configurable"]["user_id"]            (optional — falls back to get_effective_user_id())
    config["configurable"]["tenant_id"]          (optional — falls back to get_current_tenant_id())
    config["configurable"]["is_superadmin"]      (optional bool, default False)
    config["configurable"]["is_tenant_admin"]    (optional bool, default False)
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from deerflow.report_templates.permissions import Principal
from deerflow.report_templates.repository import (
    FileSystemReportTemplateRepository,
)

# ---------------------------------------------------------------------------
# Repository singleton
# ---------------------------------------------------------------------------

_repo: FileSystemReportTemplateRepository | None = None
_repo_lock = threading.Lock()


def get_repository() -> FileSystemReportTemplateRepository:
    """Return the process-wide singleton repository.

    The runtime root is ``{DEER_FLOW_HOME}/report-templates/`` (matching §7.1.1).
    The builtin root is ``<repo_root>/agents/builtin/report-templates/``; the
    walk-up from this file's location finds the project root, then the
    ``agents/builtin/`` directory checked into git (read-only).
    """
    global _repo
    if _repo is None:
        with _repo_lock:
            if _repo is None:
                _repo = _build_default_repository()
    return _repo


def reset_repository() -> None:
    """Clear the cached repository (tests + skill-disable events)."""
    global _repo
    with _repo_lock:
        _repo = None


def set_repository(repo: FileSystemReportTemplateRepository) -> None:
    """Inject a repository instance (testing hook)."""
    global _repo
    with _repo_lock:
        _repo = repo


def _build_default_repository() -> FileSystemReportTemplateRepository:
    from deerflow.config.paths import get_paths

    paths = get_paths()
    runtime_root = paths.base_dir / "report-templates"
    runtime_root.mkdir(parents=True, exist_ok=True)
    builtin_root = _locate_builtin_templates_dir()
    return FileSystemReportTemplateRepository(
        runtime_root=runtime_root,
        builtin_root=builtin_root,
    )


def _locate_builtin_templates_dir() -> Path | None:
    """Find ``agents/builtin/report-templates/`` checked into the repo, or None."""
    # Walk upward from this module looking for a sibling ``agents/builtin/``.
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "agents" / "builtin" / "report-templates"
        if candidate.is_dir():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Principal resolution
# ---------------------------------------------------------------------------


def principal_from_runnable_config(config: dict[str, Any] | None) -> Principal:
    """Build a ``Principal`` from a LangGraph ``RunnableConfig``.

    Falls back to the request-scoped contextvars when fields are missing. In
    no-auth (or test) mode the user falls back to ``"default"`` per
    ``runtime.user_context.DEFAULT_USER_ID``.
    """
    from deerflow.config.tenant import get_current_tenant_id
    from deerflow.runtime.user_context import get_effective_user_id

    cfg = (config or {}).get("configurable", {}) or {}
    user_id = cfg.get("user_id") or get_effective_user_id()
    tenant_id = cfg.get("tenant_id") or get_current_tenant_id()

    return Principal(
        user_id=str(user_id),
        tenant_id=str(tenant_id),
        is_superadmin=bool(cfg.get("is_superadmin", False)),
        is_tenant_admin=bool(cfg.get("is_tenant_admin", False)),
    )
