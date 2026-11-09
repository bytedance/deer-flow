"""DDG config, pacing and SDK calls stay off the event loop."""

import json
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from ddgs.exceptions import DDGSException

from deerflow.community.ddg_search import tools


@pytest.mark.asyncio
async def test_async_ddg_pacing_and_retry_run_in_worker(monkeypatch):
    loop_thread = threading.get_ident()
    calls = []

    def worker_only(*args, **kwargs):
        assert threading.get_ident() != loop_thread
        time.sleep(0)  # Blockbuster rejects this if accidentally run on the loop.

    def text(*args, **kwargs):
        worker_only()
        calls.append(1)
        if len(calls) == 1:
            raise DDGSException("HTTP 202 CAPTCHA")
        return []

    def config():
        worker_only()
        return SimpleNamespace(get_tool_config=lambda name: SimpleNamespace(model_extra={"min_interval_seconds": 4, "max_retries": 1}))

    monkeypatch.setattr(tools, "get_app_config", config)
    monkeypatch.setattr(tools, "sleep", worker_only)
    monkeypatch.setattr(tools, "_last_call", None)
    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=lambda **kw: SimpleNamespace(text=text)))
    result = json.loads(await tools.web_search_tool.ainvoke({"query": "news"}))
    assert result["error"] == "No results found"
    assert len(calls) == 2
