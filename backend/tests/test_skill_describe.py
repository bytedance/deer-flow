"""Tests for describe_skill tool and skill index prompt rendering."""

from pathlib import Path

import pytest

from deerflow.skills.catalog import SkillCatalog
from deerflow.skills.describe import (
    _render_skill_metadata,
    build_describe_skill_tool,
    build_skill_search_setup,
    get_skill_index_prompt_section,
)
from deerflow.skills.types import Skill, SkillCategory

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_skill(
    name: str,
    description: str = "A skill",
    category: SkillCategory = SkillCategory.PUBLIC,
    allowed_tools: tuple[str, ...] | None = None,
) -> Skill:
    base = Path("/mnt/skills") / category.value / name
    return Skill(
        name=name,
        description=description,
        license=None,
        skill_dir=base,
        skill_file=base / "SKILL.md",
        relative_path=Path(name),
        category=category,
        allowed_tools=allowed_tools,
        enabled=True,
    )


@pytest.fixture
def sample_skills() -> list[Skill]:
    return [
        _make_skill("data-analysis", "Analyze data with Python", allowed_tools=("execute_code", "read_file")),
        _make_skill("deep-research", "Multi-source research"),
        _make_skill("custom-analyzer", "Custom analyzer", category=SkillCategory.CUSTOM),
    ]


@pytest.fixture
def catalog(sample_skills: list[Skill]) -> SkillCatalog:
    return SkillCatalog(tuple(sample_skills))


# ── _render_skill_metadata ────────────────────────────────────────────────────


def test_render_metadata_format(sample_skills: list[Skill]):
    rendered = _render_skill_metadata(sample_skills[:1], "/mnt/skills")
    assert "## Skill: data-analysis" in rendered
    assert "Description: Analyze data with Python" in rendered
    assert "[built-in]" in rendered
    assert "Allowed tools: execute_code, read_file" in rendered
    assert "Location: /mnt/skills/public/data-analysis/SKILL.md" in rendered


def test_render_custom_skill_mutability(sample_skills: list[Skill]):
    custom = [s for s in sample_skills if s.category == SkillCategory.CUSTOM]
    rendered = _render_skill_metadata(custom, "/mnt/skills")
    assert "[custom, editable]" in rendered


def test_render_no_allowed_tools_shows_all(sample_skills: list[Skill]):
    """Skills without allowed_tools should show '(all)'."""
    no_tools = [s for s in sample_skills if s.allowed_tools is None]
    rendered = _render_skill_metadata(no_tools[:1], "/mnt/skills")
    assert "Allowed tools: (all)" in rendered


def test_render_multiple_skills(sample_skills: list[Skill]):
    rendered = _render_skill_metadata(sample_skills, "/mnt/skills")
    assert "## Skill: data-analysis" in rendered
    assert "## Skill: deep-research" in rendered
    assert "## Skill: custom-analyzer" in rendered


# ── build_describe_skill_tool ─────────────────────────────────────────────────


def test_describe_tool_is_invokable(catalog: SkillCatalog):
    tool = build_describe_skill_tool(catalog)
    assert tool.name == "describe_skill"
    assert hasattr(tool, "invoke")


def test_describe_tool_docstring(catalog: SkillCatalog):
    tool = build_describe_skill_tool(catalog)
    assert "describe_skill" in tool.name
    assert tool.description is not None


def test_describe_skill_parameter_name_matches_prompt(catalog: SkillCatalog):
    """Regression: the tool parameter must be 'name', matching the prompt wording
    'describe_skill(name)'.  A strict function-calling model submits exactly the
    parameter name the prompt specifies — any drift silently breaks the flow.
    """
    tool = build_describe_skill_tool(catalog)
    schema = tool.get_input_schema().model_json_schema()
    assert "name" in schema["properties"], "tool must accept 'name' (matching prompt wording)"
    assert "query" not in schema["properties"], "old 'query' parameter must not exist"


# ── build_skill_search_setup ──────────────────────────────────────────────────


def test_setup_enabled_with_skills(sample_skills: list[Skill]):
    setup = build_skill_search_setup(sample_skills, enabled=True)
    assert setup.describe_skill_tool is not None
    assert setup.skill_names == frozenset(s.name for s in sample_skills)


def test_setup_disabled():
    setup = build_skill_search_setup([_make_skill("a", "A")], enabled=False)
    assert setup.describe_skill_tool is None
    assert setup.skill_names == frozenset()


def test_setup_empty_skills():
    setup = build_skill_search_setup([], enabled=True)
    assert setup.describe_skill_tool is None
    assert setup.skill_names == frozenset()


def test_setup_frozen():
    """Empty SkillSearchSetup (describe_skill_tool=None) must be hashable.

    The populated setup contains a BaseTool, which is not hashable by design —
    so only the disabled/empty path is required to hash.  frozen=True still
    prevents accidental mutation in both cases.
    """
    setup = build_skill_search_setup([], enabled=True)
    assert hash(setup) is not None


