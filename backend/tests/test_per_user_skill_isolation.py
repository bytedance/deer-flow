"""User-isolation tests for custom skills.

Verifies that:
- User A's custom skills are invisible to User B via the router
- User A and User B can each CRUD their own skills without affecting each other
- The per-user prompt cache is keyed separately for each user
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import anyio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

skills_router = importlib.import_module("app.gateway.routers.skills")
skill_manage_module = importlib.import_module("deerflow.tools.skill_manage_tool")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SKILL_MD = "---\nname: {name}\ndescription: Test skill {name}\nlicense: MIT\n---\n\n# {name}\n"


def _make_app(storage) -> FastAPI:
    from app.gateway.deps import get_skill_storage

    app = FastAPI()
    app.state.config = SimpleNamespace(
        skills=SimpleNamespace(container_path="/mnt/skills"),
        skill_evolution=SimpleNamespace(enabled=False),
    )
    app.include_router(skills_router.router)
    app.dependency_overrides[get_skill_storage] = lambda: storage
    return app


def _make_storage(tmp_path, user_id: str):
    from deerflow.skills.storage.local_skill_storage import LocalSkillStorage

    return LocalSkillStorage(host_path=str(tmp_path / "skills"), user_id=user_id)


async def _noop_refresh():
    pass


# ---------------------------------------------------------------------------
# Router-level isolation tests
# ---------------------------------------------------------------------------


def test_users_cannot_see_each_others_custom_skills(monkeypatch, tmp_path):
    """User A's custom skill must not appear in User B's skill list."""
    monkeypatch.setattr(skills_router, "refresh_skills_system_prompt_cache_async", _noop_refresh)
    monkeypatch.setattr(skills_router, "scan_skill_content", lambda *a, **k: _noop_scan())

    storage_a = _make_storage(tmp_path, "user-a")
    storage_b = _make_storage(tmp_path, "user-b")

    # Create a skill for user-a directly on disk
    skill_dir_a = storage_a._get_custom_base() / "skill-a"
    skill_dir_a.mkdir(parents=True)
    (skill_dir_a / "SKILL.md").write_text(_SKILL_MD.format(name="skill-a"), encoding="utf-8")

    client_a = TestClient(_make_app(storage_a))
    client_b = TestClient(_make_app(storage_b))

    resp_a = client_a.get("/api/skills/custom")
    assert resp_a.status_code == 200
    names_a = {s["name"] for s in resp_a.json()["skills"]}
    assert "skill-a" in names_a

    resp_b = client_b.get("/api/skills/custom")
    assert resp_b.status_code == 200
    names_b = {s["name"] for s in resp_b.json()["skills"]}
    assert "skill-a" not in names_b


def test_user_b_cannot_edit_user_a_skill(monkeypatch, tmp_path):
    """User B's router must return 404 when trying to edit user A's skill."""
    monkeypatch.setattr(skills_router, "refresh_skills_system_prompt_cache_async", _noop_refresh)

    storage_a = _make_storage(tmp_path, "user-a")
    storage_b = _make_storage(tmp_path, "user-b")

    # Create a skill for user-a
    skill_dir_a = storage_a._get_custom_base() / "shared-name"
    skill_dir_a.mkdir(parents=True)
    (skill_dir_a / "SKILL.md").write_text(_SKILL_MD.format(name="shared-name"), encoding="utf-8")

    client_b = TestClient(_make_app(storage_b))
    resp = client_b.put("/api/skills/custom/shared-name", json={"content": _SKILL_MD.format(name="shared-name")})
    assert resp.status_code == 404


def test_user_b_cannot_delete_user_a_skill(monkeypatch, tmp_path):
    """User B's router must return 404 when trying to delete user A's skill."""
    monkeypatch.setattr(skills_router, "refresh_skills_system_prompt_cache_async", _noop_refresh)

    storage_a = _make_storage(tmp_path, "user-a")
    storage_b = _make_storage(tmp_path, "user-b")

    skill_dir_a = storage_a._get_custom_base() / "shared-name"
    skill_dir_a.mkdir(parents=True)
    (skill_dir_a / "SKILL.md").write_text(_SKILL_MD.format(name="shared-name"), encoding="utf-8")

    client_b = TestClient(_make_app(storage_b))
    resp = client_b.delete("/api/skills/custom/shared-name")
    assert resp.status_code == 404

    # Original skill still exists for user-a
    assert (skill_dir_a / "SKILL.md").exists()


def test_two_users_same_skill_name_independent(monkeypatch, tmp_path):
    """Two users can independently create skills with the same name."""
    monkeypatch.setattr(skills_router, "refresh_skills_system_prompt_cache_async", _noop_refresh)
    monkeypatch.setattr(skills_router, "scan_skill_content", lambda *a, **k: _noop_scan())

    storage_a = _make_storage(tmp_path, "user-a")
    storage_b = _make_storage(tmp_path, "user-b")

    for storage in (storage_a, storage_b):
        skill_dir = storage._get_custom_base() / "common-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(_SKILL_MD.format(name="common-skill"), encoding="utf-8")

    client_a = TestClient(_make_app(storage_a))
    client_b = TestClient(_make_app(storage_b))

    resp_a = client_a.get("/api/skills/custom/common-skill")
    resp_b = client_b.get("/api/skills/custom/common-skill")

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    assert resp_a.json()["name"] == "common-skill"
    assert resp_b.json()["name"] == "common-skill"


# ---------------------------------------------------------------------------
# Prompt-cache isolation test
# ---------------------------------------------------------------------------


def test_prompt_cache_keyed_per_user(monkeypatch, tmp_path):
    """get_enabled_skills_for_config must return different skills for different users."""
    import deerflow.agents.lead_agent.prompt as prompt_module

    skills_root = tmp_path / "skills"
    config = SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: skills_root,
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        ),
        skill_evolution=SimpleNamespace(enabled=False),
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)

    from deerflow.runtime.user_context import reset_current_user, set_current_user
    from deerflow.skills.storage import reset_skill_storage

    reset_skill_storage()
    prompt_module._enabled_skills_by_config_cache.clear()

    def _write_skill(user_id: str, name: str) -> None:
        from deerflow.skills.storage.local_skill_storage import LocalSkillStorage

        s = LocalSkillStorage(host_path=str(skills_root), user_id=user_id)
        base = s._get_custom_base() / name
        base.mkdir(parents=True, exist_ok=True)
        (base / "SKILL.md").write_text(_SKILL_MD.format(name=name), encoding="utf-8")

    _write_skill("user-x", "skill-x")
    _write_skill("user-y", "skill-y")

    token_x = set_current_user(SimpleNamespace(id="user-x", email="x@test"))
    try:
        skills_x = prompt_module.get_enabled_skills_for_config(config)
        names_x = {s.name for s in skills_x}
    finally:
        reset_current_user(token_x)

    token_y = set_current_user(SimpleNamespace(id="user-y", email="y@test"))
    try:
        skills_y = prompt_module.get_enabled_skills_for_config(config)
        names_y = {s.name for s in skills_y}
    finally:
        reset_current_user(token_y)

    assert "skill-x" in names_x
    assert "skill-y" not in names_x
    assert "skill-y" in names_y
    assert "skill-x" not in names_y


# ---------------------------------------------------------------------------
# skill_manage_tool isolation test
# ---------------------------------------------------------------------------


def test_skill_manage_tool_isolated_by_user_id(monkeypatch, tmp_path):
    """Skills created by user-a's runtime must not be visible to user-b's runtime."""
    skills_root = tmp_path / "skills"
    config = SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: skills_root,
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        ),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.skills.security_scanner.get_app_config", lambda: config)
    monkeypatch.setattr(skill_manage_module, "refresh_skills_system_prompt_cache_async", _noop_refresh)
    monkeypatch.setattr(skill_manage_module, "scan_skill_content", lambda *a, **k: _noop_scan())

    runtime_a = SimpleNamespace(context={"thread_id": "t1", "user_id": "user-a"}, config={"configurable": {}})
    runtime_b = SimpleNamespace(context={"thread_id": "t2", "user_id": "user-b"}, config={"configurable": {}})

    anyio.run(skill_manage_module.skill_manage_tool.coroutine, runtime_a, "create", "my-skill", _SKILL_MD.format(name="my-skill"))

    # user-b should not see my-skill — edit must raise FileNotFoundError
    with pytest.raises((ValueError, FileNotFoundError)):
        anyio.run(skill_manage_module.skill_manage_tool.coroutine, runtime_b, "edit", "my-skill", _SKILL_MD.format(name="my-skill"))

    # user-a skill exists at the correct path
    from deerflow.skills.storage.local_skill_storage import LocalSkillStorage

    storage_a = LocalSkillStorage(host_path=str(skills_root), user_id="user-a")
    assert storage_a.custom_skill_exists("my-skill")

    storage_b = LocalSkillStorage(host_path=str(skills_root), user_id="user-b")
    assert not storage_b.custom_skill_exists("my-skill")


# ---------------------------------------------------------------------------
# Async scan helper
# ---------------------------------------------------------------------------


async def _noop_scan(*args, **kwargs):
    from deerflow.skills.security_scanner import ScanResult

    return ScanResult(decision="allow", reason="ok")
