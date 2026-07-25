"""Shared classification for skill files that require executable scanning."""

from pathlib import Path

_CODE_SUFFIXES = frozenset({".bash", ".cjs", ".js", ".mjs", ".php", ".pl", ".ps1", ".py", ".rb", ".sh", ".ts", ".zsh"})


def is_script_path(rel_path: Path) -> bool:
    """Return whether *rel_path* belongs to the top-level scripts directory."""
    return bool(rel_path.parts) and rel_path.parts[0] == "scripts"


def is_skill_code_file(rel_path: Path, *, has_shebang: bool = False) -> bool:
    """Classify a skill file for the executable LLM scan policy.

    Code suffixes count anywhere in the skill tree. Extensionless files count
    when their content starts with a shebang.
    """
    return is_script_path(rel_path) or rel_path.suffix.lower() in _CODE_SUFFIXES or (not rel_path.suffix and has_shebang)
