"""Real SQLite and policy serialization stay outside async HTTP execution."""

import asyncio
from pathlib import Path

import httpx
import pytest
from deerflow_extension_api.auth import ExtensionPrincipal
from fastapi import FastAPI


@pytest.mark.asyncio
async def test_platform_policy_and_effective_http_do_not_block(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[3]
    for package in ("knowledge-platform", "knowledge-management"):
        monkeypatch.syspath_prepend(str(root / "examples" / f"deerflow-extension-{package}"))
    from deerflow_extension_knowledge_platform.models import Settings, resource_key
    from deerflow_extension_knowledge_platform.router import build_router
    from deerflow_extension_knowledge_platform.service import Platform
    from deerflow_extension_knowledge_platform.store import Store

    settings = Settings.model_validate({"enabled": True, "storage_path": str(tmp_path / "platform.db"), "connections": [{"id": "test", "provider": "weknora", "resources": [{"base_id": "kb", "dataset_id": "wk1_synthetic"}]}]})
    store = await asyncio.to_thread(Store, settings)
    app = FastAPI()
    app.include_router(build_router(Platform(settings, store, {})))
    app.state.deerflow_extension_principal_resolver = lambda request: ExtensionPrincipal("admin", is_admin=True)

    async def authorize(request, namespace, scope):
        return True

    app.state.deerflow_extension_plugin_authz_resolver_async = authorize
    policy = {"spaces": {"root": {"title": "Synthetic", "resources": [resource_key("weknora", "test", "kb")], "members": {"admin": "manager"}}}}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.put("/api/extensions/knowledge-platform/policy", json={"revision": 0, "policy": policy})).status_code == 200
        assert (await client.get("/api/extensions/knowledge-platform/policy")).json()["revision"] == 1
        assert len((await client.get("/api/extensions/knowledge-platform/spaces")).json()["items"]) == 1
        assert (await client.get("/api/extensions/knowledge-platform/spaces/root")).json()["resources"][0]["dataset_id"] == "wk1_synthetic"
