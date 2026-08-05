from pathlib import Path

import yaml


SKILL_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "public"
    / "github-issue-coding"
    / "SKILL.md"
)


def _load_skill() -> tuple[dict, str]:
    text = SKILL_PATH.read_text(encoding="utf-8")
    _, frontmatter, body = text.split("---", 2)
    return yaml.safe_load(frontmatter), body


def test_skill_can_only_use_github_issue_mcp_tool():
    frontmatter, _ = _load_skill()

    assert frontmatter["name"] == "github-issue-coding"
    assert frontmatter["allowed-tools"] == ["github_issue_get_github_issue"]


def test_skill_defines_issue_to_coding_brief_workflow():
    frontmatter, body = _load_skill()
    full_text = f"{frontmatter}\n{body}".lower()

    assert "todo" not in full_text
    assert "github_issue_get_github_issue" in body

    required_contract = {
        "coding_brief",
        "repository",
        "issue_number",
        "goal",
        "acceptance_criteria",
        "constraints",
        "open_questions",
        "tasks",
    }
    missing = sorted(field for field in required_contract if field not in body)
    assert not missing, f"SKILL.md is missing coding brief fields: {missing}"
