import asyncio
import logging
import os
import threading
from pathlib import Path

from .parser import parse_skill_file
from .types import Skill

logger = logging.getLogger(__name__)

_SKILLS_CACHE: dict[tuple[str | None, bool], list[Skill]] = {}
_SKILLS_CACHE_LOCK = threading.Lock()


def get_skills_root_path() -> Path:
    """
    Get the root path of the skills directory.

    Returns:
        Path to the skills directory (deer-flow/skills)
    """
    # loader.py lives at packages/harness/deerflow/skills/loader.py — 5 parents up reaches backend/
    backend_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
    # skills directory is sibling to backend directory
    skills_dir = backend_dir.parent / "skills"
    return skills_dir


def _cache_key(skills_path: Path | None, enabled_only: bool) -> tuple[str | None, bool]:
    return (str(skills_path.resolve()) if skills_path is not None else None, enabled_only)


def invalidate_skills_cache() -> None:
    """Drop the in-process skills cache."""
    with _SKILLS_CACHE_LOCK:
        _SKILLS_CACHE.clear()


def _resolve_skills_path(skills_path: Path | None, use_config: bool) -> Path:
    if skills_path is not None:
        return skills_path

    if use_config:
        try:
            from deerflow.config import get_app_config

            config = get_app_config()
            return config.skills.get_skills_path()
        except Exception:
            # Fallback to default if config fails
            return get_skills_root_path()

    return get_skills_root_path()


def _scan_skills(skills_path: Path) -> list[Skill]:
    if not skills_path.exists():
        return []

    skills_by_name: dict[str, Skill] = {}

    # Scan public and custom directories
    for category in ["public", "custom"]:
        category_path = skills_path / category
        if not category_path.exists() or not category_path.is_dir():
            continue

        for current_root, dir_names, file_names in os.walk(category_path, followlinks=True):
            # Keep traversal deterministic and skip hidden directories.
            dir_names[:] = sorted(name for name in dir_names if not name.startswith("."))
            if "SKILL.md" not in file_names:
                continue

            skill_file = Path(current_root) / "SKILL.md"
            relative_path = skill_file.parent.relative_to(category_path)

            skill = parse_skill_file(skill_file, category=category, relative_path=relative_path)
            if skill:
                skills_by_name[skill.name] = skill

    skills = list(skills_by_name.values())

    # Load skills state configuration and update enabled status
    # NOTE: We use ExtensionsConfig.from_file() instead of get_extensions_config()
    # to always read the latest configuration from disk. This ensures that changes
    # made through the Gateway API (which runs in a separate process) are immediately
    # reflected in the LangGraph Server when loading skills.
    try:
        from deerflow.config.extensions_config import ExtensionsConfig

        extensions_config = ExtensionsConfig.from_file()
        for skill in skills:
            skill.enabled = extensions_config.is_skill_enabled(skill.name, skill.category)
    except Exception as e:
        # If config loading fails, default to all enabled
        logger.warning("Failed to load extensions config: %s", e)

    # Sort by name for consistent ordering
    skills.sort(key=lambda s: s.name)
    return skills


def refresh_skills_cache(skills_path: Path | None = None, use_config: bool = True) -> None:
    """Refresh the in-process skills cache synchronously."""
    resolved = _resolve_skills_path(skills_path, use_config)
    scanned = _scan_skills(resolved)
    full_key = _cache_key(resolved, False)
    enabled_key = _cache_key(resolved, True)
    with _SKILLS_CACHE_LOCK:
        _SKILLS_CACHE[full_key] = scanned
        _SKILLS_CACHE[enabled_key] = [skill for skill in scanned if skill.enabled]


def load_skills(skills_path: Path | None = None, use_config: bool = True, enabled_only: bool = False) -> list[Skill]:
    """
    Load all skills from the skills directory.

    Scans both public and custom skill directories, parsing SKILL.md files
    to extract metadata. The enabled state is determined by the skills_state_config.json file.

    Args:
        skills_path: Optional custom path to skills directory.
                     If not provided and use_config is True, uses path from config.
                     Otherwise defaults to deer-flow/skills
        use_config: Whether to load skills path from config (default: True)
        enabled_only: If True, only return enabled skills (default: False)

    Returns:
        List of Skill objects, sorted by name
    """
    resolved = _resolve_skills_path(skills_path, use_config)
    key = _cache_key(resolved, enabled_only)

    with _SKILLS_CACHE_LOCK:
        cached = _SKILLS_CACHE.get(key)
    if cached is not None:
        return list(cached)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        refresh_skills_cache(resolved, use_config=False)
    else:
        logger.warning("Skills cache miss inside running event loop; returning empty list until cache is refreshed.")
        return []

    with _SKILLS_CACHE_LOCK:
        return list(_SKILLS_CACHE.get(key, []))
