"""Unit tests for identity-scoped skills loading."""

import json
from pathlib import Path

import pytest

from deerflow.identity.agent_identity import AgentIdentity


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _make_skill(skills_root: Path, category: str, name: str) -> Path:
    """Create a minimal SKILL.md in the given skills directory."""
    skill_dir = skills_root / category / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Test skill {name}\nlicense: MIT\n---\n",
        encoding="utf-8",
    )
    return skill_dir


class TestLoadSkillsWithIdentity:
    def test_global_skills_all_enabled_by_default(self, tmp_path):
        from deerflow.skills.loader import load_skills

        skills_root = tmp_path / "skills"
        _make_skill(skills_root, "public", "skill-a")
        _make_skill(skills_root, "custom", "skill-b")

        skills = load_skills(skills_path=skills_root)
        names = {s.name for s in skills}
        assert "skill-a" in names
        assert "skill-b" in names

    def test_identity_uses_layered_extensions(self, tmp_path):
        """When identity is provided, layered extensions determine enabled state."""
        from deerflow.skills.loader import load_skills
        import deerflow.config.paths as paths_module
        from deerflow.config.paths import Paths

        skills_root = tmp_path / "skills"
        _make_skill(skills_root, "public", "skill-allowed")
        _make_skill(skills_root, "public", "skill-blocked")

        # Global: both enabled
        ext_global = tmp_path / "extensions_config.json"
        _write_json(ext_global, {
            "skills": {
                "skill-allowed": {"enabled": True},
                "skill-blocked": {"enabled": True},
            }
        })
        # Dept: skill-blocked disabled
        paths_obj = Paths(tmp_path)
        dept_ext = paths_obj.dept_dir("d") / "extensions_config.json"
        _write_json(dept_ext, {
            "skills": {"skill-blocked": {"enabled": False}}
        })

        orig = paths_module.get_paths
        try:
            paths_module.get_paths = lambda: paths_obj
            identity = AgentIdentity(dept_id="d", user_id="u")
            skills = load_skills(skills_path=skills_root, identity=identity)
            enabled = {s.name: s.enabled for s in skills}
            assert enabled.get("skill-allowed") is True
            assert enabled.get("skill-blocked") is False
        finally:
            paths_module.get_paths = orig

    def test_enabled_only_filters(self, tmp_path):
        from deerflow.skills.loader import load_skills
        import deerflow.config.paths as paths_module
        from deerflow.config.paths import Paths

        skills_root = tmp_path / "skills"
        _make_skill(skills_root, "public", "skill-on")
        _make_skill(skills_root, "public", "skill-off")

        paths_obj = Paths(tmp_path)
        _write_json(tmp_path / "extensions_config.json", {
            "skills": {
                "skill-on": {"enabled": True},
                "skill-off": {"enabled": False},
            }
        })

        orig = paths_module.get_paths
        try:
            paths_module.get_paths = lambda: paths_obj
            skills = load_skills(skills_path=skills_root, enabled_only=True)
            names = {s.name for s in skills}
            assert "skill-on" in names
            assert "skill-off" not in names
        finally:
            paths_module.get_paths = orig

    def test_global_identity_uses_global_extensions(self, tmp_path):
        """When identity.is_global is True, ExtensionsConfig.from_file() is used (no layered merge)."""
        from deerflow.skills.loader import load_skills
        import deerflow.config.paths as paths_module
        from deerflow.config.paths import Paths

        skills_root = tmp_path / "skills"
        _make_skill(skills_root, "public", "skill-x")

        paths_obj = Paths(tmp_path)
        _write_json(tmp_path / "extensions_config.json", {
            "skills": {"skill-x": {"enabled": True}}
        })

        orig = paths_module.get_paths
        try:
            paths_module.get_paths = lambda: paths_obj
            # is_global = True (no dept/user)
            identity = AgentIdentity(agent_name="my-agent")
            skills = load_skills(skills_path=skills_root, identity=identity)
            names = {s.name for s in skills}
            assert "skill-x" in names
        finally:
            paths_module.get_paths = orig

    def test_skills_sorted_by_name(self, tmp_path):
        from deerflow.skills.loader import load_skills

        skills_root = tmp_path / "skills"
        _make_skill(skills_root, "public", "z-skill")
        _make_skill(skills_root, "public", "a-skill")
        _make_skill(skills_root, "public", "m-skill")

        skills = load_skills(skills_path=skills_root)
        names = [s.name for s in skills]
        assert names == sorted(names)
