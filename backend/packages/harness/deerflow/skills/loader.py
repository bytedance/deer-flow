import logging
import os
import shutil
import subprocess
from importlib.util import find_spec
from pathlib import Path

from .parser import parse_skill_file
from .types import Skill

logger = logging.getLogger(__name__)
_CHECKED_SKILL_DEPENDENCIES: set[str] = set()


def _has_module_spec(module_name: str) -> bool:
    try:
        return find_spec(module_name) is not None
    except Exception:
        return False


def ensure_skill_dependencies(skill: Skill) -> None:
    """Ensure declared skill dependencies are installed (pip only)."""
    skill_key = f"{skill.category}:{skill.name}"
    if skill_key in _CHECKED_SKILL_DEPENDENCIES:
        return
    _CHECKED_SKILL_DEPENDENCIES.add(skill_key)

    dependencies = skill.dependencies
    if not dependencies or not dependencies.pip:
        return

    missing_packages: list[str] = []
    for package in dependencies.pip:
        if not isinstance(package, str) or not package.strip():
            continue

        normalized_name = package.replace("-", "_")
        if not _has_module_spec(package) and not _has_module_spec(normalized_name):
            missing_packages.append(package)

    if not missing_packages:
        return

    command = ["uv", "pip", "install", *missing_packages] if shutil.which("uv") else ["pip", "install", *missing_packages]
    try:
        subprocess.run(command)
    except FileNotFoundError:
        if command[0] == "uv":
            subprocess.run(["pip", "install", *missing_packages])


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
    if skills_path is None:
        if use_config:
            try:
                from deerflow.config import get_app_config

                config = get_app_config()
                skills_path = config.skills.get_skills_path()
            except Exception:
                # Fallback to default if config fails
                skills_path = get_skills_root_path()
        else:
            skills_path = get_skills_root_path()

    if not skills_path.exists():
        return []

    skills = []

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
                skills.append(skill)

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

    for skill in skills:
        if skill.enabled:
            ensure_skill_dependencies(skill)

    # Filter by enabled status if requested
    if enabled_only:
        skills = [skill for skill in skills if skill.enabled]

    # Sort by name for consistent ordering
    skills.sort(key=lambda s: s.name)

    return skills
