from deerflow.skills.loader import get_skills_root_path, load_skills
from deerflow.skills.validation import _validate_skill_frontmatter


SKILL_CASES = [
    ("autodrive/analyze-log", "autodrive-analyze-log"),
    ("autodrive/check-data-exists", "autodrive-check-data-exists"),
    ("autodrive/download-pdcl-data", "autodrive-download-pdcl-data"),
    ("autodrive/download_feishu_project_data", "autodrive-download-feishu-project-data"),
    ("autodrive/extract_proto_data", "autodrive-extract-proto-data"),
    ("autodrive/feishu_issue_resolver", "autodrive-feishu-issue-resolver"),
    ("autodrive/fetch_vehicle_logs", "autodrive-fetch-vehicle-logs"),
    ("autodrive/render-plotly-chart", "autodrive-render-plotly-chart"),
]


def test_autodrive_skill_frontmatter_is_valid() -> None:
    skills_root = get_skills_root_path() / "custom"

    for relative_dir, expected_name in SKILL_CASES:
        skill_dir = skills_root / relative_dir
        valid, message, skill_name = _validate_skill_frontmatter(skill_dir)
        assert valid is True, f"{relative_dir}: {message}"
        assert skill_name == expected_name


def test_load_skills_includes_autodrive_skills() -> None:
    names = {skill.name for skill in load_skills(use_config=False, enabled_only=False)}
    expected_names = {expected_name for _, expected_name in SKILL_CASES}
    assert expected_names <= names
