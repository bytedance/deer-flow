from collections.abc import Callable
from pathlib import Path
from typing import cast

import src.gateway.routers.skills as skills_router

VALIDATE_SKILL_FRONTMATTER = cast(
    Callable[[Path], tuple[bool, str, str | None]],
    getattr(skills_router, "_validate_skill_frontmatter"),
)


def _write_skill(skill_dir: Path, frontmatter: str) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(frontmatter, encoding="utf-8")


def test_validate_skill_frontmatter_allows_standard_optional_metadata(tmp_path: Path) -> None:
    skill_dir = tmp_path / "demo-skill"
    _write_skill(
        skill_dir,
        """---
name: demo-skill
description: Demo skill
version: 1.0.0
author: example.com/demo
compatibility: OpenClaw >= 1.0
license: MIT
---

# Demo Skill
""",
    )

    valid, message, skill_name = VALIDATE_SKILL_FRONTMATTER(skill_dir)

    assert valid is True
    assert message == "Skill is valid!"
    assert skill_name == "demo-skill"


def test_validate_skill_frontmatter_still_rejects_unknown_keys(tmp_path: Path) -> None:
    skill_dir = tmp_path / "demo-skill"
    _write_skill(
        skill_dir,
        """---
name: demo-skill
description: Demo skill
unsupported: true
---

# Demo Skill
""",
    )

    valid, message, skill_name = VALIDATE_SKILL_FRONTMATTER(skill_dir)

    assert valid is False
    assert "unsupported" in message
    assert skill_name is None
