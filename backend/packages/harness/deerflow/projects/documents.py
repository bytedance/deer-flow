"""Project document shelf service: staging, atomic insert, conversion.

Implements the Phase-2 shelf-insert atomicity (spec §6.3): bytes are staged
under ``.staging/{uuid}``, hashed, then — inside the repository's one
transaction (active-project row lock → dedup select → insert) — atomically
renamed into the document's exclusive namespace **before** the row exists
(file-before-row, §10.3). A dedup hit removes staging and returns the existing
row (the first writer's name wins, §10.9); a failed insert cleans up only its
own namespace, best-effort. Every filesystem operation runs off the event
loop via :func:`deerflow.utils.file_io.run_file_io`.

Files are immutable and hash-qualified: ``stored_relpath`` (relative to
``users/{user_id}/projects/``) embeds the content hash and the row's own
document ID, so rows never share bytes and a re-upload after trash lands in a
fresh namespace (§6.2). Conversion is lazy: a convertible original is turned
into ``derived/converted.md`` on first read, written through a temporary file
and an atomic rename, and only when ``uploads.auto_convert_documents`` is on
(§6.4, §7.3).
"""

from __future__ import annotations

import asyncio
import codecs
import hashlib
import logging
import os
import shutil
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deerflow.config.paths import Paths
from deerflow.utils.file_conversion import CONVERTIBLE_EXTENSIONS, convert_file_to_markdown
from deerflow.utils.file_io import run_file_io
from deerflow.utils.text_detection import is_text_file_by_content

if TYPE_CHECKING:
    from deerflow.persistence.projects import ProjectDocumentRepository

logger = logging.getLogger(__name__)

_MAX_FILENAME_BYTES = 255


class ShelfUploadTooLargeError(Exception):
    """Raised when staged bytes exceed ``uploads.max_file_size`` (mapped to 413)."""


def validate_shelf_filename(name: str) -> str:
    """Normalize and validate a shelf display filename; ``ValueError`` ⇒ 400.

    The display filename occupies its own path component (no hash prefix or
    suffix), so it must be a bare, non-empty filename within the 255 UTF-8
    byte filesystem limit — path separators are rejected outright rather than
    stripped (§6.5).
    """
    candidate = name.strip() if name else ""
    if not candidate:
        raise ValueError("Filename is empty")
    if "/" in candidate or "\\" in candidate:
        raise ValueError(f"Filename contains a path separator: {name!r}")
    if candidate in {".", ".."}:
        raise ValueError(f"Filename is unsafe: {name!r}")
    if len(candidate.encode("utf-8")) > _MAX_FILENAME_BYTES:
        raise ValueError(f"Filename exceeds {_MAX_FILENAME_BYTES} UTF-8 bytes")
    return candidate


def shelf_relpath(project_id: str, sha256: str, document_id: str) -> str:
    """Content-addressed namespace root for one row, relative to ``users/{user_id}/projects/``."""
    return f"{project_id}/documents/{sha256[:2]}/{sha256}/{document_id}"


def original_file_path(paths: Paths, *, user_id: str, row: dict) -> Path:
    """Absolute host path of a row's immutable original bytes."""
    return resolve_document_paths(paths, user_id=user_id, relpath=row["stored_relpath"], name=row["name"])[0]


def converted_markdown_path(paths: Paths, *, user_id: str, row: dict) -> Path:
    """Absolute host path of a row's optional ``derived/converted.md`` companion."""
    return resolve_document_paths(paths, user_id=user_id, relpath=row["stored_relpath"], name=row["name"])[1]


def resolve_document_paths(paths: Paths, *, user_id: str, relpath: str, name: str) -> tuple[Path, Path]:
    """Resolve a row's ``(original, derived)`` host paths — worker-thread only on async paths.

    ``Paths.project_document_path`` resolves symlinks against the real
    filesystem, so async callers MUST dispatch this through ``run_file_io``
    (filesystem-offload convention); the helper itself stays sync because it
    is also used from worker contexts already off the loop.
    """
    namespace = paths.project_document_path(user_id, relpath)
    return namespace / "original" / name, namespace / "derived" / "converted.md"


