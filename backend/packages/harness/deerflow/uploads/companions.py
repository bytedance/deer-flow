"""Server-owned ownership records for converted upload Markdown files.

Records live beside ``user-data``, outside the sandbox mount. A matching
basename in the writable uploads directory is never evidence of ownership.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def _records_dir(uploads_dir: Path) -> Path:
    # Production layout is <thread>/user-data/uploads. Tests and embedded
    # callers may use a flat <thread>/uploads layout.
    thread_dir = uploads_dir.parent.parent if uploads_dir.parent.name == "user-data" else uploads_dir.parent
    return thread_dir / "upload-companions"


def _record_path(uploads_dir: Path, filename: str) -> Path:
    digest = hashlib.sha256(filename.encode("utf-8")).hexdigest()
    return _records_dir(uploads_dir) / f"{digest}.json"


def register_companion(original: Path, markdown: Path) -> None:
    """Atomically associate a successfully converted file with its source."""
    if original.parent != markdown.parent or original.suffix.lower() == ".md" or markdown.suffix.lower() != ".md":
        raise ValueError("Companion and source must be in the same uploads directory")
    records_dir = _records_dir(original.parent)
    records_dir.mkdir(parents=True, exist_ok=True)
    record = _record_path(original.parent, original.name)
    source_stat = original.stat(follow_symlinks=False)
    markdown_stat = markdown.stat(follow_symlinks=False)
    fd, staged = tempfile.mkstemp(prefix=".companion-", dir=records_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(
                {
                    "original": original.name,
                    "markdown": markdown.name,
                    "source_identity": [source_stat.st_dev, source_stat.st_ino, source_stat.st_size, source_stat.st_mtime_ns, source_stat.st_ctime_ns],
                    "markdown_identity": [markdown_stat.st_dev, markdown_stat.st_ino, markdown_stat.st_size, markdown_stat.st_ctime_ns],
                },
                output,
            )
        os.replace(staged, record)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)


def unregister_companion(original: Path) -> None:
    _record_path(original.parent, original.name).unlink(missing_ok=True)


def invalidate_overwritten_upload(path: Path) -> None:
    """Forget any relationship involving a file independently re-uploaded in place."""
    unregister_companion(path)
    if path.suffix.lower() != ".md":
        return
    records_dir = _records_dir(path.parent)
    if not records_dir.is_dir():
        return
    for record in records_dir.glob("*.json"):
        try:
            if record.is_symlink():
                continue
            if json.loads(record.read_text(encoding="utf-8")).get("markdown") == path.name:
                record.unlink(missing_ok=True)
        except (OSError, ValueError, AttributeError):
            continue


def resolve_companion(original: Path) -> Path | None:
    """Return only the Markdown named by a valid server-owned record."""
    if original.suffix.lower() == ".md" or not original.is_file() or original.is_symlink():
        return None
    try:
        record = _record_path(original.parent, original.name)
        if record.is_symlink():
            return None
        data = json.loads(record.read_text(encoding="utf-8"))
        name = data["markdown"]
        if data["original"] != original.name or not isinstance(name, str) or Path(name).name != name or not name.endswith(".md"):
            return None
        source_stat = original.stat(follow_symlinks=False)
        # Legacy three-field records cannot establish whether an equal-size
        # source edit happened. Reject them rather than backfilling timestamps.
        if data.get("source_identity") != [source_stat.st_dev, source_stat.st_ino, source_stat.st_size, source_stat.st_mtime_ns, source_stat.st_ctime_ns]:
            source_identity = data.get("source_identity")
            if isinstance(source_identity, list) and len(source_identity) == 3:
                logger.debug("Rejected upload companion for %r: legacy source identity lacks version timestamps", original.name)
            else:
                logger.debug("Rejected upload companion for %r: source identity or version timestamps do not match", original.name)
            return None
        markdown = original.parent / name
        if not markdown.is_file() or markdown.is_symlink():
            return None
        markdown_stat = markdown.stat(follow_symlinks=False)
        if data.get("markdown_identity") != [markdown_stat.st_dev, markdown_stat.st_ino, markdown_stat.st_size, markdown_stat.st_ctime_ns]:
            logger.debug("Rejected upload companion for %r: Markdown identity or version timestamp does not match", original.name)
            return None
        return markdown
    except (OSError, ValueError, KeyError, TypeError):
        return None


def companion_names(uploads_dir: Path) -> set[str]:
    """Names of present, explicitly owned derived Markdown files."""
    return {markdown.name for original in uploads_dir.iterdir() if original.is_file() and (markdown := resolve_companion(original)) is not None}
