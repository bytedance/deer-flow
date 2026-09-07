"""Route-level authorization tests for the Gateway permission decorators."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.authz import (
    Permissions,
    _authenticate,
    _get_cached_route_provider,
    require_permission,
    resolve_route_permissions,
)
from app.gateway.routers import runs, scheduled_tasks
from deerflow.authz.provider import AuthzDecision, AuthzReason
from deerflow.authz.rbac import RbacAuthorizationProvider
from deerflow.config.authorization_config import AuthorizationConfig, AuthorizationProviderConfig


class _RecordingProvider:
    name = "recording"

    def __init__(
        self,
        *,
        denied: set[str] | None = None,
        errors: set[str] | None = None,
    ) -> None:
        self.denied = denied or set()
        self.errors = errors or set()
        self.requests = []

    def authorize(self, request):
        raise AssertionError("route authorization must use the async provider API")

    async def aauthorize(self, request):
        self.requests.append(request)
        if request.target in self.errors:
            raise RuntimeError(f"provider failed for {request.target}")
        allowed = request.target not in self.denied
        return AuthzDecision(
            allow=allowed,
            reasons=[AuthzReason(code="authz.allowed" if allowed else "authz.denied")],
        )

    def filter_resources(self, principal, resource_type, candidates):
        raise AssertionError("route authorization must preserve per-action requests")


def _user(**overrides):
    values = {
        "id": "user-123",
        "system_role": "user",
        "oauth_provider": "github",
        "oauth_id": "oauth-456",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _enable_authorization(monkeypatch, provider, *, fail_closed: bool = True) -> None:
    config = AuthorizationConfig(
        enabled=True,
        fail_closed=fail_closed,
        default_role="user",
    )
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: config)
    # Bypass the provider cache so each test gets its own provider instance.
    monkeypatch.setattr("app.gateway.authz._get_cached_route_provider", lambda c: provider)


@pytest.mark.asyncio
async def test_route_permissions_disabled_preserves_all_permissions(monkeypatch):
    config = AuthorizationConfig(enabled=False)
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: config)
    # Bypass cache + ensure provider is never resolved when disabled.
    cached = AsyncMock(side_effect=AssertionError("disabled authorization must not resolve a provider"))
    monkeypatch.setattr("app.gateway.authz._get_cached_route_provider", cached)

    permissions = await resolve_route_permissions(_user(), is_internal=False)

    assert permissions == [
        Permissions.THREADS_READ,
        Permissions.THREADS_WRITE,
        Permissions.THREADS_DELETE,
        Permissions.RUNS_CREATE,
        Permissions.RUNS_READ,
        Permissions.RUNS_CANCEL,
    ]
    cached.assert_not_called()


@pytest.mark.asyncio
async def test_route_permissions_use_async_provider_and_trusted_principal(monkeypatch):
    provider = _RecordingProvider(denied={Permissions.THREADS_DELETE, Permissions.RUNS_CANCEL})
    _enable_authorization(monkeypatch, provider)

    permissions = await resolve_route_permissions(_user(), is_internal=True)

    assert permissions == [
        Permissions.THREADS_READ,
        Permissions.THREADS_WRITE,
        Permissions.RUNS_CREATE,
        Permissions.RUNS_READ,
    ]
    assert [(request.resource, request.action, request.target) for request in provider.requests] == [
        ("route", "read", Permissions.THREADS_READ),
        ("route", "write", Permissions.THREADS_WRITE),
        ("route", "delete", Permissions.THREADS_DELETE),
        ("route", "create", Permissions.RUNS_CREATE),
        ("route", "read", Permissions.RUNS_READ),
        ("route", "cancel", Permissions.RUNS_CANCEL),
    ]
    principal = provider.requests[0].principal
    assert principal.user_id == "user-123"
    assert principal.role == "user"
    assert principal.oauth_provider == "github"
    assert principal.oauth_id == "oauth-456"
    assert principal.is_internal is True


@pytest.mark.asyncio
async def test_route_permissions_fail_closed_denies_only_the_failed_permission(monkeypatch):
    provider = _RecordingProvider(errors={Permissions.RUNS_CANCEL})
    _enable_authorization(monkeypatch, provider, fail_closed=True)

    permissions = await resolve_route_permissions(_user(), is_internal=False)

    assert permissions == [
        Permissions.THREADS_READ,
        Permissions.THREADS_WRITE,
        Permissions.THREADS_DELETE,
        Permissions.RUNS_CREATE,
        Permissions.RUNS_READ,
    ]


@pytest.mark.asyncio
async def test_route_permissions_fail_open_allows_the_failed_permission(monkeypatch):
    provider = _RecordingProvider(errors={Permissions.RUNS_CANCEL})
    _enable_authorization(monkeypatch, provider, fail_closed=False)

    permissions = await resolve_route_permissions(_user(), is_internal=False)

    assert permissions == [
        Permissions.THREADS_READ,
        Permissions.THREADS_WRITE,
        Permissions.THREADS_DELETE,
        Permissions.RUNS_CREATE,
        Permissions.RUNS_READ,
        Permissions.RUNS_CANCEL,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fail_closed", "expected"),
    [
        (True, []),
        (
            False,
            [
                Permissions.THREADS_READ,
                Permissions.THREADS_WRITE,
                Permissions.THREADS_DELETE,
                Permissions.RUNS_CREATE,
                Permissions.RUNS_READ,
                Permissions.RUNS_CANCEL,
            ],
        ),
    ],
)
async def test_route_permissions_apply_failure_mode_to_provider_resolution(monkeypatch, fail_closed, expected):
    config = AuthorizationConfig(
        enabled=True,
        fail_closed=fail_closed,
        default_role="user",
    )
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: config)

    def fail_cached(c):
        raise ValueError("invalid provider configuration")

    monkeypatch.setattr("app.gateway.authz._get_cached_route_provider", fail_cached)

    assert await resolve_route_permissions(_user(), is_internal=False) == expected


@pytest.mark.asyncio
async def test_route_permissions_use_builtin_rbac_route_policy(monkeypatch):
    provider = RbacAuthorizationProvider(
        roles={
            "user": {
                "routes": {
                    "allow": [Permissions.THREADS_READ, Permissions.RUNS_READ],
                }
            }
        }
    )
    _enable_authorization(monkeypatch, provider)

    permissions = await resolve_route_permissions(_user(), is_internal=False)

    assert permissions == [Permissions.THREADS_READ, Permissions.RUNS_READ]


@pytest.mark.asyncio
async def test_authenticate_uses_route_permission_resolution(monkeypatch):
    user = User(email="route-authz@example.com", password_hash="hash")
    permission_resolver = AsyncMock(return_value=[Permissions.THREADS_READ])
    monkeypatch.setattr("app.gateway.deps.get_optional_user_from_request", AsyncMock(return_value=user))
    monkeypatch.setattr("app.gateway.authz.resolve_route_permissions", permission_resolver)
    request = SimpleNamespace(state=SimpleNamespace())

    auth_context = await _authenticate(request)

    assert auth_context.user is user
    assert auth_context.permissions == [Permissions.THREADS_READ]
    permission_resolver.assert_awaited_once_with(user, is_internal=False)


def _make_middleware_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/api/threads")
    @require_permission("threads", "read")
    async def read_threads(request: Request):
        return {"ok": True}

    @app.delete("/api/threads")
    @require_permission("threads", "delete")
    async def delete_threads(request: Request):
        return {"ok": True}

    return app


def test_auth_middleware_stamps_provider_derived_permissions(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    permission_resolver = AsyncMock(return_value=[Permissions.THREADS_READ])
    monkeypatch.setattr("app.gateway.auth_middleware.resolve_route_permissions", permission_resolver)

    with TestClient(_make_middleware_app()) as client:
        assert client.get("/api/threads").status_code == 200
        assert client.delete("/api/threads").status_code == 403

    assert permission_resolver.await_count == 2
    for call in permission_resolver.await_args_list:
        assert call.kwargs == {"is_internal": False}


def test_auth_middleware_marks_internal_route_principal(monkeypatch):
    from app.gateway.internal_auth import create_internal_auth_headers

    permission_resolver = AsyncMock(return_value=[Permissions.THREADS_READ])
    monkeypatch.setattr("app.gateway.auth_middleware.resolve_route_permissions", permission_resolver)

    with TestClient(_make_middleware_app()) as client:
        response = client.get("/api/threads", headers=create_internal_auth_headers())

    assert response.status_code == 200
    permission_resolver.assert_awaited_once()
    assert permission_resolver.await_args.kwargs == {"is_internal": True}


_STATELESS_RUN_PATHS = ("/api/runs/stream", "/api/runs/wait")


def _enable_auth_disabled_for_route_test(monkeypatch) -> None:
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    monkeypatch.delenv("DEER_FLOW_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)


def _make_stateless_runs_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(runs.router)
    app.state.stream_bridge = MagicMock()
    app.state.run_manager = MagicMock()
    return app


@pytest.mark.parametrize("path", _STATELESS_RUN_PATHS)
def test_stateless_run_creation_requires_runs_create(monkeypatch, path):
    _enable_auth_disabled_for_route_test(monkeypatch)
    monkeypatch.setattr(
        "app.gateway.auth_middleware.resolve_route_permissions",
        AsyncMock(return_value=[Permissions.RUNS_READ]),
    )
    start_run = AsyncMock(side_effect=HTTPException(status_code=418, detail="run creation reached"))
    monkeypatch.setattr(runs, "start_run", start_run)

    with TestClient(_make_stateless_runs_app()) as client:
        response = client.post(path, json={})

    assert response.status_code == 403
    assert response.json() == {"detail": "Permission denied: runs:create"}
    start_run.assert_not_awaited()


@pytest.mark.parametrize("path", _STATELESS_RUN_PATHS)
def test_stateless_run_creation_allows_runs_create(monkeypatch, path):
    _enable_auth_disabled_for_route_test(monkeypatch)
    monkeypatch.setattr(
        "app.gateway.auth_middleware.resolve_route_permissions",
        AsyncMock(return_value=[Permissions.RUNS_CREATE]),
    )
    start_run = AsyncMock(side_effect=HTTPException(status_code=418, detail="run creation reached"))
    monkeypatch.setattr(runs, "start_run", start_run)

    with TestClient(_make_stateless_runs_app()) as client:
        response = client.post(path, json={})

    assert response.status_code == 418
    assert response.json() == {"detail": "run creation reached"}
    start_run.assert_awaited_once()


_SCHEDULED_RUN_CREATION_REQUESTS = (
    (
        "POST",
        "/api/scheduled-tasks",
        {
            "title": "Daily summary",
            "prompt": "Summarize the latest activity",
            "schedule_type": "cron",
            "schedule_spec": {"cron": "0 9 * * *"},
            "timezone": "UTC",
        },
    ),
    ("PATCH", "/api/scheduled-tasks/task-1", {"title": "Updated summary"}),
    ("POST", "/api/scheduled-tasks/task-1/resume", None),
    ("POST", "/api/scheduled-tasks/task-1/trigger", None),
)


def _make_scheduled_tasks_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(scheduled_tasks.router)
    return app


@pytest.mark.parametrize(("method", "path", "payload"), _SCHEDULED_RUN_CREATION_REQUESTS)
@pytest.mark.parametrize(
    ("permissions", "denied_permission"),
    [
        ([Permissions.THREADS_WRITE], Permissions.RUNS_CREATE),
        ([Permissions.RUNS_CREATE], Permissions.THREADS_WRITE),
    ],
)
def test_scheduled_run_creation_requires_thread_write_and_runs_create(monkeypatch, method, path, payload, permissions, denied_permission):
    _enable_auth_disabled_for_route_test(monkeypatch)
    monkeypatch.setattr(
        "app.gateway.auth_middleware.resolve_route_permissions",
        AsyncMock(return_value=permissions),
    )

    with TestClient(_make_scheduled_tasks_app()) as client:
        response = client.request(method, path, json=payload)

    assert response.status_code == 403
    assert response.json() == {"detail": f"Permission denied: {denied_permission}"}


# ── Provider cache tests ────────────────────────────────────────────────


class TestRouteProviderCache:
    """Verify the provider cache returns the same instance for unchanged config
    and re-resolves when config content changes."""

    def test_same_config_returns_same_provider(self):
        """Calling twice with the same config object returns the same instance."""
        import app.gateway.authz as authz_module

        # Reset cache
        authz_module._route_provider_cache.clear()
        authz_module._route_provider_config_id = None
        authz_module._route_provider_config_sig = None

        config = AuthorizationConfig(
            enabled=True,
            provider=AuthorizationProviderConfig(
                use="deerflow.authz.rbac:RbacAuthorizationProvider",
                config={"roles": {"user": {"routes": {"allow": "*"}}}},
            ),
        )

        p1 = _get_cached_route_provider(config)
        p2 = _get_cached_route_provider(config)
        assert p1 is not None
        assert p2 is p1

    def test_changed_config_returns_new_provider(self):
        """A config with different content triggers re-resolution."""
        import app.gateway.authz as authz_module

        authz_module._route_provider_cache.clear()
        authz_module._route_provider_config_id = None
        authz_module._route_provider_config_sig = None

        config1 = AuthorizationConfig(
            enabled=True,
            provider=AuthorizationProviderConfig(
                use="deerflow.authz.rbac:RbacAuthorizationProvider",
                config={"roles": {"user": {"routes": {"allow": "*"}}}},
            ),
        )
        config2 = AuthorizationConfig(
            enabled=True,
            provider=AuthorizationProviderConfig(
                use="deerflow.authz.rbac:RbacAuthorizationProvider",
                config={"roles": {"user": {"routes": {"allow": []}}}},
            ),
        )

        p1 = _get_cached_route_provider(config1)
        p2 = _get_cached_route_provider(config2)
        assert p1 is not None
        assert p2 is not None
        assert p1 is not p2

    def test_same_content_different_object_reuses_provider(self):
        """Same content in a new object (e.g. hot-reload with no changes) reuses provider."""
        import app.gateway.authz as authz_module

        authz_module._route_provider_cache.clear()
        authz_module._route_provider_config_id = None
        authz_module._route_provider_config_sig = None

        config1 = AuthorizationConfig(
            enabled=True,
            provider=AuthorizationProviderConfig(
                use="deerflow.authz.rbac:RbacAuthorizationProvider",
                config={"roles": {"user": {"routes": {"allow": "*"}}}},
            ),
        )
        # Same content, different object
        config2 = AuthorizationConfig(
            enabled=True,
            provider=AuthorizationProviderConfig(
                use="deerflow.authz.rbac:RbacAuthorizationProvider",
                config={"roles": {"user": {"routes": {"allow": "*"}}}},
            ),
        )

        p1 = _get_cached_route_provider(config1)
        p2 = _get_cached_route_provider(config2)
        assert p1 is p2
