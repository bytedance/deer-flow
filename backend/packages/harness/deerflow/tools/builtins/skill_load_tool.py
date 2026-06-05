import logging
from pathlib import Path
from typing import TYPE_CHECKING

from langchain.tools import tool

from deerflow.config import get_app_config
from deerflow.skills.storage import get_or_new_skill_storage
from deerflow.skills.storage.skill_storage import SkillStorage
from deerflow.skills.types import SKILL_MD_FILE, Skill
from deerflow.tools.types import Runtime

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig

logger = logging.getLogger(__name__)


def _resolve_skill_file(skill: Skill, file_path: str) -> Path:
    if not file_path:
        raise ValueError("file_path must not be empty.")

    relative = Path(file_path)
    if relative.is_absolute():
        raise ValueError("file_path must be relative to the skill directory.")
    if any(part in {"", ".."} for part in relative.parts):
        raise ValueError("file_path must not contain parent-directory traversal.")

    skill_dir = skill.skill_dir.resolve()
    target = (skill_dir / relative).resolve()
    try:
        target.relative_to(skill_dir)
    except ValueError as exc:
        raise ValueError("file_path must resolve within the skill directory.") from exc
    return target


def _get_runtime_app_config(runtime: Runtime) -> "AppConfig | None":
    context = getattr(runtime, "context", None)
    if isinstance(context, dict):
        app_config = context.get("app_config")
        if app_config is not None:
            return app_config

    config = getattr(runtime, "config", None)
    if isinstance(config, dict):
        configurable = config.get("configurable", {})
        if isinstance(configurable, dict):
            app_config = configurable.get("app_config")
            if app_config is not None:
                return app_config
    return None


def _coerce_available_skills(value: object) -> set[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return {SkillStorage.validate_skill_name(value)}
    if isinstance(value, (list, tuple, set, frozenset)):
        if not all(isinstance(item, str) for item in value):
            raise ValueError("available_skills collections must contain only skill name strings.")
        return {SkillStorage.validate_skill_name(item) for item in value}
    raise ValueError("available_skills must be None, a skill name string, or a collection of skill name strings.")


def _get_runtime_available_skills(runtime: Runtime) -> set[str] | None:
    context = getattr(runtime, "context", None)
    if isinstance(context, dict) and "available_skills" in context:
        value = context["available_skills"]
        if value is not None:
            return _coerce_available_skills(value)

    config = getattr(runtime, "config", None)
    if isinstance(config, dict):
        metadata = config.get("metadata", {})
        if isinstance(metadata, dict) and "available_skills" in metadata:
            value = metadata["available_skills"]
            return _coerce_available_skills(value)
    return None


def _truncate_content(content: str, *, app_config: "AppConfig | None") -> str:
    try:
        config = app_config or get_app_config()
        sandbox_cfg = getattr(config, "sandbox", None)
        max_chars = sandbox_cfg.read_file_output_max_chars if sandbox_cfg else 50000
    except Exception:
        max_chars = 50000

    if max_chars is None or max_chars <= 0 or len(content) <= max_chars:
        return content
    return content[:max_chars] + f"\n\n... [truncated: showing first {max_chars} of {len(content)} characters]"


@tool("skill_load", parse_docstring=True)
def skill_load_tool(
    runtime: Runtime,
    skill_name: str,
    file_path: str = SKILL_MD_FILE,
) -> str:
    """Load a skill file from the configured skills directory.

    Use this to read a skill's main SKILL.md file or a referenced resource
    inside that skill directory. Do not use read_file for /mnt/skills paths.

    Args:
        runtime: Injected runtime with current agent context.
        skill_name: The hyphen-case skill name to load.
        file_path: Relative path within the skill directory. Defaults to SKILL.md.
    """
    try:
        normalized_name = SkillStorage.validate_skill_name(skill_name)
        available_skills = _get_runtime_available_skills(runtime)
        if available_skills is not None and normalized_name not in available_skills:
            return f"Error: Skill is not available to this agent: {normalized_name}"

        app_config = _get_runtime_app_config(runtime)
        storage = get_or_new_skill_storage(app_config=app_config) if app_config is not None else get_or_new_skill_storage()
        skill = storage.get_skill(normalized_name, enabled_only=True)
        if skill is None:
            return f"Error: Skill not found or disabled: {normalized_name}"

        target = _resolve_skill_file(skill, file_path)
        if not target.is_file():
            return f"Error: Skill file not found: {normalized_name}/{file_path}"
        content = target.read_text(encoding="utf-8")
        return _truncate_content(content, app_config=app_config) if content else "(empty)"
    except ValueError as e:
        return f"Error: {e}"
    except UnicodeDecodeError:
        return f"Error: Skill file is not valid UTF-8: {skill_name}/{file_path}"
    except Exception:
        logger.exception("Failed to load skill %s/%s", skill_name, file_path)
        return "Error: Failed to load skill."
