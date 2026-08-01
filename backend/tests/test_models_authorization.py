"""Phase 3 model-level authorization tests.

Covers two enforcement layers:
- Gateway routes (``list_models``, ``get_model``) — request-scoped Principal,
  mirrors Phase 2A's ``resolve_route_permissions``.
- Runtime model resolution (``_authorize_model_name``) — context-scoped
  Principal with graceful fallback, mirrors Phase 1B's ``apply_tool_authorization``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import models as models_router
from deerflow.authz.provider import AuthzDecision, AuthzReason
from deerflow.authz.rbac import RbacAuthorizationProvider
from deerflow.config.app_config import AppConfig
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.token_usage_config import TokenUsageConfig

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


def _make_app_config(model_names: list[str]) -> AppConfig:
    """Build a minimal AppConfig with the given model names."""
    return AppConfig(
        models=[ModelConfig(name=n, model=n, use="langchain_openai:ChatOpenAI") for n in model_names],
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        token_usage=TokenUsageConfig(enabled=False),
        authorization=AuthorizationConfig(),
    )


def _enable_authorization(monkeypatch, provider, *, fail_closed: bool = True, default_role: str = "user") -> None:
    config = AuthorizationConfig(
        enabled=True,
        fail_closed=fail_closed,
        default_role=default_role,
    )
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: config)
    monkeypatch.setattr("app.gateway.authz._get_cached_route_provider", lambda c: provider)


def _make_models_app(app_config: AppConfig) -> FastAPI:
    """Build a FastAPI app with the models router and a pinned config."""
    app = FastAPI()
    app.include_router(models_router.router)
    # Pin the config dependency so routes use our test AppConfig.
    app.dependency_overrides[models_router.get_config] = lambda: app_config
    return app


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


# ── list_models tests ──────────────────────────────────────────────────


def test_list_models_disabled_returns_all(monkeypatch):
    """When authorization is disabled, all models are visible."""
    config = AuthorizationConfig(enabled=False)
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: config)
    cached = AsyncMock(side_effect=AssertionError("disabled must not resolve provider"))
    monkeypatch.setattr("app.gateway.authz._get_cached_route_provider", cached)

    app_config = _make_app_config(["gpt-4", "claude-3"])
    monkeypatch.setattr(
        "app.gateway.routers.models.get_optional_user_from_request",
        AsyncMock(return_value=_user()),
    )

    with TestClient(_make_models_app(app_config)) as client:
        response = client.get("/api/models")

    assert response.status_code == 200
    names = [m["name"] for m in response.json()["models"]]
    assert names == ["gpt-4", "claude-3"]
    cached.assert_not_called()


def test_list_models_anonymous_user_returns_all(monkeypatch):
    """Anonymous requests (user=None) are not filtered."""
    provider = _RecordingProvider()
    _enable_authorization(monkeypatch, provider)

    app_config = _make_app_config(["gpt-4", "claude-3"])
    monkeypatch.setattr(
        "app.gateway.routers.models.get_optional_user_from_request",
        AsyncMock(return_value=None),
    )

    with TestClient(_make_models_app(app_config)) as client:
        response = client.get("/api/models")

    assert response.status_code == 200
    names = [m["name"] for m in response.json()["models"]]
    assert names == ["gpt-4", "claude-3"]
    assert provider.filter_requests == []


def test_list_models_rbac_filters_by_allow(monkeypatch):
    """Role with allowlist sees only allowed models."""
    provider = RbacAuthorizationProvider(
        roles={"user": {"models": {"allow": ["gpt-4"]}}},
    )
    _enable_authorization(monkeypatch, provider)

    app_config = _make_app_config(["gpt-4", "claude-3", "llama-3"])
    monkeypatch.setattr(
        "app.gateway.routers.models.get_optional_user_from_request",
        AsyncMock(return_value=_user()),
    )

    with TestClient(_make_models_app(app_config)) as client:
        response = client.get("/api/models")

    assert response.status_code == 200
    names = [m["name"] for m in response.json()["models"]]
    assert names == ["gpt-4"]


def test_list_models_rbac_filters_by_deny(monkeypatch):
    """Role with deny hides denied models."""
    provider = RbacAuthorizationProvider(
        roles={"user": {"models": {"allow": "*", "deny": ["claude-3"]}}},
    )
    _enable_authorization(monkeypatch, provider)

    app_config = _make_app_config(["gpt-4", "claude-3", "llama-3"])
    monkeypatch.setattr(
        "app.gateway.routers.models.get_optional_user_from_request",
        AsyncMock(return_value=_user()),
    )

    with TestClient(_make_models_app(app_config)) as client:
        response = client.get("/api/models")

    assert response.status_code == 200
    names = [m["name"] for m in response.json()["models"]]
    assert names == ["gpt-4", "llama-3"]


def test_list_models_wildcard_returns_all(monkeypatch):
    """Role with allow: '*' sees all models."""
    provider = RbacAuthorizationProvider(
        roles={"user": {"models": {"allow": "*"}}},
    )
    _enable_authorization(monkeypatch, provider)

    app_config = _make_app_config(["gpt-4", "claude-3"])
    monkeypatch.setattr(
        "app.gateway.routers.models.get_optional_user_from_request",
        AsyncMock(return_value=_user()),
    )

    with TestClient(_make_models_app(app_config)) as client:
        response = client.get("/api/models")

    assert response.status_code == 200
    names = [m["name"] for m in response.json()["models"]]
    assert names == ["gpt-4", "claude-3"]


@pytest.mark.parametrize(
    ("fail_closed", "expected_count"),
    [(True, 0), (False, 3)],
)
def test_list_models_provider_error_fail_closed_vs_open(monkeypatch, fail_closed, expected_count):
    """Provider error → empty (fail-closed) or all (fail-open)."""
    provider = _RecordingProvider(errors={"model"})
    _enable_authorization(monkeypatch, provider, fail_closed=fail_closed)

    app_config = _make_app_config(["gpt-4", "claude-3", "llama-3"])
    app_config.authorization.fail_closed = fail_closed
    monkeypatch.setattr(
        "app.gateway.routers.models.get_optional_user_from_request",
        AsyncMock(return_value=_user()),
    )

    with TestClient(_make_models_app(app_config)) as client:
        response = client.get("/api/models")

    assert response.status_code == 200
    assert len(response.json()["models"]) == expected_count


# ── get_model tests ────────────────────────────────────────────────────


def test_get_model_disabled_returns_model(monkeypatch):
    """When authorization is disabled, get_model works as before."""
    config = AuthorizationConfig(enabled=False)
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: config)

    app_config = _make_app_config(["gpt-4"])
    monkeypatch.setattr(
        "app.gateway.routers.models.get_optional_user_from_request",
        AsyncMock(return_value=_user()),
    )

    with TestClient(_make_models_app(app_config)) as client:
        response = client.get("/api/models/gpt-4")

    assert response.status_code == 200
    assert response.json()["name"] == "gpt-4"


def test_get_model_404_when_not_found(monkeypatch):
    """Non-existent model returns 404 regardless of authorization."""
    provider = RbacAuthorizationProvider(roles={"user": {"models": {"allow": "*"}}})
    _enable_authorization(monkeypatch, provider)

    app_config = _make_app_config(["gpt-4"])
    monkeypatch.setattr(
        "app.gateway.routers.models.get_optional_user_from_request",
        AsyncMock(return_value=_user()),
    )

    with TestClient(_make_models_app(app_config)) as client:
        response = client.get("/api/models/nonexistent")

    assert response.status_code == 404


def test_get_model_denied_returns_403(monkeypatch):
    """Role denied model:use → 403 (not 404)."""
    provider = RbacAuthorizationProvider(
        roles={"user": {"models": {"allow": ["claude-3"]}}},
    )
    _enable_authorization(monkeypatch, provider)

    app_config = _make_app_config(["gpt-4", "claude-3"])
    monkeypatch.setattr(
        "app.gateway.routers.models.get_optional_user_from_request",
        AsyncMock(return_value=_user()),
    )

    with TestClient(_make_models_app(app_config)) as client:
        response = client.get("/api/models/gpt-4")

    assert response.status_code == 403


def test_get_model_allowed_returns_200(monkeypatch):
    """Role allowed model:use → 200."""
    provider = RbacAuthorizationProvider(
        roles={"user": {"models": {"allow": ["gpt-4", "claude-3"]}}},
    )
    _enable_authorization(monkeypatch, provider)

    app_config = _make_app_config(["gpt-4", "claude-3"])
    monkeypatch.setattr(
        "app.gateway.routers.models.get_optional_user_from_request",
        AsyncMock(return_value=_user()),
    )

    with TestClient(_make_models_app(app_config)) as client:
        response = client.get("/api/models/gpt-4")

    assert response.status_code == 200
    assert response.json()["name"] == "gpt-4"


@pytest.mark.parametrize(
    ("fail_closed", "expected_status"),
    [(True, 403), (False, 200)],
)
def test_get_model_provider_error_fail_closed_vs_open(monkeypatch, fail_closed, expected_status):
    """Provider error on model:use → 403 (fail-closed) or 200 (fail-open)."""
    provider = _RecordingProvider(errors={"gpt-4"})
    _enable_authorization(monkeypatch, provider, fail_closed=fail_closed)

    app_config = _make_app_config(["gpt-4"])
    app_config.authorization.fail_closed = fail_closed
    monkeypatch.setattr(
        "app.gateway.routers.models.get_optional_user_from_request",
        AsyncMock(return_value=_user()),
    )

    with TestClient(_make_models_app(app_config)) as client:
        response = client.get("/api/models/gpt-4")

    assert response.status_code == expected_status


@pytest.mark.parametrize(
    ("fail_closed", "expected_status"),
    [(True, 403), (False, 200)],
)
def test_get_model_provider_unavailable_fail_closed_vs_open(monkeypatch, fail_closed, expected_status):
    """Provider *resolution* failure → 403 (fail-closed) or 200 (fail-open).

    Distinct from ``test_get_model_provider_error_fail_closed_vs_open``: that
    test exercises a provider that resolves but errors inside ``authorize``.
    This one exercises ``_AuthorizationUnavailable`` (the provider cannot be
    resolved at all, e.g. misconfigured class path) and pins the fail-open
    path so the docstring's "provider resolution error yields 403 (fail-closed)
    or allows the request (fail-open)" claim is backed by a test.
    """
    config = AuthorizationConfig(
        enabled=True,
        fail_closed=fail_closed,
        default_role="user",
    )
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: config)

    # Force provider resolution to raise → _AuthorizationUnavailable.
    def _boom(_config):
        raise RuntimeError("provider class path invalid")

    monkeypatch.setattr("app.gateway.authz._get_cached_route_provider", _boom)

    app_config = _make_app_config(["gpt-4"])
    app_config.authorization.fail_closed = fail_closed
    monkeypatch.setattr(
        "app.gateway.routers.models.get_optional_user_from_request",
        AsyncMock(return_value=_user()),
    )

    with TestClient(_make_models_app(app_config)) as client:
        response = client.get("/api/models/gpt-4")

    assert response.status_code == expected_status


# ── Runtime model resolution tests (_authorize_model_name) ─────────────


def _rbac_context(**overrides):
    """Build a minimal run context dict for build_principal_from_context."""
    values = {
        "user_id": "user-123",
        "user_role": "user",
        "oauth_provider": "github",
        "oauth_id": "oauth-456",
        "is_internal": False,
    }
    values.update(overrides)
    return values


def _enable_runtime_authorization(monkeypatch, provider) -> AuthorizationConfig:
    """Patch resolve_authorization_provider in agent.py to return *provider*.

    Returns an enabled AuthorizationConfig the caller assigns to app_config.
    """
    monkeypatch.setattr(
        "deerflow.agents.lead_agent.agent.resolve_authorization_provider",
        lambda config: provider,
    )
    return AuthorizationConfig(enabled=True, fail_closed=True, default_role="user")


def test_authorize_model_name_disabled_is_noop():
    """When authorization is disabled, model name is returned unchanged."""
    from deerflow.agents.lead_agent.agent import _authorize_model_name

    app_config = _make_app_config(["gpt-4", "claude-3"])
    # AuthorizationConfig() defaults to enabled=False.
    result = _authorize_model_name("gpt-4", context=_rbac_context(), app_config=app_config)
    assert result == "gpt-4"


def test_authorize_model_name_allowed_returns_same(monkeypatch):
    """Allowed model → returned unchanged."""
    from deerflow.agents.lead_agent.agent import _authorize_model_name

    provider = RbacAuthorizationProvider(
        roles={"user": {"models": {"allow": ["gpt-4", "claude-3"]}}},
    )
    app_config = _make_app_config(["gpt-4", "claude-3"])
    app_config.authorization = _enable_runtime_authorization(monkeypatch, provider)

    result = _authorize_model_name("gpt-4", context=_rbac_context(), app_config=app_config)
    assert result == "gpt-4"


def test_authorize_model_name_denied_falls_back_gracefully(monkeypatch):
    """Denied model → falls back to first allowed model (RFC §9)."""
    from deerflow.agents.lead_agent.agent import _authorize_model_name

    provider = RbacAuthorizationProvider(
        roles={"user": {"models": {"allow": ["claude-3"]}}},
    )
    app_config = _make_app_config(["gpt-4", "claude-3"])
    app_config.authorization = _enable_runtime_authorization(monkeypatch, provider)

    result = _authorize_model_name("gpt-4", context=_rbac_context(), app_config=app_config)
    assert result == "claude-3"


def test_authorize_model_name_all_denied_fail_closed_raises(monkeypatch):
    """All models denied + fail_closed → ValueError."""
    from deerflow.agents.lead_agent.agent import _authorize_model_name

    provider = RbacAuthorizationProvider(
        roles={"user": {"models": {"allow": []}}},
    )
    app_config = _make_app_config(["gpt-4", "claude-3"])
    app_config.authorization = _enable_runtime_authorization(monkeypatch, provider)

    with pytest.raises(ValueError, match="No models are authorized"):
        _authorize_model_name("gpt-4", context=_rbac_context(), app_config=app_config)


def test_authorize_model_name_all_denied_fail_open_returns_original(monkeypatch):
    """All models denied + fail_open → returns original model name."""
    from deerflow.agents.lead_agent.agent import _authorize_model_name

    provider = RbacAuthorizationProvider(
        roles={"user": {"models": {"allow": []}}},
    )
    app_config = _make_app_config(["gpt-4", "claude-3"])
    app_config.authorization = AuthorizationConfig(
        enabled=True,
        fail_closed=False,
        default_role="user",
    )
    monkeypatch.setattr(
        "deerflow.agents.lead_agent.agent.resolve_authorization_provider",
        lambda config: provider,
    )

    result = _authorize_model_name("gpt-4", context=_rbac_context(), app_config=app_config)
    assert result == "gpt-4"


def test_authorize_model_name_custom_provider_list_vs_use_divergence(monkeypatch):
    """Custom provider that allows 'list' but denies 'use' → model is denied.

    Regression for willem-bd's forward-looking note: a custom provider that
    distinguishes ``list`` from ``use`` must not let a model through the
    runtime path just because ``filter_resources`` includes it. The runtime
    path checks ``authorize("model", "use")`` first; only on deny does it
    fall back to ``filter_resources`` to pick a replacement.
    """

    class _ListButNotUseProvider:
        """Allows listing gpt-4 but denies using it."""

        name = "list-not-use"

        def authorize(self, request):
            if request.resource == "model" and request.action == "use" and request.target == "gpt-4":
                return AuthzDecision(allow=False, reasons=[AuthzReason(code="authz.denied")])
            return AuthzDecision(allow=True, reasons=[AuthzReason(code="authz.allowed")])

        async def aauthorize(self, request):
            return self.authorize(request)

        def filter_resources(self, principal, resource_type, candidates):
            # gpt-4 is "visible" (listable) but not "usable"
            return list(candidates)

    app_config = _make_app_config(["gpt-4", "claude-3"])
    app_config.authorization = AuthorizationConfig(enabled=True, fail_closed=True, default_role="user")
    monkeypatch.setattr(
        "deerflow.agents.lead_agent.agent.resolve_authorization_provider",
        lambda config: _ListButNotUseProvider(),
    )

    # gpt-4 is listable but denied for use → falls back to claude-3
    from deerflow.agents.lead_agent.agent import _authorize_model_name

    result = _authorize_model_name("gpt-4", context=_rbac_context(), app_config=app_config)
    assert result != "gpt-4"
    assert result == "claude-3"


def test_authorize_model_name_custom_provider_no_usable_fallback_fail_closed(monkeypatch):
    """All visible models denied for use + fail_closed → ValueError.

    Regression for willem-bd's edge-case note: when ``filter_resources``
    returns only models that are themselves denied for ``use``, the fallback
    must NOT silently reselect a denied model. With ``fail_closed=True`` it
    must raise; with ``fail_closed=False`` it returns the original name.
    """

    class _AllListNoneUseProvider:
        """Lists all models but denies use for every one of them."""

        name = "all-list-none-use"

        def authorize(self, request):
            if request.resource == "model" and request.action == "use":
                return AuthzDecision(allow=False, reasons=[AuthzReason(code="authz.denied")])
            return AuthzDecision(allow=True, reasons=[AuthzReason(code="authz.allowed")])

        async def aauthorize(self, request):
            return self.authorize(request)

        def filter_resources(self, principal, resource_type, candidates):
            return list(candidates)  # all visible

    app_config = _make_app_config(["gpt-4", "claude-3"])
    app_config.authorization = AuthorizationConfig(enabled=True, fail_closed=True, default_role="user")
    monkeypatch.setattr(
        "deerflow.agents.lead_agent.agent.resolve_authorization_provider",
        lambda config: _AllListNoneUseProvider(),
    )

    from deerflow.agents.lead_agent.agent import _authorize_model_name

    # gpt-4 denied for use; fallback candidates also denied → ValueError
    with pytest.raises(ValueError, match="No models are authorized"):
        _authorize_model_name("gpt-4", context=_rbac_context(), app_config=app_config)


def test_authorize_model_name_custom_provider_no_usable_fallback_fail_open(monkeypatch):
    """All visible models denied for use + fail_open → returns original name."""

    class _AllListNoneUseProvider:
        name = "all-list-none-use"

        def authorize(self, request):
            if request.resource == "model" and request.action == "use":
                return AuthzDecision(allow=False, reasons=[AuthzReason(code="authz.denied")])
            return AuthzDecision(allow=True, reasons=[AuthzReason(code="authz.allowed")])

        async def aauthorize(self, request):
            return self.authorize(request)

        def filter_resources(self, principal, resource_type, candidates):
            return list(candidates)

    app_config = _make_app_config(["gpt-4", "claude-3"])
    app_config.authorization = AuthorizationConfig(enabled=True, fail_closed=False, default_role="user")
    monkeypatch.setattr(
        "deerflow.agents.lead_agent.agent.resolve_authorization_provider",
        lambda config: _AllListNoneUseProvider(),
    )

    from deerflow.agents.lead_agent.agent import _authorize_model_name

    result = _authorize_model_name("gpt-4", context=_rbac_context(), app_config=app_config)
    assert result == "gpt-4"


# ── DeerFlowClient._ensure_agent path ─────────────────────────────────
# Regression for willem-bd's Round 4 coverage observation: the embedded/library
# lead-agent construction path (``DeerFlowClient._ensure_agent``) must enforce
# ``model:use`` too, not just the Gateway runtime path (``_make_lead_agent``).
# Otherwise a consumer that enables ``authorization`` with role-scoped model
# policies gets tools filtered yet can still run a model the role is denied
# ``use`` for, diverging from the contract this PR establishes.


def test_client_ensure_agent_enforces_model_use_when_authorized(monkeypatch):
    """``_ensure_agent`` routes the resolved model through ``_authorize_model_name``.

    Real-path test: we let the genuine ``_authorize_model_name`` run against a
    real RBAC provider (only ``resolve_authorization_provider`` is patched, as
    in the runtime tests above) so the full ``client → authz gate → RBAC →
    fallback → create_chat_model`` chain is exercised — not just "the gate was
    called". The provider allows only ``claude-3`` for ``use``, so the denied
    ``gpt-4`` must be swapped for ``claude-3`` before reaching the model factory.
    """
    from langchain_core.runnables import RunnableConfig

    app_config = _make_app_config(["gpt-4", "claude-3"])
    app_config.authorization = AuthorizationConfig(enabled=True, fail_closed=True, default_role="user")

    provider = RbacAuthorizationProvider(roles={"user": {"models": {"allow": ["claude-3"]}}})
    monkeypatch.setattr(
        "deerflow.agents.lead_agent.agent.resolve_authorization_provider",
        lambda config: provider,
    )
    captured_name = _stub_client_assembly(monkeypatch)

    client = _bare_client(app_config)
    config: RunnableConfig = {"configurable": {"model_name": "gpt-4", "user_id": "user-123", "user_role": "user"}}
    client._ensure_agent(config)

    # Denied ``gpt-4`` was swapped for the authorized fallback ``claude-3``.
    assert captured_name["name"] == "claude-3"


def test_client_ensure_agent_resolves_none_default_before_authorization(monkeypatch):
    """A ``None`` model name is resolved to the default before the authz gate.

    Guards the ``create_chat_model(name=None)`` semantic: when the caller omits
    ``model_name`` the implicit default (first configured model) must still pass
    ``model:use`` — otherwise the embedded path could run an unauthorized default.
    """
    from langchain_core.runnables import RunnableConfig

    app_config = _make_app_config(["gpt-4", "claude-3"])
    app_config.authorization = AuthorizationConfig(enabled=True, fail_closed=True, default_role="user")

    # Deny the default ``gpt-4``; the gate must fallback to ``claude-3``.
    provider = RbacAuthorizationProvider(roles={"user": {"models": {"allow": ["claude-3"]}}})
    monkeypatch.setattr(
        "deerflow.agents.lead_agent.agent.resolve_authorization_provider",
        lambda config: provider,
    )
    captured_name = _stub_client_assembly(monkeypatch)

    client = _bare_client(app_config)
    # No model_name supplied → defaults to ``gpt-4`` (first configured) → denied → fallback.
    config: RunnableConfig = {"configurable": {"user_id": "user-123", "user_role": "user"}}
    client._ensure_agent(config)

    assert captured_name["name"] == "claude-3"


def test_client_ensure_agent_noop_when_authorization_disabled(monkeypatch):
    """When ``authorization.enabled`` is false, ``_ensure_agent`` leaves the model unchanged."""
    from langchain_core.runnables import RunnableConfig

    app_config = _make_app_config(["gpt-4"])
    # AuthorizationConfig() defaults to enabled=False.

    captured_name = _stub_client_assembly(monkeypatch)
    client = _bare_client(app_config)
    config: RunnableConfig = {"configurable": {"model_name": "gpt-4"}}
    client._ensure_agent(config)

    # Disabled → gate is a no-op: original name passed straight through.
    assert captured_name["name"] == "gpt-4"


def _stub_client_assembly(monkeypatch) -> dict[str, str]:
    """Stub the heavy dependencies ``_ensure_agent`` pulls in after the authz gate.

    Returns a dict the caller can inspect to see what ``create_chat_model`` got.
    Everything here is downstream of the contract under test, so we replace it
    with no-ops to keep the test focused on the ``_authorize_model_name`` call.
    """
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        "deerflow.client.create_chat_model",
        lambda **kwargs: captured.__setitem__("name", kwargs.get("name")) or object(),
    )
    monkeypatch.setattr("deerflow.client.create_agent", lambda **kwargs: object())
    monkeypatch.setattr("deerflow.client.build_middlewares", lambda *args, **kwargs: [])
    monkeypatch.setattr("deerflow.client.DeerFlowClient._get_tools", staticmethod(lambda *, model_name, subagent_enabled: []))  # noqa: ARG005
    monkeypatch.setattr("deerflow.client.get_enabled_skills_for_config", lambda app_config: [])  # noqa: ARG005
    monkeypatch.setattr(
        "deerflow.client.build_skill_search_setup",
        lambda skills, *, enabled, container_base_path: SimpleNamespace(describe_skill_tool=None, skill_names=frozenset()),  # noqa: ARG005
    )
    monkeypatch.setattr(
        "deerflow.client.assemble_deferred_tools",
        lambda tools, *, enabled: ([], SimpleNamespace(deferred_names=frozenset())),  # noqa: ARG005
    )
    monkeypatch.setattr("deerflow.client.build_mcp_routing_middleware", lambda *args, **kwargs: None)  # noqa: ARG005
    monkeypatch.setattr("deerflow.client.get_mcp_routing_hints_prompt_section", lambda *args, **kwargs: "")  # noqa: ARG005
    monkeypatch.setattr("deerflow.client.apply_prompt_template", lambda **kwargs: "")  # noqa: ARG005
    monkeypatch.setattr("deerflow.client.get_thread_state_schema", lambda *args, **kwargs: object())  # noqa: ARG005
    monkeypatch.setattr("deerflow.client.normalize_middleware_state_schemas", lambda schemas, mode, freq: [])  # noqa: ARG005
    monkeypatch.setattr("deerflow.client.get_effective_user_id", lambda: "user-123")
    # ``apply_tool_authorization`` (called with the empty tool list above) still
    # resolves a provider via ``tool_filter.resolve_authorization_provider``; route
    # it at an allow-all RBAC provider so the empty list stays empty.
    monkeypatch.setattr(
        "deerflow.authz.tool_filter.resolve_authorization_provider",
        lambda config: RbacAuthorizationProvider(roles={"user": {"tools": {"allow": "*"}}}),
    )
    return captured


def _bare_client(app_config):
    """Construct a ``DeerFlowClient`` without running ``__init__``."""
    from deerflow.client import DeerFlowClient

    client = DeerFlowClient.__new__(DeerFlowClient)
    client._app_config = app_config
    client._agent_name = "default"
    client._available_skills = None
    client._checkpoint_channel_mode = "full"
    client._checkpoint_snapshot_frequency = None
    client._middlewares = []
    client._agent = None
    client._agent_config_key = None
    # Non-None so ``_ensure_agent`` skips the real (postgres/sqlite) checkpointer
    # resolution — the value is never used because ``create_agent`` is stubbed.
    client._checkpointer = object()
    return client
