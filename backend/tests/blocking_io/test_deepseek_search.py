"""Keep DeepSeek provider config reads and HTTPX TLS setup off the loop."""

import importlib
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from deerflow.config.pii_redaction_config import PiiRedactionConfig


@pytest.fixture
def provider(monkeypatch):
    module = importlib.import_module("deerflow.community.deepseek.tools")
    threads = []

    def config():
        threads.append(threading.get_ident())
        Path(__file__).read_text(encoding="utf-8")
        return SimpleNamespace(get_tool_config=lambda _name: SimpleNamespace(model_extra={"api_key": "test-key"}), pii_redaction=PiiRedactionConfig())

    def respond(request):
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "", "server_tool_calls": []}}]})

    def client(**kwargs):
        threads.append(threading.get_ident())
        Path(__file__).read_text(encoding="utf-8")
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    private_httpx = SimpleNamespace(**vars(httpx))
    private_httpx.AsyncClient = client
    monkeypatch.setattr(module, "get_app_config", config)
    monkeypatch.setattr(module, "httpx", private_httpx)
    return module.web_search_tool, threads


@pytest.mark.asyncio
async def test_deepseek_search_initializes_off_loop(provider):
    tool, threads = provider
    result = json.loads(await tool.ainvoke({"query": "test"}))
    assert result["error"] == "No results found"
    assert len(threads) == 2
    assert all(thread != threading.get_ident() for thread in threads)