# ── get_skill_index_prompt_section ────────────────────────────────────────────


def test_skill_index_contains_names():
    section = get_skill_index_prompt_section(
        skill_names=frozenset({"data-analysis", "deep-research"}),
    )
    assert "<skill_index>" in section
    assert "data-analysis" in section
    assert "deep-research" in section


def test_skill_index_no_description():
    """Index should NOT contain descriptions (that's the whole point)."""
    section = get_skill_index_prompt_section(
        skill_names=frozenset({"data-analysis"}),
    )
    assert "Analyze data with Python" not in section


def test_skill_index_no_location():
    """Index should NOT contain file paths."""
    section = get_skill_index_prompt_section(
        skill_names=frozenset({"data-analysis"}),
    )
    assert "/mnt/skills/public/data-analysis/SKILL.md" not in section


def test_skill_index_contains_discovery_instructions():
    section = get_skill_index_prompt_section(
        skill_names=frozenset({"data-analysis"}),
    )
    assert "describe_skill" in section
    assert "Skill Discovery" in section


def test_skill_index_empty_returns_empty():
    section = get_skill_index_prompt_section(skill_names=frozenset())
    assert section == ""


def test_skill_index_default_returns_empty():
    section = get_skill_index_prompt_section()
    assert section == ""


def test_skill_index_with_evolution_section():
    section = get_skill_index_prompt_section(
        skill_names=frozenset({"a"}),
        skill_evolution_section="## Skill Self-Evolution\n...",
    )
    assert "Skill Self-Evolution" in section


def test_skill_index_without_evolution_section():
    section = get_skill_index_prompt_section(
        skill_names=frozenset({"a"}),
        skill_evolution_section="",
    )
    assert "Skill Self-Evolution" not in section


def test_skill_index_custom_container_path():
    section = get_skill_index_prompt_section(
        skill_names=frozenset({"a"}),
        container_base_path="/custom/skills",
    )
    assert "/custom/skills" in section


def test_skill_index_names_are_sorted():
    """Names should be sorted for deterministic output."""
    section = get_skill_index_prompt_section(
        skill_names=frozenset({"z-skill", "a-skill", "m-skill"}),
    )
    # Extract just the <skill_index> block content
    import re

    match = re.search(r"<skill_index>\n(.*?)\n</skill_index>", section, re.DOTALL)
    assert match is not None
    names_str = match.group(1).strip()
    names = [n.strip() for n in names_str.split(",")]
    assert names == sorted(names)


# ── Integration: describe_skill tool invocation ───────────────────────────────


def test_describe_tool_returns_command_with_tool_message(catalog: SkillCatalog):
    """describe_skill should return a Command with a ToolMessage."""
    tool = build_describe_skill_tool(catalog)

    # Tools with InjectedToolCallId must be invoked with a full ToolCall dict
    result = tool.invoke(
        {"args": {"name": "select:data-analysis"}, "name": "describe_skill", "type": "tool_call", "id": "test_call_123"},
    )

    # Result is a Command wrapping a ToolMessage
    messages = result.update["messages"]
    assert len(messages) == 1
    msg = messages[0]
    assert msg.name == "describe_skill"
    assert msg.tool_call_id == "test_call_123"
    assert "## Skill: data-analysis" in msg.content


def test_describe_tool_no_match(catalog: SkillCatalog):
    tool = build_describe_skill_tool(catalog)
    result = tool.invoke(
        {"args": {"name": "xyz_nonexistent"}, "name": "describe_skill", "type": "tool_call", "id": "test_call_456"},
    )
    messages = result.update["messages"]
    assert "No skills matched" in messages[0].content


def test_describe_tool_keyword_search(catalog: SkillCatalog):
    tool = build_describe_skill_tool(catalog)
    result = tool.invoke(
        {"args": {"name": "research"}, "name": "describe_skill", "type": "tool_call", "id": "test_call_789"},
    )
    messages = result.update["messages"]
    assert "deep-research" in messages[0].content


def test_describe_tool_select_uncapped(tmp_path):
    """select: must return ALL requested skills, not capped at MAX_RESULTS."""
    from deerflow.skills.catalog import MAX_RESULTS

    # Build more skills than MAX_RESULTS so the cap would visibly truncate
    many_skills = [_make_skill(f"skill-{i:02d}") for i in range(MAX_RESULTS + 2)]
    big_catalog = SkillCatalog(tuple(many_skills))
    tool = build_describe_skill_tool(big_catalog)

    names_csv = ",".join(s.name for s in many_skills)
    result = tool.invoke(
        {"args": {"name": f"select:{names_csv}"}, "name": "describe_skill", "type": "tool_call", "id": "test_select_uncapped"},
    )
    content = result.update["messages"][0].content
    for s in many_skills:
        assert s.name in content, f"select: truncated — {s.name} missing from result"
