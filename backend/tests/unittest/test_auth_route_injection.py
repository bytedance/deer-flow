from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI
from starlette.requests import Request

from app.plugins.auth.authorization import AuthContext
from app.plugins.auth.domain.models import User
from app.plugins.auth.injection import load_route_policy_registry, validate_route_policy_registry
from app.plugins.auth.injection.registry_loader import RoutePolicyRegistry, RoutePolicySpec
from app.plugins.auth.injection.route_guard import enforce_route_policy
from app.plugins.auth.injection.route_injector import install_route_guards


def test_load_route_policy_registry_flattens_yaml_sections() -> None:
    registry = load_route_policy_registry()

    public_spec = registry.get("POST", "/api/v1/auth/login/local")
    assert public_spec is not None
    assert public_spec.public is True

    run_stream_spec = registry.get("GET", "/api/threads/{thread_id}/runs/{run_id}/stream")
    assert run_stream_spec is not None
    assert run_stream_spec.capability == "runs:read"
    assert run_stream_spec.policies == ("owner:run",)

    post_stream_spec = registry.get("POST", "/api/threads/{thread_id}/runs/{run_id}/stream")
    assert post_stream_spec == run_stream_spec


def test_validate_route_policy_registry_rejects_missing_entry() -> None:
    app = FastAPI()
    router = APIRouter()

    @router.get("/api/needs-policy")
    async def needs_policy() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(router)
    registry = RoutePolicyRegistry([])

    with pytest.raises(RuntimeError, match="Missing route policy entries"):
        validate_route_policy_registry(app, registry)


def test_install_route_guards_appends_route_dependency() -> None:
    app = FastAPI()
    router = APIRouter()

    @router.get("/api/demo")
    async def demo() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(router)

    route = next(route for route in app.routes if getattr(route, "path", None) == "/api/demo")
    before = len(route.dependencies)

    install_route_guards(app)

    assert len(route.dependencies) == before + 1
    assert route.dependencies[-1].dependency is enforce_route_policy


@pytest.mark.anyio
async def test_enforce_route_policy_denies_missing_capability() -> None:
    user = User(id=uuid4(), email="user@example.com", password_hash="hash")
    auth = AuthContext(user=user, permissions=["threads:read"])
    registry = RoutePolicyRegistry(
        [
            SimpleNamespace(
                method="GET",
                path="/api/threads/{thread_id}/uploads/list",
                spec=RoutePolicySpec(capability="threads:delete"),
                matches_request=lambda *_args, **_kwargs: True,
            )
        ]
    )

    app = SimpleNamespace(state=SimpleNamespace(auth_route_policy_registry=registry))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/threads/thread-1/uploads/list",
        "headers": [],
        "app": app,
        "route": SimpleNamespace(path="/api/threads/{thread_id}/uploads/list"),
        "path_params": {"thread_id": "thread-1"},
        "auth": auth,
    }
    request = Request(scope)
    request.state.auth = auth

    with pytest.raises(Exception) as exc_info:
        await enforce_route_policy(request)

    assert getattr(exc_info.value, "status_code", None) == 403


@pytest.mark.anyio
async def test_enforce_route_policy_runs_owner_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    user = User(id=uuid4(), email="user@example.com", password_hash="hash")
    auth = AuthContext(user=user, permissions=["threads:read"])
    registry = RoutePolicyRegistry(
        [
            SimpleNamespace(
                method="GET",
                path="/api/threads/{thread_id}/state",
                spec=RoutePolicySpec(capability="threads:read", policies=("owner:thread",)),
                matches_request=lambda *_args, **_kwargs: True,
            )
        ]
    )

    called: dict[str, object] = {}

    async def fake_owner_check(request: Request, auth_context: AuthContext, *, thread_id: str, require_existing: bool) -> None:
        called["request"] = request
        called["auth"] = auth_context
        called["thread_id"] = thread_id
        called["require_existing"] = require_existing

    monkeypatch.setattr("app.plugins.auth.injection.route_guard.require_thread_owner", fake_owner_check)

    app = SimpleNamespace(state=SimpleNamespace(auth_route_policy_registry=registry))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/threads/thread-1/state",
        "headers": [],
        "app": app,
        "route": SimpleNamespace(path="/api/threads/{thread_id}/state"),
        "path_params": {"thread_id": "thread-1"},
        "auth": auth,
    }
    request = Request(scope)
    request.state.auth = auth

    await enforce_route_policy(request)

    assert called["thread_id"] == "thread-1"
    assert called["auth"] is auth
    assert called["require_existing"] is True
