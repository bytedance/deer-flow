"""A registered plugin action is authorized before its handler runs (O2).

Drives the real route through a real FastAPI app and the real provider factory:
the target, the identity and the ordering (decision before the request body is
read) are all observable.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest
from deerflow_extension_api.auth import EXTENSION_PRINCIPAL_RESOLVER_KEY, ExtensionPrincipal
from deerflow_extension_api.plugins import BackendAction, PluginContribution
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway import authz as gateway_authz
from app.gateway.auth_disabled import AUTH_SOURCE_INTERNAL, AUTH_SOURCE_SESSION
from app.gateway.internal_auth import INTERNAL_SYSTEM_ROLE
from app.gateway.routers.plugins import router
from deerflow.authz.provider import AuthzDecision, AuthzReason
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.config.authorization_config import AuthorizationConfig, AuthorizationProviderConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.extensions.registry import ExtensionRegistry

RBAC = "deerflow.authz.rbac:RbacAuthorizationProvider"
NAMESPACE = "community.check"
ACTION_URL = f"/api/plugins/{NAMESPACE}/actions/check"

_DECISIONS: list = []


class _RecordingProvider:
    """Records every decision and refuses the wrong entry points."""

    name = "recording"

    def __init__(self, *, allow: bool = True, fail: bool = False) -> None:
        self._allow = allow
        self._fail = fail

    def authorize(self, request):  # pragma: no cover - an async route must not use this
        raise AssertionError("the async plugin path must not call authorize()")

    async def aauthorize(self, request):
        if self._fail:
            raise RuntimeError("provider failed")
        _DECISIONS.append(request)
        return AuthzDecision(allow=self._allow, reasons=[] if self._allow else [AuthzReason(code="authz.denied")])

    def filter_resources(self, principal, resource_type, candidates):  # pragma: no cover
        raise AssertionError("the action path must not batch-filter")


@pytest.fixture(autouse=True)
def _isolated_authorization():
    """Both the config singleton and the plugin provider cache are process-global."""
    reset_app_config()
    gateway_authz._plugin_provider_cache.clear()
    _DECISIONS.clear()
    yield
    gateway_authz._plugin_provider_cache.clear()
    _DECISIONS.clear()
    reset_app_config()


@pytest.fixture
def plugin_app():
    calls = []

    async def check(payload, context):
        calls.append((payload, context))
        return {"length": len(payload["text"])}

    plugin = PluginContribution(
        namespace=NAMESPACE,
        title="Check",
        enabled=True,
        backend=(BackendAction("check", check),),
    )
    registry = ExtensionRegistry()
    with registry.attributed_to("test:install"):
        assert registry.plugin(plugin) is True
    app = FastAPI()
    app.state.extensions = registry.build()
    identity = {"role": "user", "auth_source": AUTH_SOURCE_SESSION}

    @app.middleware("http")
    async def stamp_identity(request, call_next):
        request.state.user = SimpleNamespace(id="user-1", system_role=identity["role"], oauth_provider=None, oauth_id=None)
        request.state.auth_source = identity["auth_source"]
        return await call_next(request)

    setattr(app.state, EXTENSION_PRINCIPAL_RESOLVER_KEY, lambda request: ExtensionPrincipal("user-1"))
    app.include_router(router)
    with TestClient(app) as http:
        yield http, calls, identity


def _use_authorization(*, roles: dict | None = None, enabled: bool = True, fail_closed: bool = True, provider_use: str = RBAC, provider_config: dict | None = None, default_role: str = "user") -> None:
    authorization = AuthorizationConfig(
        enabled=enabled,
        fail_closed=fail_closed,
        default_role=default_role,
        provider=AuthorizationProviderConfig(use=provider_use, config=provider_config if provider_config is not None else ({"roles": roles or {}} if provider_use == RBAC else {})),
    )
    set_app_config(
        AppConfig(
            models=[ModelConfig(name="gpt-4", model="gpt-4", use="langchain_openai:ChatOpenAI")],
            sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
            authorization=authorization,
        )
    )


def _recording_provider_class_path(monkeypatch: pytest.MonkeyPatch, name: str) -> str:
    """Install the recording provider under a class path the factory can import."""
    module = ModuleType(name)
    module.Provider = _RecordingProvider
    monkeypatch.setitem(sys.modules, name, module)
    return f"{name}:Provider"


# --- Allow and deny ------------------------------------------------------------


def test_allowed_action_reaches_the_handler_once(plugin_app, monkeypatch):
    http, calls, _ = plugin_app
    _use_authorization(provider_use=_recording_provider_class_path(monkeypatch, "plugin_action_allow_provider"))

    response = http.post(ACTION_URL, json={"text": "hello"})

    assert response.status_code == 200
    assert response.json() == {"length": 5}
    assert len(calls) == 1
    (decision,) = _DECISIONS
    assert (decision.resource, decision.action, decision.target) == ("plugin_action", "invoke", f"{NAMESPACE}/check")
    assert decision.principal.user_id == "user-1"
    assert decision.principal.role == "user"


def test_denied_action_returns_403_and_never_invokes_the_handler(plugin_app):
    http, calls, _ = plugin_app
    _use_authorization(roles={"user": {"plugin_actions": {"allow": []}}})

    response = http.post(ACTION_URL, json={"text": "hello"})

    assert response.status_code == 403
    assert response.json() == {"detail": "Plugin action not permitted for your role."}
    assert calls == []


def test_deny_is_decided_before_the_request_body_is_read(plugin_app):
    """A denied caller cannot spend the 256 KiB input budget."""
    http, calls, _ = plugin_app
    _use_authorization(roles={"user": {"plugin_actions": {"allow": []}}})

    response = http.post(ACTION_URL, content=b"{" + b" " * (300 * 1024) + b"}")

    assert response.status_code == 403
    assert calls == []


def test_allow_list_matches_the_declared_target_exactly(plugin_app):
    http, calls, _ = plugin_app
    _use_authorization(roles={"user": {"plugin_actions": {"allow": [f"{NAMESPACE}/other"]}}})

    assert http.post(ACTION_URL, json={"text": "hello"}).status_code == 403
    assert calls == []


def test_no_policy_for_the_resource_is_unrestricted(plugin_app):
    """Omitted config key = unrestricted, the documented non-breaking path."""
    http, calls, _ = plugin_app
    _use_authorization(roles={"user": {"tools": {"allow": []}}})

    assert http.post(ACTION_URL, json={"text": "hello"}).status_code == 200
    assert len(calls) == 1


# --- Failure policy ------------------------------------------------------------


def test_provider_error_denies_under_fail_closed(plugin_app, monkeypatch):
    http, calls, _ = plugin_app
    class_path = _recording_provider_class_path(monkeypatch, "plugin_action_failing_provider")
    _use_authorization(fail_closed=True, provider_use=class_path, provider_config={"fail": True})

    assert http.post(ACTION_URL, json={"text": "hello"}).status_code == 403
    assert calls == []


def test_provider_error_proceeds_under_fail_open(plugin_app, monkeypatch):
    http, calls, _ = plugin_app
    class_path = _recording_provider_class_path(monkeypatch, "plugin_action_failing_provider_open")
    _use_authorization(fail_closed=False, provider_use=class_path, provider_config={"fail": True})

    assert http.post(ACTION_URL, json={"text": "hello"}).status_code == 200
    assert len(calls) == 1


def test_unresolvable_provider_denies_under_fail_closed(plugin_app):
    http, calls, _ = plugin_app
    _use_authorization(provider_use="nonexistent.module:FakeProvider")

    assert http.post(ACTION_URL, json={"text": "hello"}).status_code == 403
    assert calls == []


def test_unresolvable_provider_proceeds_under_fail_open(plugin_app):
    http, calls, _ = plugin_app
    _use_authorization(fail_closed=False, provider_use="nonexistent.module:FakeProvider")

    assert http.post(ACTION_URL, json={"text": "hello"}).status_code == 200
    assert len(calls) == 1


# --- Compatibility -------------------------------------------------------------


def test_disabled_authorization_is_a_noop(plugin_app):
    """No provider is resolved and today's behavior is exact."""
    http, calls, _ = plugin_app
    _use_authorization(enabled=False, provider_use="nonexistent.module:FakeProvider")

    assert http.post(ACTION_URL, json={"text": "hello"}).status_code == 200
    assert len(calls) == 1
    assert _DECISIONS == []


