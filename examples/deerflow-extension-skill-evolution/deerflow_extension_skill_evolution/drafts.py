"""Deterministic annotation-driven draft synthesis (Plan A).

``evolution_mode: append`` keeps annotation-driven evolution
offline: this backend action reads the skill's current SKILL.md through the
guarded managed pipeline (same ``read`` as the stage editor) and the
caller's trajectory annotations from the plugin-owned store, then
synthesizes a draft — the current content plus a trailing
``## Usage Feedback`` section listing each note with its run/event
reference. The page prefills the stage editor with the draft, so the
existing stage → check → commit pipeline (and every host safety boundary
around it) applies unchanged. No new model surface, no new authorization.

Degradation is deliberate and graceful: without a store (no configured
``storage_path``) or without annotations the draft is simply the current
content with ``feedback_count: 0`` — the page tells the user instead of
failing. When the operator switched to ``evolution_mode: model`` (Plan B),
this action answers ``UNAVAILABLE`` so the switch stays authoritative
server-side, not just in the UI.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Mapping
from typing import Any

from deerflow_extension_api import ActionContext

from .evolved import EvolvedSkillStore
from .modes import MODE_APPEND, read_evolution_mode
from .mutations import ManagedEvolution, _check_skill_name, _error

logger = logging.getLogger(__name__)

#: Bounded synthesis: newest notes first, hard caps so a pathological
#: annotation set cannot overflow the managed pipeline's content quota.
_MAX_DRAFT_NOTES = 20
_MAX_FEEDBACK_SECTION_BYTES = 4096
_FEEDBACK_HEADING = "## Usage Feedback"


def _select_annotations(annotations: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    """Pick the notes to include: newest first, then render chronologically."""
    newest_first = annotations[:_MAX_DRAFT_NOTES]
    selected: list[dict[str, Any]] = []
    total = 0
    for row in newest_first:
        note = str(row.get("note", ""))
        size = len(note.encode("utf-8")) + 180  # the run/event reference line overhead
        if selected and total + size > _MAX_FEEDBACK_SECTION_BYTES:
            break
        selected.append(row)
        total += size
    # Render chronologically. The store orders by updated_at DESC with a
    # run_id tie-break, so same-second notes need an explicit stable sort to
    # keep the section readable.
    selected.sort(key=lambda row: (str(row.get("updated_at") or ""), str(row.get("run_id") or ""), str(row.get("event_id") or "")))
    return selected, len(annotations) > len(selected)


def _feedback_entry(row: dict[str, Any]) -> str:
    run_id = str(row.get("run_id", ""))
    event_id = str(row.get("event_id", ""))
    updated = row.get("updated_at") or ""
    note = str(row.get("note", "")).strip()
    return f"- [run {run_id[:8]} · event {event_id[:8]} · {updated}] {note}"


def _feedback_marker(row: dict[str, Any], *, owner: str, skill_name: str) -> str:
    # Full source identity + normalized note, not timestamps or truncated IDs:
    # re-saving identical feedback stays consumed; editing feedback does not.
    identity = [owner, skill_name, row.get("run_id"), row.get("event_id"), str(row.get("note", "")).strip()]
    digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"<!-- deerflow-skill-feedback:v1:{digest} -->"


def _already_included(content: str, row: dict[str, Any], *, owner: str, skill_name: str) -> bool:
    if _feedback_marker(row, owner=owner, skill_name=skill_name) in content:
        return True
    # Compatibility with pre-marker feedback: require the exact rendered
    # entry and a line boundary. A marked entry belongs to its full ID hash,
    # even if another note happens to share its eight-character display IDs.
    entry = _feedback_entry(row)
    padded = "\n" + content + "\n"
    prefix = "\n" + entry + "\n"
    start = 0
    while (offset := padded.find(prefix, start)) >= 0:
        after = padded[offset + len(prefix) :]
        if not after.startswith("<!-- deerflow-skill-feedback:v1:"):
            return True
        start = offset + len(prefix)
    return False


def _feedback_section(rows: list[dict[str, Any]], *, owner: str, skill_name: str) -> str:
    lines = [_FEEDBACK_HEADING, ""]
    for row in rows:
        lines.extend((_feedback_entry(row), _feedback_marker(row, owner=owner, skill_name=skill_name)))
    return "\n".join(lines)


class AnnotationDrafts:
    """Backend action: synthesize a draft SKILL.md from saved annotations."""

    def __init__(self, evolution: ManagedEvolution, store: EvolvedSkillStore | None, *, mode_reader: Callable[[], str] = read_evolution_mode) -> None:
        self._evolution = evolution
        self._store = store
        self._mode_reader = mode_reader

    async def annotation_draft(self, payload: Any, ctx: ActionContext) -> dict[str, Any]:
        principal = getattr(ctx, "principal", None)
        user_id = getattr(principal, "user_id", None)
        if not isinstance(user_id, str) or not user_id:
            return {"ok": False, "error": {"code": "UNAUTHENTICATED"}}
        if not isinstance(payload, Mapping) or set(payload) != {"skill_name"}:
            return {"ok": False, "error": {"code": "INVALID_REQUEST"}}
        if self._mode_reader() != MODE_APPEND:
            # evolution_mode: model — the model-evolution jobs own
            # annotation-driven evolution.
            return {"ok": False, "error": {"code": "UNAVAILABLE"}}
        try:
            name = _check_skill_name(payload.get("skill_name"))
        except Exception as exc:
            return _error(exc)
        read = await self._evolution.read(user_id=user_id, source=None, skill_name=name)
        if not read.get("ok"):
            return read
        content = read.get("skill", {}).get("content")
        if not isinstance(content, str):
            return {"ok": False, "error": {"code": "INTERNAL"}}
        annotations: list[dict[str, Any]] = []
        if self._store is not None:
            try:
                annotations = list(self._store.list_annotations(owner=user_id, skill_name=name))
            except Exception:
                logger.warning("skill-evolution: failed to load annotations for the %s draft", name, exc_info=True)
        fresh = [row for row in annotations if not _already_included(content, row, owner=user_id, skill_name=name)]
        selected, truncated = _select_annotations(fresh)
        if selected:
            content = f"{content}\n\n{_feedback_section(selected, owner=user_id, skill_name=name)}"
        return {
            "ok": True,
            "skill_name": name,
            "content": content,
            "feedback_count": len(annotations),
            "included_count": len(selected),
            "already_included_count": len(annotations) - len(fresh),
            "truncated": truncated,
        }
