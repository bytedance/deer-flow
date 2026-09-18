"""Run-start project context: admission resolution and pure request rendering.

One async resolution per run (:func:`resolve_project_context`, spec §7.1) pins
``{project_id, name, instructions, shelf}`` under the server-owned
``PROJECT_CONTEXT_KEY`` runtime-context key. Everything else in this module is
pure rendering over that pinned snapshot (spec §7.2): no database or
filesystem I/O, no memory-retrieval dependence, no history comparison. The
rendered ``<project>`` block and its bounded ``<documents>`` shelf index ride
the assembled model request only — they are never persisted into
``state["messages"]`` or checkpoints, and the next run simply renders the next
pinned snapshot (latest-only semantics).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from deerflow_extension_api import ContentKind, provenance_kwargs, read_provenance
from langchain_core.messages import HumanMessage, SystemMessage

from deerflow.agents.middlewares.input_sanitization_middleware import neutralize_untrusted_tags
from deerflow.agents.middlewares.message_utils import is_genuine_user_message
from deerflow.persistence.thread_meta import THREAD_PROJECT_METADATA_KEY
from deerflow.runtime.context_keys import CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY, PROJECT_CONTEXT_KEY

logger = logging.getLogger(__name__)

# Project statuses whose members keep receiving instructions at run time
# (archived membership retains instructions and read-only shelf access, §7.1).
_RESOLVABLE_PROJECT_STATUSES = frozenset({"active", "archived"})

# Server-owned additional_kwargs marker identifying this injector's transient
# request message. Gateway admission strips client-supplied copies from input
# message metadata (spec §12), so a marked message inside a run is always
# middleware-produced.
PROJECT_CONTEXT_MESSAGE_MARKER = "deerflow_project_context"

# Reserved message-ID prefix for the transient project message. Recognition
# never relies on this prefix alone — user messages must never be removed by
# an ID-prefix or text match (§7.2), so :func:`is_project_context_message`
# additionally requires the marker and this producer's provenance.
PROJECT_CONTEXT_MESSAGE_ID_PREFIX = "__deerflow_project_context__"

# Provenance producer kind stamped on the transient project message.
_PROJECT_CONTEXT_PRODUCER_KIND = "dynamic_context_project"


async def resolve_project_context(thread_store: Any, project_repo: Any, thread_id: str, document_repo: Any = None) -> dict[str, Any] | None:
    """Resolve the pinned project snapshot for *thread_id*, or ``None``.

    Reads ``threads_meta.project_id`` through the thread store; when non-NULL,
    loads the owner-scoped project row (both stores resolve the caller from the
    ambient user ContextVar, the pattern admission already uses) plus a bounded
    shelf snapshot: the active-document count and the first
    ``shelf_index_max_entries + 1`` rows in ``updated_at DESC, id ASC`` order
    from one consistent database read (§7.1 step 2). The extra row exists only
    to decide index truncation at render time and is never rendered. Tools
    later read live rows under the pinned project ID and may legitimately
    differ after a concurrent shelf mutation.

    ``None`` means the run proceeds unassigned: the thread has no membership,
    or resolution failed (database error, missing thread row, unavailable
    repository). Failures log a warning and never fail the run — the fault is
    organizational, not authorization (§7.1 step 5, §11). Membership itself is
    never written here (§10.7).
    """
    try:
        if thread_store is None or project_repo is None:
            raise LookupError("thread store or project repository unavailable")
        record = await thread_store.get(thread_id)
        if record is None:
            raise LookupError("thread row does not exist yet")
        metadata = record.get("metadata")
        project_id = metadata.get(THREAD_PROJECT_METADATA_KEY) if isinstance(metadata, dict) else None
        if not project_id:
            # Unassigned thread: no project context, and no warning — this is
            # the common case, not a failure.
            return None
        row = await project_repo.get(project_id)
        if row is None or row.get("status") not in _RESOLVABLE_PROJECT_STATUSES:
            logger.warning(
                "Project context resolution for thread %s found no owned active/archived project row; run proceeds unassigned",
                thread_id,
            )
            return None
        snapshot: dict[str, Any] = {
            "project_id": str(row.get("id") or project_id),
            "name": str(row.get("name") or ""),
            "instructions": str(row.get("instructions") or ""),
        }
        if document_repo is not None:
            max_entries = _projects_config().shelf_index_max_entries
            rows, total = await document_repo.shelf_snapshot(snapshot["project_id"], limit=max_entries + 1)
            snapshot["shelf"] = {
                "total": total,
                "entries": [
                    {
                        "id": str(r["id"]),
                        "name": str(r.get("name") or ""),
                        "size_bytes": int(r.get("size_bytes") or 0),
                        "updated_at": str(r.get("updated_at") or ""),
                    }
                    for r in rows
                ],
            }
        return snapshot
    except Exception:
        logger.warning(
            "Failed to resolve project context for thread %s; run proceeds unassigned",
            thread_id,
            exc_info=True,
        )
        return None


def pinned_project_snapshot(runtime: Any) -> dict[str, Any] | None:
    """Return the admission-pinned project snapshot from ``runtime.context``."""
    context = getattr(runtime, "context", None)
    if not isinstance(context, dict):
        return None
    snapshot = context.get(PROJECT_CONTEXT_KEY)
    return snapshot if isinstance(snapshot, dict) else None


def _escape_attribute(value: str) -> str:
    """Escape a value rendered inside a double-quoted XML-ish attribute."""
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def render_project_block(snapshot: Mapping[str, Any] | None) -> str | None:
    """Render the ``<project>`` block for the pinned snapshot, or ``None``.

    ``None`` means the run is unassigned and no block is delivered. Empty
    instructions omit the instructions body but keep the project identity —
    the block always carries the pinned ``id``/``name`` (§7.2). Instructions
    are untrusted user text and pass through ``neutralize_untrusted_tags`` so a
    literal ``</project>`` cannot close the block early; attribute values are
    escaped for quotes, ampersands and angle brackets.
    """
    if not isinstance(snapshot, Mapping):
        return None
    project_id = str(snapshot.get("project_id") or "")
    if not project_id:
        return None
    name = str(snapshot.get("name") or "")
    instructions = neutralize_untrusted_tags(str(snapshot.get("instructions") or "")).strip()
    open_tag = f'<project id="{_escape_attribute(project_id)}" name="{_escape_attribute(name)}">'
    if instructions:
        return f"{open_tag}\n{instructions}\n</project>"
    return f"{open_tag}\n</project>"


# Actionable overflow note for a truncated shelf index (§10.10): names the
# tool that walks the tail, so the model is never left knowing "there is
# more" without a next step.
_SHELF_OVERFLOW_NOTE_TEMPLATE = "…and {omitted} more — call list_project_documents to list them all"


def _projects_config() -> Any:
    """Projects config, falling back to defaults when the app config is unavailable."""
    from deerflow.config.app_config import get_app_config
    from deerflow.config.projects_config import ProjectsConfig

    try:
        return get_app_config().projects
    except (FileNotFoundError, RuntimeError):
        return ProjectsConfig()


def _format_shelf_size(size_bytes: int) -> str:
    """Human-readable shelf size, e.g. ``870 B`` / ``2.1 MB``."""
    size = max(int(size_bytes), 0)
    if size < 1024:
        return f"{size} B"
    value = float(size)
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024.0
        if value < 1024.0 or unit == "TB":
            return f"{value:.1f} {unit}"
    return f"{value:.1f} TB"


def _render_shelf_entry(entry: Mapping[str, Any]) -> str:
    """One line-atomic shelf index entry: ``- id=… | name (size, modified date)``.

    The document name is untrusted user text and passes through
    ``neutralize_untrusted_tags`` so it cannot forge framework blocks; the ID
    is a server-generated content address rendered verbatim so it stays
    directly usable by ``read_project_document`` (including for same-name
    documents).
    """
    document_id = str(entry.get("id") or "")
    name = neutralize_untrusted_tags(str(entry.get("name") or ""))
    size = _format_shelf_size(int(entry.get("size_bytes") or 0))
    updated_at = str(entry.get("updated_at") or "")
    modified = updated_at[:10] if len(updated_at) >= 10 else updated_at
    return f"- id={document_id} | {name} ({size}, modified {modified})"


def render_documents_block(snapshot: Mapping[str, Any] | None, *, max_entries: int, max_bytes: int) -> str | None:
    """Render the bounded ``<documents>`` shelf index, or ``None`` for an empty shelf.

    Pure rendering over the pinned snapshot's ``shelf`` mapping (§7.2, §10.4):
    entries are whole lines in the pinned ``updated_at DESC, id ASC`` order,
    bounded by both ``max_entries`` and the UTF-8 ``max_bytes`` cap. Header,
    closing tag, entry lines (IDs and escaped names included) and the overflow
    note all count toward the byte cap, wrapper/note space is reserved before
    any entry, and no partial entry is ever emitted. The header reports the
    exact shelf ``count`` and rendered ``shown``; a truncated index always
    carries the actionable overflow note. Deterministic: the same snapshot and
    caps always render the same text, which is what the journal's
    ``project_shelf_revision`` fingerprint hashes.
    """
    if not isinstance(snapshot, Mapping):
        return None
    shelf = snapshot.get("shelf")
    if not isinstance(shelf, Mapping):
        return None
    try:
        total = int(shelf.get("total") or 0)
    except (TypeError, ValueError):
        return None
    entries = shelf.get("entries")
    if total <= 0 or not isinstance(entries, list) or not entries:
        return None
    lines = [_render_shelf_entry(entry) for entry in entries[: max(max_entries, 0)] if isinstance(entry, Mapping)]

    def _assemble(shown: int) -> str:
        parts = [f'<documents count="{total}" shown="{shown}">', *lines[:shown]]
        if total > shown:
            parts.append(_SHELF_OVERFLOW_NOTE_TEMPLATE.format(omitted=total - shown))
        parts.append("</documents>")
        return "\n".join(parts)

    for shown in range(len(lines), -1, -1):
        block = _assemble(shown)
        if len(block.encode("utf-8")) <= max_bytes:
            return block
    return None


def build_project_context_message(block: str, run_id: str | None) -> HumanMessage:
    """Build the transient request-only project message for one model call.

    Marked ``hide_from_ui`` and stamped with the server-owned marker plus
    provenance so later assemblies recognize it as this injector's own (and
    the UI/export scrubbers drop it). It deliberately never carries
    ``dynamic_context_reminder``: it is request-scoped, must stay out of the
    summarizer's reminder-preservation path, and is never a state update.
    """
    return HumanMessage(
        content=block,
        id=f"{PROJECT_CONTEXT_MESSAGE_ID_PREFIX}{run_id or 'run'}",
        additional_kwargs={
            "hide_from_ui": True,
            PROJECT_CONTEXT_MESSAGE_MARKER: True,
            **provenance_kwargs(ContentKind.MIDDLEWARE_INJECTION, _PROJECT_CONTEXT_PRODUCER_KIND),
        },
    )


def is_project_context_message(message: object) -> bool:
    """Return whether *message* is this injector's own transient message.

    Recognition requires all three of the reserved ID prefix, the server-owned
    marker and this producer's provenance, so a user message can never be
    removed by matching its text or an ID prefix alone, and a forged
    marker/ID pair (which admission strips anyway) cannot suppress or replace
    the real block.
    """
    if not isinstance(message, HumanMessage):
        return False
    if not str(message.id or "").startswith(PROJECT_CONTEXT_MESSAGE_ID_PREFIX):
        return False
    kwargs = getattr(message, "additional_kwargs", None)
    if not isinstance(kwargs, dict) or kwargs.get(PROJECT_CONTEXT_MESSAGE_MARKER) is not True:
        return False
    provenance = read_provenance(message)
    return provenance is not None and provenance.content_kind == ContentKind.MIDDLEWARE_INJECTION and provenance.producer_kind == _PROJECT_CONTEXT_PRODUCER_KIND


def project_context_insertion_index(messages: list, runtime: Any) -> int:
    """Return the insertion index for the transient project message.

    Primary anchor: immediately before the genuine current-run user message,
    identified through the server-owned pre-run message-ID set rather than as
    the last arbitrary HumanMessage. The anchor is stable across the run's
    tool loop — assistant tool calls and their results all sit after it — and
    is recomputed from each request, so post-compaction requests re-anchor.

    Resumed/internal runs without a retained current-user anchor fall back to
    the protocol-safe position after the leading SystemMessages (the same
    front-insertion rule ``insert_after_leading_system_messages`` encodes).
    """
    pre_existing_ids = _pre_existing_message_ids(runtime)
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if not is_genuine_user_message(message):
            continue
        if pre_existing_ids is not None and str(message.id or "") in pre_existing_ids:
            continue
        return index
    index = 0
    while index < len(messages) and isinstance(messages[index], SystemMessage):
        index += 1
    return index


def _pre_existing_message_ids(runtime: Any) -> frozenset[str] | None:
    """Server-owned pre-run message IDs, or ``None`` when no identity is pinned.

    ``None`` (key absent — embedded callers, unit tests) means every genuine
    user message is a valid anchor candidate; a present-but-empty set means a
    first run, where the same holds. A populated set restricts the anchor to
    messages introduced by the current run.
    """
    context = getattr(runtime, "context", None)
    if not isinstance(context, dict) or CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY not in context:
        return None
    raw = context.get(CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY)
    if not isinstance(raw, (frozenset, set, list, tuple)):
        return None
    return frozenset(str(message_id) for message_id in raw if message_id)
