import json
from pathlib import Path

from deerflow.skills.parser import parse_skill_file
from deerflow.skills.review import LocalDirectoryReader, analyze_skill_package
from deerflow.skills.types import SkillCategory

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = REPO_ROOT / "skills" / "public" / "skill-reviewer"


def test_skill_reviewer_public_skill_parses():
    skill = parse_skill_file(SKILL_DIR / "SKILL.md", SkillCategory.PUBLIC, Path("skill-reviewer"))

    assert skill is not None
    assert skill.name == "skill-reviewer"
    assert skill.allowed_tools == ("review_skill_package",)


def test_skill_reviewer_declares_review_tool_boundary():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

    assert "Always inspect the target through `review_skill_package`" in text
    assert "Do not read the target `SKILL.md`" in text
    assert "skill-creator" in text


def test_skill_reviewer_references_exist():
    for rel in [
        "references/review-rubric.md",
        "references/review-checklist.md",
        "references/report-rendering.md",
        "references/eval-design.md",
        "references/effect-verification.md",
        "evals/evals.json",
    ]:
        assert (SKILL_DIR / rel).exists(), rel


def test_skill_reviewer_eval_manifest_has_required_fixtures():
    payload = json.loads((SKILL_DIR / "evals" / "evals.json").read_text(encoding="utf-8"))
    case_ids = {case["id"] for case in payload["cases"]}

    assert {"publish-candidate", "needs-revision", "blocked", "prompt-injection", "zh-output", "partial-package"} <= case_ids
    for case in payload["cases"]:
        fixture = case.get("fixture")
        if fixture:
            assert (SKILL_DIR / "evals" / fixture / "SKILL.md").exists()


def test_skill_reviewer_package_review_keeps_root_identity_visible():
    facts = analyze_skill_package(LocalDirectoryReader(SKILL_DIR).read())

    assert facts["subject"]["declared_name"] == "skill-reviewer"
    assert facts["subject"]["package_digest"].startswith("sha256:")
