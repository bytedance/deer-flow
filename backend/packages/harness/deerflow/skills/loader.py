import os
from pathlib import Path

from .parser import parse_skill_file
from .types import Skill


def get_skills_root_path() -> Path:
    """
    Get the root 路径 of the skills 目录.

    Returns:
        Path to the skills 目录 (deer-flow/skills)
    """
    #    loader.py lives at packages/harness/deerflow/skills/loader.py — 5 parents 上 reaches 后端/


    backend_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
    #    skills 目录 is sibling to 后端 目录


    skills_dir = backend_dir.parent / "skills"
    return skills_dir


def load_skills(skills_path: Path | None = None, use_config: bool = True, enabled_only: bool = False) -> list[Skill]:
    """
    Load all skills from the skills 目录.

    Scans both public and custom skill directories, parsing SKILL.md files
    to extract metadata. The 已启用 状态 is determined by the skills_state_config.json 文件.

    Args:
        skills_path: Optional custom 路径 to skills 目录.
                     If not provided and use_config is True, uses 路径 from 配置.
                     Otherwise defaults to deer-flow/skills
        use_config: Whether to load skills 路径 from 配置 (默认: True)
        enabled_only: If True, only 返回 已启用 skills (默认: False)

    Returns:
        List of Skill objects, sorted by 名称
    """
    if skills_path is None:
        if use_config:
            try:
                from deerflow.config import get_app_config

                config = get_app_config()
                skills_path = config.skills.get_skills_path()
            except Exception:
                #    Fallback to 默认 如果 配置 fails


                skills_path = get_skills_root_path()
        else:
            skills_path = get_skills_root_path()

    if not skills_path.exists():
        return []

    skills = []

    #    Scan public and custom directories


    for category in ["public", "custom"]:
        category_path = skills_path / category
        if not category_path.exists() or not category_path.is_dir():
            continue

        for current_root, dir_names, file_names in os.walk(category_path):
            #    Keep traversal deterministic and skip 隐藏 directories.


            dir_names[:] = sorted(name for name in dir_names if not name.startswith("."))
            if "SKILL.md" not in file_names:
                continue

            skill_file = Path(current_root) / "SKILL.md"
            relative_path = skill_file.parent.relative_to(category_path)

            skill = parse_skill_file(skill_file, category=category, relative_path=relative_path)
            if skill:
                skills.append(skill)

    #    Load skills 状态 configuration and 更新 已启用 status


    #    NOTE: We use ExtensionsConfig.from_file() instead of get_extensions_config()


    #    to always read the 最新 configuration from disk. This ensures that changes


    #    made through the Gateway API (which runs in a separate 处理) are immediately


    #    reflected in the LangGraph Server when 加载中 skills.


    try:
        from deerflow.config.extensions_config import ExtensionsConfig

        extensions_config = ExtensionsConfig.from_file()
        for skill in skills:
            skill.enabled = extensions_config.is_skill_enabled(skill.name, skill.category)
    except Exception as e:
        #    If 配置 加载中 fails, 默认 to all 已启用


        print(f"Warning: Failed to load extensions config: {e}")

    #    Filter by 已启用 status 如果 requested


    if enabled_only:
        skills = [skill for skill in skills if skill.enabled]

    #    Sort by 名称 对于 consistent ordering


    skills.sort(key=lambda s: s.name)

    return skills