def _content_intact(paths: Paths, *, user_id: str, row: dict) -> bool:
    """Worker-thread: resolve the original and verify it exists and matches the row's recorded size."""
    original = original_file_path(paths, user_id=user_id, row=row)
    try:
        return original.stat().st_size == int(row.get("size_bytes") or -1)
    except OSError:
        return False


async def check_document_content(paths: Paths, *, user_id: str, row: dict) -> bool:
    """True when the row's immutable original exists and matches ``size_bytes``.

    The one content check shared by the text serving path, restore (under
    the document lock), the content endpoint, and the retention sweep's row
    reconciliation (§8.3/§11): missing or size-mismatched bytes mean external
    interference — reported as ``content_missing``, never served, repaired,
    or treated as an empty document.
    """
    return await run_file_io(_content_intact, paths, user_id=user_id, row=row)


def _content_intact_batch(paths: Paths, *, user_id: str, rows: list[dict]) -> list[bool]:
    """Worker-thread: existence+size check for a whole page of rows in one offload pass."""
    return [_content_intact(paths, user_id=user_id, row=row) for row in rows]


@dataclass(slots=True)
class StagedDocument:
    """Bytes staged under ``.staging/`` with their content address."""

    staging_path: Path
    sha256: str
    size_bytes: int


def _open_staging(staging_dir: Path, staging_path: Path):
    """Worker-thread: create the staging directory and open the staging file."""
    staging_dir.mkdir(parents=True, exist_ok=True)
    return open(staging_path, "wb")


def _close_and_unlink(handle: Any, staging_path: Path) -> None:
    try:
        handle.close()
    finally:
        staging_path.unlink(missing_ok=True)


async def stage_document_bytes(paths: Paths, *, user_id: str, project_id: str, chunks: AsyncIterator[bytes] | list[bytes], max_bytes: int) -> StagedDocument:
    """Stage upload/promote bytes off-loop, enforcing the single-file size cap.

    Chunks are streamed to ``.staging/{uuid}`` (writes offloaded one by one,
    the uploads router's discipline) while the content hash accumulates.
    ``max_bytes`` is the thread-upload limit (``uploads.max_file_size``) —
    the shelf deliberately reuses it instead of growing a second knob with
    the same meaning (§6.4). Overflow raises :class:`ShelfUploadTooLargeError`
    (the route maps it to 413, mirroring the uploads router) and leaves no
    staging file behind.
    """
    staging_dir = paths.project_documents_dir(user_id, project_id) / ".staging"
    staging_path = staging_dir / uuid.uuid4().hex
    handle = await run_file_io(_open_staging, staging_dir, staging_path)
    digest = hashlib.sha256()
    size = 0

    async def _aiter() -> AsyncIterator[bytes]:
        if isinstance(chunks, list):
            for chunk in chunks:
                yield chunk
        else:
            async for chunk in chunks:
                yield chunk

    try:
        async for chunk in _aiter():
            size += len(chunk)
            if size > max_bytes:
                raise ShelfUploadTooLargeError(f"File exceeds the {max_bytes}-byte limit")
            digest.update(chunk)
            await run_file_io(handle.write, chunk)
        await run_file_io(handle.close)
    except Exception:
        await run_file_io(_close_and_unlink, handle, staging_path)
        raise
    return StagedDocument(staging_path=staging_path, sha256=digest.hexdigest(), size_bytes=size)


def _place_staging(staging_path: Path, final_path: Path) -> None:
    """Atomically move staged bytes into the document's exclusive namespace."""
    final_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(staging_path, final_path)
    except Exception:
        staging_path.unlink(missing_ok=True)
        raise


def _remove_staging(staging_path: Path) -> None:
    staging_path.unlink(missing_ok=True)


