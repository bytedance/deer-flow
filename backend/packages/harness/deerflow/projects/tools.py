"""Project shelf tools: bounded live reads through the pinned project identity.

Read-only tools (Phase-2 spec §7.3; the shelf is user-curated — there is
no agent-initiated shelf write). All take ``project_id`` from the run's
admission-pinned context (``PROJECT_CONTEXT_KEY``) and ``user_id`` from
:func:`resolve_runtime_user_id`, then query **live** shelf rows: the pinned
snapshot fixes *which* project, never *what* the shelf currently holds. A
missing pin or a missing session factory is a tool error, never an empty
success; a document trashed after this run's index was rendered fails with a
"no longer on the shelf" error rather than serving stale content (§11).

Registration is conditional on the pinned key (§10.11) — see
``agents/lead_agent/agent.py``; subagents never receive these tools. Every
file read and conversion is offloaded via
:func:`deerflow.utils.file_io.run_file_io`.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Annotated, Any

from langchain.tools import tool

from deerflow.agents.middlewares.input_sanitization_middleware import neutralize_untrusted_tags
from deerflow.config.paths import Paths, get_paths
from deerflow.projects.context import pinned_project_snapshot
from deerflow.projects.documents import auto_convert_documents_enabled, document_char_count, read_document_text_window, read_text_serving_path
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.tools.types import Runtime
from deerflow.utils.file_io import run_file_io

logger = logging.getLogger(__name__)

_LIST_DEFAULT_LIMIT = 50
_LIST_MAX_LIMIT = 200
_READ_DEFAULT_LIMIT = 8000
_READ_MAX_LIMIT = 20000
_SEARCH_DEFAULT_LIMIT = 10
_SEARCH_MAX_LIMIT = 50
_SEARCH_QUERY_MAX_CHARS = 200
#: Excerpt window: this many characters on each side of the match (spec §7;
#: a constant, deliberately not a config knob).
_SEARCH_EXCERPT_CONTEXT = 80
#: Cap on each id list in the search result payload.
_SEARCH_ID_LIST_CAP = 20

_BINARY_DECLINE_MESSAGE = "This document is binary and cannot be read as text. To let the agent process it, attach it to a thread (attach-to-thread) instead."
_CONVERSION_DISABLED_MESSAGE = "This document is a convertible office/PDF file, but automatic document conversion is disabled (uploads.auto_convert_documents). Enable conversion, or attach the file to a thread (attach-to-thread) instead."
_NOT_ON_SHELF_MESSAGE = "This document is no longer on the shelf (it was trashed or removed after this run started). Call list_project_documents for the current shelf."
_CONTENT_MISSING_MESSAGE = "This document's content is missing from storage (content_missing); only its shelf row remains. Move it to trash from the project page."
_NO_PROJECT_CONTEXT_MESSAGE = "No project is pinned for this run; project document tools are only available in project member threads."
_NO_STORE_MESSAGE = "Project document store is unavailable."


def _error(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False)


def _resolve_pin_and_repo(runtime: Runtime) -> tuple[str, str, Any] | str:
    """Resolve ``(project_id, user_id, repository)`` or a JSON error string.

    Fail closed (§7.3): no pinned project context or no session factory is a
    tool error with no data, never an empty success.
    """
    snapshot = pinned_project_snapshot(runtime)
    project_id = str(snapshot.get("project_id") or "") if snapshot is not None else ""
    if not project_id:
        return _error(_NO_PROJECT_CONTEXT_MESSAGE)
    from deerflow.persistence import get_session_factory
    from deerflow.persistence.projects import ProjectDocumentRepository

    session_factory = get_session_factory()
    if session_factory is None:
        return _error(_NO_STORE_MESSAGE)
    user_id = resolve_runtime_user_id(runtime)
    return project_id, user_id, ProjectDocumentRepository(session_factory)


def _resolve_auto_convert() -> bool:
    """Worker-thread config read: the app config may cold-load from disk."""
    try:
        from deerflow.config.app_config import get_app_config

        return auto_convert_documents_enabled(get_app_config())
    except Exception:
        return False


def _clamp(value: int, *, default: int, lower: int, upper: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(lower, min(parsed, upper))


def _shelf_entry_json(row: dict) -> dict[str, Any]:
    summary = row.get("summary")
    return {
        "id": row["id"],
        "name": neutralize_untrusted_tags(str(row.get("name") or "")),
        "size_bytes": int(row.get("size_bytes") or 0),
        "updated_at": str(row.get("updated_at") or ""),
        # LLM-processed untrusted content: neutralized here exactly like the
        # name, mirroring the injected index line.
        "summary": (neutralize_untrusted_tags(str(summary)) if summary else None),
    }


async def _list_project_documents_impl(runtime: Runtime, *, offset: int, limit: int) -> str:
    resolved = _resolve_pin_and_repo(runtime)
    if isinstance(resolved, str):
        return resolved
    project_id, user_id, repo = resolved
    limit = _clamp(limit, default=_LIST_DEFAULT_LIMIT, lower=1, upper=_LIST_MAX_LIMIT)
    offset = max(_clamp(offset, default=0, lower=0, upper=1 << 62), 0)
    rows = await repo.list_active(project_id, limit=limit, offset=offset, user_id=user_id)
    total = await repo.count_active(project_id, user_id=user_id)
    next_offset: int | None = offset + len(rows) if offset + len(rows) < total else None
    return json.dumps(
        {
            "total": total,
            "offset": offset,
            "next_offset": next_offset,
            "documents": [_shelf_entry_json(row) for row in rows],
        },
        ensure_ascii=False,
    )


async def _read_project_document_impl(runtime: Runtime, *, document_id: str, offset: int, limit: int, paths: Paths | None = None) -> str:
    resolved = _resolve_pin_and_repo(runtime)
    if isinstance(resolved, str):
        return resolved
    project_id, user_id, repo = resolved
    row = await repo.get(document_id, user_id=user_id)
    # Fail closed on every mismatch: trashed/purged after the index rendered,
    # foreign, or belonging to a different project than the pinned one — one
    # stale-entry error, never cross-project reads, never stale content (§11).
    if row is None or row.get("project_id") != project_id:
        return _error(_NOT_ON_SHELF_MESSAGE)
    paths = paths or get_paths()
    auto_convert = await run_file_io(_resolve_auto_convert)
    serving_path, reason = await read_text_serving_path(repo, paths, user_id=user_id, row=row, auto_convert=auto_convert)
    if serving_path is None:
        if reason == "content_missing":
            return _error(_CONTENT_MISSING_MESSAGE)
        if reason == "conversion_disabled":
            return _error(_CONVERSION_DISABLED_MESSAGE)
        return _error(_BINARY_DECLINE_MESSAGE)
    offset = _clamp(offset, default=0, lower=0, upper=1 << 62)
    limit = _clamp(limit, default=_READ_DEFAULT_LIMIT, lower=1, upper=_READ_MAX_LIMIT)
    # The character count is content-identity cached (immutable rows, §6.2);
    # the windowed read decodes only what the page needs — and past-end pages
    # read nothing at all.
    total_chars = await document_char_count(document_id=row["id"], sha256=row["sha256"], path=serving_path)
    content = await read_document_text_window(serving_path, offset=offset, limit=limit) if offset < total_chars else ""
    return json.dumps(
        {
            "name": neutralize_untrusted_tags(str(row.get("name") or "")),
            "total_chars": total_chars,
            "offset": offset,
            "returned_chars": len(content),
            "truncated": offset + len(content) < total_chars,
            "content": content,
        },
        ensure_ascii=False,
    )


@tool
async def list_project_documents(
    runtime: Runtime,
    offset: Annotated[int, "Number of shelf entries to skip for pagination (default 0). Use next_offset from a previous call to walk the shelf."] = 0,
    limit: Annotated[int, "Maximum entries to return (default 50, max 200)."] = _LIST_DEFAULT_LIMIT,
) -> str:
    """List documents on the current project's shelf (metadata only, no content).

    Returns JSON: {"total", "offset", "next_offset", "documents": [{"id",
    "name", "size_bytes", "updated_at", "summary"}, ...]} in the shelf's own
    order (recently updated first). "summary" is an optional one-line
    description of the document (null while generation is pending/disabled/
    failed) — use it to decide whether a read_project_document call is worth
    it before paying for a content slice. Use this tool when the <documents>
    index says the shelf has more entries than it shows, or the user asks
    what documents the project holds. Each entry's stable "id" is what
    read_project_document takes. Live data: reflects the shelf as of this
    call.
    """
    return await _list_project_documents_impl(runtime, offset=offset, limit=limit)


@tool
async def read_project_document(
    runtime: Runtime,
    document_id: Annotated[str, "Stable document ID from the <documents> index or list_project_documents."],
    offset: Annotated[int, "Character offset into the document's text (default 0)."] = 0,
    limit: Annotated[int, "Maximum characters to return (default 8000, max 20000)."] = _READ_DEFAULT_LIMIT,
) -> str:
    """Read a bounded text slice of one project shelf document.

    Returns JSON: {"name", "total_chars", "offset", "returned_chars",
    "truncated", "content"}. Long documents are served in slices: advance
    "offset" by the returned character count while "truncated" is true.
    Office/PDF documents are served as converted markdown when conversion is
    enabled. Binary documents cannot be read — attach them to a thread
    instead. A document trashed after this run started reports that it is no
    longer on the shelf.
    """
    return await _read_project_document_impl(runtime, document_id=document_id, offset=offset, limit=limit)


_QUERY_BLANK_MESSAGE = "Query must be 1-200 non-whitespace characters."


def _resolve_search_budgets() -> tuple[int, int]:
    """Worker-thread config read: per-call so edits apply without a restart."""
    try:
        from deerflow.config.app_config import get_app_config
        from deerflow.config.projects_config import ProjectsConfig

        cfg = getattr(get_app_config(), "projects", None)
        if not isinstance(cfg, ProjectsConfig):
            cfg = ProjectsConfig()
        return cfg.search_max_chars_per_document, cfg.search_max_total_chars
    except Exception:
        from deerflow.config.projects_config import ProjectsConfig

        fallback = ProjectsConfig()
        return fallback.search_max_chars_per_document, fallback.search_max_total_chars


def _search_excerpt(text: str, match: re.Match) -> str:
    """Slice ±``_SEARCH_EXCERPT_CONTEXT`` around *match* on the ORIGINAL text, then neutralize.

    Order matters: slicing on neutralized text would misalign every offset.
    """
    start = max(0, match.start() - _SEARCH_EXCERPT_CONTEXT)
    end = min(len(text), match.end() + _SEARCH_EXCERPT_CONTEXT)
    snippet = text[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet += "…"
    return neutralize_untrusted_tags(snippet)


def _capped_id_list(ids: list[str]) -> tuple[list[str], int]:
    """The first ``_SEARCH_ID_LIST_CAP`` ids plus the full count (spec §6)."""
    return ids[:_SEARCH_ID_LIST_CAP], len(ids)


async def _search_project_documents_impl(runtime: Runtime, *, query: str, limit: int) -> str:
    resolved = _resolve_pin_and_repo(runtime)
    if isinstance(resolved, str):
        return resolved
    project_id, user_id, repo = resolved

    query = query.strip()
    if not query or len(query) > _SEARCH_QUERY_MAX_CHARS:
        return _error(_QUERY_BLANK_MESSAGE)
    limit = _clamp(limit, default=_SEARCH_DEFAULT_LIMIT, lower=1, upper=_SEARCH_MAX_LIMIT)
    per_doc_cap, total_budget = await run_file_io(_resolve_search_budgets)
    # re.IGNORECASE, NOT casefold: indices must stay original-text character
    # positions — casefold changes length (ß→ss, İ→i̇) and would corrupt both
    # the returned offset and the excerpt slice (spec §5.3).
    pattern = re.compile(re.escape(query), re.IGNORECASE)

    # Tier 1: name/summary over the whole shelf, materialized in ONE query.
    # The rows are kept and reused for tier 2 — a stable candidate set.
    # Offset paging would re-read the live shelf per page, so a concurrent
    # upload/trash between pages could duplicate a row (an unrelated newest
    # upload shifts every offset) or silently skip one (a trash shrinks
    # earlier pages); a single SELECT reads one snapshot. A row trashed
    # between the snapshot and its content read follows the normal serving
    # rules ("missing" etc.) — shelf membership is fixed as of this call.
    shelf_rows = await repo.list_active(project_id, limit=1 << 62, offset=0, user_id=user_id)  # effectively unbounded: one read snapshot
    name_hits: list[dict] = []
    summary_hits: list[dict] = []
    tier1_ids: set[str] = set()
    for row in shelf_rows:
        name = str(row.get("name") or "")
        summary = row.get("summary") or None
        name_match = pattern.search(name)
        if name_match is not None:
            name_hits.append({"id": row["id"], "name": neutralize_untrusted_tags(name), "matched": "name", "excerpt": _search_excerpt(name, name_match), "offset": None})
            tier1_ids.add(row["id"])
        elif summary:
            summary_match = pattern.search(str(summary))
            if summary_match is not None:
                summary_hits.append({"id": row["id"], "name": neutralize_untrusted_tags(name), "matched": "summary", "excerpt": _search_excerpt(str(summary), summary_match), "offset": None})
                tier1_ids.add(row["id"])

    results = (name_hits + summary_hits)[:limit]
    if len(results) >= limit:
        # Tier 1 alone filled the page: content was never read, and the
        # ranking is exact — the answer must NOT claim coverage (spec §6).
        return json.dumps(
            {
                "results": results,
                "stop_reason": "limit",
                "content_scanned": False,
                "skipped": {"non_text": 0, "unconverted": 0, "missing": 0, "error": 0},
                "truncated_document_ids": [],
                "truncated_count": 0,
                "unscanned_document_ids": [],
                "unscanned_count": 0,
            },
            ensure_ascii=False,
        )

    # Tier 2: content scan over the SAME snapshot, in shelf order, skipping
    # tier-1 hits, bounded by the whole-shelf budget. auto_convert=False:
    # search NEVER converts (a first search must not synchronously convert
    # every PDF on the shelf).
    remaining = limit - len(results)
    budget_left = total_budget
    stop_reason = "complete"
    skipped = {"non_text": 0, "unconverted": 0, "missing": 0, "error": 0}
    truncated_ids: list[str] = []
    unscanned_ids: list[str] = []
    processed = 0  # non-tier-1 rows examined before any budget trip
    paths = get_paths()
    for row in shelf_rows:
        if remaining == 0:
            stop_reason = "limit"
            break
        if row["id"] in tier1_ids:
            # Tier 1 was fully scanned over this snapshot: these are already
            # in results and were searched — never "unscanned".
            continue
        if budget_left <= 0:
            # Budget tripped. Unscanned ids are enumerated in memory, up to
            # the payload cap; the honest total is derived after the loop
            # from the snapshot — no further DB reads for rows already ruled
            # out.
            stop_reason = "budget"
            if len(unscanned_ids) < _SEARCH_ID_LIST_CAP:
                unscanned_ids.append(row["id"])
            continue
        processed += 1
        try:
            serving_path, reason = await read_text_serving_path(repo, paths, user_id=user_id, row=row, auto_convert=False)
        except Exception:
            skipped["error"] += 1
            logger.warning("Shelf search: failed to resolve serving path for %s", row["id"], exc_info=True)
            continue
        if serving_path is None:
            skipped[{"content_missing": "missing", "conversion_disabled": "unconverted"}.get(reason, "non_text")] += 1
            continue
        cap = min(per_doc_cap, budget_left)
        try:
            text = await read_document_text_window(serving_path, offset=0, limit=cap + 1)
        except Exception:
            skipped["error"] += 1
            logger.warning("Shelf search: failed to read %s", row["id"], exc_info=True)
            continue
        budget_left -= len(text)
        if len(text) > cap:
            text = text[:cap]
            truncated_ids.append(row["id"])
        match = pattern.search(text)
        if match is not None:
            results.append({"id": row["id"], "name": neutralize_untrusted_tags(str(row.get("name") or "")), "matched": "content", "excerpt": _search_excerpt(text, match), "offset": match.start()})
            remaining -= 1

    truncated_capped, truncated_total = _capped_id_list(truncated_ids)
    if stop_reason == "complete" and remaining == 0:
        # The limit filled exactly on the snapshot's final row — a limit stop,
        # not a complete scan.
        stop_reason = "limit"
    unscanned_total = 0
    if stop_reason == "budget":
        # Exact — the snapshot IS the candidate set: unscanned = non-tier-1
        # rows minus those processed before the trip.
        unscanned_total = len(shelf_rows) - len(tier1_ids) - processed
    return json.dumps(
        {
            "results": results,
            "stop_reason": stop_reason,
            "content_scanned": True,
            "skipped": skipped,
            "truncated_document_ids": truncated_capped,
            "truncated_count": truncated_total,
            "unscanned_document_ids": unscanned_ids,
            "unscanned_count": unscanned_total,
        },
        ensure_ascii=False,
    )


@tool
async def search_project_documents(
    runtime: Runtime,
    query: Annotated[str, "Case-insensitive keyword to find on the shelf (plain substring, not regex; 1-200 chars)."],
    limit: Annotated[int, "Maximum results to return (default 10, max 50)."] = _SEARCH_DEFAULT_LIMIT,
) -> str:
    """Search the current project's shelf by keyword across names, summaries, and content.

    Two tiers: every document's name and summary are matched first (cheap),
    and content is scanned only if that produced too few hits — so ranking is
    always name > summary > content, with the shelf's own order inside a
    tier. Each document appears at most once, credited to its best field.

    Returns JSON: {"results": [{"id", "name", "matched", "excerpt",
    "offset"}], "stop_reason", "content_scanned", "skipped",
    "truncated_document_ids", "truncated_count", "unscanned_document_ids",
    "unscanned_count"}. "offset" is set ONLY for content hits: a character
    position to pass straight to read_project_document(offset=...).
    stop_reason is "complete" (everything searched), "limit" (enough hits;
    unsearched remainder is irrelevant), or "budget" (the whole-shelf scan
    budget ran out — unscanned_document_ids lists what was not searched).
    content_scanned=false means content was never read (tier 1 was enough);
    never treat that as full coverage. skipped counts non_text binaries,
    unconverted office/PDF (never converted on the fly), and missing
    content. Live data: reflects the shelf as of this call.
    """
    return await _search_project_documents_impl(runtime, query=query, limit=limit)


def get_project_document_tools() -> list:
    """The shelf tools the lead agent gains in project runs (§7.3)."""
    return [list_project_documents, read_project_document, search_project_documents]
