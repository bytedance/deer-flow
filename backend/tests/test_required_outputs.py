"""Tests for skill frontmatter required-outputs parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from deerflow.skills.frontmatter import ALLOWED_FRONTMATTER_PROPERTIES
from deerflow.skills.parser import parse_required_outputs, parse_skill_file
from deerflow.skills.types import SkillCategory
from deerflow.skills.validation import _validate_skill_frontmatter


def test_required_outputs_in_allowed_frontmatter():
    assert "required-outputs" in ALLOWED_FRONTMATTER_PROPERTIES


def test_parse_required_outputs_accepts_basenames():
    assert parse_required_outputs(["content-research.json", "extra.md"], Path("SKILL.md")) == (
        "content-research.json",
        "extra.md",
    )


def test_parse_required_outputs_rejects_non_list():
    with pytest.raises(ValueError, match="must be a list"):
        parse_required_outputs({"file": "x.json"}, Path("SKILL.md"))


def test_parse_required_outputs_drops_path_traversal():
    assert parse_required_outputs(["../escape.json", "ok.json", "a/b.json"], Path("SKILL.md")) == ("ok.json",)


def test_parse_skill_file_loads_required_outputs(tmp_path: Path):
    skill_dir = tmp_path / "demo"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        "---\nname: demo\ndescription: demo skill\nrequired-outputs:\n  - demo.json\n---\n\n# Demo\n",
        encoding="utf-8",
    )
    skill = parse_skill_file(skill_md, category=SkillCategory.CUSTOM)
    assert skill is not None
    assert skill.required_outputs == ("demo.json",)


def test_validate_skill_frontmatter_accepts_required_outputs(tmp_path: Path):
    skill_dir = tmp_path / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\ndescription: demo\nrequired-outputs:\n  - demo.json\n---\n\nBody\n",
        encoding="utf-8",
    )
    valid, msg, name = _validate_skill_frontmatter(skill_dir)
    assert valid is True
    assert name == "demo"
