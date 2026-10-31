from deerflow_extension_skill_evolution.config import SkillEvolutionSettings
from deerflow_extension_skill_evolution.prompt import build_evolution_prompt


def test_default_prompt_renders_full_policy() -> None:
    text = build_evolution_prompt(SkillEvolutionSettings())
    assert "## Skill Self-Evolution" in text
    assert "5+ tool calls" in text
    # All six actions keep their established names and semantics.
    for action in ("create", "patch", "edit", "write_file", "remove_file", "delete"):
        assert f'action="{action}"' in text
    assert "skill_manage" in text
    assert "NEVER write SKILL.md" in text
    assert "/mnt/user-data/outputs" in text
    assert "Prefer `patch` over `edit`" in text
    assert "confirm with the user first" in text
    assert "Skip simple one-off tasks" in text
    assert "skill-creator" in text


def test_tool_call_hint_is_parameterized() -> None:
    text = build_evolution_prompt(SkillEvolutionSettings(min_tool_calls_hint=12))
    assert "12+ tool calls" in text
    assert "5+ tool calls" not in text


def test_prefer_patch_can_be_relaxed() -> None:
    text = build_evolution_prompt(SkillEvolutionSettings(prefer_patch=False))
    assert "Prefer `patch` over `edit`" not in text
    assert "Use `patch` for small, targeted changes" in text


def test_confirm_before_create_can_be_relaxed() -> None:
    text = build_evolution_prompt(SkillEvolutionSettings(confirm_before_create=False))
    assert "confirm with the user first" not in text
    assert "clearly reusable" in text


def test_hint_is_advice_not_a_counter() -> None:
    text = build_evolution_prompt(SkillEvolutionSettings(min_tool_calls_hint=3))
    # The hint stays soft prose ("consider", "when"), never a promise that the
    # runtime counts tool calls and fires at the threshold.
    assert "required 3+ tool calls" in text
    assert "consider creating or updating" in text
    assert "will be created" not in text
    assert "automatically created" not in text


def test_feedback_guidance_is_gated_on_the_tool_declaration() -> None:
    # Default (Plan A): no model-visible feedback surface, so no guidance.
    draft = build_evolution_prompt(SkillEvolutionSettings())
    assert "skill_feedback" not in draft
    # Plan B only renders the guidance when the tool is declared in the same
    # build — the prompt must never advertise a missing tool.
    agent_with_tool = build_evolution_prompt(SkillEvolutionSettings(feedback_mode="agent"), feedback_tool_declared=True)
    assert "skill_feedback(skill_name=" in agent_with_tool
    assert "feedback notes" in agent_with_tool
    agent_without_tool = build_evolution_prompt(SkillEvolutionSettings(feedback_mode="agent"), feedback_tool_declared=False)
    assert "skill_feedback" not in agent_without_tool
