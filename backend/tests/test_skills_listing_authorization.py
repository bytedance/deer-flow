"""Phase 4 skill-listing authorization tests.

Covers the Gateway route layer only (``list_skills``): the request-scoped
Principal and ``filter_resources(principal, "skill", ...)`` visibility filter,
mirroring Phase 3's ``list_models`` tests (``resolve_skill_authorization`` is
the ``resolve_model_authorization`` twin). Runtime skill authorization —
assembly filtering and slash-activation — is the #4541 layer and is
deliberately out of scope here; this file pins only which skills a caller
may *see* on the user-facing listing surface.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import skills as skills_router
from deerflow.authz.provider import AuthzDecision, AuthzReason
from deerflow.authz.rbac import RbacAuthorizationProvider
from deerflow.config.app_config import AppConfig
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.skills import Skill
from deerflow.skills.types import SkillCategory

# ── Helpers ────────────────────────────────────────────────────────────


def _user(**overrides):
    values = {
        "id": "user-123",
        "system_role": "user",
        "oauth_provider": "github",
        "oauth_id": "oauth-456",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _skill(name: str, *, category: SkillCategory = SkillCategory.PUBLIC, enabled: bool = True) -> Skill:
    """Build a minimal Skill with dummy paths; only name/category/enabled matter here."""
    return Skill(
        name=name,
        description=f"Skill {name}",
        license=None,
        skill_dir=Path(f"/skills/{category}/{name}"),
        skill_file=Path(f"/skills/{category}/{name}/SKILL.md"),
        relative_path=Path(name),
        category=category,
        enabled=enabled,
    )


class _FakeStorage:
    """Stand-in for user-scoped SkillStorage: returns preloaded skills."""

    def __init__(self, skills: list[Skill]) -> None:
        self._skills = skills
        self.load_calls: list[bool] = []

    def load_skills(self, *, enabled_only: bool = False) -> list[Skill]:
        self.load_calls.append(enabled_only)
        return list(self._skills)


def _make_app_config() -> AppConfig:
    return AppConfig(
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        authorization=AuthorizationConfig(),
    )


def _make_skills_app(app_config: AppConfig) -> FastAPI:
    """Build a FastAPI app with the skills router and a pinned config."""
    app = FastAPI()
    app.include_router(skills_router.router)
    app.dependency_overrides[skills_router.get_config] = lambda: app_config
    return app


def _stub_storage(monkeypatch, storage: _FakeStorage) -> None:
    # list_skills resolves the candidate universe through user-scoped storage
    # (a plain module-level call, not a FastAPI dependency); pin it so tests
    # control the catalog without touching the filesystem.
    monkeypatch.setattr("app.gateway.routers.skills._get_user_skill_storage", lambda config: storage)


def _enable_authorization(monkeypatch, provider, *, fail_closed: bool = True, default_role: str = "user") -> None:
    config = AuthorizationConfig(
        enabled=True,
        fail_closed=fail_closed,
        default_role=default_role,
    )
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: config)
    monkeypatch.setattr("app.gateway.authz._get_cached_route_provider", lambda c: provider)


class _RecordingProvider:
    """Provider that records all requests and can deny/error specific targets."""

    name = "recording"

    def __init__(self, *, denied: set[str] | None = None, errors: set[str] | None = None) -> None:
        self.denied = denied or set()
        self.errors = errors or set()
        self.authorize_requests: list = []
        self.filter_requests: list = []

    def authorize(self, request):
        self.authorize_requests.append(request)
        if request.target in self.errors:
            raise RuntimeError(f"provider failed for {request.target}")
        allowed = request.target not in self.denied
        return AuthzDecision(
            allow=allowed,
            reasons=[AuthzReason(code="authz.allowed" if allowed else "authz.denied")],
        )

    async def aauthorize(self, request):
        return self.authorize(request)

    def filter_resources(self, principal, resource_type, candidates):
        self.filter_requests.append((resource_type, list(candidates)))
        if resource_type in self.errors:
            raise RuntimeError(f"provider failed for {resource_type}")
        return [c for c in candidates if c not in self.denied]


def _stub_user(monkeypatch, user) -> None:
    monkeypatch.setattr(
        "app.gateway.routers.skills.get_optional_user_from_request",
        AsyncMock(return_value=user),
    )


# ── list_skills tests ──────────────────────────────────────────────────


def test_list_skills_disabled_returns_all(monkeypatch):
    """When authorization is disabled, all skills are visible."""
    config = AuthorizationConfig(enabled=False)
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: config)
    cached = AsyncMock(side_effect=AssertionError("disabled must not resolve provider"))
    monkeypatch.setattr("app.gateway.authz._get_cached_route_provider", cached)

    storage = _FakeStorage([_skill("pdf-export"), _skill("web-research")])
    _stub_user(monkeypatch, _user())
    _stub_storage(monkeypatch, storage)

    with TestClient(_make_skills_app(_make_app_config())) as client:
        response = client.get("/api/skills")

    assert response.status_code == 200
    names = [s["name"] for s in response.json()["skills"]]
    assert names == ["pdf-export", "web-research"]
    cached.assert_not_called()


def test_list_skills_anonymous_user_returns_all(monkeypatch):
    """Anonymous requests (user=None) are not filtered."""
    provider = _RecordingProvider()
    _enable_authorization(monkeypatch, provider)

    storage = _FakeStorage([_skill("pdf-export"), _skill("web-research")])
    _stub_user(monkeypatch, None)
    _stub_storage(monkeypatch, storage)

    with TestClient(_make_skills_app(_make_app_config())) as client:
        response = client.get("/api/skills")

    assert response.status_code == 200
    names = [s["name"] for s in response.json()["skills"]]
    assert names == ["pdf-export", "web-research"]
    assert provider.filter_requests == []


def test_list_skills_rbac_filters_by_allow(monkeypatch):
    """Role with a skill allowlist sees only allowed skills, in storage order."""
    provider = RbacAuthorizationProvider(
        roles={"user": {"skills": {"allow": ["pdf-export"]}}},
    )
    _enable_authorization(monkeypatch, provider)

    storage = _FakeStorage([_skill("pdf-export"), _skill("web-research"), _skill("data-viz")])
    _stub_user(monkeypatch, _user())
    _stub_storage(monkeypatch, storage)

    with TestClient(_make_skills_app(_make_app_config())) as client:
        response = client.get("/api/skills")

    assert response.status_code == 200
    names = [s["name"] for s in response.json()["skills"]]
    assert names == ["pdf-export"]


def test_list_skills_rbac_filters_by_deny(monkeypatch):
    """Role with a skill denylist no longer sees denied skills."""
    provider = RbacAuthorizationProvider(
        roles={"user": {"skills": {"allow": "*", "deny": ["web-research"]}}},
    )
    _enable_authorization(monkeypatch, provider)

    storage = _FakeStorage([_skill("pdf-export"), _skill("web-research"), _skill("data-viz")])
    _stub_user(monkeypatch, _user())
    _stub_storage(monkeypatch, storage)

    with TestClient(_make_skills_app(_make_app_config())) as client:
        response = client.get("/api/skills")

    assert response.status_code == 200
    names = [s["name"] for s in response.json()["skills"]]
    assert names == ["pdf-export", "data-viz"]


def test_list_skills_wildcard_returns_all(monkeypatch):
    """Role with skills allow: '*' sees all skills."""
    provider = RbacAuthorizationProvider(
        roles={"user": {"skills": {"allow": "*"}}},
    )
    _enable_authorization(monkeypatch, provider)

    storage = _FakeStorage([_skill("pdf-export"), _skill("web-research")])
    _stub_user(monkeypatch, _user())
    _stub_storage(monkeypatch, storage)

    with TestClient(_make_skills_app(_make_app_config())) as client:
        response = client.get("/api/skills")

    assert response.status_code == 200
    names = [s["name"] for s in response.json()["skills"]]
    assert names == ["pdf-export", "web-research"]


def test_list_skills_no_role_policy_returns_all(monkeypatch):
    """A role with no ``skills`` policy is unrestricted for skills (mirrors the
    permissive-on-absent default; policies for other resources don't leak in)."""
    provider = RbacAuthorizationProvider(
        roles={"user": {"models": {"allow": ["gpt-4"]}}},
    )
    _enable_authorization(monkeypatch, provider)

    storage = _FakeStorage([_skill("pdf-export"), _skill("web-research")])
    _stub_user(monkeypatch, _user())
    _stub_storage(monkeypatch, storage)

    with TestClient(_make_skills_app(_make_app_config())) as client:
        response = client.get("/api/skills")

    assert response.status_code == 200
    names = [s["name"] for s in response.json()["skills"]]
    assert names == ["pdf-export", "web-research"]


def test_list_skills_filters_custom_and_public_uniformly(monkeypatch):
    """The visibility filter applies by name across categories: a denied
    custom skill disappears even while other custom skills remain."""
    provider = RbacAuthorizationProvider(
        roles={"user": {"skills": {"allow": "*", "deny": ["my-private-skill"]}}},
    )
    _enable_authorization(monkeypatch, provider)

    storage = _FakeStorage(
        [
            _skill("pdf-export"),
            _skill("my-private-skill", category=SkillCategory.CUSTOM),
            _skill("team-playbook", category=SkillCategory.CUSTOM),
        ]
    )
    _stub_user(monkeypatch, _user())
    _stub_storage(monkeypatch, storage)

    with TestClient(_make_skills_app(_make_app_config())) as client:
        response = client.get("/api/skills")

    assert response.status_code == 200
    names = [s["name"] for s in response.json()["skills"]]
    assert names == ["pdf-export", "team-playbook"]


@pytest.mark.parametrize(
    ("fail_closed", "expected_count"),
    [(True, 0), (False, 3)],
)
def test_list_skills_provider_error_fail_closed_vs_open(monkeypatch, fail_closed, expected_count):
    """Provider error → empty (fail-closed) or all (fail-open)."""
    provider = _RecordingProvider(errors={"skill"})
    _enable_authorization(monkeypatch, provider, fail_closed=fail_closed)

    app_config = _make_app_config()
    app_config.authorization.fail_closed = fail_closed
    storage = _FakeStorage([_skill("pdf-export"), _skill("web-research"), _skill("data-viz")])
    _stub_user(monkeypatch, _user())
    _stub_storage(monkeypatch, storage)

    with TestClient(_make_skills_app(app_config)) as client:
        response = client.get("/api/skills")

    assert response.status_code == 200
    assert len(response.json()["skills"]) == expected_count


@pytest.mark.parametrize(
    ("fail_closed", "expected_count"),
    [(True, 0), (False, 2)],
)
def test_list_skills_provider_unavailable_fail_closed_vs_open(monkeypatch, fail_closed, expected_count):
    """Provider cannot be resolved → empty (fail-closed) or all (fail-open)."""
    config = AuthorizationConfig(enabled=True, fail_closed=fail_closed, default_role="user")
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: config)

    def _raise_resolution_error(c):
        raise RuntimeError("provider resolution failed")

    monkeypatch.setattr("app.gateway.authz._get_cached_route_provider", _raise_resolution_error)

    app_config = _make_app_config()
    app_config.authorization.fail_closed = fail_closed
    storage = _FakeStorage([_skill("pdf-export"), _skill("web-research")])
    _stub_user(monkeypatch, _user())
    _stub_storage(monkeypatch, storage)

    with TestClient(_make_skills_app(app_config)) as client:
        response = client.get("/api/skills")

    assert response.status_code == 200
    assert len(response.json()["skills"]) == expected_count


