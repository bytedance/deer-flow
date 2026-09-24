"""Shared content-signature helper for runtime-editable config files.

Both ``config/app_config.py`` (``config.yaml``) and ``mcp/cache.py``
(``extensions_config.json``) need to detect when a runtime-editable config
file has actually changed, even under conditions a bare mtime comparison
misses: same-second edits, mtime that stays put or moves backward
(``git checkout``, ``cp -p`` / backup restore, ``tar`` / ``rsync`` that
preserve timestamps, object-store / network mounts), or a switch to a
different file whose mtime is <= the previously recorded one.

This module is the single implementation of that ``(mtime, size, sha256)``
signature so the two call sites share one behavior instead of maintaining
verbatim-duplicate copies that can silently drift apart over time.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

# (mtime, size, sha256-hexdigest) recorded for a config file, or the current
# values recomputed for comparison against a previously recorded one. A
# ``None`` digest (third element) means the stat succeeded but the content
# could not be read; the whole tuple is ``None`` when the file could not be
# stat-ed at all (e.g. it does not exist).
ConfigSignature = tuple[float | None, int | None, str | None]


def get_config_signature(config_path: Path) -> ConfigSignature | None:
    """Get cache metadata for *config_path*, including a content digest.

    Returns ``None`` when the file cannot be stat-ed (e.g. it does not
    exist), so callers can treat "no file" as a distinct case from "file
    with unreadable content" (which still yields a partial signature below).
    """
    try:
        stat_result = config_path.stat()
    except OSError:
        return None

    # Always hash the full file here rather than short-circuiting when
    # mtime/size already match a previously recorded signature: swapping in
    # different content of identical byte length within the same second
    # leaves mtime *and* size unchanged, so only the sha256 catches that
    # swap. Skipping the hash on an mtime/size match would reopen the narrow
    # gap this signature was built to close.
    digest = hashlib.sha256()
    try:
        with config_path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return (stat_result.st_mtime, stat_result.st_size, None)

    return (stat_result.st_mtime, stat_result.st_size, digest.hexdigest())
