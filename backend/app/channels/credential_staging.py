"""Best-effort cleanup for identifiable crash-orphaned credential copies.

All calls touch disk and belong on the existing worker-thread state-load paths.
Only the reserved per-target namespace is owned here: anonymous temporary files
from older releases cannot safely be attributed to a credential writer.
"""

from __future__ import annotations

import logging
import os
import stat
import time
from contextlib import suppress
from pathlib import Path

logger = logging.getLogger(__name__)

_STALE_AFTER_SECONDS = 24 * 60 * 60


def credential_staging_prefix(target: Path) -> str:
    """Reserve a namespace for this target without changing tempfile's 0600 mode."""
    return f".{target.name}.deerflow-"


def cleanup_stale_credential_staging(target: Path) -> None:
    """Remove only this store's regular staging files older than a day.

    Scan siblings only, never attachments or symlink targets. The age guard
    leaves fresh files to concurrent writers. Failure to inspect or remove a
    stale copy, including failure to report it, must not stop credential loading.
    Missing files are expected when a peer completes its atomic publication.
    """
    prefix = credential_staging_prefix(target)
    cutoff = time.time() - _STALE_AFTER_SECONDS
    try:
        with os.scandir(target.parent) as entries:
            for entry in entries:
                if not entry.name.startswith(prefix) or not entry.name.endswith(".tmp"):
                    continue
                try:
                    metadata = entry.stat(follow_symlinks=False)
                    if not stat.S_ISREG(metadata.st_mode) or metadata.st_mtime >= cutoff:
                        continue
                    Path(entry.path).unlink(missing_ok=True)
                except FileNotFoundError:
                    continue
                except OSError:
                    with suppress(Exception):
                        logger.warning("Failed to clean stale channel credential staging file %s", entry.path, exc_info=True)
    except FileNotFoundError:
        return
    except OSError:
        with suppress(Exception):
            logger.warning("Failed to scan channel credential staging directory %s", target.parent, exc_info=True)