@pytest.mark.parametrize(
    ("fail_closed", "expected_count"),
    [(True, 0), (False, 2)],
)
def test_list_skills_provider_bad_filter_return_type(monkeypatch, fail_closed, expected_count):
    """A provider whose filter_resources returns non-list[str] is treated as a
    provider failure (TypeError guard), not an unfiltered passthrough."""
    provider = SimpleNamespace(
        filter_resources=lambda principal, resource_type, candidates: "pdf-export",
    )
    _enable_authorization(monkeypatch, provider, fail_closed=fail_closed)

    app_config = _make_app_config()
    app_config.authorization.fail_closed = fail_closed
    storage = _FakeStorage([_skill("pdf-export"), _skill("web-research")])
    _stub_user(monkeypatch, _user())
    _stub_storage(monkeypatch, storage)

    with TestClient(_make_skills_app(app_config)) as client:
        response = client.get("/api/skills")

    assert response.status_code == 200
    assert len(response.json()["skills"]) == expected_count


def test_list_skills_requests_skill_resource_type(monkeypatch):
    """The route filters through resource_type "skill" with the full catalog
    as candidates (pins the provider contract the RBAC ``skills`` key maps to)."""
    provider = _RecordingProvider()
    _enable_authorization(monkeypatch, provider)

    storage = _FakeStorage([_skill("pdf-export"), _skill("web-research")])
    _stub_user(monkeypatch, _user())
    _stub_storage(monkeypatch, storage)

    with TestClient(_make_skills_app(_make_app_config())) as client:
        response = client.get("/api/skills")

    assert response.status_code == 200
    assert provider.filter_requests == [
        ("skill", ["pdf-export", "web-research"]),
    ]


