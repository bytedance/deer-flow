"""Validate every bundled SKILL.md under skills/public/.

Catches regressions like #2443 — a SKILL.md whose YAML front-matter fails to
parse (e.g. an unquoted description containing a colon, which YAML interprets
as a nested mapping). Each bundled skill is checked individually so the
failure message identifies the exact file.
"""

from pathlib import Path

import pytest

from deerflow.skills.validation import _validate_skill_frontmatter

SKILLS_PUBLIC_DIR = Path(__file__).resolve().parents[2] / "skills" / "public"


def _bundled_skill_dirs() -> list[Path]:
    return sorted(p.parent for p in SKILLS_PUBLIC_DIR.rglob("SKILL.md"))


@pytest.mark.parametrize(
    "skill_dir",
    _bundled_skill_dirs(),
    ids=lambda p: str(p.relative_to(SKILLS_PUBLIC_DIR)),
)
def test_bundled_skill_frontmatter_is_valid(skill_dir: Path) -> None:
    valid, msg, name = _validate_skill_frontmatter(skill_dir)
    assert valid, f"{skill_dir.relative_to(SKILLS_PUBLIC_DIR)}: {msg}"
    assert name, f"{skill_dir.relative_to(SKILLS_PUBLIC_DIR)}: no name extracted"


def test_skills_public_dir_has_skills() -> None:
    assert _bundled_skill_dirs(), f"no SKILL.md found under {SKILLS_PUBLIC_DIR}"