def _remove_namespace(paths: Paths, *, user_id: str, relpath: str) -> None:
    """Best-effort removal of one document's exclusive namespace (never another row's)."""
    shutil.rmtree(paths.project_document_path(user_id, relpath), ignore_errors=True)


async def add_staged_document(
    repo: ProjectDocumentRepository,
    paths: Paths,
    *,
    user_id: str,
    project_id: str,
    name: str,
    staged: StagedDocument,
    source_thread_id: str | None = None,
    source_kind: str | None = None,
    source_name: str | None = None,
) -> tuple[dict, bool] | None:
    """Publish staged bytes as a shelf row, or fold into the dedup hit.

    Returns ``(row, created)`` — ``created`` is ``False`` for a dedup hit, in
    which case the returned row is the pre-existing one (its name and
    provenance win, §10.9) and the staged bytes are discarded. ``None`` means
    the project is missing, foreign, or archived (the route maps it to 404).
    A failure removes this document's namespace only when the row PROVABLY
    does not exist: a post-commit failure (e.g. the insert's trailing
    refresh) leaves the live row serving its placed bytes and is reported as
    success, and an indeterminate liveness check leaves the namespace for
    the reference-aware sweep (§8.3).
    """
    document_id = uuid.uuid4().hex
    relpath = shelf_relpath(project_id, staged.sha256, document_id)
    # Symlink-resolving lookup — offloaded like every filesystem touch here.
    final_path = (await run_file_io(resolve_document_paths, paths, user_id=user_id, relpath=relpath, name=name))[0]

    async def _place() -> None:
        await run_file_io(_place_staging, staged.staging_path, final_path)

    try:
        row = await repo.insert_active(
            project_id,
            document_id=document_id,
            name=name,
            relpath=relpath,
            sha256=staged.sha256,
            size_bytes=staged.size_bytes,
            source_thread_id=source_thread_id,
            source_kind=source_kind,
            source_name=source_name,
            place_file=_place,
            user_id=user_id,
        )
    except Exception:
        # ``insert_active`` owns its commit: a failure may surface AFTER the
        # row committed (e.g. its trailing refresh), so the placed namespace
        # is removed only when the row PROVABLY does not exist. When the row
        # is live the insert effectively succeeded — the shelf already serves
        # these bytes — so return it instead of raising; when liveness cannot
        # be determined, leave the namespace for the reference-aware
        # retention sweep (§8.3), which only collects unreferenced files and
        # protects any row's namespace. The probe includes TRASHED rows: a
        # row raced into trash (or a trashing project deletion) before the
        # re-check still owns the placed bytes — trash is recoverable, so
        # deleting the namespace would destroy a recoverable document.
        await run_file_io(_remove_staging, staged.staging_path)
        committed: dict | None
        try:
            committed = await repo.get(document_id, include_trashed=True, user_id=user_id)
        except Exception:
            committed = None
            row_provably_absent = False
            logger.warning(
                "Shelf insert of %s failed and the liveness re-check failed too; leaving the namespace for the retention sweep",
                document_id,
                exc_info=True,
            )
        else:
            row_provably_absent = committed is None
        if committed is not None:
            if committed.get("trashed_at") is None:
                logger.warning("Shelf insert of %s raised after commit; the row is live — keeping its namespace and reporting success", document_id)
                return committed, True
            # Committed but raced into trash before the re-check: keep the
            # bytes recoverable in trash and surface the failure rather than
            # presenting a trashed row as created.
            logger.warning("Shelf insert of %s raised after commit and the row was trashed meanwhile; keeping its namespace in trash", document_id)
        elif row_provably_absent:
            # Confirmed rollback: the bytes are unreferenced — clean up only
            # this document's own namespace (§6.3).
            await run_file_io(_remove_namespace, paths, user_id=user_id, relpath=relpath)
        raise
    if row is None:
        # Missing/foreign/archived project: nothing was placed or inserted.
        await run_file_io(_remove_staging, staged.staging_path)
        return None
    if row["id"] != document_id:
        # Dedup hit: the existing row wins; discard the staged duplicate.
        await run_file_io(_remove_staging, staged.staging_path)
        return row, False
    return row, True


