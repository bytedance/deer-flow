"""Tests for recursive skills loading."""

import asyncio
import os
from pathlib import Path

from deerflow.skills.loader import get_skills_root_path, invalidate_skills_cache, load_skills, refresh_skills_cache


def _write_skill(skill_dir: Path, name: str, description: str) -> None:
    """Write a minimal SKILL.md for tests."""
    skill_dir.mkdir(parents=True, exist_ok=True)
    content = f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n"
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")


def test_get_skills_root_path_points_to_project_root_skills():
    """get_skills_root_path() should point to deer-flow/skills (sibling of backend/), not backend/packages/skills."""
    path = get_skills_root_path()
    assert path.name == "skills", f"Expected 'skills', got '{path.name}'"
    assert (path.parent / "backend").is_dir(), f"Expected skills path's parent to be project root containing 'backend/', but got {path}"


def test_load_skills_discovers_nested_skills_and_sets_container_paths(tmp_path: Path):
    """Nested skills should be discovered recursively with correct container paths."""
    skills_root = tmp_path / "skills"

    _write_skill(skills_root / "public" / "root-skill", "root-skill", "Root skill")
    _write_skill(skills_root / "public" / "parent" / "child-skill", "child-skill", "Child skill")
    _write_skill(skills_root / "custom" / "team" / "helper", "team-helper", "Team helper")

    skills = load_skills(skills_path=skills_root, use_config=False, enabled_only=False)
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


def test_load_skills_skips_hidden_directories(tmp_path: Path):
    """Hidden directories should be excluded from recursive discovery."""
    skills_root = tmp_path / "skills"

    _write_skill(skills_root / "public" / "visible" / "ok-skill", "ok-skill", "Visible skill")
    _write_skill(
        skills_root / "public" / "visible" / ".hidden" / "secret-skill",
        "secret-skill",
        "Hidden skill",
    )

    skills = load_skills(skills_path=skills_root, use_config=False, enabled_only=False)
    names = {skill.name for skill in skills}

    assert "ok-skill" in names
    assert "secret-skill" not in names


def test_load_skills_prefers_custom_over_public_with_same_name(tmp_path: Path):
    skills_root = tmp_path / "skills"
    _write_skill(skills_root / "public" / "shared-skill", "shared-skill", "Public version")
    _write_skill(skills_root / "custom" / "shared-skill", "shared-skill", "Custom version")

    skills = load_skills(skills_path=skills_root, use_config=False, enabled_only=False)
    shared = next(skill for skill in skills if skill.name == "shared-skill")

    assert shared.category == "custom"
    assert shared.description == "Custom version"


def test_load_skills_uses_cache_after_first_scan(tmp_path: Path, monkeypatch) -> None:
    skills_root = tmp_path / "skills"
    _write_skill(skills_root / "public" / "cached-skill", "cached-skill", "Cached skill")

    invalidate_skills_cache()
    original_walk = os.walk
    calls = {"count": 0}

    def counting_walk(*args, **kwargs):
        calls["count"] += 1
        yield from original_walk(*args, **kwargs)

    monkeypatch.setattr("deerflow.skills.loader.os.walk", counting_walk)

    first = load_skills(skills_path=skills_root, use_config=False, enabled_only=False)
    second = load_skills(skills_path=skills_root, use_config=False, enabled_only=False)

    assert [skill.name for skill in first] == [skill.name for skill in second]
    assert calls["count"] == 1


def test_invalidate_skills_cache_forces_rescan(tmp_path: Path, monkeypatch) -> None:
    skills_root = tmp_path / "skills"
    _write_skill(skills_root / "public" / "cached-skill", "cached-skill", "Cached skill")

    invalidate_skills_cache()
    original_walk = os.walk
    calls = {"count": 0}

    def counting_walk(*args, **kwargs):
        calls["count"] += 1
        yield from original_walk(*args, **kwargs)

    monkeypatch.setattr("deerflow.skills.loader.os.walk", counting_walk)

    load_skills(skills_path=skills_root, use_config=False, enabled_only=False)
    invalidate_skills_cache()
    load_skills(skills_path=skills_root, use_config=False, enabled_only=False)

    assert calls["count"] == 2


def test_load_skills_uses_warmed_cache_inside_running_loop(tmp_path: Path, monkeypatch) -> None:
    skills_root = tmp_path / "skills"
    _write_skill(skills_root / "public" / "cached-skill", "cached-skill", "Cached skill")

    invalidate_skills_cache()
    refresh_skills_cache(skills_path=skills_root, use_config=False)
    refresh_target = load_skills(skills_path=skills_root, use_config=False, enabled_only=False)
    assert [skill.name for skill in refresh_target] == ["cached-skill"]

    def fail_walk(*args, **kwargs):
        raise AssertionError("os.walk should not run when the skills cache is already warm")

    monkeypatch.setattr("deerflow.skills.loader.os.walk", fail_walk)

    async def _call_from_loop():
        loaded = load_skills(skills_path=skills_root, use_config=False, enabled_only=False)
        assert [skill.name for skill in loaded] == ["cached-skill"]

    asyncio.run(_call_from_loop())
