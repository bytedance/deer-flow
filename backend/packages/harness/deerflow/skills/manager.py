"""Compatibility shim — delegates to ``SkillStorage``.

All new code should import from ``deerflow.skills.storage`` directly.
This module exists only so that existing import paths
(``from deerflow.skills.manager import append_history``) continue to work
unchanged during the migration period.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from deerflow.config.app_config import AppConfig, get_app_config  # noqa: F401 — kept for test monkeypatching
from deerflow.skills.storage import get_or_new_skill_storage

HISTORY_FILE_NAME = "HISTORY.jsonl"
HISTORY_DIR_NAME = ".history"
ALLOWED_SUPPORT_SUBDIRS = {"references", "templates", "scripts", "assets"}


def get_skills_root_dir(*, app_config: AppConfig | None = None) -> Path:
    return get_or_new_skill_storage(app_config=app_config).get_skills_root_path()


def get_public_skills_dir(*, app_config: AppConfig | None = None) -> Path:
    return get_or_new_skill_storage(app_config=app_config).get_skills_root_path() / "public"


def get_custom_skills_dir(*, app_config: AppConfig | None = None) -> Path:
    path = get_or_new_skill_storage(app_config=app_config).get_skills_root_path() / "custom"
    path.mkdir(parents=True, exist_ok=True)
    return path


def validate_skill_name(name: str) -> str:
    from deerflow.skills.storage.skill_storage import SkillStorage

    return SkillStorage.validate_skill_name(name)


def get_custom_skill_dir(name: str, *, app_config: AppConfig | None = None) -> Path:
    return get_or_new_skill_storage(app_config=app_config).get_custom_skill_dir(name)


def get_custom_skill_file(name: str, *, app_config: AppConfig | None = None) -> Path:
    return get_or_new_skill_storage(app_config=app_config).get_custom_skill_file(name)


def get_custom_skill_history_dir(*, app_config: AppConfig | None = None) -> Path:
    path = get_or_new_skill_storage(app_config=app_config).get_skills_root_path() / "custom" / ".history"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_skill_history_file(name: str, *, app_config: AppConfig | None = None) -> Path:
    return get_or_new_skill_storage(app_config=app_config).get_skill_history_file(name)


def get_public_skill_dir(name: str, *, app_config: AppConfig | None = None) -> Path:
    return get_or_new_skill_storage(app_config=app_config).get_skills_root_path() / "public" / validate_skill_name(name)


def custom_skill_exists(name: str, *, app_config: AppConfig | None = None) -> bool:
    return get_or_new_skill_storage(app_config=app_config).custom_skill_exists(name)


def public_skill_exists(name: str, *, app_config: AppConfig | None = None) -> bool:
    return get_or_new_skill_storage(app_config=app_config).public_skill_exists(name)


def ensure_custom_skill_is_editable(name: str, *, app_config: AppConfig | None = None) -> None:
    get_or_new_skill_storage(app_config=app_config).ensure_custom_skill_is_editable(name)


def ensure_safe_support_path(name: str, relative_path: str, *, app_config: AppConfig | None = None) -> Path:
    return get_or_new_skill_storage(app_config=app_config).ensure_safe_support_path(name, relative_path)


def validate_skill_markdown_content(name: str, content: str) -> None:
    from deerflow.skills.storage.skill_storage import SkillStorage

    SkillStorage.validate_skill_markdown_content(name, content)


def atomic_write(path: Path, content: str) -> None:
    """Standalone atomic write — preserved for callers that use raw ``Path`` objects."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent)) as tmp_file:
        tmp_file.write(content)
        tmp_path = Path(tmp_file.name)
    tmp_path.replace(path)


def append_history(name: str, record: dict[str, Any], *, app_config: AppConfig | None = None) -> None:
    get_or_new_skill_storage(app_config=app_config).append_history(name, record)


def read_history(name: str, *, app_config: AppConfig | None = None) -> list[dict[str, Any]]:
    return get_or_new_skill_storage(app_config=app_config).read_history(name)


def list_custom_skills(*, app_config: AppConfig | None = None) -> list:
    from deerflow.skills.types import SkillCategory

    return [skill for skill in get_or_new_skill_storage(app_config=app_config).load_skills(enabled_only=False) if skill.category == SkillCategory.CUSTOM]


def read_custom_skill_content(name: str, *, app_config: AppConfig | None = None) -> str:
    return get_or_new_skill_storage(app_config=app_config).read_custom_skill(name)