def _convert_in_thread(original: Path, output_path: Path) -> Path | None:
    """Run the async conversion engine on a private loop inside the worker.

    ``convert_file_to_markdown`` offloads its own heavy work (>1 MiB) but
    stats and writes on its caller's loop; running the whole coroutine here
    keeps every byte of the conversion path off the serving event loop.
    """
    return asyncio.run(convert_file_to_markdown(original, output_path=output_path))


def _convert_and_publish(original: Path, derived: Path) -> bool:
    """Worker-thread body: convert to a temp file, then atomically publish.

    The temp file lives beside the final path (same filesystem) so the
    rename is atomic: readers only ever see a complete ``converted.md`` or
    none at all. A conversion failure publishes nothing and removes the temp.
    """
    derived.parent.mkdir(parents=True, exist_ok=True)
    temp_path = derived.parent / f".{derived.name}.{uuid.uuid4().hex}.tmp"
    try:
        produced = _convert_in_thread(original, temp_path)
        if produced is None:
            return False
        os.replace(produced, derived)
        return True
    except Exception:
        logger.warning("Failed to convert shelf document %s", original, exc_info=True)
        temp_path.unlink(missing_ok=True)
        return False
    finally:
        temp_path.unlink(missing_ok=True)


async def ensure_converted_markdown(repo: ProjectDocumentRepository, paths: Paths, *, user_id: str, row: dict, auto_convert: bool) -> tuple[Path | None, str | None]:
    """Return ``(converted_path, None)`` or ``(None, reason)``, converting on first read.

    Conversion runs — and ``derived/converted.md`` is published — while the
    repository holds the document row lock, with ownership, shelf membership
    and active state revalidated AFTER locking (§6.3): a trash/purge that
    committed first makes this decline as ``content_missing`` without
    converting or publishing anything, and one arriving during conversion
    blocks on the row lock and then proceeds. The temp-file + atomic
    ``os.replace`` publish stays inside the lock, so no partial converted
    text is ever exposed. The published companion is valid for the lifetime
    of the row's immutable original and never needs invalidation (§6.2,
    §10.9). ``reason`` is one of ``"conversion_disabled"`` (auto-convert
    off, §7.3), ``"content_missing"`` (row no longer live), or ``"binary"``
    (not convertible, or the conversion itself failed).
    """
    if not auto_convert:
        return None, "conversion_disabled"
    original, derived = await run_file_io(resolve_document_paths, paths, user_id=user_id, relpath=row["stored_relpath"], name=row["name"])
    if original.suffix.lower() not in CONVERTIBLE_EXTENSIONS:
        return None, "binary"
    if await run_file_io(derived.is_file):
        return derived, None

    async def _convert(_locked_row: dict) -> bool:
        # Re-check under the lock: a conversion that blocked on this row's
        # lock may already have been published by the lock's previous holder.
        if await run_file_io(derived.is_file):
            return True
        return await run_file_io(_convert_and_publish, original, derived)

    locked = await repo.convert_under_live_lock(row["id"], project_id=row["project_id"], convert=_convert, user_id=user_id)
    if locked is None:
        # Purged/trashed (or foreign) between the caller's read and the
        # locked revalidation: decline without publishing anything (§6.3).
        return None, "content_missing"
    _locked_row, published = locked
    return (derived, None) if published else (None, "binary")


