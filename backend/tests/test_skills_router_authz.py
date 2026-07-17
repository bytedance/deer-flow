"""Authorization regression tests for the skills router.

Custom skill SKILL.md content is injected into every user's agent system
prompt. The mutating endpoints that write global shared state (install,
toggle PUBLIC skills, edit/delete custom skill content, and the endpoints
that expose raw custom-skill content/history) must be admin-only, matching
the MCP router which guards the equivalent global extensions_config mutations
with ``require_admin_user``.

Under per-user skill isolation, ``list_custom_skills`` is open to all
authenticated users (they see only their own custom skills), but all other
custom-skill endpoints remain admin-only because they write global state
(install writes to the shared archive, toggle writes extensions_config.json
for PUBLIC skills, and edit/delete modify the on-disk skill tree).

These tests pin the access-control boundary: a normal authenticated
(non-admin) user must receive 403 on every guarded endpoint.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from _router_auth_helpers import make_authed_test_app
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.deps import get_config
from app.gateway.routers import skills as skills_router


def _make_user(system_role: str) -> User:
    return User(email=f"{system_role}-test@example.com", password_hash="x", system_role=system_role, id=uuid4())


def _make_app(*, system_role: str) -> FastAPI:
    config = SimpleNamespace(
        skills=SimpleNamespace(get_skills_path=lambda: "/tmp/skills", container_path="/mnt/skills", use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage"),
        skill_evolution=SimpleNamespace(enabled=True, moderation_model_name=None),
    )
    app = make_authed_test_app(user_factory=lambda: _make_user(system_role))
    app.state.config = config
    app.dependency_overrides[get_config] = lambda: config
    app.include_router(skills_router.router)
    return app


# (method, path, json_body) for every endpoint that must require admin.
# Under per-user skill isolation, list_custom_skills is open to normal users
# (they see only their own skills), so it is NOT in this list.
# All other mutating endpoints write/read global shared state and must be
# admin-only. PUT /api/skills/{name} is included: toggling enabled writes
# the shared extensions_config.json (for PUBLIC skills) and changes every
# tenant's injected skill set.
_GUARDED_ENDPOINTS = [
    ("post", "/api/skills/install", {"thread_id": "t1", "path": "mnt/user-data/outputs/x.skill"}),
    ("post", "/api/skills/reload", None),
    ("get", "/api/skills/custom/demo", None),
    ("put", "/api/skills/custom/demo", {"content": "---\nname: demo\ndescription: hijacked\n---\n"}),
    ("delete", "/api/skills/custom/demo", None),
    ("get", "/api/skills/custom/demo/history", None),
    ("post", "/api/skills/custom/demo/rollback", {"history_index": -1}),
    ("put", "/api/skills/demo", {"enabled": False}),
]


def test_non_admin_is_forbidden_on_all_mutating_skills_endpoints():
    """A normal (non-admin) authenticated user must get 403, never 200/500.

    403 proves the admin guard fired before any business logic ran. If the
    guard were missing the request would instead reach the handler and return
    200 or a 4xx/5xx from the storage layer.
    """
    app = _make_app(system_role="user")
    with TestClient(app) as client:
        for method, path, body in _GUARDED_ENDPOINTS:
            resp = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
            assert resp.status_code == 403, f"{method.upper()} {path} expected 403 for non-admin, got {resp.status_code}"


def test_basic_skill_listing_stays_open_to_normal_users(monkeypatch):
    """The basic list/detail endpoints expose only name/description and are
    needed by the normal-user UI, so they must NOT be admin-gated.

    Under per-user skill isolation, ``list_custom_skills`` (GET /api/skills/custom)
    is also open to normal users — they see only their own custom skills.
    """

    def _load_skills(*, enabled_only: bool):
        from pathlib import Path

        from deerflow.skills.types import Skill

        return [
            Skill(
                name="demo",
                description="d",
                license="MIT",
                skill_dir=Path("/tmp/demo"),
                skill_file=Path("/tmp/demo/SKILL.md"),
                relative_path=Path("demo"),
                category="public",
                enabled=True,
            )
        ]

    app = _make_app(system_role="user")
    app.dependency_overrides[get_config] = lambda: SimpleNamespace()
    monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda cfg: SimpleNamespace(load_skills=_load_skills))
    with TestClient(app) as client:
        assert client.get("/api/skills").status_code == 200
        assert client.get("/api/skills/custom").status_code == 200
        assert client.get("/api/skills/demo").status_code == 200


def test_enable_toggle_allowed_for_admin(monkeypatch, tmp_path):
    """`PUT /api/skills/{name}` writes the shared extensions_config.json, so it
    is admin-only. This confirms the guard does not block a legitimate admin.
    """
    from pathlib import Path

    from deerflow.skills.types import Skill

    config_path = tmp_path / "extensions_config.json"

    def _load_skills(*, enabled_only: bool):
        return [
            Skill(
                name="demo",
                description="d",
                license="MIT",
                skill_dir=Path("/tmp/demo"),
                skill_file=Path("/tmp/demo/SKILL.md"),
                relative_path=Path("demo"),
                category="public",
                enabled=True,
            )
        ]

    app = _make_app(system_role="admin")
    monkeypatch.setattr(skills_router, "_get_user_skill_storage", lambda cfg: SimpleNamespace(load_skills=_load_skills))
    monkeypatch.setattr(skills_router, "get_extensions_config", lambda: SimpleNamespace(mcp_servers={}, skills={}))
    monkeypatch.setattr(skills_router, "reload_extensions_config", lambda: None)
    monkeypatch.setattr(skills_router.ExtensionsConfig, "resolve_config_path", staticmethod(lambda: config_path))

    async def _refresh(_user_id: str):
        return None

    monkeypatch.setattr(skills_router, "refresh_user_skills_system_prompt_cache_async", _refresh)
    with TestClient(app) as client:
        resp = client.put("/api/skills/demo", json={"enabled": False})
        assert resp.status_code == 200, f"admin toggle should succeed, got {resp.status_code}"
