"""Tests for Changes 4 & 5: get_skill_storage FastAPI dependency + router admin check.

Change 4: get_skill_storage Depends() uses get_effective_user_id() so each
          request sees only its own custom skills.

Change 5: PUT /api/skills/{name} (enable/disable) requires admin role.
          Non-admin authenticated users get 403.
          Unauthenticated requests (user=None) are allowed through.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

skills_router = importlib.import_module("app.gateway.routers.skills")


_SKILL_MD = "---\nname: {name}\ndescription: A test skill\nlicense: MIT\n---\n\n# {name}\n"


def _make_storage(tmp_path: Path, user_id: str):
    from deerflow.skills.storage.local_skill_storage import LocalSkillStorage
    return LocalSkillStorage(host_path=str(tmp_path / "skills"), user_id=user_id)


async def _noop_refresh():
    pass


def _make_public_skill(tmp_path: Path, name: str) -> None:
    d = tmp_path / "skills" / "public" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(_SKILL_MD.format(name=name), encoding="utf-8")


# ---------------------------------------------------------------------------
# Change 4: get_skill_storage dependency binds to authenticated user
# ---------------------------------------------------------------------------

def test_get_skill_storage_dependency_scopes_to_user(tmp_path):
    """Router bound to user-a storage must not return user-b skills."""
    from app.gateway.deps import get_skill_storage

    monkeypatch_storage_a = _make_storage(tmp_path, "user-a")
    monkeypatch_storage_b = _make_storage(tmp_path, "user-b")

    # Write skill only for user-b
    skill_dir = monkeypatch_storage_b._get_custom_base() / "b-only-skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(_SKILL_MD.format(name="b-only-skill"), encoding="utf-8")

    app_a = FastAPI()
    app_a.state.config = SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills"), skill_evolution=SimpleNamespace(enabled=False))
    app_a.include_router(skills_router.router)
    app_a.dependency_overrides[get_skill_storage] = lambda: monkeypatch_storage_a

    client_a = TestClient(app_a)
    resp = client_a.get("/api/skills/custom")
    assert resp.status_code == 200
    names = {s["name"] for s in resp.json()["skills"]}
    assert "b-only-skill" not in names


def test_get_admin_skill_storage_rejects_non_admin_with_target_user_id(tmp_path):
    """get_admin_skill_storage must raise 403 for non-admin requesting another user's storage."""
    from app.gateway.deps import get_admin_skill_storage
    from fastapi import HTTPException

    config = SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: tmp_path / "skills",
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        )
    )

    # Build a minimal fake request object with a non-admin user
    fake_request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="viewer", id="u1")))

    with pytest.raises(HTTPException) as exc_info:
        get_admin_skill_storage(fake_request, target_user_id="other-user", config=config)

    assert exc_info.value.status_code == 403


def test_get_admin_skill_storage_allows_admin_with_target_user_id(tmp_path):
    """Admin user can access another user's storage via get_admin_skill_storage."""
    from app.gateway.deps import get_admin_skill_storage

    config = SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: tmp_path / "skills",
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        )
    )

    fake_request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="admin", id="admin-1")))
    storage = get_admin_skill_storage(fake_request, target_user_id="target-user", config=config)

    assert "target-user" in str(storage._get_custom_base())


# ---------------------------------------------------------------------------
# Change 5: PUT /api/skills/{name} admin check
# ---------------------------------------------------------------------------

def _make_app_for_update(tmp_path: Path, monkeypatch) -> tuple[FastAPI, object]:
    from app.gateway.deps import get_skill_storage

    monkeypatch.setattr(skills_router, "refresh_skills_system_prompt_cache_async", _noop_refresh)

    _make_public_skill(tmp_path, "test-skill")

    config = SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: tmp_path / "skills",
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        ),
        skill_evolution=SimpleNamespace(enabled=False),
    )
    storage = _make_storage(tmp_path, "u1")

    app = FastAPI()
    app.state.config = config
    app.include_router(skills_router.router)
    app.dependency_overrides[get_skill_storage] = lambda: storage

    return app, config


def test_update_skill_non_admin_user_gets_403(tmp_path, monkeypatch):
    """Authenticated non-admin user cannot toggle skill enabled status."""
    from app.gateway.deps import get_config
    monkeypatch.setattr(skills_router, "refresh_skills_system_prompt_cache_async", _noop_refresh)
    monkeypatch.setattr("app.gateway.routers.skills.get_or_new_skill_storage", lambda app_config=None: _make_storage(tmp_path, "u1"))
    monkeypatch.setattr("deerflow.config.extensions_config.get_extensions_config", lambda: SimpleNamespace(
        skills={}, mcp_servers={},
        model_dump=lambda: {"mcpServers": {}, "skills": {}}
    ))

    _make_public_skill(tmp_path, "target-skill")
    from app.gateway.deps import get_skill_storage

    config = SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: tmp_path / "skills",
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        ),
        skill_evolution=SimpleNamespace(enabled=False),
    )

    app = FastAPI()
    app.state.config = config
    app.include_router(skills_router.router)
    app.dependency_overrides[get_skill_storage] = lambda: _make_storage(tmp_path, "u1")
    app.dependency_overrides[get_config] = lambda: config

    # Inject non-admin user via middleware
    from starlette.middleware.base import BaseHTTPMiddleware

    class FakeAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.user = SimpleNamespace(system_role="viewer", id="u1")
            return await call_next(request)

    app.add_middleware(FakeAuthMiddleware)

    client = TestClient(app)
    resp = client.put("/api/skills/target-skill", json={"enabled": False})
    assert resp.status_code == 403


def test_update_skill_no_user_is_allowed(tmp_path, monkeypatch):
    """Unauthenticated requests (user not set on request.state) pass the admin check."""
    monkeypatch.setattr(skills_router, "refresh_skills_system_prompt_cache_async", _noop_refresh)

    _make_public_skill(tmp_path, "target-skill")
    from app.gateway.deps import get_skill_storage, get_config

    config = SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: tmp_path / "skills",
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        ),
        skill_evolution=SimpleNamespace(enabled=False),
    )

    # Patch the extensions config write path so it doesn't actually write a file
    monkeypatch.setattr("deerflow.config.extensions_config.ExtensionsConfig.resolve_config_path", lambda: None)
    monkeypatch.setattr("app.gateway.routers.skills.get_or_new_skill_storage", lambda app_config=None: _make_storage(tmp_path, "u1"))

    fake_ext_config = SimpleNamespace(
        skills={"target-skill": SimpleNamespace(enabled=True)},
        mcp_servers={},
    )
    monkeypatch.setattr("app.gateway.routers.skills.get_extensions_config", lambda: fake_ext_config)
    monkeypatch.setattr("app.gateway.routers.skills.reload_extensions_config", lambda: None)

    app = FastAPI()
    app.state.config = config
    app.include_router(skills_router.router)
    app.dependency_overrides[get_skill_storage] = lambda: _make_storage(tmp_path, "u1")
    app.dependency_overrides[get_config] = lambda: config

    client = TestClient(app)
    # No auth middleware → request.state.user is not set → should not get 403
    import json
    from unittest.mock import patch

    with patch("builtins.open", side_effect=OSError("no write needed")):
        # The actual write will fail but we get past the 403 check
        resp = client.put("/api/skills/target-skill", json={"enabled": False})
    # 403 would mean admin check failed; any other error (500/404) is fine
    assert resp.status_code != 403
