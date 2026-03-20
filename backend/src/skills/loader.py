import logging
import os
from pathlib import Path

from .parser import parse_skill_file
from .types import Skill

logger = logging.getLogger(__name__)


def get_skills_root_path() -> Path:
    """
    Get the root path of the skills directory.

    Returns:
        Path to the skills directory (thinktank-ai/skills)
    """
    # backend directory is current file's parent's parent's parent
    backend_dir = Path(__file__).resolve().parent.parent.parent
    # skills directory is sibling to backend directory
    skills_dir = backend_dir.parent / "skills"
    return skills_dir


def load_skills(
    skills_path: Path | None = None,
    plugins_path: Path | None = None,
    use_config: bool = True,
    enabled_only: bool = False,
) -> list[Skill]:
    """
    Load all skills from the skills directory and optionally from plugins.

    Scans both public and custom skill directories, plus plugin skills directories,
    parsing SKILL.md files to extract metadata. The enabled state is determined by
    the extensions_config.json file.

    Args:
        skills_path: Optional custom path to skills directory.
                     If not provided and use_config is True, uses path from config.
                     Otherwise defaults to thinktank-ai/skills
        plugins_path: Optional path to installed plugins directory.
                      If not provided and use_config is True, uses path from config.
                      Plugin skills are scanned from <plugin>/skills/ subdirectories.
        use_config: Whether to load skills path from config (default: True)
        enabled_only: If True, only return enabled skills (default: False)

    Returns:
        List of Skill objects, sorted by name
    """
    if skills_path is None:
        if use_config:
            try:
                from src.config import get_app_config

                config = get_app_config()
                skills_path = config.skills.get_skills_path()
            except Exception:
                # Fallback to default if config fails
                skills_path = get_skills_root_path()
        else:
            skills_path = get_skills_root_path()

    skills = []

    # Scan public and custom directories
    if skills_path.exists():
        skills.extend(_scan_skills_directory(skills_path))

    # Scan plugin skills directories
    if plugins_path is None and use_config:
        try:
            from src.config import get_app_config

            config = get_app_config()
            if hasattr(config, "plugins") and config.plugins:
                plugins_path = config.plugins.get_plugins_path()
        except Exception:
            pass

    if plugins_path and plugins_path.exists():
        skills.extend(_scan_plugin_skills(plugins_path))

    # Load skills state configuration and update enabled status
    # NOTE: We use ExtensionsConfig.from_file() instead of get_extensions_config()
    # to always read the latest configuration from disk. This ensures that changes
    # made through the Gateway API (which runs in a separate process) are immediately
    # reflected in the LangGraph Server when loading skills.
    try:
        from src.config.extensions_config import ExtensionsConfig

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


def _scan_skills_directory(skills_path: Path) -> list[Skill]:
    """Scan the traditional skills/public and skills/custom directories.

    Args:
        skills_path: Path to the skills root directory.

    Returns:
        List of discovered Skill objects.
    """
    skills: list[Skill] = []

    for category in ["public", "custom"]:
        category_path = skills_path / category
        if not category_path.exists() or not category_path.is_dir():
            continue

        for current_root, dir_names, file_names in os.walk(category_path):
            # Keep traversal deterministic and skip hidden directories.
            dir_names[:] = sorted(name for name in dir_names if not name.startswith("."))
            if "SKILL.md" not in file_names:
                continue

            skill_file = Path(current_root) / "SKILL.md"
            relative_path = skill_file.parent.relative_to(category_path)

            skill = parse_skill_file(skill_file, category=category, relative_path=relative_path)
            if skill:
                skills.append(skill)

    return skills


def _scan_plugin_skills(plugins_path: Path) -> list[Skill]:
    """Scan installed plugins for skills in their skills/ subdirectories.

    Plugin skills get the category 'plugin:<plugin_name>'.

    Args:
        plugins_path: Path to the installed plugins directory.

    Returns:
        List of discovered Skill objects from plugins.
    """
    skills: list[Skill] = []

    if not plugins_path.exists() or not plugins_path.is_dir():
        return skills

    for plugin_dir in sorted(plugins_path.iterdir()):
        if not plugin_dir.is_dir() or plugin_dir.name.startswith("."):
            continue

        plugin_skills_dir = plugin_dir / "skills"
        if not plugin_skills_dir.exists() or not plugin_skills_dir.is_dir():
            continue

        plugin_name = plugin_dir.name
        category = f"plugin:{plugin_name}"

        for skill_dir in sorted(plugin_skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue

            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue

            relative_path = skill_file.parent.relative_to(plugin_skills_dir)
            skill = parse_skill_file(skill_file, category=category, relative_path=relative_path)
            if skill:
                skills.append(skill)

    return skills
