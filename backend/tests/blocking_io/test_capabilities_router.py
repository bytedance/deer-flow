"""Capability discovery must offload manifest and integration storage reads."""

from types import SimpleNamespace

import pytest

from app.gateway.capabilities import AdapterContext, MCPAdapter
from app.gateway.routers import capabilities
from deerflow.config.extensions_config import ExtensionsConfig


@pytest.mark.asyncio
async def test_catalog_reads_files_off_loop():
    result = await capabilities.catalog()
    assert any(entry.id == "github" for entry in result)


@pytest.mark.asyncio
async def test_installation_discovery_reads_files_off_loop(tmp_path, monkeypatch):
    path = tmp_path / "extensions_config.json"
    import asyncio

    await asyncio.to_thread(path.write_text, '{"mcpServers":{"sample":{"enabled":false}},"skills":{}}')
    monkeypatch.setattr(ExtensionsConfig, "resolve_config_path", lambda *args: path)
    context = AdapterContext(SimpleNamespace(), SimpleNamespace(), "default")
    result = await MCPAdapter().list_installations(context)
    assert result[0].name == "sample"
