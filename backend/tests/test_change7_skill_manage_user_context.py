"""Tests for Change 7: skill_manage_tool uses resolve_runtime_user_id(runtime).

Verifies:
- runtime.context["user_id"] takes priority for storage namespace
- ContextVar fallback is used when runtime has no user_id
- Different runtime user_ids create/read from separate namespaces
- create/patch/edit/delete all respect the per-user namespace
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest

skill_manage_module = importlib.import_module("deerflow.tools.skill_manage_tool")

_SKILL_MD = "---\nname: {name}\ndescription: Test skill\nlicense: MIT\n---\n\n# {name}\n"


async def _noop_scan(*a, **k):
    from deerflow.skills.security_scanner import ScanResult
    return ScanResult(decision="allow", reason="ok")


async def _noop_refresh():
    pass


def _setup(tmp_path: Path, monkeypatch) -> None:
    config = SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: tmp_path / "skills",
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        ),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.skills.security_scanner.get_app_config", lambda: config)
    monkeypatch.setattr(skill_manage_module, "refresh_skills_system_prompt_cache_async", _noop_refresh)
    monkeypatch.setattr(skill_manage_module, "scan_skill_content", lambda *a, **k: _noop_scan())
    return tmp_path / "skills"


def _runtime(user_id: str) -> object:
    return SimpleNamespace(context={"thread_id": "t1", "user_id": user_id}, config={"configurable": {}})


def _runtime_no_user() -> object:
    """Runtime with no user_id — should fall back to ContextVar."""
    return SimpleNamespace(context={"thread_id": "t1"}, config={"configurable": {}})


# ---------------------------------------------------------------------------
# Change 7a: runtime.context["user_id"] drives the namespace
# ---------------------------------------------------------------------------

def test_create_uses_runtime_user_id_for_namespace(tmp_path, monkeypatch):
    skills_root = _setup(tmp_path, monkeypatch)
    runtime = _runtime("user-alpha")

    anyio.run(skill_manage_module.skill_manage_tool.coroutine, runtime, "create", "my-skill", _SKILL_MD.format(name="my-skill"))

    assert (skills_root / "custom" / "user-alpha" / "my-skill" / "SKILL.md").exists()
    assert not (skills_root / "custom" / "my-skill").exists(), "Should be scoped to user, not flat"


def test_different_runtime_users_get_separate_namespaces(tmp_path, monkeypatch):
    skills_root = _setup(tmp_path, monkeypatch)

    for uid in ("user-a", "user-b"):
        runtime = _runtime(uid)
        anyio.run(skill_manage_module.skill_manage_tool.coroutine, runtime, "create", "shared-name", _SKILL_MD.format(name="shared-name"))

    assert (skills_root / "custom" / "user-a" / "shared-name" / "SKILL.md").exists()
    assert (skills_root / "custom" / "user-b" / "shared-name" / "SKILL.md").exists()


def test_edit_resolves_only_own_user_skill(tmp_path, monkeypatch):
    """User B edit must not find user A's skill."""
    skills_root = _setup(tmp_path, monkeypatch)

    # Create for user-a
    anyio.run(skill_manage_module.skill_manage_tool.coroutine, _runtime("user-a"), "create", "exclusive", _SKILL_MD.format(name="exclusive"))

    # User-b edit must fail (FileNotFoundError or ValueError)
    with pytest.raises((ValueError, FileNotFoundError)):
        anyio.run(skill_manage_module.skill_manage_tool.coroutine, _runtime("user-b"), "edit", "exclusive", _SKILL_MD.format(name="exclusive"))


def test_patch_scoped_to_runtime_user(tmp_path, monkeypatch):
    skills_root = _setup(tmp_path, monkeypatch)

    anyio.run(skill_manage_module.skill_manage_tool.coroutine, _runtime("patcher"), "create", "patch-me", _SKILL_MD.format(name="patch-me"))
    anyio.run(
        skill_manage_module.skill_manage_tool.coroutine,
        _runtime("patcher"), "patch", "patch-me", None, None, "Test skill", "Updated skill",
    )

    content = (skills_root / "custom" / "patcher" / "patch-me" / "SKILL.md").read_text(encoding="utf-8")
    assert "Updated skill" in content


def test_delete_scoped_to_runtime_user(tmp_path, monkeypatch):
    skills_root = _setup(tmp_path, monkeypatch)

    for uid in ("del-user", "keep-user"):
        anyio.run(skill_manage_module.skill_manage_tool.coroutine, _runtime(uid), "create", "to-delete", _SKILL_MD.format(name="to-delete"))

    anyio.run(skill_manage_module.skill_manage_tool.coroutine, _runtime("del-user"), "delete", "to-delete")

    assert not (skills_root / "custom" / "del-user" / "to-delete").exists()
    assert (skills_root / "custom" / "keep-user" / "to-delete" / "SKILL.md").exists()


# ---------------------------------------------------------------------------
# Change 7b: ContextVar fallback when no user_id in runtime.context
# ---------------------------------------------------------------------------

def test_contextvar_fallback_when_no_runtime_user_id(tmp_path, monkeypatch):
    skills_root = _setup(tmp_path, monkeypatch)

    from deerflow.runtime.user_context import reset_current_user, set_current_user

    token = set_current_user(SimpleNamespace(id="ctx-fallback-user", email="f@test"))
    try:
        anyio.run(skill_manage_module.skill_manage_tool.coroutine, _runtime_no_user(), "create", "ctx-skill", _SKILL_MD.format(name="ctx-skill"))
    finally:
        reset_current_user(token)

    assert (skills_root / "custom" / "ctx-fallback-user" / "ctx-skill" / "SKILL.md").exists()


# ---------------------------------------------------------------------------
# Change 7c: history is written to user namespace
# ---------------------------------------------------------------------------

def test_history_written_to_user_namespace(tmp_path, monkeypatch):
    skills_root = _setup(tmp_path, monkeypatch)
    runtime = _runtime("hist-user")

    anyio.run(skill_manage_module.skill_manage_tool.coroutine, runtime, "create", "hist-skill", _SKILL_MD.format(name="hist-skill"))

    history_file = skills_root / "custom" / "hist-user" / ".history" / "hist-skill.jsonl"
    assert history_file.exists()
    assert "create" in history_file.read_text(encoding="utf-8")
