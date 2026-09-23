"""Regression tests for UTF-8 BOM handling in SKILL.md (deer-flow issue #5587).

On Windows, Notepad ("UTF-8 with BOM") and Windows PowerShell 5.1's
``Set-Content -Encoding UTF8`` / ``Out-File`` prepend ``U+FEFF``.  The leading
mark made the front-matter anchor fail, so a byte-for-byte valid SKILL.md was
silently dropped from the catalog (``parse_skill_file`` returned ``None``) and
rejected by install-time validation ("No YAML frontmatter found") — with no
log line pointing at the encoding artifact.
"""

from __future__ import annotations

from pathlib import Path

from deerflow.skills.frontmatter import split_skill_markdown
from deerflow.skills.parser import parse_skill_file
from deerflow.skills.validation import _validate_skill_frontmatter

_SKILL_TEXT = "---\nname: demo-skill\ndescription: Say hello\n---\n# Demo\n"


def _write_bom_skill(tmp_path: Path) -> Path:
    skill_dir = tmp_path / "demo-skill"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    # The only difference from a working skill file is the BOM.
    skill_file.write_bytes(_SKILL_TEXT.encode("utf-8-sig"))
    return skill_dir


def test_parse_skill_file_tolerates_utf8_bom(tmp_path: Path) -> None:
    skill_dir = _write_bom_skill(tmp_path)
    skill = parse_skill_file(skill_dir / "SKILL.md", category="custom")
    assert skill is not None
    assert skill.name == "demo-skill"
    assert skill.description == "Say hello"
    assert "\ufeff" not in skill.name
    assert "\ufeff" not in skill.description


def test_validate_skill_frontmatter_tolerates_utf8_bom(tmp_path: Path) -> None:
    skill_dir = _write_bom_skill(tmp_path)
    is_valid, message, name = _validate_skill_frontmatter(skill_dir)
    assert is_valid, message
    assert name == "demo-skill"


def test_split_skill_markdown_strips_leading_bom() -> None:
    parts, error = split_skill_markdown("\ufeff" + _SKILL_TEXT)
    assert error is None
    assert parts is not None
    assert parts.metadata["name"] == "demo-skill"
    assert not parts.body.startswith("\ufeff")
