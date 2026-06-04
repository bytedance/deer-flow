"""Tests for Change 3: get_or_new_skill_storage() transparently passes user_id.

Verifies:
- user_id kwarg bypasses the process singleton and creates a fresh instance
- Different user_ids produce storages with different _get_custom_base() paths
- user_id=None still returns/creates the singleton
- app_config + user_id creates a fresh per-user instance (no singleton pollution)
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from deerflow.skills.storage import get_or_new_skill_storage, reset_skill_storage
from deerflow.skills.storage.local_skill_storage import LocalSkillStorage


def _config(root: Path) -> object:
    return SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: root,
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        )
    )


# ---------------------------------------------------------------------------
# Change 3a: user_id bypasses the singleton
# ---------------------------------------------------------------------------

def test_user_id_creates_fresh_instance_not_singleton(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    reset_skill_storage()

    s1 = get_or_new_skill_storage(user_id="alice")
    s2 = get_or_new_skill_storage(user_id="alice")
    # Each call creates a fresh instance (never the singleton)
    assert s1 is not s2


def test_no_user_id_returns_singleton(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    reset_skill_storage()

    s1 = get_or_new_skill_storage()
    s2 = get_or_new_skill_storage()
    assert s1 is s2


# ---------------------------------------------------------------------------
# Change 3b: different user_ids produce different base paths
# ---------------------------------------------------------------------------

def test_different_user_ids_produce_different_custom_bases(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)

    s_alice = get_or_new_skill_storage(user_id="alice")
    s_bob = get_or_new_skill_storage(user_id="bob")

    assert s_alice._get_custom_base() != s_bob._get_custom_base()
    assert s_alice._get_custom_base() == tmp_path / "custom" / "alice"
    assert s_bob._get_custom_base() == tmp_path / "custom" / "bob"


def test_user_id_with_app_config_uses_config_skills_path(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: _config(tmp_path / "wrong"))

    s = get_or_new_skill_storage(user_id="frank", app_config=config)
    # Must use the explicitly passed config, not the ambient one
    assert str(s._get_custom_base()).startswith(str(tmp_path))
    assert "frank" in str(s._get_custom_base())


# ---------------------------------------------------------------------------
# Change 3c: user_id instance is a proper LocalSkillStorage
# ---------------------------------------------------------------------------

def test_user_id_returns_local_skill_storage_instance(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)

    s = get_or_new_skill_storage(user_id="grace")
    assert isinstance(s, LocalSkillStorage)


def test_singleton_does_not_have_user_id(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    reset_skill_storage()

    singleton = get_or_new_skill_storage()
    # Singleton has no user_id, so _get_custom_base() returns flat path
    assert singleton._get_custom_base() == tmp_path / "custom"
