"""File helper utilities for atomic writes and common file operations."""

import json
import os
import tempfile
from pathlib import Path


def atomic_write_json(path: Path, data: dict | list) -> None:
    """Atomically write JSON data to a file.

    This uses a temp file + rename pattern to ensure atomicity,
    which prevents data corruption if the process is interrupted.

    Args:
        path: Target file path
        data: JSON-serializable data to write
    """
    # Write to temp file in the same directory
    fd, temp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        # Atomic rename on POSIX systems
        os.replace(temp_path, path)
    except Exception:
        # Clean up temp file on error
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path, content: str) -> None:
    """Atomically write text content to a file.

    This uses a temp file + rename pattern to ensure atomicity.

    Args:
        path: Target file path
        content: Text content to write
    """
    fd, temp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        # Atomic rename on POSIX systems
        os.replace(temp_path, path)
    except Exception:
        # Clean up temp file on error
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
