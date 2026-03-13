from pathlib import Path

from fastapi import HTTPException

from src.gateway.routers.skills import _resolve_skill_dir_from_archive_root


def _write_skill(skill_dir: Path) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: demo-skill
description: Demo skill
---

# Demo Skill
""",
        encoding="utf-8",
    )


def test_resolve_skill_dir_ignores_macosx_wrapper(tmp_path: Path) -> None:
    _write_skill(tmp_path / "demo-skill")
    (tmp_path / "__MACOSX").mkdir()

    assert _resolve_skill_dir_from_archive_root(tmp_path) == tmp_path / "demo-skill"


def test_resolve_skill_dir_ignores_hidden_top_level_entries(tmp_path: Path) -> None:
    _write_skill(tmp_path / "demo-skill")
    (tmp_path / ".DS_Store").write_text("metadata", encoding="utf-8")

    assert _resolve_skill_dir_from_archive_root(tmp_path) == tmp_path / "demo-skill"


def test_resolve_skill_dir_rejects_archive_with_only_metadata(tmp_path: Path) -> None:
    (tmp_path / "__MACOSX").mkdir()
    (tmp_path / ".DS_Store").write_text("metadata", encoding="utf-8")

    try:
        _resolve_skill_dir_from_archive_root(tmp_path)
    except HTTPException as error:
        assert error.status_code == 400
        assert error.detail == "Skill archive is empty"
    else:
        raise AssertionError("Expected HTTPException for metadata-only archive")
