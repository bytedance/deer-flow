"""Tests for the SKILL.md parser regression introduced in issue #1803.

The previous hand-rolled YAML parser stored quoted string values with their
surrounding quotes intact (e.g. ``name: "my-skill"`` → ``'"my-skill"'``).
This caused a mismatch with ``_validate_skill_frontmatter`` (which uses
``yaml.safe_load``) and broke skill lookup after installation.

The parser now uses ``yaml.safe_load`` consistently with ``validation.py``.
"""

from __future__ import annotations

from pathlib import Path

from deerflow.skills.parser import parse_skill_file

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_skill(tmp_path: Path, front_matter: str, body: str = "# My Skill\n") -> Path:
    """Write a minimal SKILL.md and return the path."""
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(f"---\n{front_matter}\n---\n{body}", encoding="utf-8")
    return skill_file


# ---------------------------------------------------------------------------
# Basic parsing
# ---------------------------------------------------------------------------


def test_parse_plain_name(tmp_path):
    """Unquoted name is parsed correctly."""
    skill_file = _write_skill(tmp_path, "name: my-skill\ndescription: A test skill")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert skill.name == "my-skill"


def test_parse_quoted_name_no_quotes_in_result(tmp_path):
    """Quoted name (YAML string) must not include surrounding quotes in result.

    Regression: the old hand-rolled parser stored ``'"my-skill"'`` instead of
    ``'my-skill'`` when the YAML value was wrapped in double-quotes.
    """
    skill_file = _write_skill(tmp_path, 'name: "my-skill"\ndescription: A test skill')
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert skill.name == "my-skill", f"Expected 'my-skill', got {skill.name!r}"


def test_parse_single_quoted_name(tmp_path):
    """Single-quoted YAML strings are also handled correctly."""
    skill_file = _write_skill(tmp_path, "name: 'my-skill'\ndescription: A test skill")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert skill.name == "my-skill"


def test_parse_description_returned(tmp_path):
    """Description field is correctly extracted."""
    skill_file = _write_skill(tmp_path, "name: my-skill\ndescription: Does amazing things")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert skill.description == "Does amazing things"


def test_parse_multiline_description(tmp_path):
    """Multi-line YAML descriptions are collapsed correctly by yaml.safe_load."""
    front_matter = "name: my-skill\ndescription: >\n  A folded\n  description"
    skill_file = _write_skill(tmp_path, front_matter)
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert "folded" in skill.description


def test_parse_license_field(tmp_path):
    """Optional license field is captured when present."""
    skill_file = _write_skill(tmp_path, "name: my-skill\ndescription: Test\nlicense: MIT")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert skill.license == "MIT"


def test_parse_missing_allowed_tools_returns_none(tmp_path):
    skill_file = _write_skill(tmp_path, "name: my-skill\ndescription: Test")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert skill.allowed_tools is None


def test_parse_allowed_tools_list(tmp_path):
    skill_file = _write_skill(tmp_path, 'name: my-skill\ndescription: Test\nallowed-tools: ["bash", "read_file"]')
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert skill.allowed_tools == ["bash", "read_file"]


def test_parse_empty_allowed_tools_list(tmp_path):
    skill_file = _write_skill(tmp_path, "name: my-skill\ndescription: Test\nallowed-tools: []")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is not None
    assert skill.allowed_tools == []


def test_parse_invalid_allowed_tools_returns_none(tmp_path):
    skill_file = _write_skill(tmp_path, "name: my-skill\ndescription: Test\nallowed-tools: bash")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is None


def test_parse_missing_name_returns_none(tmp_path):
    """Skills missing a name field are rejected."""
    skill_file = _write_skill(tmp_path, "description: A test skill")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is None


def test_parse_missing_description_returns_none(tmp_path):
    """Skills missing a description field are rejected."""
    skill_file = _write_skill(tmp_path, "name: my-skill")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is None


def test_parse_no_front_matter_returns_none(tmp_path):
    """Files without YAML front-matter delimiters return None."""
    skill_dir = tmp_path / "no-fm"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# No front matter here\n", encoding="utf-8")
    skill = parse_skill_file(skill_file, category="public")
    assert skill is None


def test_parse_invalid_yaml_returns_none(tmp_path):
    """Malformed YAML front-matter is handled gracefully (returns None)."""
    skill_file = _write_skill(tmp_path, "name: [unclosed")
    skill = parse_skill_file(skill_file, category="custom")
    assert skill is None


def test_parse_category_stored(tmp_path):
    """Category is propagated into the returned Skill object."""
    skill_file = _write_skill(tmp_path, "name: my-skill\ndescription: Test")
    skill = parse_skill_file(skill_file, category="public")
    assert skill is not None
    assert skill.category == "public"


def test_parse_nonexistent_file_returns_none(tmp_path):
    """Non-existent files are handled gracefully."""
    skill = parse_skill_file(tmp_path / "ghost" / "SKILL.md", category="custom")
    assert skill is None
