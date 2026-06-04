"""Tests for Change 2: LocalSkillStorage supports per-user namespace via user_id.

Verifies:
- user_id=None  →  flat legacy layout  custom/<name>/
- user_id="uid" →  namespaced layout   custom/<uid>/<name>/
- _iter_skill_files only walks the current user's subtree
- ainstall_skill_from_archive lands in the user's namespace
"""

from __future__ import annotations

import zipfile
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from deerflow.skills.storage.local_skill_storage import LocalSkillStorage
from deerflow.skills.types import SkillCategory


_SKILL_MD = "---\nname: {name}\ndescription: A test skill\nlicense: MIT\n---\n\n# {name}\n"


def _make_storage(root: Path, user_id=None) -> LocalSkillStorage:
    return LocalSkillStorage(host_path=str(root), user_id=user_id)


# ---------------------------------------------------------------------------
# Change 2a: path construction with and without user_id
# ---------------------------------------------------------------------------

def test_no_user_id_uses_flat_custom_path(tmp_path):
    s = _make_storage(tmp_path)
    assert s._get_custom_base() == tmp_path / "custom"


def test_user_id_creates_namespaced_custom_path(tmp_path):
    s = _make_storage(tmp_path, user_id="alice")
    assert s._get_custom_base() == tmp_path / "custom" / "alice"


def test_user_id_skill_dir_includes_user_segment(tmp_path):
    s = _make_storage(tmp_path, user_id="bob")
    assert s.get_custom_skill_dir("my-skill") == tmp_path / "custom" / "bob" / "my-skill"


def test_user_id_history_file_includes_user_segment(tmp_path):
    s = _make_storage(tmp_path, user_id="carol")
    assert s.get_skill_history_file("my-skill") == tmp_path / "custom" / "carol" / ".history" / "my-skill.jsonl"


def test_different_user_ids_produce_different_paths(tmp_path):
    s1 = _make_storage(tmp_path, user_id="user-1")
    s2 = _make_storage(tmp_path, user_id="user-2")
    assert s1._get_custom_base() != s2._get_custom_base()
    assert s1.get_custom_skill_dir("skill") != s2.get_custom_skill_dir("skill")


# ---------------------------------------------------------------------------
# Change 2b: _iter_skill_files scoped to user subtree
# ---------------------------------------------------------------------------

def _write_skill(root: Path, user_id: str | None, name: str) -> Path:
    if user_id:
        base = root / "custom" / user_id / name
    else:
        base = root / "custom" / name
    base.mkdir(parents=True, exist_ok=True)
    (base / "SKILL.md").write_text(_SKILL_MD.format(name=name), encoding="utf-8")
    return base


def test_iter_skill_files_user_only_sees_own_skills(tmp_path):
    _write_skill(tmp_path, "alice", "skill-a")
    _write_skill(tmp_path, "bob", "skill-b")

    s_alice = _make_storage(tmp_path, user_id="alice")
    names_alice = {f.parent.name for _, _, f in s_alice._iter_skill_files() if f.parent.parent != tmp_path / "custom" / "alice"}

    # load_skills uses _iter_skill_files
    skills_alice = list(s_alice.load_skills(enabled_only=False))
    names_alice = {s.name for s in skills_alice if s.category == SkillCategory.CUSTOM}

    assert "skill-a" in names_alice
    assert "skill-b" not in names_alice


def test_iter_skill_files_no_user_id_sees_flat_layout(tmp_path):
    _write_skill(tmp_path, None, "public-flat-skill")

    s = _make_storage(tmp_path, user_id=None)
    skills = list(s.load_skills(enabled_only=False))
    names = {sk.name for sk in skills if sk.category == SkillCategory.CUSTOM}
    assert "public-flat-skill" in names


def test_iter_skill_files_does_not_walk_other_user_dirs(tmp_path):
    _write_skill(tmp_path, "user-x", "x-skill")
    _write_skill(tmp_path, "user-y", "y-skill")

    s_x = _make_storage(tmp_path, user_id="user-x")
    skills = list(s_x.load_skills(enabled_only=False))
    names = {sk.name for sk in skills if sk.category == SkillCategory.CUSTOM}

    assert "x-skill" in names
    assert "y-skill" not in names


# ---------------------------------------------------------------------------
# Change 2c: write / exists / read / delete respect user namespace
# ---------------------------------------------------------------------------

def test_write_and_exists_in_user_namespace(tmp_path):
    s = _make_storage(tmp_path, user_id="dana")
    s.write_custom_skill("new-skill", "SKILL.md", _SKILL_MD.format(name="new-skill"))
    assert s.custom_skill_exists("new-skill")
    # File is under user namespace
    assert (tmp_path / "custom" / "dana" / "new-skill" / "SKILL.md").exists()


def test_write_does_not_leak_to_other_user(tmp_path):
    s_alice = _make_storage(tmp_path, user_id="alice")
    s_bob = _make_storage(tmp_path, user_id="bob")
    s_alice.write_custom_skill("shared-name", "SKILL.md", _SKILL_MD.format(name="shared-name"))

    assert s_alice.custom_skill_exists("shared-name")
    assert not s_bob.custom_skill_exists("shared-name")


def test_delete_only_removes_from_user_namespace(tmp_path):
    s_alice = _make_storage(tmp_path, user_id="alice")
    s_bob = _make_storage(tmp_path, user_id="bob")

    for s in (s_alice, s_bob):
        s.write_custom_skill("common", "SKILL.md", _SKILL_MD.format(name="common"))

    s_alice.delete_custom_skill("common")
    assert not s_alice.custom_skill_exists("common")
    assert s_bob.custom_skill_exists("common")


# ---------------------------------------------------------------------------
# Change 2d: ainstall_skill_from_archive goes to user namespace
# ---------------------------------------------------------------------------

def _build_skill_archive(tmp_path: Path, name: str) -> Path:
    skill_dir = tmp_path / f"{name}-src"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(_SKILL_MD.format(name=name), encoding="utf-8")

    archive = tmp_path / f"{name}.skill"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(skill_dir / "SKILL.md", f"{name}/SKILL.md")
    return archive


import anyio


async def _noop_scan(*a, **k):
    return None


def test_install_places_skill_in_user_namespace(tmp_path, monkeypatch):
    monkeypatch.setattr("deerflow.skills.installer._scan_skill_archive_contents_or_raise", _noop_scan)
    archive = _build_skill_archive(tmp_path, "installed-skill")
    s = _make_storage(tmp_path, user_id="eve")
    result = anyio.run(s.ainstall_skill_from_archive, archive)
    assert result["success"] is True
    assert (tmp_path / "custom" / "eve" / "installed-skill" / "SKILL.md").exists()
