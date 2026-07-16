"""describe_skill — deferred skill metadata retrieval at runtime.

Builds the ``describe_skill`` tool as a closure over a :class:`SkillCatalog`.
The tool returns structured metadata (description, allowed tools, file location)
so the LLM can decide whether to ``read_file`` the full SKILL.md.

Mirrors ``build_tool_search_tool`` from ``tool_search.py``: same query syntax,
same ``Command`` + ``ToolMessage`` return shape, same fail-safe degradation.
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.types import Command

if TYPE_CHECKING:
    from langchain.tools import BaseTool

from deerflow.constants import DEFAULT_SKILLS_CONTAINER_PATH
from deerflow.skills.catalog import SkillCatalog
from deerflow.skills.types import SkillCategory

logger = logging.getLogger(__name__)


# ── Setup ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SkillSearchSetup:
    """Result of assembling skill search for one agent build.

    Mirrors ``DeferredToolSetup`` from ``tool_search.py``.

    - **Empty** ``(None, frozenset())``: no skills available or skill search
      disabled.  The agent falls back to the legacy full-metadata prompt.
    - **Populated**: ``describe_skill_tool`` is appended to the agent's tools,
      ``skill_names`` are rendered in ``<skill_index>`` instead of full metadata.
    """

    describe_skill_tool: BaseTool | None
    skill_names: frozenset[str]


def build_describe_skill_tool(
    catalog: SkillCatalog,
    *,
    container_base_path: str = DEFAULT_SKILLS_CONTAINER_PATH,
) -> BaseTool:
    """Build the ``describe_skill`` tool as a closure over *catalog*.

    The returned tool is a plain ``@tool``-decorated function that searches the
    catalog and returns a ``Command`` wrapping a ``ToolMessage``.  No graph state
    mutation is needed (unlike ``tool_search`` which promotes deferred tools).
    """

    @tool
    def describe_skill(
        name: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        """Fetch usage metadata for installed skills so you can decide whether to load them.

        Skills appear by name in <skill_index> in the system prompt.  Until
        fetched, only the name is known.  This tool matches a query against
        installed skills and returns their full metadata — description, allowed
        tools, and file location — so you can decide whether to load the
        SKILL.md via read_file.

        Query forms:
          - "select:data-analysis,deep-research" -- fetch these exact skills (no cap)
          - "chart visualization" -- keyword search, best matches (up to 5)
          - "+podcast gen" -- require "podcast" in the name, rank by remaining terms (up to 5)
        """
        matched = catalog.search(name)
        if not matched:
            content = f"No skills matched: {name}"
        else:
            content = _render_skill_metadata(matched, container_base_path)

        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=content,
                        tool_call_id=tool_call_id,
                        name="describe_skill",
                    )
                ],
            }
        )

    return describe_skill


def build_skill_search_setup(
    skills: list,
    *,
    enabled: bool,
    container_base_path: str = DEFAULT_SKILLS_CONTAINER_PATH,
) -> SkillSearchSetup:
    """Build the skill search setup from a filtered skill list.

    Mirrors ``build_deferred_tool_setup`` from ``tool_search.py``.

    Returns an empty setup when *enabled* is ``False`` or *skills* is empty.
    """
    if not enabled or not skills:
        return SkillSearchSetup(None, frozenset())

    catalog = SkillCatalog(tuple(skills))
    return SkillSearchSetup(
        describe_skill_tool=build_describe_skill_tool(
            catalog,
            container_base_path=container_base_path,
        ),
        skill_names=catalog.names,
    )


# ── Rendering ────────────────────────────────────────────────────────────────


def _render_skill_metadata(skills: list, container_base_path: str) -> str:
    """Render structured metadata for a list of matched skills."""
    blocks: list[str] = []
    for s in skills:
        mutability = "[custom, editable]" if s.category == SkillCategory.CUSTOM else "[built-in]"
        tools_line = ", ".join(s.allowed_tools) if s.allowed_tools else "(all)"
        location = s.get_container_file_path(container_base_path)
        # name/description/allowed-tools come from untrusted ``.skill`` frontmatter;
        # escape so a value cannot forge a framework tag in the describe_skill output.
        name = html.escape(s.name, quote=False)
        description = html.escape(s.description, quote=False)
        tools = html.escape(tools_line, quote=False)
        loc = html.escape(location, quote=False)
        blocks.append(f"## Skill: {name}\n- Description: {description} {mutability}\n- Allowed tools: {tools}\n- Location: {loc}")
    return "\n\n".join(blocks)


# ── Prompt rendering ─────────────────────────────────────────────────────────


def get_skill_index_prompt_section(
    *,
    skill_names: frozenset[str] = frozenset(),
    container_base_path: str = DEFAULT_SKILLS_CONTAINER_PATH,
    skill_evolution_section: str = "",
) -> str:
    """Generate ``<skill_system>`` with a name-only ``<skill_index>``.

    Mirrors ``get_deferred_tools_prompt_section`` from ``tool_search.py``.
    The agent knows what exists and can use ``describe_skill`` to load metadata.

    Returns empty string when there are no skills.
    """
    if not skill_names:
        return ""

    names = ", ".join(html.escape(name, quote=False) for name in sorted(skill_names))
    evolution = f"\n{skill_evolution_section}" if skill_evolution_section else ""

    return f"""<skill_system>
You have access to skills that provide optimized workflows for specific tasks.

**Skill Discovery:**
1. Check <skill_index> for a skill name that matches your task
2. Call describe_skill(name) to fetch its description and capabilities
3. If the skill matches, call read_file on the returned location to load full instructions
4. Follow the skill's instructions precisely

**Explicit Slash Skill Activation:**
- If the user starts a request with `/<skill-name>`, that skill was explicitly requested.
- The runtime injects the activated skill content; do not call `read_file` for that SKILL.md again unless the injected skill references supporting resources you need.
{evolution}
<skill_index>
{names}
</skill_index>

Skills are located at: {container_base_path}
</skill_system>"""
