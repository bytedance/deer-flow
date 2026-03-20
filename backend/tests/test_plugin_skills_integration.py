"""Tests for plugin skills integration with the existing skills loader."""

import json
from pathlib import Path

from src.skills.loader import load_skills


def _write_skill(skill_dir: Path, name: str, description: str) -> None:
    """Write a minimal SKILL.md for tests."""
    skill_dir.mkdir(parents=True, exist_ok=True)
    content = f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n"
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")


def _create_plugin(plugins_root: Path, plugin_name: str, skills: list[tuple[str, str]] | None = None) -> Path:
    """Create a plugin with optional skills."""
    plugin_dir = plugins_root / plugin_name
    manifest_dir = plugin_dir / ".claude-plugin"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"name": plugin_name, "version": "1.0.0", "description": f"{plugin_name} plugin", "author": {"name": "Test"}}
    (manifest_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")

    if skills:
        for skill_name, skill_desc in skills:
            _write_skill(plugin_dir / "skills" / skill_name, skill_name, skill_desc)

    return plugin_dir


class TestLoadSkillsWithPlugins:
    """Tests for loading skills from both skills/ and plugins/ directories."""

    def test_load_skills_includes_plugin_skills(self, tmp_path: Path):
        """Skills from plugins should be discovered alongside regular skills."""
        skills_root = tmp_path / "skills"
        plugins_root = tmp_path / "plugins" / "installed"

        # Create a regular skill
        _write_skill(skills_root / "public" / "pdf-processing", "pdf-processing", "Process PDFs")

        # Create a plugin with skills
        _create_plugin(plugins_root, "sales", [
            ("call-prep", "Prepare for calls"),
            ("account-research", "Research accounts"),
        ])

        skills = load_skills(skills_path=skills_root, plugins_path=plugins_root, use_config=False, enabled_only=False)

        names = {s.name for s in skills}
        assert "pdf-processing" in names
        assert "call-prep" in names
        assert "account-research" in names

    def test_plugin_skills_have_plugin_category(self, tmp_path: Path):
        """Plugin skills should have category 'plugin:<plugin_name>'."""
        skills_root = tmp_path / "skills"
        skills_root.mkdir(parents=True)
        plugins_root = tmp_path / "plugins" / "installed"

        _create_plugin(plugins_root, "sales", [("call-prep", "Prepare for calls")])

        skills = load_skills(skills_path=skills_root, plugins_path=plugins_root, use_config=False, enabled_only=False)

        call_prep = next(s for s in skills if s.name == "call-prep")
        assert call_prep.category == "plugin:sales"

    def test_plugin_skills_container_path(self, tmp_path: Path):
        """Plugin skills should use /mnt/plugins/<plugin>/<skill>/SKILL.md container paths."""
        skills_root = tmp_path / "skills"
        skills_root.mkdir(parents=True)
        plugins_root = tmp_path / "plugins" / "installed"

        _create_plugin(plugins_root, "sales", [("call-prep", "Prepare for calls")])

        skills = load_skills(skills_path=skills_root, plugins_path=plugins_root, use_config=False, enabled_only=False)

        call_prep = next(s for s in skills if s.name == "call-prep")
        container_path = call_prep.get_container_file_path("/mnt/plugins")
        assert container_path == "/mnt/plugins/plugin:sales/call-prep/SKILL.md"

    def test_load_skills_without_plugins_path(self, tmp_path: Path):
        """Should still work when no plugins_path is provided (backward compatible)."""
        skills_root = tmp_path / "skills"
        _write_skill(skills_root / "public" / "test-skill", "test-skill", "Test")

        skills = load_skills(skills_path=skills_root, use_config=False, enabled_only=False)

        assert len(skills) == 1
        assert skills[0].name == "test-skill"

    def test_load_skills_with_nonexistent_plugins_path(self, tmp_path: Path):
        """Should gracefully handle nonexistent plugins path."""
        skills_root = tmp_path / "skills"
        _write_skill(skills_root / "public" / "test-skill", "test-skill", "Test")

        skills = load_skills(
            skills_path=skills_root,
            plugins_path=tmp_path / "nonexistent",
            use_config=False,
            enabled_only=False,
        )

        assert len(skills) == 1

    def test_load_skills_sorted_across_sources(self, tmp_path: Path):
        """Skills from all sources should be sorted together by name."""
        skills_root = tmp_path / "skills"
        plugins_root = tmp_path / "plugins" / "installed"

        _write_skill(skills_root / "public" / "zebra-skill", "zebra-skill", "Z")
        _create_plugin(plugins_root, "sales", [("alpha-skill", "A")])
        _write_skill(skills_root / "custom" / "mid-skill", "mid-skill", "M")

        skills = load_skills(skills_path=skills_root, plugins_path=plugins_root, use_config=False, enabled_only=False)

        names = [s.name for s in skills]
        assert names == sorted(names)

    def test_plugin_without_skills_dir(self, tmp_path: Path):
        """Plugins without a skills/ directory should be skipped gracefully."""
        skills_root = tmp_path / "skills"
        skills_root.mkdir(parents=True)
        plugins_root = tmp_path / "plugins" / "installed"

        # Plugin with no skills/ subdirectory
        _create_plugin(plugins_root, "no-skills", skills=None)
        # Plugin with skills
        _create_plugin(plugins_root, "has-skills", [("one", "One skill")])

        skills = load_skills(skills_path=skills_root, plugins_path=plugins_root, use_config=False, enabled_only=False)

        assert len(skills) == 1
        assert skills[0].name == "one"
