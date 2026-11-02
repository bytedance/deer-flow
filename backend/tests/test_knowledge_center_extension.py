"""The optional page must ship real assets without installing a second backend."""

from pathlib import Path

import pytest

from deerflow.extensions.loader import ExtensionSpec, load_extensions


@pytest.fixture
def load_center(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-knowledge-center"))

    def load(config):
        return load_extensions([ExtensionSpec(use="deerflow_extension_knowledge_center:install", config=config)])

    return load


@pytest.mark.parametrize("enabled", [False, True])
def test_optional_center_has_packaged_page_and_no_management_backend(load_center, enabled):
    loaded, diagnostics = load_center({"enabled": enabled})
    assert not diagnostics
    ((_, plugin),) = loaded.plugins
    assert plugin.namespace == "knowledge-center"
    assert plugin.enabled is enabled
    assert not plugin.backend and not plugin.tools and not loaded.routers
    assets = plugin.frontend
    assert assets.entry == "static/index.mjs"
    assert set(assets.files) == {"static/index.mjs", "static/center.mjs", "static/styles.css", "static/copy.mjs", "static/library.mjs", "static/library-copy.mjs", "static/graph.mjs"}
    assert b"requestBackend" in assets.files["static/center.mjs"].content


@pytest.mark.parametrize("config", [{"enabled": "true"}, {"endpoint": "https://example.invalid"}, {"enabled": True, "token": "secret"}])
def test_page_config_cannot_introduce_credentials_or_provider_configuration(load_center, config):
    loaded, diagnostics = load_center(config)
    assert not loaded.plugins
    assert diagnostics


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("root_path", ["", "/proxy"])
async def test_stale_browser_viewer_never_reaches_contributed_routes(monkeypatch, method, root_path):
    from types import SimpleNamespace

    import httpx
    from fastapi import FastAPI

    from app.gateway.auth_middleware import AuthMiddleware

    async def user(request):
        return SimpleNamespace(id="bob", system_role="admin")

    async def permissions(*args, **kwargs):
        return []

    monkeypatch.setattr("app.gateway.auth_middleware.is_auth_disabled", lambda: False)
    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", user)
    monkeypatch.setattr("app.gateway.auth_middleware.resolve_route_permissions", permissions)
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    calls = []

    @app.api_route("/api/extensions/example/documents", methods=["GET", "POST"])
    async def contributed():
        calls.append("provider")
        return {"ok": True}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, root_path=root_path), base_url="http://test", cookies={"access_token": "session-b"}) as client:
        path = root_path + "/api/extensions/example/documents"
        stale = await client.request(method, path, headers={"X-Deerflow-Plugin-Viewer": "alice"})
        assert stale.status_code == 409
        assert calls == []
        for header in ({"X-Deerflow-Plugin-Viewer": "bob"}, {}):
            assert (await client.request(method, path, headers=header)).status_code == 200
        assert calls == ["provider", "provider"]
