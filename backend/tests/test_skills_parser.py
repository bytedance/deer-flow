"""Tests for skill file parser."""

from pathlib import Path

from deerflow.skills.parser import parse_skill_file


def _write_skill(tmp_path: Path, content: str) -> Path:
    """Write a SKILL.md file and return its path."""
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(content, encoding="utf-8")
    return skill_file


class TestParseSkillFile:
    def test_valid_skill_file(self, tmp_path):
        skill_file = _write_skill(
            tmp_path,
            "---\nname: my-skill\ndescription: A test skill\nlicense: MIT\n---\n\n# My Skill\n",
        )
        result = parse_skill_file(skill_file, "public")
        assert result is not None
        assert result.name == "my-skill"
        assert result.description == "A test skill"
        assert result.license == "MIT"
        assert result.category == "public"
        assert result.enabled is True
        assert result.skill_dir == tmp_path
        assert result.skill_file == skill_file

    def test_missing_name_returns_none(self, tmp_path):
        skill_file = _write_skill(
            tmp_path,
            "---\ndescription: A test skill\n---\n\nBody\n",
        )
        assert parse_skill_file(skill_file, "public") is None

    def test_missing_description_returns_none(self, tmp_path):
        skill_file = _write_skill(
            tmp_path,
            "---\nname: my-skill\n---\n\nBody\n",
        )
        assert parse_skill_file(skill_file, "public") is None

    def test_no_front_matter_returns_none(self, tmp_path):
        skill_file = _write_skill(tmp_path, "# Just a markdown file\n\nNo front matter here.\n")
        assert parse_skill_file(skill_file, "public") is None

    def test_nonexistent_file_returns_none(self, tmp_path):
        skill_file = tmp_path / "SKILL.md"
        assert parse_skill_file(skill_file, "public") is None

    def test_wrong_filename_returns_none(self, tmp_path):
        wrong_file = tmp_path / "README.md"
        wrong_file.write_text("---\nname: test\ndescription: test\n---\n", encoding="utf-8")
        assert parse_skill_file(wrong_file, "public") is None

    def test_optional_license_field(self, tmp_path):
        skill_file = _write_skill(
            tmp_path,
            "---\nname: my-skill\ndescription: A test skill\n---\n\nBody\n",
        )
        result = parse_skill_file(skill_file, "custom")
        assert result is not None
        assert result.license is None
        assert result.category == "custom"

    def test_custom_relative_path(self, tmp_path):
        skill_file = _write_skill(
            tmp_path,
            "---\nname: nested-skill\ndescription: Nested\n---\n\nBody\n",
        )
        rel = Path("group/nested-skill")
        result = parse_skill_file(skill_file, "public", relative_path=rel)
        assert result is not None
        assert result.relative_path == rel

    def test_default_relative_path_is_parent_name(self, tmp_path):
        skill_file = _write_skill(
            tmp_path,
            "---\nname: my-skill\ndescription: Test\n---\n\nBody\n",
        )
        result = parse_skill_file(skill_file, "public")
        assert result is not None
        assert result.relative_path == Path(tmp_path.name)

    def test_colons_in_description(self, tmp_path):
        skill_file = _write_skill(
            tmp_path,
            "---\nname: my-skill\ndescription: A skill: does things\n---\n\nBody\n",
        )
        result = parse_skill_file(skill_file, "public")
        assert result is not None
        assert result.description == "A skill: does things"

    def test_empty_front_matter_returns_none(self, tmp_path):
        skill_file = _write_skill(tmp_path, "---\n\n---\n\nBody\n")
        assert parse_skill_file(skill_file, "public") is None
