"""Regression coverage for complete SKILL.md delimiter lines."""

from pathlib import Path

import pytest

from deerflow.skills.frontmatter import split_skill_markdown
from deerflow.skills.parser import parse_skill_file
from deerflow.skills.validation import validate_skill_frontmatter_text


@pytest.mark.parametrize("closing", ["---suffix", "----", "--- body text"])
def test_non_delimiter_line_cannot_close_frontmatter(tmp_path: Path, closing: str) -> None:
    content = f"---\nname: my-skill\ndescription: A valid skill\n{closing}\nInstructions\n"
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(content, encoding="utf-8")

    parts, error = split_skill_markdown(content)

    assert parts is None
    assert error == "No YAML frontmatter found"
    assert parse_skill_file(skill_file, category="custom") is None
    valid, _, name = validate_skill_frontmatter_text(content)
    assert not valid
    assert name is None


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("bom", ["", "\ufeff"])
def test_delimiter_preserves_body_whitespace(newline: str, bom: str) -> None:
    body = f"{newline}    print('keep indentation'){newline}{newline}Instructions{newline}"
    content = f"{bom}--- \t{newline}name: my-skill{newline}description: A valid skill{newline}--- \t{newline}{body}"

    parts, error = split_skill_markdown(content)

    assert error is None
    assert parts is not None
    assert parts.metadata == {"name": "my-skill", "description": "A valid skill"}
    assert parts.body == body
    assert validate_skill_frontmatter_text(content) == (True, "Skill is valid!", "my-skill")


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_closing_delimiter_at_end_of_file(newline: str) -> None:
    content = f"---{newline}name: my-skill{newline}description: A valid skill{newline}--- \t"

    parts, error = split_skill_markdown(content)

    assert error is None
    assert parts is not None
    assert parts.metadata["name"] == "my-skill"
    assert parts.body == ""