# ── list_custom_skills / get_skill: the remaining visibility surfaces ──


def test_list_custom_skills_rbac_filters_by_deny(monkeypatch):
    """The custom-only listing surface applies the same visibility filter:
    without it, a denied name hidden from GET /api/skills would remain
    visible on GET /api/skills/custom."""
    provider = RbacAuthorizationProvider(
        roles={"user": {"skills": {"allow": "*", "deny": ["my-private-skill"]}}},
    )
    _enable_authorization(monkeypatch, provider)

    storage = _FakeStorage(
        [
            _skill("pdf-export"),
            _skill("my-private-skill", category=SkillCategory.CUSTOM),
            _skill("team-playbook", category=SkillCategory.CUSTOM),
        ]
    )
    _stub_user(monkeypatch, _user())
    _stub_storage(monkeypatch, storage)

    with TestClient(_make_skills_app(_make_app_config())) as client:
        response = client.get("/api/skills/custom")

    assert response.status_code == 200
    names = [s["name"] for s in response.json()["skills"]]
    assert names == ["team-playbook"]


def test_get_skill_denied_is_indistinguishable_from_missing(monkeypatch):
    """A denied skill returns the same 404 as a nonexistent one — the detail
    surface must not become an existence oracle that the filtered list
    closed (403 would leak that the name exists)."""
    provider = RbacAuthorizationProvider(
        roles={"user": {"skills": {"allow": ["pdf-export"]}}},
    )
    _enable_authorization(monkeypatch, provider)

    storage = _FakeStorage([_skill("pdf-export"), _skill("web-research")])
    _stub_user(monkeypatch, _user())
    _stub_storage(monkeypatch, storage)

    with TestClient(_make_skills_app(_make_app_config())) as client:
        denied = client.get("/api/skills/web-research")
        missing = client.get("/api/skills/does-not-exist")
        allowed = client.get("/api/skills/pdf-export")

    assert denied.status_code == 404
    assert missing.status_code == 404
    # The detail echoes the caller-supplied name through the standard
    # not-found template — byte-identical to a genuine miss of that name,
    # so the response carries no extra information.
    assert denied.json()["detail"] == "Skill 'web-research' not found"
    assert missing.json()["detail"] == "Skill 'does-not-exist' not found"
    assert allowed.status_code == 200
    assert allowed.json()["name"] == "pdf-export"


