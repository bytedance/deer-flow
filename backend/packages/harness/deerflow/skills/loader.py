import logging
import os
from pathlib import Path

from deerflow.config.paths import get_paths

from .parser import parse_skill_file
from .types import Skill

logger = logging.getLogger(__name__)


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


def get_runtime_skills_root_path() -> Path:
    """Get the writable runtime skills directory under DEER_FLOW_HOME."""
    return get_paths().base_dir / "skills"


def get_runtime_custom_skills_path() -> Path:
    """Get the writable runtime custom skills directory."""
    return get_runtime_skills_root_path() / "custom"


def get_custom_skills_path(skills_root: Path | None = None) -> Path:
    """Return the effective custom skills directory.

    Runtime-installed custom skills under DEER_FLOW_HOME take precedence when
    present. Otherwise we fall back to the repo/configured ``skills/custom``.
    """
    runtime_custom = get_runtime_custom_skills_path()
    if runtime_custom.exists():
        return runtime_custom

    root = skills_root or get_skills_root_path()
    return root / "custom"


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
    skills = []

    if skills_path is None:
        if use_config:
            try:
                from deerflow.config import get_app_config

                configured_root = get_app_config().skills.get_skills_path()
            except Exception:
                configured_root = get_skills_root_path()
        else:
            configured_root = get_skills_root_path()

        category_paths = {
            "public": configured_root / "public",
            "custom": get_custom_skills_path(configured_root),
        }
    else:
        category_paths = {
            "public": skills_path / "public",
            "custom": skills_path / "custom",
        }

    for category, category_path in category_paths.items():
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

    # Filter by enabled status if requested
    if enabled_only:
        skills = [skill for skill in skills if skill.enabled]

    # Sort by name for consistent ordering
    skills.sort(key=lambda s: s.name)

    return skills
