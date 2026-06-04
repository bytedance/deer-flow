"""Tests for Change 8: migrate_skills_to_user_namespace.py migration script.

Verifies:
- Flat layout custom/<name>/ is moved to custom/default/<name>/
- History is moved from custom/.history/ to custom/default/.history/
- Dry-run mode previews without modifying the filesystem
- Script is idempotent (second run moves nothing)
- Directories without SKILL.md are not treated as skills
- Target that already exists is skipped (not overwritten)
- Non-existent custom/ dir exits cleanly with 0 items migrated
- Hidden dirs (starting with '.') are ignored
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Import the migrate function directly
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.migrate_skills_to_user_namespace import migrate


_SKILL_MD = "---\nname: {name}\ndescription: Test\nlicense: MIT\n---\n\n# {name}\n"


def _write_flat_skill(root: Path, name: str) -> Path:
    d = root / "custom" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(_SKILL_MD.format(name=name), encoding="utf-8")
    return d


def _write_history(root: Path, name: str) -> Path:
    h = root / "custom" / ".history"
    h.mkdir(parents=True, exist_ok=True)
    f = h / f"{name}.jsonl"
    f.write_text('{"ts":"2026-01-01","action":"create"}\n', encoding="utf-8")
    return f


# ---------------------------------------------------------------------------
# Change 8a: basic migration moves skills and history
# ---------------------------------------------------------------------------

def test_migration_moves_flat_skill_to_default(tmp_path):
    _write_flat_skill(tmp_path, "my-skill")
    count = migrate(tmp_path, dry_run=False)
    assert count == 1
    assert (tmp_path / "custom" / "default" / "my-skill" / "SKILL.md").exists()
    assert not (tmp_path / "custom" / "my-skill").exists()


def test_migration_moves_multiple_skills(tmp_path):
    for name in ("skill-a", "skill-b", "skill-c"):
        _write_flat_skill(tmp_path, name)
    count = migrate(tmp_path, dry_run=False)
    assert count == 3
    for name in ("skill-a", "skill-b", "skill-c"):
        assert (tmp_path / "custom" / "default" / name / "SKILL.md").exists()


def test_migration_moves_history_file(tmp_path):
    _write_flat_skill(tmp_path, "hist-skill")
    _write_history(tmp_path, "hist-skill")
    count = migrate(tmp_path, dry_run=False)
    assert count == 2
    assert (tmp_path / "custom" / "default" / ".history" / "hist-skill.jsonl").exists()
    assert not (tmp_path / "custom" / ".history").exists()


def test_migration_removes_empty_history_dir(tmp_path):
    _write_flat_skill(tmp_path, "s")
    _write_history(tmp_path, "s")
    migrate(tmp_path, dry_run=False)
    assert not (tmp_path / "custom" / ".history").exists()


# ---------------------------------------------------------------------------
# Change 8b: dry-run does not modify filesystem
# ---------------------------------------------------------------------------

def test_dry_run_does_not_move_skills(tmp_path):
    _write_flat_skill(tmp_path, "dry-skill")
    count = migrate(tmp_path, dry_run=True)
    assert count == 1
    assert (tmp_path / "custom" / "dry-skill" / "SKILL.md").exists(), "Dry run should not move"
    assert not (tmp_path / "custom" / "default").exists()


def test_dry_run_does_not_move_history(tmp_path):
    _write_flat_skill(tmp_path, "s")
    _write_history(tmp_path, "s")
    count = migrate(tmp_path, dry_run=True)
    assert count == 2
    assert (tmp_path / "custom" / ".history" / "s.jsonl").exists()


# ---------------------------------------------------------------------------
# Change 8c: idempotency
# ---------------------------------------------------------------------------

def test_migration_is_idempotent(tmp_path):
    _write_flat_skill(tmp_path, "idem-skill")
    _write_history(tmp_path, "idem-skill")

    first = migrate(tmp_path, dry_run=False)
    assert first == 2

    second = migrate(tmp_path, dry_run=False)
    assert second == 0


def test_migration_skips_already_migrated_target(tmp_path):
    """If target custom/default/<name>/ already exists, skip without overwriting."""
    _write_flat_skill(tmp_path, "existing")
    # Pre-create the target
    target = tmp_path / "custom" / "default" / "existing"
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text("existing content", encoding="utf-8")

    count = migrate(tmp_path, dry_run=False)
    assert count == 0
    # Target still has its original content
    assert (target / "SKILL.md").read_text() == "existing content"


# ---------------------------------------------------------------------------
# Change 8d: edge cases
# ---------------------------------------------------------------------------

def test_migration_no_custom_dir_returns_zero(tmp_path):
    count = migrate(tmp_path, dry_run=False)
    assert count == 0


def test_migration_ignores_dir_without_skill_md(tmp_path):
    """A directory without SKILL.md is not a skill — must not be moved."""
    (tmp_path / "custom" / "not-a-skill").mkdir(parents=True)
    (tmp_path / "custom" / "not-a-skill" / "notes.txt").write_text("notes")
    count = migrate(tmp_path, dry_run=False)
    assert count == 0
    assert (tmp_path / "custom" / "not-a-skill").exists(), "Non-skill dir must not be moved"


def test_migration_ignores_hidden_dirs(tmp_path):
    """Hidden dirs like .history should not be treated as skill dirs."""
    (tmp_path / "custom" / ".history").mkdir(parents=True)
    count = migrate(tmp_path, dry_run=False)
    assert count == 0


def test_migration_already_namespaced_skills_unaffected(tmp_path):
    """Skills already under custom/default/ should not be double-moved."""
    (tmp_path / "custom" / "default" / "already-migrated").mkdir(parents=True)
    (tmp_path / "custom" / "default" / "already-migrated" / "SKILL.md").write_text(
        _SKILL_MD.format(name="already-migrated")
    )
    count = migrate(tmp_path, dry_run=False)
    # default/ dir contains SKILL.md in a subdir but the loop only operates on
    # items directly under custom/ — and custom/default/ has no SKILL.md directly
    assert count == 0
