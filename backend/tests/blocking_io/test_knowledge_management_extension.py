"""Management performs SSL trust loading outside the Gateway event loop."""

import asyncio
import ssl
from pathlib import Path

import httpx
import pytest
from deerflow_extension_api.auth import ExtensionPrincipal


@pytest.mark.asyncio
async def test_management_http_client_setup_is_off_loop(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "examples/deerflow-extension-knowledge-management"))
    from deerflow_extension_knowledge_management.contracts import IngestRequest, ManagementContext
    from deerflow_extension_knowledge_management.weknora import WeKnoraManagement

    monkeypatch.setenv("MANAGEMENT_BLOCKING_KEY", "synthetic")
    provider = WeKnoraManagement(
        {"connections": [{"id": "test", "base_url": "https://weknora.invalid", "tenant_id": "1", "api_key_env": "MANAGEMENT_BLOCKING_KEY", "grants": [{"user_id": "alice", "knowledge_base_ids": ["kb"], "operations": ["manual"]}]}]}
    )

    async def send(self, request, **kwargs):
        data = {"id": "kb", "capabilities": {}} if request.method == "GET" else {"id": "doc", "knowledge_base_id": "kb", "parse_status": "pending", "enable_status": "enabled"}
        return httpx.Response(200, request=request, json={"success": True, "data": data})

    original = ssl.create_default_context

    def ssl_context(*args, **kwargs):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return original(*args, **kwargs)
        raise AssertionError("SSL trust loading must run off the event loop")

    monkeypatch.setattr(ssl, "create_default_context", ssl_context)
    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    result = await provider.ingest(ManagementContext(ExtensionPrincipal("alice", is_admin=True)), "test", "kb", IngestRequest(kind="manual", title="Guide", content="Evidence"))
    assert result.state == "queued"
