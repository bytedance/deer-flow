"""Utilities for managing custom skills and their history."""

from __future__ import annotations

import json
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deerflow.config import get_app_config
from deerflow.config.app_config import AppConfig
from deerflow.skills.loader import load_skills
from deerflow.skills.validation import _validate_skill_frontmatter

SKILL_FILE_NAME = "SKILL.md"
HISTORY_FILE_NAME = "HISTORY.jsonl"
HISTORY_DIR_NAME = ".history"
ALLOWED_SUPPORT_SUBDIRS = {"references", "templates", "scripts", "assets"}
_SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def get_skills_root_dir(*, app_config: AppConfig | None = None) -> Path:
    config = app_config or get_app_config()
    return config.skills.get_skills_path()


def get_public_skills_dir(*, app_config: AppConfig | None = None) -> Path:
    return get_skills_root_dir(app_config=app_config) / "public"


def get_custom_skills_dir(*, app_config: AppConfig | None = None) -> Path:
    path = get_skills_root_dir(app_config=app_config) / "custom"
    path.mkdir(parents=True, exist_ok=True)
    return path


def validate_skill_name(name: str) -> str:
    normalized = name.strip()
    if not _SKILL_NAME_PATTERN.fullmatch(normalized):
        raise ValueError("Skill name must be hyphen-case using lowercase letters, digits, and hyphens only.")
    if len(normalized) > 64:
        raise ValueError("Skill name must be 64 characters or fewer.")
    return normalized


def get_custom_skill_dir(name: str, *, app_config: AppConfig | None = None) -> Path:
    return get_custom_skills_dir(app_config=app_config) / validate_skill_name(name)


def get_custom_skill_file(name: str, *, app_config: AppConfig | None = None) -> Path:
    return get_custom_skill_dir(name, app_config=app_config) / SKILL_FILE_NAME


def get_custom_skill_history_dir(*, app_config: AppConfig | None = None) -> Path:
    path = get_custom_skills_dir(app_config=app_config) / HISTORY_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_skill_history_file(name: str, *, app_config: AppConfig | None = None) -> Path:
    return get_custom_skill_history_dir(app_config=app_config) / f"{validate_skill_name(name)}.jsonl"


def get_public_skill_dir(name: str, *, app_config: AppConfig | None = None) -> Path:
    return get_public_skills_dir(app_config=app_config) / validate_skill_name(name)


def custom_skill_exists(name: str, *, app_config: AppConfig | None = None) -> bool:
    return get_custom_skill_file(name, app_config=app_config).exists()


def public_skill_exists(name: str, *, app_config: AppConfig | None = None) -> bool:
    return (get_public_skill_dir(name, app_config=app_config) / SKILL_FILE_NAME).exists()


def ensure_custom_skill_is_editable(name: str, *, app_config: AppConfig | None = None) -> None:
    if custom_skill_exists(name, app_config=app_config):
        return
    if public_skill_exists(name, app_config=app_config):
        raise ValueError(f"'{name}' is a built-in skill. To customise it, create a new skill with the same name under skills/custom/.")
    raise FileNotFoundError(f"Custom skill '{name}' not found.")


def ensure_safe_support_path(name: str, relative_path: str, *, app_config: AppConfig | None = None) -> Path:
    skill_dir = get_custom_skill_dir(name, app_config=app_config).resolve()
    if not relative_path or relative_path.endswith("/"):
        raise ValueError("Supporting file path must include a filename.")
    relative = Path(relative_path)
    if relative.is_absolute():
        raise ValueError("Supporting file path must be relative.")
    if any(part in {"..", ""} for part in relative.parts):
        raise ValueError("Supporting file path must not contain parent-directory traversal.")

    top_level = relative.parts[0] if relative.parts else ""
    if top_level not in ALLOWED_SUPPORT_SUBDIRS:
        raise ValueError(f"Supporting files must live under one of: {', '.join(sorted(ALLOWED_SUPPORT_SUBDIRS))}.")

    target = (skill_dir / relative).resolve()
    allowed_root = (skill_dir / top_level).resolve()
    try:
        target.relative_to(allowed_root)
    except ValueError as exc:
        raise ValueError("Supporting file path must stay within the selected support directory.") from exc
    return target


def validate_skill_markdown_content(name: str, content: str) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        temp_skill_dir = Path(tmp_dir) / validate_skill_name(name)
        temp_skill_dir.mkdir(parents=True, exist_ok=True)
        (temp_skill_dir / SKILL_FILE_NAME).write_text(content, encoding="utf-8")
        is_valid, message, parsed_name = _validate_skill_frontmatter(temp_skill_dir)
        if not is_valid:
            raise ValueError(message)
        if parsed_name != name:
            raise ValueError(f"Frontmatter name '{parsed_name}' must match requested skill name '{name}'.")


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent)) as tmp_file:
        tmp_file.write(content)
        tmp_path = Path(tmp_file.name)
    tmp_path.replace(path)


def append_history(name: str, record: dict[str, Any], *, app_config: AppConfig | None = None) -> None:
    history_path = get_skill_history_file(name, app_config=app_config)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": datetime.now(UTC).isoformat(),
        **record,
    }
    with history_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False))
        f.write("\n")


def read_history(name: str, *, app_config: AppConfig | None = None) -> list[dict[str, Any]]:
    history_path = get_skill_history_file(name, app_config=app_config)
    if not history_path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in history_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        records.append(json.loads(line))
    return records


def list_custom_skills(*, app_config: AppConfig | None = None) -> list:
    return [skill for skill in load_skills(enabled_only=False, app_config=app_config) if skill.category == "custom"]


def read_custom_skill_content(name: str, *, app_config: AppConfig | None = None) -> str:
    skill_file = get_custom_skill_file(name, app_config=app_config)
    if not skill_file.exists():
        raise FileNotFoundError(f"Custom skill '{name}' not found.")
    return skill_file.read_text(encoding="utf-8")
