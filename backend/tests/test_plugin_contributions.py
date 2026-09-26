"""One installation owns its settings, browser artifact and gated backend actions."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from deerflow_extension_api.auth import EXTENSION_PRINCIPAL_RESOLVER_KEY, ExtensionPrincipal
from deerflow_extension_api.plugins import BackendAction, BrowserModule, PluginContribution
from deerflow_extension_api.settings import SettingsField
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers.plugins import router
from deerflow.extensions.registry import ExtensionRegistry


@pytest.fixture
def plugin_client():
    calls = []

    async def check(payload, context):
        calls.append((payload, context))
        return {"length": len(payload["text"]), "limit": context.settings["limit"]}

    plugin = PluginContribution(
        namespace="community.check",
        title="Check",
        fields=(SettingsField("limit", "Limit", "integer", 20, minimum=1, maximum=100),),
        frontend=BrowserModule("check.v1", 'export default {apiVersion:1,module:"check.v1"};'),
        backend=(BackendAction("check", check),),
    )
    registry = ExtensionRegistry()
    with registry.attributed_to("test:install"):
        assert registry.plugin(plugin) is True
    app = FastAPI()
    app.state.extensions = registry.build()
    role = {"value": "admin"}

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.user = SimpleNamespace(id="user-1", system_role=role["value"])
        request.state.auth_source = "session"
        return await call_next(request)

    setattr(app.state, EXTENSION_PRINCIPAL_RESOLVER_KEY, lambda request: ExtensionPrincipal("user-1", is_admin=role["value"] == "admin"))
    app.include_router(router)
    with TestClient(app) as http:
        yield http, role, calls, plugin


def test_one_card_and_deployment_owned_switch(plugin_client):
    http, role, calls, plugin = plugin_client
    (page,) = http.get("/api/plugins").json()
    assert page["namespace"] == "community.check"
    assert page["settings"] == {"enabled": False}
    asset = http.get(page["entry"])
    assert asset.text.startswith("export default")
    assert asset.headers["x-content-type-options"] == "nosniff"
    assert asset.headers["content-type"].startswith("text/javascript")
    assert "limit" not in page["settings"]
    url = "/api/plugins/community.check"
    assert http.patch(url, json={"changes": {"enabled": True}}).status_code == 404
    assert http.post(url + "/reset", json={}).status_code == 404
    assert http.post(url + "/actions/check", json={"text": "hello"}).status_code == 403
    assert not calls
    registry = ExtensionRegistry()
    with registry.attributed_to("test:install"):
        registry.plugin(replace(plugin, enabled=True))
    http.app.state.extensions = registry.build()
    role["value"] = "member"
    assert http.post(url + "/actions/check", json={"text": "hello"}).json() == {"length": 5, "limit": 20}
    assert calls[0][1].principal.user_id == "user-1"
    assert http.post(url + "/actions/check", json={"text": "old-account"}, headers={"x-deerflow-plugin-viewer": "other-account"}).status_code == 409
    with pytest.raises(TypeError):
        calls[0][1].settings["enabled"] = False


def test_backend_only_and_frontend_only_share_registration_and_rollback(plugin_client):
    _, _, _, plugin = plugin_client
    registry = ExtensionRegistry()
    with registry.attributed_to("example"):
        registry.plugin(replace(plugin, namespace="community.backend", frontend=None))
        mark = registry.mark()
        registry.plugin(replace(plugin, namespace="community.frontend", backend=()))
        assert len(registry.build().plugins) == 2
        registry.rollback_to(mark)
        assert len(registry.build().plugins) == 1
        before = registry.mark()
        with pytest.raises(ValueError):
            registry.plugin(replace(plugin, namespace="community.invalid", backend=(plugin.backend[0], plugin.backend[0])))
        assert registry.mark() == before
    registry.discard("example")
    assert not registry.build().plugins


def test_unauthenticated_backend_call_fails_closed(plugin_client):
    http, _, calls, _ = plugin_client
    setattr(http.app.state, EXTENSION_PRINCIPAL_RESOLVER_KEY, lambda request: None)
    assert http.post("/api/plugins/community.check/actions/check", json={}).status_code == 401
    assert http.get("/api/plugins").status_code == 401
    assert http.get("/api/plugins/modules/check.v1/" + "a" * 64 + ".mjs").status_code == 401
    assert not calls


def test_input_limits_and_handler_errors_do_not_leak_details(plugin_client):
    http, _, calls, plugin = plugin_client

    async def fail(payload, context):
        raise RuntimeError("private-provider-secret")

    registry = ExtensionRegistry()
    with registry.attributed_to("example"):
        registry.plugin(replace(plugin, enabled=True, backend=(BackendAction("fail", fail),)))
    http.app.state.extensions = registry.build()
    url = "/api/plugins/community.check/actions/fail"
    assert http.post(url, content="bad-json").status_code == 422
    assert http.post(url, json=[]).status_code == 422
    assert http.post(url, json={"text": "x" * (256 * 1024)}).status_code == 413
    failure = http.post(url, json={})
    assert failure.status_code == 502
    assert "private-provider-secret" not in failure.text
    assert not calls


def test_backend_only_plugin_is_visible_without_loading_a_browser_module(plugin_client):
    http, role, _, plugin = plugin_client
    registry = ExtensionRegistry()
    with registry.attributed_to("example"):
        registry.plugin(replace(plugin, frontend=None, fields=(), enabled=True))
    http.app.state.extensions = registry.build()
    role["value"] = "member"
    (item,) = http.get("/api/plugins").json()
    assert item["module"] is None and item["entry"] is None
    assert item["backend_actions"] == ["check"]
    assert item["settings"] == {"enabled": True}


def test_conflicting_manifest_cannot_half_register(plugin_client):
    _, _, _, plugin = plugin_client
    registry = ExtensionRegistry()
    with registry.attributed_to("example"):
        registry.plugin(plugin)
        mark = registry.mark()
        for invalid in (
            plugin,
            replace(plugin, namespace="community.other"),
            replace(plugin, namespace="community.invalid", frontend=None, backend=()),
            replace(plugin, namespace="community.invalid", fields=(SettingsField("enabled", "Override", "boolean", True),)),
        ):
            with pytest.raises(ValueError):
                registry.plugin(invalid)
            assert registry.mark() == mark
