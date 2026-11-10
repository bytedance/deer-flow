"""Library Providers construct real SSL clients outside the Gateway loop."""

import asyncio
import ssl
from pathlib import Path

import httpx
import pytest
from deerflow_extension_api.auth import ExtensionPrincipal


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ["weknora", "lightrag"])
async def test_library_http_client_setup_is_off_loop(monkeypatch, engine):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "examples/deerflow-extension-knowledge-management"))
    from deerflow_extension_knowledge_management.contracts import ManagementContext
    from deerflow_extension_knowledge_management.library import LibraryQuery
    from deerflow_extension_knowledge_management.lightrag import LightRAGLibrary
    from deerflow_extension_knowledge_management.weknora import WeKnoraManagement

    monkeypatch.setenv("LIBRARY_BLOCKING_KEY", "synthetic")
    operation = "documents" if engine == "weknora" else "graph"
    base = "kb" if engine == "weknora" else "workspace"
    conn = {"id": "test", "base_url": "https://library.invalid", "api_key_env": "LIBRARY_BLOCKING_KEY", "grants": [{"user_id": "alice", "knowledge_base_ids": [base], "operations": [operation]}]}
    if engine == "weknora":
        conn["tenant_id"] = "1"
    provider = (WeKnoraManagement if engine == "weknora" else LightRAGLibrary)({"connections": [conn]})

    async def send(self, request, **kwargs):
        if request.url.path.endswith("/knowledge-bases/kb"):
            payload = {"success": True, "data": {"id": "kb", "capabilities": {}}}
        elif engine == "weknora":
            payload = {"success": True, "data": [], "total": 0}
        else:
            payload = {"status": "success", "data": {"entities": [], "relationships": [], "chunks": []}}
        return httpx.Response(200, request=request, json=payload)

    original = ssl.create_default_context

    def ssl_context(*args, **kwargs):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return original(*args, **kwargs)
        raise AssertionError("SSL trust loading must run off the event loop")

    monkeypatch.setattr(ssl, "create_default_context", ssl_context)
    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    result = await provider.library(ManagementContext(ExtensionPrincipal("alice", is_admin=True)), "test", base, operation, LibraryQuery(search="Cedar"))
    assert result.provider == engine
