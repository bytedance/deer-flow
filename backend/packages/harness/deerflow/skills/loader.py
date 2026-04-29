"""Compatibility shim — delegates to ``SkillStorage``.

All new code should import from ``deerflow.skills.storage`` directly.
This module exists only so that existing import paths
(``from deerflow.skills.loader import load_skills``) continue to work
unchanged during the migration period.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig

from .types import Skill

logger = logging.getLogger(__name__)


def get_skills_root_path() -> Path:
    """Return the skills root path via the active SkillStorage.

    Origin: preserved for backwards compatibility.
    """
    from deerflow.skills.storage import get_or_new_skill_storage

    return get_or_new_skill_storage().get_skills_root_path()


def load_skills(
    skills_path: Path | None = None,
    use_config: bool = True,
    enabled_only: bool = False,
    *,
    app_config: AppConfig | None = None,
) -> list[Skill]:
    """Load all skills, delegating to the active SkillStorage.

    Origin: ``deerflow.skills.loader.load_skills`` — signature preserved for
    backwards compatibility.

    Args:
        skills_path: If provided, construct a temporary ``LocalSkillStorage``
            rooted at this path instead of using the singleton.
        use_config: Ignored when ``skills_path`` is given (kept for signature
            compatibility).
        enabled_only: If True, only return enabled skills.
        app_config: Optional ``AppConfig`` forwarded to the storage factory.
    """
    from deerflow.skills.storage import get_or_new_skill_storage

    storage = get_or_new_skill_storage(skills_path=skills_path, app_config=app_config)
    return storage.load_skills(enabled_only=enabled_only)
