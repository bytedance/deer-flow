"""Webz configuration resolution must not run on the agent event loop."""

import json
import threading
from types import SimpleNamespace

import httpx
import pytest


@pytest.mark.asyncio
async def test_webz_configuration_runs_off_event_loop(monkeypatch):
    import deerflow.community.webz.tools as module

    loop_thread = threading.get_ident()
    config_threads = []

    def config():
        config_threads.append(threading.get_ident())
        return SimpleNamespace(get_tool_config=lambda _: SimpleNamespace(model_extra={"api_key": "synthetic-key"}))

    monkeypatch.setattr(module, "get_app_config", config)
    client_class = httpx.AsyncClient
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"results": []}))
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: client_class(transport=transport, **kwargs))
    result = json.loads(await module.web_search_tool.ainvoke({"query": "news"}))
    assert result["results"] == []
    assert config_threads and all(thread != loop_thread for thread in config_threads)
