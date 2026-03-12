"""Backward-compatible helpers for the artifacts router."""

from pathlib import Path


def is_text_file_by_content(path: Path, sample_size: int = 8192) -> bool:
    """Check if file is text by examining content for null bytes."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(sample_size)
            return b"\x00" not in chunk
    except Exception:
        return False
