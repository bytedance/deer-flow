"""Shared path helpers for skill files."""

from pathlib import PurePosixPath

from deerflow.skills.types import SKILL_MD_FILE


def normalize_skill_file_path(file_path: str) -> str:
    """Normalize a skill-relative file path and reject traversal."""
    path = file_path.strip().replace("\\", "/")
    if not path:
        return SKILL_MD_FILE

    parts: list[str] = []
    for part in PurePosixPath(path).parts:
        if part in {"", "."}:
            continue
        if part == "..":
            raise ValueError("file_path must not contain parent-directory traversal.")
        if part.startswith("/"):
            raise ValueError("file_path must be relative to the skill directory.")
        parts.append(part)
    return "/".join(parts) if parts else SKILL_MD_FILE
