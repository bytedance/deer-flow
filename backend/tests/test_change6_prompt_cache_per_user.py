"""Tests for Change 6: Prompt cache keyed per-user (id(app_config), user_id).

Verifies:
- Cache key includes user_id — two users with same config get separate entries
- Same user with same config reuses the cached skills (load_skills called once)
- Invalidation clears all user entries for the config
- ContextVar user_id is correctly picked up by get_enabled_skills_for_config
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import deerflow.agents.lead_agent.prompt as prompt_module
from deerflow.runtime.user_context import reset_current_user, set_current_user


_SKILL_MD = "---\nname: {name}\ndescription: Test\nlicense: MIT\n---\n\n# {name}\n"


def _config(root: Path) -> object:
    return SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: root,
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        ),
        skill_evolution=SimpleNamespace(enabled=False),
    )


def _write_skill(root: Path, user_id: str, name: str) -> None:
    from deerflow.skills.storage.local_skill_storage import LocalSkillStorage
    s = LocalSkillStorage(host_path=str(root), user_id=user_id)
    d = s._get_custom_base() / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(_SKILL_MD.format(name=name), encoding="utf-8")


@pytest.fixture(autouse=True)
def _clear_prompt_cache():
    prompt_module._enabled_skills_by_config_cache.clear()
    prompt_module._get_cached_skills_prompt_section.cache_clear()
    yield
    prompt_module._enabled_skills_by_config_cache.clear()
    prompt_module._get_cached_skills_prompt_section.cache_clear()


# ---------------------------------------------------------------------------
# Change 6a: cache key is (id(config), user_id) — separate per user
# ---------------------------------------------------------------------------

def test_cache_keyed_by_both_config_and_user_id(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)

    _write_skill(tmp_path, "u1", "skill-u1")
    _write_skill(tmp_path, "u2", "skill-u2")

    t1 = set_current_user(SimpleNamespace(id="u1", email="u1@test"))
    try:
        skills_u1 = prompt_module.get_enabled_skills_for_config(config)
    finally:
        reset_current_user(t1)

    t2 = set_current_user(SimpleNamespace(id="u2", email="u2@test"))
    try:
        skills_u2 = prompt_module.get_enabled_skills_for_config(config)
    finally:
        reset_current_user(t2)

    names_u1 = {s.name for s in skills_u1}
    names_u2 = {s.name for s in skills_u2}

    assert "skill-u1" in names_u1
    assert "skill-u2" not in names_u1
    assert "skill-u2" in names_u2
    assert "skill-u1" not in names_u2


def test_cache_has_separate_entries_for_different_users(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)

    for uid in ("ua", "ub"):
        t = set_current_user(SimpleNamespace(id=uid, email=f"{uid}@test"))
        try:
            prompt_module.get_enabled_skills_for_config(config)
        finally:
            reset_current_user(t)

    # Two separate cache entries
    keys = list(prompt_module._enabled_skills_by_config_cache.keys())
    user_ids_in_cache = {k[1] for k in keys if k[0] == id(config)}
    assert "ua" in user_ids_in_cache
    assert "ub" in user_ids_in_cache


# ---------------------------------------------------------------------------
# Change 6b: same user reuses cached entry (no duplicate disk reads)
# ---------------------------------------------------------------------------

def test_same_user_reuses_cache(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    _write_skill(tmp_path, "cached-user", "skill-x")

    call_count = 0
    original_get = prompt_module.get_or_new_skill_storage

    def counting_get(**kwargs):
        nonlocal call_count
        call_count += 1
        return original_get(**kwargs)

    monkeypatch.setattr(prompt_module, "get_or_new_skill_storage", counting_get)

    t = set_current_user(SimpleNamespace(id="cached-user", email="c@test"))
    try:
        prompt_module.get_enabled_skills_for_config(config)
        prompt_module.get_enabled_skills_for_config(config)
    finally:
        reset_current_user(t)

    assert call_count == 1, f"Expected 1 load call but got {call_count}"


# ---------------------------------------------------------------------------
# Change 6c: invalidation clears all user cache entries
# ---------------------------------------------------------------------------

def test_invalidation_clears_all_per_user_entries(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)

    for uid in ("x", "y", "z"):
        t = set_current_user(SimpleNamespace(id=uid, email=f"{uid}@test"))
        try:
            prompt_module.get_enabled_skills_for_config(config)
        finally:
            reset_current_user(t)

    assert len(prompt_module._enabled_skills_by_config_cache) >= 3

    prompt_module._invalidate_enabled_skills_cache()

    assert len(prompt_module._enabled_skills_by_config_cache) == 0


# ---------------------------------------------------------------------------
# Change 6d: cache key uses user_id from ContextVar fallback
# ---------------------------------------------------------------------------

def test_cache_uses_effective_user_id_from_contextvar(tmp_path, monkeypatch):
    """get_enabled_skills_for_config reads user_id from ContextVar automatically."""
    config = _config(tmp_path)
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)

    t = set_current_user(SimpleNamespace(id="ctx-user", email="ctx@test"))
    try:
        prompt_module.get_enabled_skills_for_config(config)
        keys = list(prompt_module._enabled_skills_by_config_cache.keys())
    finally:
        reset_current_user(t)

    user_ids = {k[1] for k in keys}
    assert "ctx-user" in user_ids
