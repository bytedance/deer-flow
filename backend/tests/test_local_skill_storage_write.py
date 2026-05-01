"""Tests for LocalSkillStorage.write_custom_skill path-traversal guards."""

from __future__ import annotations

import os

import pytest

from deerflow.skills.storage import get_or_new_skill_storage


@pytest.fixture()
def storage(tmp_path):
    return get_or_new_skill_storage(skills_path=str(tmp_path))


@pytest.fixture()
def skill_dir(tmp_path, storage):
    """Pre-create the skill directory so symlink tests can plant files inside."""
    d = tmp_path / "custom" / "demo-skill"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_write_creates_file(tmp_path, storage):
    storage.write_custom_skill("demo-skill", "SKILL.md", "# hello")
    assert (tmp_path / "custom" / "demo-skill" / "SKILL.md").read_text() == "# hello"


def test_write_creates_subdirectory(tmp_path, storage):
    storage.write_custom_skill("demo-skill", "references/ref.md", "# ref")
    assert (tmp_path / "custom" / "demo-skill" / "references" / "ref.md").exists()


def test_write_is_atomic_overwrite(tmp_path, storage):
    storage.write_custom_skill("demo-skill", "SKILL.md", "first")
    storage.write_custom_skill("demo-skill", "SKILL.md", "second")
    assert (tmp_path / "custom" / "demo-skill" / "SKILL.md").read_text() == "second"


# ---------------------------------------------------------------------------
# Empty / blank path
# ---------------------------------------------------------------------------


def test_rejects_empty_string(storage):
    with pytest.raises(ValueError, match="empty"):
        storage.write_custom_skill("demo-skill", "", "x")


# ---------------------------------------------------------------------------
# Absolute paths
# ---------------------------------------------------------------------------


def test_rejects_absolute_unix_path(storage):
    with pytest.raises(ValueError, match="skill directory"):
        storage.write_custom_skill("demo-skill", "/etc/passwd", "x")


def test_rejects_absolute_path_with_skill_prefix(tmp_path, storage):
    """Absolute path within skill dir: containment check passes (not a security issue).

    Python's Path(base) / "/abs/path" ignores base and returns /abs/path directly.
    If that absolute path resolves within skill_dir, the write succeeds.
    This is not an escape — the file lands in the correct location.
    """
    absolute = str(tmp_path / "custom" / "demo-skill" / "SKILL.md")
    # Does not raise; the write goes to the expected place
    storage.write_custom_skill("demo-skill", absolute, "# ok")
    assert (tmp_path / "custom" / "demo-skill" / "SKILL.md").read_text() == "# ok"


# ---------------------------------------------------------------------------
# Parent-directory traversal
# ---------------------------------------------------------------------------


def test_rejects_dotdot_escape(storage):
    with pytest.raises(ValueError, match="skill directory"):
        storage.write_custom_skill("demo-skill", "../../escaped.txt", "x")


def test_rejects_dotdot_sibling(storage):
    with pytest.raises(ValueError, match="skill directory"):
        storage.write_custom_skill("demo-skill", "../sibling/x.txt", "x")


def test_rejects_dotdot_in_subpath(storage):
    with pytest.raises(ValueError, match="skill directory"):
        storage.write_custom_skill("demo-skill", "sub/../../escape.txt", "x")


def test_rejects_dotdot_only(storage):
    with pytest.raises(ValueError, match="skill directory"):
        storage.write_custom_skill("demo-skill", "..", "x")


# ---------------------------------------------------------------------------
# Symlink escape
# ---------------------------------------------------------------------------


def test_rejects_symlink_pointing_outside(tmp_path, storage, skill_dir):
    outside = tmp_path / "outside.txt"
    link = skill_dir / "escape_link.txt"
    os.symlink(outside, link)
    with pytest.raises(ValueError, match="skill directory"):
        storage.write_custom_skill("demo-skill", "escape_link.txt", "x")


def test_rejects_symlink_dir_pointing_outside(tmp_path, storage, skill_dir):
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    link_dir = skill_dir / "linked_dir"
    os.symlink(outside_dir, link_dir)
    with pytest.raises(ValueError, match="skill directory"):
        storage.write_custom_skill("demo-skill", "linked_dir/file.txt", "x")


def test_allows_symlink_within_skill_dir(tmp_path, storage, skill_dir):
    """A symlink that resolves inside the skill directory is allowed.

    Because target is resolved before writing, the write goes to the real file
    the symlink points to (both the link and the real file end up with the new
    content).
    """
    real_file = skill_dir / "real.md"
    real_file.write_text("real")
    link = skill_dir / "alias.md"
    os.symlink(real_file, link)
    # Should not raise
    storage.write_custom_skill("demo-skill", "alias.md", "updated")
    # resolve() writes through to the real target file
    assert real_file.read_text() == "updated"
    assert (skill_dir / "alias.md").read_text() == "updated"


# ---------------------------------------------------------------------------
# Invalid skill-name traversal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,method_name",
    [
        ("../../escaped", "get_custom_skill_dir"),
        ("../../escaped", "get_custom_skill_file"),
        ("../../escaped", "get_skill_history_file"),
        ("../../escaped", "custom_skill_exists"),
        ("../../escaped", "public_skill_exists"),
    ],
)
def test_rejects_invalid_skill_name_in_path_helpers(storage, name, method_name):
    method = getattr(storage, method_name)
    with pytest.raises(ValueError, match="hyphen-case"):
        method(name)
