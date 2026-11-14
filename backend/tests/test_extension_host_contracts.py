"""Host/extension compatibility checks that core CI must own.

The bundled examples' own suites live behind the `bundled_extension` marker, so
an example regression cannot red an unrelated core PR. These checks are the
other side of that split: they assert what the host promises any extension
(API-version gates and the authorization gate on contributed routes), and they
belong to the core shards even when an example package is the payload.
"""

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from deerflow.extensions.loader import ExtensionSpec, load_extensions


@pytest.mark.parametrize("host_version", ["0.2.10", "0.2.11"])
def test_extension_requiring_a_newer_host_api_is_rejected(tmp_path, monkeypatch, host_version):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-agent-teams"))
    monkeypatch.setattr("deerflow.extensions.loader.API_VERSION", host_version)
    loaded, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_agent_teams:install", config={"enabled": True, "storage_path": str(tmp_path / "teams.sqlite")})])

    if host_version == "0.2.10":
        assert not loaded.plugins
        assert len(diagnostics) == 1
        assert "requires extension-api 0.2.11, host provides 0.2.10" in diagnostics[0].message
    else:
        assert not diagnostics
        assert len(loaded.plugins) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("root_path", ["", "/proxy"])
async def test_stale_browser_viewer_never_reaches_contributed_routes(monkeypatch, method, root_path):
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
