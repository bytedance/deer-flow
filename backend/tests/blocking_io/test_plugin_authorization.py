"""Plugin authorization must keep its blocking work off the async event loop.

Anchors the placement contract of ``authz/plugin_authz.py`` and
``app/gateway/authz.py``: config loading, provider *discovery* and the
synchronous ``filter_resources`` call all run in a worker, while provider
*construction* and ``aauthorize`` stay on the calling loop. Each test drives a
real production entry point with a probe that performs genuine blocking file IO,
so the gate fires if the offload is reverted.

Each test records that its probe really ran, so an anchor cannot pass because
the production path stopped calling it. `test_gate_smoke.py` protects the gate
itself from silently losing teeth.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest
from deerflow_extension_api.auth import (
    EXTENSION_PRINCIPAL_RESOLVER_KEY,
    ExtensionPrincipal,
)
from deerflow_extension_api.plugins import BackendAction, PluginContribution
from fastapi import HTTPException
from starlette.requests import Request

from app.gateway import authz as gateway_authz
from app.gateway.app import _resolve_extension_plugin_management_async
from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
from app.gateway.routers.plugins import invoke_plugin_action
from deerflow.authz.plugin_authz import afilter_plugin_management
from deerflow.authz.provider import Principal
from deerflow.authz.rbac import RbacAuthorizationProvider
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.config.authorization_config import AuthorizationConfig, AuthorizationProviderConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.extensions.registry import ExtensionRegistry

pytestmark = pytest.mark.asyncio

NAMESPACE = "community.check"
RBAC = "deerflow.authz.rbac:RbacAuthorizationProvider"


def _blocking_probe(tmp_path: Path) -> Path:
    path = tmp_path / "plugin-authz-blocking-probe"
    path.write_text("probe", encoding="utf-8")
    return path


def _app_config(*, roles: dict, provider_use: str = RBAC, provider_config: dict | None = None) -> AppConfig:
    return AppConfig(
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        authorization=AuthorizationConfig(
            enabled=True,
            fail_closed=True,
            default_role="user",
            provider=AuthorizationProviderConfig(use=provider_use, config={"roles": roles} if provider_config is None else provider_config),
        ),
    )


def _plugin_extensions() -> object:
    async def check(payload, context):  # pragma: no cover - the decisions under test deny first
        return {}

    plugin = PluginContribution(namespace=NAMESPACE, title="Check", enabled=True, backend=(BackendAction("check", check),))
    registry = ExtensionRegistry()
    with registry.attributed_to("test:install"):
        registry.plugin(plugin)
    return registry.build()


def _unknown_request(*, extensions: object, user_id: str = "user-1") -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(extensions=extensions)),
        state=SimpleNamespace(user=SimpleNamespace(id=user_id, system_role="user", oauth_provider=None, oauth_id=None), auth_source=AUTH_SOURCE_SESSION),
        headers={},
    )


def _action_request(extensions: object) -> Request:
    """A real Starlette Request for the action route, without an ASGI round trip."""
    app = SimpleNamespace(state=SimpleNamespace(extensions=extensions))
    user = SimpleNamespace(id=uuid4(), system_role="user", oauth_provider=None, oauth_id=None)
    request = Request({"type": "http", "app": app, "headers": [], "method": "POST"})
    request.state.user = user
    request.state.auth_source = AUTH_SOURCE_SESSION
    setattr(app.state, EXTENSION_PRINCIPAL_RESOLVER_KEY, lambda incoming: ExtensionPrincipal(str(incoming.state.user.id)))
    return request


@pytest.fixture(autouse=True)
def _isolated_authorization():
    reset_app_config()
    gateway_authz._plugin_provider_cache.clear()
    yield
    gateway_authz._plugin_provider_cache.clear()
    reset_app_config()


async def test_action_route_offloads_config_load_and_provider_discovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Deny path of POST /api/plugins/{ns}/actions/{name} (the real route function)."""
    probe = _blocking_probe(tmp_path)
    app_config = _app_config(roles={"user": {"plugin_actions": {"allow": []}}})
    set_app_config(app_config)

    config_loads: list[str] = []
    discoveries: list[str] = []

    def blocking_config_load() -> AppConfig:
        probe.read_text(encoding="utf-8")
        config_loads.append("loaded")
        return app_config

    discover = gateway_authz.resolve_authorization_provider_spec

    def blocking_discovery(config: AuthorizationConfig):
        probe.read_text(encoding="utf-8")
        discoveries.append("discovered")
        return discover(config)

    monkeypatch.setattr(gateway_authz, "_plugin_app_config", blocking_config_load)
    monkeypatch.setattr(gateway_authz, "resolve_authorization_provider_spec", blocking_discovery)

    request = _action_request(_plugin_extensions())
    with pytest.raises(HTTPException) as error:
        await invoke_plugin_action(request, namespace=NAMESPACE, action_name="check")

    assert error.value.status_code == 403
    # Both blocking helpers really ran — inside workers, or the gate would have raised.
    assert config_loads
    assert discoveries == ["discovered"]


async def test_async_management_resolver_offloads_the_same_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The resolver installed at EXTENSION_PLUGIN_AUTHZ_RESOLVER_ASYNC_KEY."""
    probe = _blocking_probe(tmp_path)
    app_config = _app_config(roles={"user": {"plugin_management": {"allow": []}}})
    set_app_config(app_config)

    config_loads: list[str] = []

    def blocking_config_load() -> AppConfig:
        probe.read_text(encoding="utf-8")
        config_loads.append("loaded")
        return app_config

    discover = gateway_authz.resolve_authorization_provider_spec

    def blocking_discovery(config: AuthorizationConfig):
        probe.read_text(encoding="utf-8")
        return discover(config)

    monkeypatch.setattr(gateway_authz, "_plugin_app_config", blocking_config_load)
    monkeypatch.setattr(gateway_authz, "resolve_authorization_provider_spec", blocking_discovery)

    answer = await _resolve_extension_plugin_management_async(_unknown_request(extensions=_plugin_extensions()), NAMESPACE, "read")

    assert answer is False  # denied by policy, decided without blocking the loop
    assert config_loads  # reached inside a worker, or the gate would have raised


async def test_batch_decision_offloads_the_synchronous_provider_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``filter_resources`` is synchronous, so the batch helpers hop to a worker."""
    probe = _blocking_probe(tmp_path)
    module = ModuleType("plugin_blocking_io_test_provider")

    class BlockingFilterProvider(RbacAuthorizationProvider):
        def filter_resources(self, principal, resource_type, candidates):
            probe.read_text(encoding="utf-8")
            return list(candidates)

    module.BlockingFilterProvider = BlockingFilterProvider
    monkeypatch.setitem(sys.modules, module.__name__, module)

    app_config = _app_config(roles={"user": {}}, provider_use=f"{module.__name__}:BlockingFilterProvider", provider_config={"roles": {"user": {}}})
    candidates = [f"{NAMESPACE}/permissions.read"]

    allowed = await afilter_plugin_management(principal=Principal(user_id="user-1", role="user"), app_config=app_config, candidates=candidates)

    assert allowed == frozenset(candidates)
