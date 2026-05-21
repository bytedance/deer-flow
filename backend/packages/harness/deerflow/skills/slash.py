from __future__ import annotations

import re
from dataclasses import dataclass

from deerflow.skills.types import Skill

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

    skill = next((candidate for candidate in skills if candidate.name == reference.name and candidate.enabled), None)
    if skill is None:
        return None

    return ResolvedSlashSkill(
        skill=skill,
        remaining_text=reference.remaining_text,
        container_file_path=skill.get_container_file_path(container_base_path),
    )
