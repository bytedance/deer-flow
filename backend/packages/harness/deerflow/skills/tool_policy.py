import logging
from typing import Protocol

from deerflow.skills.types import Skill

logger = logging.getLogger(__name__)


class NamedTool(Protocol):
    name: str


# Framework tools required for the agent runtime itself, not subject to
# per-skill ``allowed-tools`` restrictions. ``read_file`` is needed for
# progressive skill loading: the lead-agent prompt instructs the model to
# ``read_file`` the matched skill's ``SKILL.md`` (see
# agents/lead_agent/prompt.py), and filtering it out when a skill declares a
# restrictive ``allowed-tools`` list breaks that contract with
# "read_file is not a valid tool". See #3862.
#
# ``tool_search`` is exempted separately in ``assemble_deferred_tools``
# (appended after the policy filter); it is not duplicated here.
SKILL_LOADING_FRAMEWORK_TOOLS: frozenset[str] = frozenset({"read_file"})


def allowed_tool_names_for_skills(skills: list[Skill]) -> set[str] | None:
    """Return the union of explicit skill allowed-tools declarations.

    None means legacy allow-all behavior. It is returned only when no loaded
    skill declares allowed-tools. Once any skill declares the field, legacy
    skills without the field contribute no tools instead of disabling the
    explicit restrictions from other skills.
    """
    if not skills:
        return None

    allowed: set[str] = set()
    has_explicit_declaration = False
    for skill in skills:
        if skill.allowed_tools is None:
            continue
        has_explicit_declaration = True
        if not skill.allowed_tools:
            logger.info("Skill %s declared empty allowed-tools", skill.name)
        allowed.update(skill.allowed_tools)

    if not has_explicit_declaration:
        return None
    return allowed


def filter_tools_by_skill_allowed_tools[ToolT: NamedTool](tools: list[ToolT], skills: list[Skill]) -> list[ToolT]:
    allowed = allowed_tool_names_for_skills(skills)
    if allowed is None:
        return tools

    # Exempt framework tools that the runtime itself needs (e.g. read_file
    # for progressive skill loading) so a restrictive skill allowed-tools
    # list cannot break the agent's skill-loading contract. See #3862.
    allowed = allowed | SKILL_LOADING_FRAMEWORK_TOOLS

    return [tool for tool in tools if tool.name in allowed]
