"""Trash tier service: restore orchestration, guarded purge, retention sweep.

Phase-2 spec §8.2/§8.3. Restore is a database re-point (``stored_relpath`` is
projects-root-relative, so no file ever moves, §10.6); the only filesystem
work on the restore path is the post-commit merge cleanup of the discarded
namespace, best-effort with the sweep as backstop. Purge unlinks the
original and ``derived/converted.md`` inside the repository's continuously
row-locked transaction — ``FileNotFoundError`` counts as already removed,
any other unlink error rolls the row deletion back and keeps the trashed
row retryable. The retention sweep runs lazily on the trash listing and
once at gateway startup (no daemon, §15.9): it invokes the same guarded
purge for expired rows, then reconciles storage (``.staging`` and
unreferenced files older than 24 hours only) and detects — never deletes —
rows whose content is missing or size-mismatched (§15.17).

Every filesystem touch is offloaded through ``run_file_io``; the blocking-IO
anchors in ``tests/blocking_io/test_project_trash.py`` pin that.
"""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from deerflow.config.paths import Paths
from deerflow.projects.documents import _content_intact, check_document_content, converted_markdown_path, original_file_path
from deerflow.utils.file_io import await_drained, run_file_io
from deerflow.utils.time import coerce_iso

if TYPE_CHECKING:
    from deerflow.persistence.projects import ProjectDocumentRepository

logger = logging.getLogger(__name__)

#: Nothing younger than this is ever collected or flagged, so an in-flight
#: upload or a freshly written row can never be swept (§8.3).
_ORPHAN_GUARD = timedelta(hours=24)


def _rmdir_if_empty(directory: Path) -> None:
    try:
        directory.rmdir()
    except OSError:
        pass


def _unlink_document_files(paths: Paths, *, user_id: str, row: dict) -> None:
    """Worker-thread: unlink a row's original + derived companion, then rmdir
    empty parents (best-effort). ``FileNotFoundError`` counts as already
    removed (§8.3); any other unlink error propagates so the purge
    transaction rolls back and keeps the trashed row retryable.
    """
    original = original_file_path(paths, user_id=user_id, row=row)
    derived = converted_markdown_path(paths, user_id=user_id, row=row)
    for path in (original, derived):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    namespace = paths.project_document_path(user_id, row["stored_relpath"])
    documents_dir = namespace.parents[2]
    for directory in (original.parent, derived.parent, namespace, namespace.parent, namespace.parent.parent):
        if directory != documents_dir:
            _rmdir_if_empty(directory)


def make_purge_file_remover(paths: Paths, *, user_id: str | None) -> Callable[[dict], Awaitable[None]]:
    """Build the ``remove_files`` hook for ``ProjectDocumentRepository.purge``.

    The hook runs inside the purge transaction, continuously under the
    document-row lock (§6.3). ``user_id=None`` (the startup sweep) resolves
    the owner per row.
    """

    async def _remove(row: dict) -> None:
        await run_file_io(_unlink_document_files, paths, user_id=user_id or row["user_id"], row=row)

    return _remove


def _remove_namespace_tree(paths: Paths, *, user_id: str, relpath: str) -> None:
    """Worker-thread: remove one document's whole namespace + empty parents."""
    namespace = paths.project_document_path(user_id, relpath)
    shutil.rmtree(namespace, ignore_errors=True)
    documents_dir = namespace.parents[2]
    parent = namespace.parent
    while parent != documents_dir:
        _rmdir_if_empty(parent)
        parent = parent.parent


async def restore_document(
    repo: ProjectDocumentRepository,
    paths: Paths,
    *,
    user_id: str,
    document_id: str,
    target_project_id: str,
) -> tuple[str, dict | None]:
    """Restore one trashed document into an active target project (§8.2).

    Thin orchestration over the repository's locked restore: the post-commit
    merge cleanup (unlinking the discarded source namespace, which no
    surviving row can reference) is the only filesystem work here —
    best-effort; a failure is logged and left for the sweep (§8.2/§10.6).
    Returns the repository's ``(outcome, row)`` pair unchanged.
    """
    # Read-only probe: captures the discarded namespace a merge cleanup must
    # remove. Every correctness check happens inside the repository's locked
    # transaction, so this probe decides nothing (§15.5).
    source = await repo.get(document_id, include_trashed=True, user_id=user_id)

    async def _check(row: dict) -> bool:
        return await check_document_content(paths, user_id=user_id, row=row)

    outcome, row = await repo.restore(document_id, target_project_id=target_project_id, check_content=_check, user_id=user_id)
    if outcome == "merged" and source is not None:
        try:
            await run_file_io(_remove_namespace_tree, paths, user_id=user_id, relpath=source["stored_relpath"])
        except Exception:
            logger.warning(
                "Merge cleanup of the discarded namespace for document %s failed; the sweep will collect it",
                document_id,
                exc_info=True,
            )
    return outcome, row