def test_get_skill_anonymous_returns_200(monkeypatch):
    """Anonymous requests (user=None) are not filtered, mirroring list_skills."""
    provider = _RecordingProvider()
    _enable_authorization(monkeypatch, provider)

    storage = _FakeStorage([_skill("pdf-export")])
    _stub_user(monkeypatch, None)
    _stub_storage(monkeypatch, storage)

    with TestClient(_make_skills_app(_make_app_config())) as client:
        response = client.get("/api/skills/pdf-export")

    assert response.status_code == 200
    assert provider.filter_requests == []


@pytest.mark.parametrize(
    ("fail_closed", "expected_status"),
    [(True, 404), (False, 200)],
)
def test_get_skill_provider_error_fail_closed_vs_open(monkeypatch, fail_closed, expected_status):
    """Provider error → invisible (fail-closed, 404) or visible (fail-open, 200)."""
    provider = _RecordingProvider(errors={"skill"})
    _enable_authorization(monkeypatch, provider, fail_closed=fail_closed)

    app_config = _make_app_config()
    app_config.authorization.fail_closed = fail_closed
    storage = _FakeStorage([_skill("pdf-export")])
    _stub_user(monkeypatch, _user())
    _stub_storage(monkeypatch, storage)

    with TestClient(_make_skills_app(app_config)) as client:
        response = client.get("/api/skills/pdf-export")

    assert response.status_code == expected_status
