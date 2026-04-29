from __future__ import annotations

from .storage import LocalSkillStorage, SkillStorage, get_skill_storage
from .types import Skill
from .validation import ALLOWED_FRONTMATTER_PROPERTIES, _validate_skill_frontmatter

__all__ = [
    "load_skills",
    "get_skills_root_path",
    "Skill",
    "ALLOWED_FRONTMATTER_PROPERTIES",
    "_validate_skill_frontmatter",
    "install_skill_from_archive",
    "ainstall_skill_from_archive",
    "SkillAlreadyExistsError",
    "SkillSecurityScanError",
    "SkillStorage",
    "LocalSkillStorage",
    "get_skill_storage",
]

_INSTALLER_ATTRS = frozenset(["SkillAlreadyExistsError", "SkillSecurityScanError", "ainstall_skill_from_archive", "install_skill_from_archive"])
_LOADER_ATTRS = frozenset(["load_skills", "get_skills_root_path"])


def __getattr__(name: str):
    if name in _INSTALLER_ATTRS:
        from .installer import (  # noqa: PLC0415
            SkillAlreadyExistsError,
            SkillSecurityScanError,
            ainstall_skill_from_archive,
            install_skill_from_archive,
        )

        g = globals()
        g["SkillAlreadyExistsError"] = SkillAlreadyExistsError
        g["SkillSecurityScanError"] = SkillSecurityScanError
        g["ainstall_skill_from_archive"] = ainstall_skill_from_archive
        g["install_skill_from_archive"] = install_skill_from_archive
        return g[name]

    if name in _LOADER_ATTRS:
        from .loader import get_skills_root_path, load_skills  # noqa: PLC0415

        g = globals()
        g["load_skills"] = load_skills
        g["get_skills_root_path"] = get_skills_root_path
        return g[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