async def purge_all_trashed(
    repo: ProjectDocumentRepository,
    paths: Paths,
    *,
    user_id: str,
) -> int:
    """Empty the caller's trash (§8.3): purge every trashed row regardless of age.

    Empty trash deletes exactly what the user confirmed, so the retention
    cutoff plays no part here — ``run_trash_retention_sweep`` stays the only
    age-gated purge. Each row goes through the same guarded row-locked
    ``purge`` as a single-document delete: bytes first, then the row, in one
    transaction, so a restore that wins the race leaves the row alone
    (``purge`` answers ``False`` for a no-longer-trashed row and it is
    skipped). Rows are not deleted atomically: an unlink error rolls that row
    back and propagates, leaving it — and every row not yet visited —
    trashed and retryable. Returns the number of rows actually purged.
    """
    remove_files = make_purge_file_remover(paths, user_id=user_id)
    purged = 0
    for row in await repo.list_all_trashed(user_id=user_id):
        if await repo.purge(row["id"], remove_files=remove_files, user_id=user_id):
            purged += 1
    return purged


@dataclass(slots=True)
class SweepReport:
    """Observable outcome of one retention sweep run."""

    purged: int = 0
    purge_failures: int = 0
    orphans_removed: int = 0
    staging_removed: int = 0
    content_missing: list[str] = field(default_factory=list)


def _sweep_project_documents_dir(documents_dir: Path, *, protected: set[Path], cutoff_ts: float, report: SweepReport) -> None:
    """Worker-thread: storage reconciliation under one ``documents/`` directory.

    Removes ``.staging/*`` entries and unreferenced files older than the
    24-hour guard; a row's namespace (active or trashed, even after restore
    re-pointed it to another project) is protected in full (§8.3). Empty
    parents are rmdir'd best-effort. Nothing younger is ever collected.
    """
    staging = documents_dir / ".staging"
    if staging.is_dir():
        for entry in staging.iterdir():
            try:
                if entry.stat().st_mtime >= cutoff_ts:
                    continue
                if entry.is_dir():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    entry.unlink()
            except FileNotFoundError:
                continue
            except OSError:
                logger.warning("Staging sweep could not remove %s; skipping", entry, exc_info=True)
                continue
            report.staging_removed += 1
    for dirpath, dirnames, filenames in os.walk(documents_dir):
        current = Path(dirpath)
        # Never descend into protected namespaces or .staging.
        dirnames[:] = [name for name in dirnames if (current / name) not in protected and not (current == documents_dir and name == ".staging")]
        for filename in filenames:
            file = current / filename
            try:
                if file.stat().st_mtime >= cutoff_ts:
                    continue
                file.unlink()
            except FileNotFoundError:
                continue
            except OSError:
                logger.warning("Orphan sweep could not unlink %s; skipping", file, exc_info=True)
                continue
            report.orphans_removed += 1
    # Rmdir empty parents best-effort (bottom-up), keeping the documents dir
    # itself and protected namespaces.
    for dirpath, _dirnames, _filenames in os.walk(documents_dir, topdown=False):
        current = Path(dirpath)
        if current != documents_dir and current not in protected:
            _rmdir_if_empty(current)


