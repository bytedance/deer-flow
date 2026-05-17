from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from deerflow.skills.types import Skill

ORIGINAL_USER_CONTENT_KEY = "original_user_content"

_SLASH_SKILL_RE = re.compile(r"^\s*/([a-z0-9]+(?:-[a-z0-9]+)*)(?=\s|$|[^\x00-\x7F])")


@dataclass(frozen=True, slots=True)
class SlashSkillReference:
    name: str
    remaining_text: str


@dataclass(frozen=True, slots=True)
class ResolvedSlashSkill:
    skill: Skill
    remaining_text: str
    container_file_path: str


def parse_slash_skill_reference(text: str) -> SlashSkillReference | None:
    match = _SLASH_SKILL_RE.match(text)
    if not match:
        return None
    return SlashSkillReference(
        name=match.group(1),
        remaining_text=text[match.end() :].lstrip(),
    )


def message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part)
    return str(content)


def get_original_user_content_text(content: Any, additional_kwargs: Mapping[str, Any] | None) -> str:
    original_content = (additional_kwargs or {}).get(ORIGINAL_USER_CONTENT_KEY)
    if isinstance(original_content, str):
        return original_content
    return message_content_to_text(content)


def resolve_slash_skill(
    text: str,
    skills: list[Skill],
    *,
    available_skills: set[str] | None = None,
    container_base_path: str = "/mnt/skills",
) -> ResolvedSlashSkill | None:
    reference = parse_slash_skill_reference(text)
    if reference is None:
        return None
    if available_skills is not None and reference.name not in available_skills:
        return None

    skill = next((candidate for candidate in skills if candidate.name == reference.name), None)
    if skill is None:
        return None

    return ResolvedSlashSkill(
        skill=skill,
        remaining_text=reference.remaining_text,
        container_file_path=skill.get_container_file_path(container_base_path),
    )
