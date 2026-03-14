"""File I/O helper utilities for DeerFlow."""

import json
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, data: Any, indent: int = 2) -> None:
    """Atomically write JSON data to a file using temp file + rename pattern.

    This ensures that writes are atomic - either the full data is written
    or nothing is written, preventing partial writes that could corrupt
    the file.

    Args:
        path: The file path to write to.
        data: The data to serialize as JSON.
        indent: JSON indentation level (default: 2).

    Raises:
        OSError: If the file cannot be written.
        TypeError: If data is not JSON-serializable.
    """
    fd = tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    )
    try:
        json.dump(data, fd, indent=indent)
        fd.close()
        Path(fd.name).replace(path)
    except BaseException:
        fd.close()
        Path(fd.name).unlink(missing_ok=True)
        raise