async def read_text_serving_path(repo: ProjectDocumentRepository, paths: Paths, *, user_id: str, row: dict, auto_convert: bool) -> tuple[Path | None, str | None]:
    """Resolve which file serves a row's text reads, or why none can.

    Returns ``(path, None)`` for a servable text source — the cached
    ``derived/converted.md``, the original when it samples as text, or a
    freshly converted companion — and ``(None, reason)`` otherwise, where
    ``reason`` is one of ``"content_missing"``, ``"conversion_disabled"`` or
    ``"binary"`` so the caller can produce the §11 error without re-deriving
    the classification. The immutable ORIGINAL is validated (existence AND
    recorded size, the shared §8.3 check) before either serving source is
    selected: a truncated or zero-byte original is ``content_missing``, never
    served as complete, and the derived companion is only servable while its
    owning original validates (§6.2). A convertible extension
    (``CONVERTIBLE_EXTENSIONS``) takes the conversion path — or the
    ``conversion_disabled`` decline — BEFORE the text heuristic: a
    null-free head (e.g. an ASCII85 PDF) must never be raw-served as text.
    Genuine text extensions keep the sampled-head heuristic (no
    ``mime``/``is_text`` columns exist by design, §6.1).
    """
    if not await check_document_content(paths, user_id=user_id, row=row):
        return None, "content_missing"
    original, derived = await run_file_io(resolve_document_paths, paths, user_id=user_id, relpath=row["stored_relpath"], name=row["name"])
    if await run_file_io(derived.is_file):
        return derived, None
    if original.suffix.lower() in CONVERTIBLE_EXTENSIONS:
        return await ensure_converted_markdown(repo, paths, user_id=user_id, row=row, auto_convert=auto_convert)
    if await run_file_io(is_text_file_by_content, original):
        return original, None
    return None, "binary"


#: Bounded decode window: reads stop once the requested character page is full.
_TEXT_READ_CHUNK = 65536

#: Bounded process-local LRU of decoded character counts, keyed by content
#: identity ``(document_id, sha256)``. Documents are immutable within a row's
#: lifetime (§6.2/§10.9) and ids are never reused, so a purge simply orphans
#: an entry until LRU eviction — no invalidation hook needed.
_CHAR_COUNT_CACHE: OrderedDict[tuple[str, str], int] = OrderedDict()
_CHAR_COUNT_CACHE_MAX = 256


def _read_text_window(path: Path, *, offset: int, limit: int) -> str:
    """Worker-thread: decode only enough of *path* to fill ``[offset, offset+limit)``.

    Incremental UTF-8 decode (replacement-tolerant, split-sequence safe) over
    bounded chunks: the full decoded string is never materialized and reading
    stops as soon as the window is filled, so an early page of a multi-MiB
    document never reads the whole file.
    """
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    parts: list[str] = []
    position = 0  # decoded characters seen so far
    end = offset + limit
    with open(path, "rb") as handle:
        while position < end:
            chunk = handle.read(_TEXT_READ_CHUNK)
            final = not chunk
            text = decoder.decode(chunk, final)
            if not text:
                if final:
                    break
                continue
            if position + len(text) > offset:
                parts.append(text[max(offset - position, 0) :])
            position += len(text)
            if final:
                break
    return "".join(parts)[:limit]


def _count_text_chars(path: Path) -> int:
    """Worker-thread: full scan-decode COUNT without materializing the string."""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    total = 0
    with open(path, "rb") as handle:
        while chunk := handle.read(_TEXT_READ_CHUNK):
            total += len(decoder.decode(chunk))
    return total + len(decoder.decode(b"", True))


def _cached_char_count(document_id: str, sha256: str, path: Path) -> int:
    """Worker-thread: character count of an immutable document, cached by content identity."""
    key = (document_id, sha256)
    cached = _CHAR_COUNT_CACHE.get(key)
    if cached is not None:
        _CHAR_COUNT_CACHE.move_to_end(key)
        return cached
    total = _count_text_chars(path)
    _CHAR_COUNT_CACHE[key] = total
    while len(_CHAR_COUNT_CACHE) > _CHAR_COUNT_CACHE_MAX:
        _CHAR_COUNT_CACHE.popitem(last=False)
    return total