def test_unknown_action_stays_a_404_without_a_decision(plugin_app):
    http, calls, _ = plugin_app
    _use_authorization(roles={"user": {"plugin_actions": {"allow": []}}})

    assert http.post(f"/api/plugins/{NAMESPACE}/actions/missing", json={}).status_code == 404
    assert calls == []


def test_unknown_namespace_stays_a_404(plugin_app):
    http, calls, _ = plugin_app
    _use_authorization(roles={"user": {"plugin_actions": {"allow": []}}})

    assert http.post("/api/plugins/community.missing/actions/check", json={}).status_code == 404
    assert calls == []


def test_disabled_plugin_is_refused_before_any_decision(plugin_app):
    http, calls, _ = plugin_app
    http.app.state.extensions = _extensions(enabled=False)
    _use_authorization(provider_use="deerflow.authz.rbac:RbacAuthorizationProvider", provider_config={"roles": {"user": {"plugin_actions": {"allow": "*"}}}})

    response = http.post(ACTION_URL, json={"text": "hello"})

    assert response.status_code == 403
    assert response.json() == {"detail": "Plugin disabled by administrator."}
    assert calls == []


def test_internal_caller_falls_back_to_the_default_role(plugin_app, monkeypatch):
    """INTERNAL_SYSTEM_ROLE is not a policy role, so default_role applies."""
    http, calls, identity = plugin_app
    identity["role"] = INTERNAL_SYSTEM_ROLE
    identity["auth_source"] = AUTH_SOURCE_INTERNAL
    class_path = _recording_provider_class_path(monkeypatch, "plugin_action_internal_provider")
    _use_authorization(default_role="guest", provider_use=class_path, provider_config={"allow": True})

    assert http.post(ACTION_URL, json={"text": "hello"}).status_code == 200
    (decision,) = _DECISIONS
    assert decision.principal.role == "guest"
    assert decision.principal.is_internal is True


def test_a_policy_change_is_observed_without_a_restart(plugin_app):
    """Each invocation asks the provider again; the cache is provider-level only."""
    http, calls, _ = plugin_app
    _use_authorization(roles={"user": {"plugin_actions": {"allow": []}}})
    assert http.post(ACTION_URL, json={"text": "a"}).status_code == 403

    _use_authorization(roles={"user": {"plugin_actions": {"allow": "*"}}})

    assert http.post(ACTION_URL, json={"text": "a"}).status_code == 200
    assert len(calls) == 1


def _extensions(*, enabled: bool) -> object:
    async def check(payload, context):  # pragma: no cover - never invoked
        return {}

    plugin = PluginContribution(namespace=NAMESPACE, title="Check", enabled=enabled, backend=(BackendAction("check", check),))
    registry = ExtensionRegistry()
    with registry.attributed_to("test:install"):
        registry.plugin(plugin)
    return registry.build()
