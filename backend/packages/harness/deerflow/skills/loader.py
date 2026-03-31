import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from .parser import parse_skill_file
from .types import Skill

if TYPE_CHECKING:
    from deerflow.identity.agent_identity import AgentIdentity

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


def load_skills(skills_path: Path | None = None, use_config: bool = True, enabled_only: bool = False, identity: "AgentIdentity | None" = None) -> list[Skill]:
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
        identity: Optional three-tier identity for identity-scoped extensions loading.
                  When provided and non-global, uses load_layered_extensions(identity)
                  instead of the global ExtensionsConfig to determine enabled state.

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

    # Load skills state configuration and update enabled status.
    # When identity is provided and non-global, use load_layered_extensions to respect
    # per-dept/user skill restrictions (intersection strategy: disabled at any layer → disabled).
    # Always route through load_layered_extensions so that get_paths() is used for path
    # resolution in all cases (testable via monkeypatching).  For a global identity the
    # function reads only the single base-dir extensions_config.json, which is equivalent
    # to ExtensionsConfig.from_file() but honours the configured paths root instead of CWD.
    # NOTE: We use load_layered_extensions() instead of get_extensions_config() to always
    # read the latest configuration from disk, so changes from the Gateway API
    # (separate process) are immediately reflected in the LangGraph Server.
    try:
        from deerflow.config.layered_extensions import load_layered_extensions
        from deerflow.identity.agent_identity import AgentIdentity as _AgentIdentity

        _effective_identity = identity if identity is not None else _AgentIdentity()
        extensions_config = load_layered_extensions(_effective_identity)
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