async def read_document_text_window(path: Path, *, offset: int, limit: int) -> str:
    """Decode the ``[offset, offset+limit)`` character window of a serving file, off-loop."""
    return await run_file_io(_read_text_window, path, offset=offset, limit=limit)


async def document_char_count(*, document_id: str, sha256: str, path: Path) -> int:
    """Total decoded characters of a serving file, off-loop and content-identity cached."""
    return await run_file_io(_cached_char_count, document_id, sha256, path)


def auto_convert_documents_enabled(app_config: Any) -> bool:
    """Return whether host-side document conversion is enabled (secure default off).

    Mirrors the uploads router's reader: a malformed value declines rather
    than crashing, and stringly-typed YAML booleans are honored.
    """
    try:
        uploads_cfg = getattr(app_config, "uploads", None)
        raw = uploads_cfg.get("auto_convert_documents", False) if isinstance(uploads_cfg, dict) else getattr(uploads_cfg, "auto_convert_documents", False)
        if isinstance(raw, str):
            return raw.strip().lower() in {"1", "true", "yes", "on"}
        return bool(raw)
    except Exception:
        return False


class ShelfContentMissingError(Exception):
    """A live row's original bytes are absent or size-mismatched (§11 ``content_missing``)."""


async def read_file_chunks(path: Path, *, chunk_size: int = 65536) -> AsyncIterator[bytes]:
    """Yield one file's bytes with every read off the event loop.

    Shared by the from-thread promote path (thread file → shelf staging) and
    the attach path (staged shelf copy → thread-upload ingestion).
    """

    def _open() -> Any:
        return open(path, "rb")

    handle = await run_file_io(_open)
    try:
        while chunk := await run_file_io(handle.read, chunk_size):
            yield chunk
    finally:
        await run_file_io(handle.close)


def _copy_original_under_lock(paths: Paths, staging_path: Path, *, user_id: str, row: dict) -> None:
    """Worker-thread: copy a live document's original to a stable staging file.

    Runs inside the document row lock (``stage_live_copy``): the bytes are
    immutable, so an absent file or a size disagreement means external
    interference — reported as ``content_missing``, never copied (§8.3).
    Resolving the original's path happens here too: ``project_document_path``
    resolves symlinks against the real filesystem, so it stays off the
    caller's event loop.
    """
    source = original_file_path(paths, user_id=user_id, row=row)
    expected_size = row.get("size_bytes")
    if not source.is_file():
        raise ShelfContentMissingError("original bytes are missing")
    if expected_size is not None and source.stat().st_size != expected_size:
        raise ShelfContentMissingError("original size disagrees with the row")
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, staging_path)


async def stage_document_copy_for_attach(
    repo: ProjectDocumentRepository,
    paths: Paths,
    *,
    user_id: str,
    project_id: str,
    document_id: str,
) -> tuple[dict, Path] | None:
    """Stage a stable copy of a live document's original under its row lock.

    §7.3 item 3: attach is serialized against purge/trash — the copy runs
    while the repository holds the document row lock, then the lock is
    released BEFORE the caller performs sandbox allocation/network sync.
    The copy lands in the project shelf's ``.staging/`` (a crash leftover is
    collected by the retention sweep's 24-hour orphan guard, §8.3) and is
    the caller's responsibility to unlink. ``None`` means the document is
    missing, foreign, trashed, or not on this project's shelf (the route
    maps it to 404); :class:`ShelfContentMissingError` maps to 409.
    """
    staging_path = paths.project_documents_dir(user_id, project_id) / ".staging" / f"attach-{uuid.uuid4().hex}"

    async def _copy(row: dict) -> Path:
        await run_file_io(_copy_original_under_lock, paths, staging_path, user_id=user_id, row=row)
        return staging_path

    result = await repo.stage_live_copy(document_id, project_id=project_id, stage=_copy, user_id=user_id)
    if result is None:
        return None
    row, staged_path = result
    return row, staged_path
