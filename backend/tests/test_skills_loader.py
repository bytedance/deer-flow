"""Tests for recursive skills loading."""

from pathlib import Path
from types import SimpleNamespace

from deerflow.config.skills_config import SkillsConfig
from deerflow.skills.storage import get_or_new_skill_storage


def _write_skill(skill_dir: Path, name: str, description: str) -> None:
    """Write a minimal SKILL.md for tests."""
    skill_dir.mkdir(parents=True, exist_ok=True)
    content = f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n"
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")


def test_get_skills_root_path_points_to_current_project_skills(tmp_path: Path, monkeypatch):
    """get_skills_root_path() should point to the caller project skills directory."""
    monkeypatch.delenv("DEER_FLOW_SKILLS_PATH", raising=False)
    monkeypatch.delenv("DEER_FLOW_PROJECT_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "skills").mkdir()

    app_config = SimpleNamespace(skills=SkillsConfig())
    path = get_or_new_skill_storage(app_config=app_config).get_skills_root_path()
    assert path == tmp_path / "skills"


def test_get_skills_root_path_honors_env_override(tmp_path: Path, monkeypatch):
    """DEER_FLOW_SKILLS_PATH should override the caller project skills directory."""
    skills_root = tmp_path / "team-skills"
    monkeypatch.setenv("DEER_FLOW_SKILLS_PATH", str(skills_root))

    app_config = SimpleNamespace(skills=SkillsConfig())
    path = get_or_new_skill_storage(app_config=app_config).get_skills_root_path()
    assert path == skills_root


def test_load_skills_discovers_nested_skills_and_sets_container_paths(tmp_path: Path):
    """Nested skills should be discovered recursively with correct container paths."""
    skills_root = tmp_path / "skills"

    _write_skill(skills_root / "public" / "root-skill", "root-skill", "Root skill")
    _write_skill(skills_root / "public" / "parent" / "child-skill", "child-skill", "Child skill")
    _write_skill(skills_root / "custom" / "team" / "helper", "team-helper", "Team helper")

    skills = get_or_new_skill_storage(skills_path=skills_root).load_skills(enabled_only=False)
    by_name = {skill.name: skill for skill in skills}

    assert {"root-skill", "child-skill", "team-helper"} <= set(by_name)

    root_skill = by_name["root-skill"]
    child_skill = by_name["child-skill"]
    team_skill = by_name["team-helper"]

    assert root_skill.skill_path == "root-skill"
    assert root_skill.get_container_file_path() == "/mnt/skills/public/root-skill/SKILL.md"

    assert child_skill.skill_path == "parent/child-skill"
    assert child_skill.get_container_file_path() == "/mnt/skills/public/parent/child-skill/SKILL.md"

    assert team_skill.skill_path == "team/helper"
    assert team_skill.get_container_file_path() == "/mnt/skills/custom/team/helper/SKILL.md"


def test_load_skills_stops_at_skill_package_boundary(tmp_path: Path):
    """SKILL.md files inside an existing skill package are support data, not skills."""
    skills_root = tmp_path / "skills"

    _write_skill(skills_root / "public" / "reviewer", "reviewer", "Reviews skills")
    _write_skill(
        skills_root / "public" / "reviewer" / "evals" / "fixtures" / "injection",
        "injection-example",
        "Calibration fixture",
    )
    _write_skill(
        skills_root / "public" / "reviewer" / "examples" / "helper",
        "nested-example",
        "Nested package example",
    )

    skills = get_or_new_skill_storage(skills_path=skills_root).load_skills(enabled_only=False)

    assert {skill.name for skill in skills} == {"reviewer"}


def test_load_skills_skips_hidden_directories(tmp_path: Path):
    """Hidden directories should be excluded from recursive discovery."""
    skills_root = tmp_path / "skills"

    _write_skill(skills_root / "public" / "visible" / "ok-skill", "ok-skill", "Visible skill")
    _write_skill(
        skills_root / "public" / "visible" / ".hidden" / "secret-skill",
        "secret-skill",
        "Hidden skill",
    )

    skills = get_or_new_skill_storage(skills_path=skills_root).load_skills(enabled_only=False)
    names = {skill.name for skill in skills}

    assert "ok-skill" in names
    assert "secret-skill" not in names


def test_load_skills_skips_evals_and_fixtures_directories(tmp_path: Path):
    """Skills inside evals/ or fixtures/ directories must not be discovered (issue #4095).

    Fixtures nested under a real skill package are excluded by the package-boundary
    rule.  Fixtures at the top-level with no immediate-child SKILL.md are pruned
    by the support-data directory filter.  A namespace directory named evals or
    fixtures whose immediate children are skill packages is NOT pruned — that
    case is covered by ``test_namespace_dirs_named_evals_or_fixtures_are_recursed``."""
    skills_root = tmp_path / "skills"

    # Real skill + package-boundary case: nested fixture under an actual skill package.
    _write_skill(skills_root / "public" / "real-skill", "real-skill", "A real skill")
    _write_skill(skills_root / "public" / "skill-reviewer", "skill-reviewer", "Reviews skills")
    _write_skill(skills_root / "public" / "skill-reviewer" / "evals" / "fixtures" / "prompt-injection", "injection-example", "Eval fixture")
    # Orphan fixture at the top level: evals/ has no SKILL.md and no immediate child with one.
    orphan_dir = skills_root / "public" / "evals" / "fixtures" / "restrictive"
    orphan_dir.mkdir(parents=True)
    (orphan_dir / "SKILL.md").write_text(
        "---\nname: orphan-fixture\ndescription: Orphan\n---\n\n# orphan-fixture\n",
        encoding="utf-8",
    )

    skills = get_or_new_skill_storage(skills_path=skills_root).load_skills(enabled_only=False)
    names = {skill.name for skill in skills}

    assert "real-skill" in names
    assert "skill-reviewer" in names
    assert "injection-example" not in names
    assert "orphan-fixture" not in names


def test_skill_packages_named_evals_or_fixtures_are_discovered(tmp_path: Path):
    """``evals`` and ``fixtures`` are not reserved skill names (PR #4164 review):
    a package whose own directory carries SKILL.md is discovered in both the
    public and custom walks, while nested support data below that package
    boundary stays excluded."""
    skills_root = tmp_path / "skills"

    _write_skill(skills_root / "public" / "evals", "evals", "Legit skill named evals")
    _write_skill(skills_root / "custom" / "fixtures", "fixtures", "Legit skill named fixtures")
    # Support data nested below the evals package boundary must stay out.
    _write_skill(skills_root / "public" / "evals" / "fixtures" / "nested", "nested-fixture", "Support data")

    names = {skill.name for skill in get_or_new_skill_storage(skills_path=skills_root).load_skills(enabled_only=False)}

    assert "evals" in names
    assert "fixtures" in names
    assert "nested-fixture" not in names


def test_namespace_dirs_named_evals_or_fixtures_are_recursed(tmp_path: Path):
    """Namespace directories named ``evals`` or ``fixtures`` that contain deeper
    skill packages must be recursed into, not pruned (PR #4164 review follow-up):
    ``public/fixtures/team-helper/SKILL.md`` is discovered because ``fixtures``
    is a legitimate namespace containing a skill package, not orphan support data."""
    skills_root = tmp_path / "skills"

    # Namespace: fixtures/team-helper (fixtures has no SKILL.md of its own)
    _write_skill(skills_root / "public" / "fixtures" / "team-helper", "team-helper", "Team helper under fixtures namespace")
    # Namespace: evals/quality-checker (evals has no SKILL.md of its own)
    _write_skill(skills_root / "public" / "evals" / "quality-checker", "quality-checker", "Quality checker under evals namespace")
    # Orphaned support data below an existing skill package must still be excluded.
    _write_skill(skills_root / "public" / "reviewer", "reviewer", "A real skill")
    _write_skill(skills_root / "public" / "reviewer" / "evals" / "fixtures" / "orphan", "orphan-fixture", "Orphan support data")

    names = {skill.name for skill in get_or_new_skill_storage(skills_path=skills_root).load_skills(enabled_only=False)}

    assert "team-helper" in names
    assert "quality-checker" in names
    assert "reviewer" in names
    assert "orphan-fixture" not in names


def test_eval_fixture_skills_cannot_clamp_tool_policy(tmp_path: Path):
    """End-to-end regression for issue #4095, exercising the real loader and the
    real tool-policy functions (no mocks): a restrictive eval-fixture SKILL.md
    must never reach ``allowed-tools`` filtering, so the ``task`` delegation
    tool survives for the lead agent."""
    from deerflow.skills.tool_policy import allowed_tool_names_for_skills, filter_tools_by_skill_allowed_tools

    skills_root = tmp_path / "skills"
    _write_skill(skills_root / "public" / "real-skill", "real-skill", "A real skill")
    # An orphaned fixture directory with no parent SKILL.md package boundary:
    # only the evals/fixtures directory-name exclusion keeps it undiscovered.
    fixture_dir = skills_root / "public" / "evals" / "fixtures" / "restrictive"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "SKILL.md").write_text(
        "---\nname: restrictive-fixture\ndescription: Eval fixture\nallowed-tools: [bash]\n---\n\n# restrictive-fixture\n",
        encoding="utf-8",
    )

    skills = get_or_new_skill_storage(skills_path=skills_root).load_skills(enabled_only=False)

    assert "restrictive-fixture" not in {skill.name for skill in skills}
    # No discovered skill declares allowed-tools, so the policy stays allow-all.
    assert allowed_tool_names_for_skills(skills) is None
    tools = [SimpleNamespace(name="task"), SimpleNamespace(name="bash"), SimpleNamespace(name="web_search")]
    filtered = filter_tools_by_skill_allowed_tools(tools, skills)
    assert [tool.name for tool in filtered] == ["task", "bash", "web_search"]


def test_load_skills_prefers_custom_over_public_with_same_name(tmp_path: Path):
    skills_root = tmp_path / "skills"
    _write_skill(skills_root / "public" / "shared-skill", "shared-skill", "Public version")
    _write_skill(skills_root / "custom" / "shared-skill", "shared-skill", "Custom version")

    skills = get_or_new_skill_storage(skills_path=skills_root).load_skills(enabled_only=False)
    shared = next(skill for skill in skills if skill.name == "shared-skill")

    assert shared.category == "custom"
    assert shared.description == "Custom version"