def _reconcile_storage(paths: Paths, *, user_id: str | None, rows: list[dict], guard_cutoff: datetime, report: SweepReport) -> None:
    """Worker-thread: storage reconciliation across the swept users' trees."""
    cutoff_ts = guard_cutoff.timestamp()
    protected_by_user: dict[str, set[Path]] = {}
    for row in rows:
        owner = row.get("user_id")
        if not isinstance(owner, str) or not owner:
            continue
        try:
            namespace = paths.project_document_path(owner, row["stored_relpath"])
        except (KeyError, ValueError):
            continue
        protected_by_user.setdefault(owner, set()).add(namespace)
    if user_id is not None:
        user_ids = [user_id]
    else:
        users_root = paths.base_dir / "users"
        user_ids = sorted(entry.name for entry in users_root.iterdir() if entry.is_dir()) if users_root.is_dir() else []
    for uid in user_ids:
        projects_root = paths.user_projects_dir(uid)
        if not projects_root.is_dir():
            continue
        for project_dir in sorted(projects_root.iterdir()):
            documents_dir = project_dir / "documents"
            if documents_dir.is_dir():
                _sweep_project_documents_dir(documents_dir, protected=protected_by_user.get(uid, set()), cutoff_ts=cutoff_ts, report=report)


def _parse_iso(value: object) -> datetime | None:
    text = coerce_iso(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _reconcile_rows(paths: Paths, *, rows: list[dict], guard_cutoff: datetime, report: SweepReport) -> None:
    """Worker-thread: row-side reconciliation — detect, log, NEVER delete.

    A row older than the 24-hour guard whose original is missing or
    size-mismatched is surfaced as ``content_missing`` (§8.3/§15.17): the
    row is the user's only record of the document, so disposal always
    starts with the user moving it to trash; only explicit purge or
    eligible retention purge may remove the trashed row.
    """
    for row in rows:
        created = _parse_iso(row.get("created_at"))
        if created is None or created > guard_cutoff:
            continue
        if not _content_intact(paths, user_id=row["user_id"], row=row):
            report.content_missing.append(row["id"])
            logger.warning(
                "Shelf document %s (%s) content is missing or size-mismatched; row retained and surfaced as content_missing (§8.3)",
                row["id"],
                row.get("name"),
            )


async def run_trash_retention_sweep(
    repo: ProjectDocumentRepository,
    paths: Paths,
    *,
    retention_days: int,
    user_id: str | None,
    now: datetime | None = None,
    include_reconciliation: bool = True,
) -> SweepReport:
    """Run one trash retention sweep (§8.3): expiry purge + reconciliation.

    Triggered lazily by ``GET /api/trash/documents`` (the caller's user) and
    once at gateway startup (``user_id=None`` ⇒ every user). No daemon, no
    scheduler (§15.9). Expired rows go through the same guarded purge as
    manual purges — the candidate's trash timestamp and the cutoff are
    revalidated under the purge lock, so a row restored and later re-trashed
    is not purged on its former expiry. A per-row purge failure keeps that
    row trashed and retryable without aborting the rest of the sweep.

    ``include_reconciliation=False`` skips the row/storage reconciliation and
    leaves it to the reference-aware retention purge, so repeated lazy
    triggers can stay cheap: the expiry purge is an indexed candidate scan,
    while reconciliation is O(all rows + all files) and only bounds external
    interference and orphaned staging behind the 24-hour guard. The retention
    guarantee itself (expired rows become purgeable) is unaffected.
    """
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=retention_days)
    report = SweepReport()
    remove_files = make_purge_file_remover(paths, user_id=user_id)
    for candidate in await repo.purge_candidates(retention_days, now=now, user_id=user_id):
        try:
            purged = await repo.purge(
                candidate["id"],
                retention_cutoff=cutoff,
                expected_trashed_at=candidate.get("trashed_at"),
                remove_files=remove_files,
                user_id=user_id,
            )
        except Exception:
            report.purge_failures += 1
            logger.warning(
                "Retention purge of document %s failed; trashed row retained (retryable)",
                candidate["id"],
                exc_info=True,
            )
            continue
        if purged:
            report.purged += 1
    if include_reconciliation:
        rows = await repo.list_all_for_sweep(user_id=user_id)
        guard_cutoff = now - _ORPHAN_GUARD
        await await_drained(run_file_io(_reconcile_storage, paths, user_id=user_id, rows=rows, guard_cutoff=guard_cutoff, report=report))
        await await_drained(run_file_io(_reconcile_rows, paths, rows=rows, guard_cutoff=guard_cutoff, report=report))
    return report
