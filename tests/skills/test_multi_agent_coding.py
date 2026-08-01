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


def test_skill_can_only_delegate_through_task_tool() -> None:
    frontmatter, _ = _load_skill()

    assert frontmatter["name"] == "multi-agent-coding"
    assert frontmatter["allowed-tools"] == ["task"]


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


def test_skill_stops_pipeline_after_failed_delegation() -> None:
    _, body = _load_skill()
    normalized = body.lower()

    assert "failed" in normalized
    assert "stop" in normalized
    assert "do not claim success" in normalized
