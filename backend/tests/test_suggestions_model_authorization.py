"""The suggestions route must enforce the same model policy as model details."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.gateway import authz
from app.gateway.deps import get_config
from app.gateway.routers import models, suggestions
from deerflow.authz.provider import AuthzDecision
from deerflow.authz.rbac import RbacAuthorizationProvider
from deerflow.config.app_config import AppConfig
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.utils import oneshot_llm


@pytest.fixture
def route_env(monkeypatch):
    user = SimpleNamespace(id="user-123", system_role="user", oauth_provider=None, oauth_id=None)
    config = AppConfig(
        models=[ModelConfig(name=name, model=name, use="langchain_openai:ChatOpenAI") for name in ["restricted", "allowed"]],
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        authorization=AuthorizationConfig(enabled=True, fail_closed=True),
    )
    provider = RbacAuthorizationProvider(roles={"user": {"models": {"allow": ["allowed"]}}})
    monkeypatch.setattr(authz, "_get_route_authorization_config", lambda: config.authorization)
    monkeypatch.setattr(authz, "_get_cached_route_provider", lambda _config: provider)
    monkeypatch.setattr(models, "get_optional_user_from_request", AsyncMock(return_value=user))
    invoked = []
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content='["What next?"]')))

    def create_model(**kwargs):
        invoked.append(kwargs["name"] if kwargs["name"] is not None else config.models[0].name)
        return model

    monkeypatch.setattr(oneshot_llm, "create_chat_model", create_model)
    app = FastAPI()

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        request.state.user = user
        request.state.auth_source = "session"
        request.state.auth = authz.AuthContext(user, ["threads:read", "runs:create"])
        return await call_next(request)

    app.state.thread_store = SimpleNamespace(check_access=AsyncMock(return_value=True))
    app.dependency_overrides[get_config] = lambda: config
    app.include_router(models.router)
    app.include_router(suggestions.router)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, config=config, provider=provider, invoked=invoked, model=model, app=app)


def _suggest(env, **body):
    return env.client.post(
        "/api/threads/thread-1/suggestions",
        json={"messages": [{"role": "user", "content": "Hello"}], **body},
    )


@pytest.mark.parametrize("body", [{"model_name": "restricted"}, {}, {"model_name": None}])
def test_denied_explicit_and_default_models_are_not_invoked(route_env, body):
    assert route_env.client.get("/api/models/restricted").status_code == 403
    response = _suggest(route_env, **body)
    assert response.status_code == 403
    assert route_env.invoked == []
    route_env.model.ainvoke.assert_not_awaited()


@pytest.mark.parametrize("use_default", [False, True])
def test_allowed_model_still_generates_suggestions(route_env, use_default):
    if use_default:
        route_env.config.models.reverse()
    response = _suggest(route_env, **({} if use_default else {"model_name": "allowed"}))
    assert response.status_code == 200
    assert response.json() == {"suggestions": ["What next?"]}
    assert route_env.invoked == ["allowed"]
    route_env.model.ainvoke.assert_awaited_once()


def test_disabled_authorization_preserves_existing_behavior(route_env):
    route_env.config.authorization.enabled = False
    assert _suggest(route_env, model_name="restricted").status_code == 200
    assert route_env.invoked == ["restricted"]


@pytest.mark.parametrize("fail_closed", [False, True])
@pytest.mark.parametrize("failure", ["resolution", "decision", "invalid_decision"])
def test_provider_failure_honors_configured_policy(route_env, monkeypatch, fail_closed, failure):
    route_env.config.authorization.fail_closed = fail_closed

    def broken(*_args, **_kwargs):
        if failure == "invalid_decision":
            return None
        raise RuntimeError("provider unavailable")

    if failure == "resolution":
        monkeypatch.setattr(authz, "_get_cached_route_provider", broken)
    else:
        monkeypatch.setattr(route_env.provider, "authorize", broken)
    response = _suggest(route_env, model_name="allowed")
    assert response.status_code == (403 if fail_closed else 200)
    assert route_env.invoked == ([] if fail_closed else ["allowed"])


def test_explicit_deny_is_not_treated_as_a_fail_open_error(route_env):
    route_env.config.authorization.fail_closed = False
    assert _suggest(route_env, model_name="restricted").status_code == 403
    assert route_env.invoked == []


def test_checks_use_permission_even_when_model_is_visible(route_env, monkeypatch):
    checked = []

    def authorize(request):
        checked.append((request.resource, request.action, request.target))
        return AuthzDecision(allow=request.action != "use")

    monkeypatch.setattr(route_env.provider, "authorize", authorize)
    response = _suggest(route_env, model_name="allowed")
    assert response.status_code == 403
    assert checked == [("model", "use", "allowed")]
    assert route_env.invoked == []


def test_foreign_thread_remains_denied_before_model_invocation(route_env):
    route_env.app.state.thread_store.check_access.return_value = False
    assert _suggest(route_env, model_name="allowed").status_code == 404
    assert route_env.invoked == []
