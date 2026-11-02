"""The host capability seam for the ``skill_manage`` tool.

RFC 6954 ("Pluggable Skill Self-Evolution Extension") splits responsibilities
so the *extension* owns the evolution policy and the tool entry point while
the *host* owns everything that makes a mutation safe: name/path validation,
the static (deterministic) scanner, the LLM moderation scan, per-user
storage, JSONL history, sandbox projection rebuilds, and cache invalidation.

The host landed a ``SkillMutationService`` contract in extension API 0.2.7,
but its shape is a proposal pipeline (``stage`` → ``check`` → ``commit``) for
*existing* skills, bound at Gateway start to operator-allowlisted owners and
target skills — a managed-writer backbone, not the user-bound six-action
``apply()`` seam the RFC proposes for this interactive tool. Until that seam
lands, this release binds to the host's existing, public ``skill_manage``
tool object — the same object the core assembles when the legacy
``skill_evolution.enabled`` switch is on. Importing it here instead of
re-implementing it is what guarantees this package can never drift into a
second, weaker security or storage truth.

The import is lazy and checked at install time: a host without the tool
fails the load with an actionable diagnostic rather than surfacing a missing
tool at run time. When the user-bound six-action service lands, this seam is
the only module that needs to change.
"""

from __future__ import annotations

import importlib
from typing import Any

TOOL_NAME = "skill_manage"

_HOST_TOOL_MODULE = "deerflow.tools.skill_manage_tool"
_HOST_TOOL_ATTR = "skill_manage_tool"


def resolve_skill_manage_tool() -> Any:
    """Return the host's ``skill_manage`` tool object, or raise ``RuntimeError``.

    The returned object must be a ``langchain_core.tools.BaseTool`` named
    ``skill_manage``: anything else means the host changed the contract this
    extension was written against, and silently binding it would register a
    broken or misnamed tool into every agent build.
    """
    try:
        module = importlib.import_module(_HOST_TOOL_MODULE)
    except ImportError as exc:
        raise RuntimeError(
            f"skill-evolution requires the host skill tool {_HOST_TOOL_MODULE}:{_HOST_TOOL_ATTR}, which could not be imported ({exc}). Install a deerflow-harness version that ships the skill_manage tool, or disable this extension."
        ) from exc

    tool = getattr(module, _HOST_TOOL_ATTR, None)
    if tool is None:
        raise RuntimeError(f"skill-evolution requires {_HOST_TOOL_MODULE}:{_HOST_TOOL_ATTR}, but the module no longer exports it. Upgrade the extension or pin a compatible deerflow-harness.")

    from langchain_core.tools import BaseTool

    if not isinstance(tool, BaseTool) or getattr(tool, "name", None) != TOOL_NAME:
        raise RuntimeError(f"skill-evolution expected a BaseTool named {TOOL_NAME!r} at {_HOST_TOOL_MODULE}:{_HOST_TOOL_ATTR}, got {type(tool).__name__} (name={getattr(tool, 'name', None)!r}).")
    return tool
