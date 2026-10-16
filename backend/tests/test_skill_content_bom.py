"""SKILL.md content delivery must not carry a UTF-8 BOM into the model.

`skills/frontmatter.py` deliberately tolerates a leading BOM at parse time and
documents that "neither the front matter nor the body carries it downstream", but
`split_skill_markdown` only sees the BOM because its regex consumes it. The
content-delivery paths read the file themselves with plain ``utf-8``, so a
SKILL.md saved by Notepad or PowerShell 5.1 (both prepend a BOM) reaches the
model — and the reminder's ``sha256`` attribute — with ``U+FEFF`` as its first
character.

These tests pin both delivery paths. They fail before the encoding fix, where the
first character is U+FEFF.
"""

from __future__ import annotations

import codecs
from pathlib import Path

from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware
from deerflow.skills.storage.local_skill_storage import LocalSkillStorage

BOM = "\ufeff"
FRONTMATTER = "---\nname: demo-skill\ndescription: A demo skill\n---\n"
BODY = "# Demo skill\n\nDo the demo thing.\n"


def _write_skill_md(skill_dir: Path, *, bom: bool, body: str = BODY) -> Path:
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    payload = (BOM if bom else "") + FRONTMATTER + body
    skill_md.write_bytes(payload.encode("utf-8"))
    return skill_md


def test_bom_prefixed_skill_md_really_starts_with_a_bom(tmp_path: Path) -> None:
    """Guards the fixture: the plain-utf-8 read is what leaks the character."""
    skill_md = _write_skill_md(tmp_path / "custom" / "demo-skill", bom=True)

    plain = skill_md.read_text(encoding="utf-8")
    stripped = skill_md.read_text(encoding="utf-8-sig")

    assert codecs.BOM_UTF8 == plain.encode("utf-8")[:3]
    assert plain.startswith(BOM)
    # `str.strip()` is not enough: U+FEFF is not whitespace in Python.
    assert plain.strip().startswith(BOM)
    assert not stripped.startswith(BOM)
    assert stripped == FRONTMATTER + BODY


def test_activation_reminder_content_has_no_bom(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    skill_md = _write_skill_md(skills_root / "custom" / "demo-skill", bom=True)

    content = SkillActivationMiddleware._read_skill_content(skill_md, skills_root)

    assert not content.startswith(BOM)
    assert content == FRONTMATTER + BODY


def test_activation_reminder_content_hash_ignores_the_bom(tmp_path: Path) -> None:
    """The BOM must not change the published content hash."""
    skills_root = tmp_path / "skills"
    with_bom = _write_skill_md(skills_root / "custom" / "with-bom", bom=True)
    without_bom = _write_skill_md(skills_root / "custom" / "without-bom", bom=False)

    assert SkillActivationMiddleware._read_skill_content(with_bom, skills_root) == SkillActivationMiddleware._read_skill_content(without_bom, skills_root)


def test_read_custom_skill_has_no_bom(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    _write_skill_md(skills_root / "custom" / "demo-skill", bom=True)
    storage = LocalSkillStorage(host_path=str(skills_root))

    content = storage.read_custom_skill("demo-skill")

    assert not content.startswith(BOM)
    assert content == FRONTMATTER + BODY
