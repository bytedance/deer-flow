"""Tests for Change 1: SkillStorage._get_custom_base() template method.

Verifies that the template method is correctly defined in the base class,
and that get_custom_skill_dir() / get_skill_history_file() both delegate to it,
so a subclass override propagates to all dependent path helpers.
"""

from __future__ import annotations

import pytest
from pathlib import Path
from deerflow.skills.storage.skill_storage import SkillStorage
from deerflow.skills.types import SkillCategory


class _ConcreteStorage(SkillStorage):
    """Minimal concrete subclass using the default _get_custom_base()."""

    def __init__(self, root: Path) -> None:
        super().__init__(container_path="/mnt/skills")
        self._root = root

    def get_skills_root_path(self) -> Path:
        return self._root

    # --- minimal stubs for abstract methods ---
    def custom_skill_exists(self, name): return False
    def public_skill_exists(self, name): return False
    def _iter_skill_files(self): return iter([])
    def read_custom_skill(self, name): raise NotImplementedError
    def write_custom_skill(self, name, relative_path, content): raise NotImplementedError
    def delete_custom_skill(self, name, *, history_meta=None): raise NotImplementedError
    def append_history(self, name, record): raise NotImplementedError
    def read_history(self, name): return []
    async def ainstall_skill_from_archive(self, archive_path): raise NotImplementedError


class _OverriddenStorage(_ConcreteStorage):
    """Subclass that overrides _get_custom_base() to inject user scoping."""

    def __init__(self, root: Path, user_id: str) -> None:
        super().__init__(root)
        self._user_id = user_id

    def _get_custom_base(self) -> Path:
        return self._root / SkillCategory.CUSTOM.value / self._user_id


# ---------------------------------------------------------------------------
# Change 1a: default implementation returns custom/ under root
# ---------------------------------------------------------------------------

def test_default_get_custom_base_returns_custom_subdir(tmp_path):
    storage = _ConcreteStorage(tmp_path)
    assert storage._get_custom_base() == tmp_path / "custom"


def test_default_get_custom_skill_dir_uses_custom_base(tmp_path):
    storage = _ConcreteStorage(tmp_path)
    result = storage.get_custom_skill_dir("my-skill")
    assert result == tmp_path / "custom" / "my-skill"


def test_default_get_skill_history_file_uses_custom_base(tmp_path):
    storage = _ConcreteStorage(tmp_path)
    result = storage.get_skill_history_file("my-skill")
    assert result == tmp_path / "custom" / ".history" / "my-skill.jsonl"


# ---------------------------------------------------------------------------
# Change 1b: subclass override propagates to all path helpers
# ---------------------------------------------------------------------------

def test_override_get_custom_base_changes_skill_dir(tmp_path):
    storage = _OverriddenStorage(tmp_path, "alice")
    assert storage.get_custom_skill_dir("skill-a") == tmp_path / "custom" / "alice" / "skill-a"


def test_override_get_custom_base_changes_history_file(tmp_path):
    storage = _OverriddenStorage(tmp_path, "bob")
    assert storage.get_skill_history_file("skill-b") == tmp_path / "custom" / "bob" / ".history" / "skill-b.jsonl"


def test_override_get_custom_skill_file_also_uses_custom_base(tmp_path):
    storage = _OverriddenStorage(tmp_path, "carol")
    # get_custom_skill_file calls get_custom_skill_dir which uses _get_custom_base
    result = storage.get_custom_skill_file("skill-c")
    assert result == tmp_path / "custom" / "carol" / "skill-c" / "SKILL.md"


def test_two_subclasses_different_namespaces(tmp_path):
    s_alice = _OverriddenStorage(tmp_path, "alice")
    s_bob = _OverriddenStorage(tmp_path, "bob")
    assert s_alice._get_custom_base() != s_bob._get_custom_base()
    assert s_alice.get_custom_skill_dir("shared") != s_bob.get_custom_skill_dir("shared")
