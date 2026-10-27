"""The read-only ``skill_feedback`` model tool (Plan B).

Plan A (the default ``feedback_mode: draft``) keeps annotation-driven
evolution fully offline: a deterministic backend action synthesizes a draft
and the page prefills the stage editor. Plan B (``feedback_mode: agent``)
additionally gives the *agent* eyes on the user's saved trajectory
annotations: this module builds a read-only ``skill_feedback(skill_name)``
tool, declared by :mod:`deerflow_extension_skill_evolution.middleware`
alongside the host's ``skill_manage``.

Host seams, imported lazily and checked at install time (the same
fail-closed pattern as :mod:`deerflow_extension_skill_evolution.tools`):

* ``deerflow.tools.types.Runtime`` — the injected runtime parameter type.
  LangChain excludes ``ToolRuntime``-annotated parameters from the
  model-visible args schema and injects the run's runtime at call time, so
  the model can never supply a user id.
* ``deerflow.runtime.user_context.resolve_runtime_user_id`` — the host's
  single source of truth for the effective user; the tool reads only that
  user's annotations, mirroring the owner-scoping of every other surface.

The tool never raises: a model-facing tool that throws mid-run degrades the
whole turn, so every failure mode degrades to an informative string. It is
only built when the operator configured ``storage_path`` — without a store
there is nothing to read, and declaring a permanently-empty tool would just
pollute the toolset.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .evolved import EvolvedSkillStore
from .mutations import _check_skill_name

logger = logging.getLogger(__name__)

TOOL_NAME = "skill_feedback"

#: Bounded output: newest notes first, hard caps so one pathological store
#: cannot flood the context window.
_MAX_TOOL_NOTES = 20
_MAX_TOOL_OUTPUT_CHARS = 8000


def build_skill_feedback_tool(store: EvolvedSkillStore) -> Any:
    """Return the ``skill_feedback`` BaseTool bound to *store*.

    Raises ``RuntimeError`` when the host lacks the seams this tool is
    written against, so a load-time diagnostic replaces a broken tool
    registered into every agent build.
    """
    try:
        from deerflow.runtime.user_context import resolve_runtime_user_id
        from deerflow.tools.types import Runtime
        from langchain.tools import tool as lc_tool
    except ImportError as exc:
        raise RuntimeError(
            "skill-evolution requires the host tool seams deerflow.tools.types.Runtime and "
            "deerflow.runtime.user_context.resolve_runtime_user_id, which could not be imported "
            f"({exc}). Install a compatible deerflow-harness, or keep feedback_mode at its draft default."
        ) from exc

    async def _skill_feedback_impl(runtime: Any, skill_name: str) -> str:
        """Read the current user's saved feedback notes for one skill, newest first.

        Users attach these notes to a skill's invocation points in past runs.
        Call this before creating or updating that skill and incorporate the
        relevant feedback into the new version.
        """
        try:
            name = _check_skill_name(skill_name)
        except Exception:
            return "Invalid skill name; expected a hyphen-case name such as 'my-skill'."
        user_id = resolve_runtime_user_id(runtime)
        try:
            rows = await asyncio.to_thread(store.list_annotations, owner=user_id, skill_name=name)
        except Exception:
            logger.warning("skill-evolution: skill_feedback failed to read annotations for %s", name, exc_info=True)
            return f"Feedback notes for skill '{name}' are temporarily unavailable; proceed without them."
        if not rows:
            return f"No feedback notes have been recorded for skill '{name}' yet."
        selected = rows[:_MAX_TOOL_NOTES]
        lines = [f"{len(rows)} feedback note(s) for skill '{name}' (newest first):"]
        for index, row in enumerate(selected, start=1):
            run_id = str(row.get("run_id", ""))
            updated = row.get("updated_at") or ""
            note = str(row.get("note", "")).strip()
            lines.append(f"{index}. [run {run_id[:8]} · {updated}] {note}")
        if len(rows) > len(selected):
            lines.append(f"({len(rows) - len(selected)} older note(s) omitted)")
        text = "\n".join(lines)
        if len(text) > _MAX_TOOL_OUTPUT_CHARS:
            text = text[:_MAX_TOOL_OUTPUT_CHARS] + "\n(output truncated)"
        return text

    # ``from __future__ import annotations`` turns the annotation into the
    # string "Runtime", which get_type_hints cannot resolve against this
    # module's globals (the import is factory-local by design). Bind the real
    # host alias into the signature before the decorator builds the schema,
    # so LangChain recognizes it as a directly-injected ToolRuntime argument
    # and keeps it out of the model-visible args schema.
    _skill_feedback_impl.__annotations__["runtime"] = Runtime
    return lc_tool(TOOL_NAME)(_skill_feedback_impl)
