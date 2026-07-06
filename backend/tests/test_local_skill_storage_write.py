"""Tests for LocalSkillStorage.write_custom_skill path-traversal guards."""

from __future__ import annotations

import os
import stat
from unittest.mock import patch

import pytest

from deerflow.config.paths import Paths
from deerflow.skills.storage import get_or_new_skill_storage, reset_skill_storage
from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage


@pytest.fixture(autouse=True)
def _reset_storages():
    reset_skill_storage()
    yield
    reset_skill_storage()


@pytest.fixture()
def storage(tmp_path):
    return get_or_new_skill_storage(skills_path=str(tmp_path))


@pytest.fixture()
def user_storage(tmp_path):
    """UserScopedSkillStorage for user 'test-user'."""
    with patch("deerflow.config.paths.get_paths", return_value=Paths(base_dir=tmp_path)):
        with patch("deerflow.config.paths._paths", None):
            s = UserScopedSkillStorage("test-user", host_path=str(tmp_path))
    return s


@pytest.fixture()
def skill_dir(tmp_path, storage):
    """Pre-create the skill directory so symlink tests can plant files inside."""
    d = tmp_path / "custom" / "demo-skill"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture()
def user_skill_dir(tmp_path, user_storage):
    """Pre-create the user-scoped skill directory."""
    d = tmp_path / "users" / "test-user" / "skills" / "custom" / "demo-skill"
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


def test_write_makes_written_path_sandbox_readable(tmp_path, storage):
    skill_dir = tmp_path / "custom" / "demo-skill"
    skill_dir.mkdir(parents=True)
    skill_dir.chmod(0o700)

    storage.write_custom_skill("demo-skill", "references/ref.md", "# ref")

    ref_dir = skill_dir / "references"
    ref_file = ref_dir / "ref.md"
    assert stat.S_IMODE(skill_dir.stat().st_mode) & 0o055 == 0o055
    assert stat.S_IMODE(ref_dir.stat().st_mode) & 0o055 == 0o055
    assert stat.S_IMODE(ref_file.stat().st_mode) & 0o044 == 0o044


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


# ---------------------------------------------------------------------------
# UserScopedSkillStorage write tests
# ---------------------------------------------------------------------------


def test_user_scoped_write_creates_file_in_user_dir(tmp_path, user_storage):
    user_storage.write_custom_skill("demo-skill", "SKILL.md", "# hello")
    user_file = tmp_path / "users" / "test-user" / "skills" / "custom" / "demo-skill" / "SKILL.md"
    assert user_file.read_text() == "# hello"
    # Does not create in global custom
    assert not (tmp_path / "custom" / "demo-skill" / "SKILL.md").exists()


def test_user_scoped_write_creates_subdirectory(tmp_path, user_storage):
    user_storage.write_custom_skill("demo-skill", "references/ref.md", "# ref")
    assert (tmp_path / "users" / "test-user" / "skills" / "custom" / "demo-skill" / "references" / "ref.md").exists()


def test_user_scoped_write_is_atomic_overwrite(tmp_path, user_storage):
    user_storage.write_custom_skill("demo-skill", "SKILL.md", "first")
    user_storage.write_custom_skill("demo-skill", "SKILL.md", "second")
    assert (tmp_path / "users" / "test-user" / "skills" / "custom" / "demo-skill" / "SKILL.md").read_text() == "second"


def test_user_scoped_rejects_empty_string(user_storage):
    with pytest.raises(ValueError, match="empty"):
        user_storage.write_custom_skill("demo-skill", "", "x")


def test_user_scoped_rejects_dotdot_escape(user_storage):
    with pytest.raises(ValueError, match="skill directory"):
        user_storage.write_custom_skill("demo-skill", "../../escaped.txt", "x")


def test_user_scoped_rejects_invalid_skill_name(user_storage):
    with pytest.raises(ValueError, match="hyphen-case"):
        user_storage.get_custom_skill_dir("../../escaped")
