from pathlib import Path

import yaml


SKILL_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "public"
    / "multi-agent-coding"
    / "SKILL.md"
)


def _load_skill() -> tuple[dict, str]:
    text = SKILL_PATH.read_text(encoding="utf-8")
    _, frontmatter, body = text.split("---", 2)
    return yaml.safe_load(frontmatter), body


def test_skill_exposes_only_coding_workflow_and_human_approval_tools() -> None:
    frontmatter, _ = _load_skill()

    assert frontmatter["name"] == "multi-agent-coding"
    assert frontmatter["allowed-tools"] == [
        "ask_clarification",
        "submit_task_plan",
        "create_coding_worktree",
        "recover_coding_task",
        "continue_after_review",
        "task",
    ]


def test_skill_defines_three_user_selected_workflows() -> None:
    _, body = _load_skill()
    normalized = body.lower()

    assert "analyze_only" in normalized
    assert "review_only" in normalized
    assert "implement_and_review" in normalized
    assert '"id": "coding-analysis"' in normalized
    assert '"id": "coding-review"' in normalized
    assert '"id": "coding-implementation"' in normalized
    assert '"blocked_by": ["coding-analysis"]' in normalized
    assert '"blocked_by": ["coding-implementation"]' in normalized


def test_skill_requires_approval_before_side_effects_and_before_review_followup() -> (
    None
):
    _, body = _load_skill()
    normalized = body.lower()

    assert normalized.index("coding_plan_approval") < normalized.index(
        "submit_task_plan"
    )
    assert "approve coding plan" in normalized
    assert "coding_review_followup:{review_task_id}" in normalized
    assert "reanalyze and fix" in normalized
    assert normalized.index("continue_after_review") > normalized.index(
        "coding_review_followup"
    )
    assert "不得自动循环" in body
