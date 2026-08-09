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


def test_skill_can_only_use_coding_workflow_and_human_input_tools() -> None:
    frontmatter, _ = _load_skill()

    assert frontmatter["name"] == "multi-agent-coding"
    assert frontmatter["allowed-tools"] == [
        "ask_clarification",
        "submit_task_plan",
        "create_coding_worktree",
        "recover_coding_task",
        "task",
    ]


def test_skill_persists_stable_stage_dag_before_delegation() -> None:
    _, body = _load_skill()
    normalized = body.lower()

    assert normalized.index("submit_task_plan") < normalized.index("code-analyzer")
    assert normalized.index("submit_task_plan") < normalized.index(
        "create_coding_worktree"
    )
    assert normalized.index("## prepare isolated worktree") < normalized.index(
        "## workflow"
    )
    assert normalized.index("## workflow") < normalized.index("### 1. analyze")
    assert '"id": "coding-analysis"' in normalized
    assert '"id": "coding-implementation"' in normalized
    assert '"id": "coding-review"' in normalized
    assert '"blocked_by": ["coding-analysis"]' in normalized
    assert '"blocked_by": ["coding-implementation"]' in normalized
    assert '"agent_type": "code-analyzer"' in normalized
    assert '"agent_type": "code-implementer"' in normalized
    assert '"agent_type": "code-reviewer"' in normalized

    assert "`coding_task_id`: `coding-analysis`" in normalized
    assert "`coding_task_id`: `coding-implementation`" in normalized
    assert "`coding_task_id`: `coding-review`" in normalized


def test_skill_defines_ordered_three_agent_handoffs() -> None:
    _, body = _load_skill()
    normalized = body.lower()

    assert "todo" not in normalized

    ordered_agents = ["code-analyzer", "code-implementer", "code-reviewer"]
    positions = [normalized.index(agent) for agent in ordered_agents]
    assert positions == sorted(positions)

    required_contract = {
        "coding_brief",
        "analysis_report",
        "implementation_report",
        "review_report",
        "subagent_type",
    }
    missing = sorted(field for field in required_contract if field not in normalized)
    assert not missing, f"SKILL.md is missing orchestration fields: {missing}"


def test_skill_requires_plan_approval_before_side_effects() -> None:
    _, body = _load_skill()
    normalized = body.lower()

    approval = normalized.index("coding_plan_approval")
    assert approval < normalized.index("submit_task_plan")
    assert "approve coding plan" in normalized
    assert "reject coding plan" in normalized


def test_skill_requires_explicit_approval_before_each_recovery() -> None:
    _, body = _load_skill()
    normalized = body.lower()

    assert "failed" in normalized
    assert "coding_task_recovery:{coding_task_id}" in normalized
    assert "retry failed task" in normalized
    assert "stop pipeline" in normalized
    assert normalized.index(
        "ask_clarification", normalized.index("## failure handling")
    ) < normalized.index("recover_coding_task")
    assert "each retry requires a fresh human confirmation" in normalized
    assert "do not retry automatically" in normalized
    assert "do not claim success" in normalized
