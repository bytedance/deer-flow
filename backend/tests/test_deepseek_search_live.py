"""Opt-in API checks. Set DEER_FLOW_RUN_LIVE_TESTS=1 and DEEPSEEK_API_KEY."""

import json
import os
from types import SimpleNamespace

import pytest

from deerflow.community.deepseek import tools as deepseek
from deerflow.config.pii_redaction_config import PiiRedactionConfig

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.getenv("DEER_FLOW_RUN_LIVE_TESTS") != "1", reason="Live DeepSeek requests are opt-in"),
    pytest.mark.skipif(not os.getenv("DEEPSEEK_API_KEY"), reason="DEEPSEEK_API_KEY is required"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("thinking", [False, True])
async def test_deepseek_search_api_returns_public_sources(monkeypatch, thinking):
    extras = {"thinking": thinking, "max_results": 2}
    monkeypatch.setattr(deepseek, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda name: SimpleNamespace(model_extra=extras), pii_redaction=PiiRedactionConfig()))
    result = json.loads(
        await deepseek.web_search_tool.ainvoke(
            {
                "query": "Search the official Python website for the Python 3.13.0 release date and provide its release page URL.",
            }
        )
    )
    assert "error" not in result
    assert 0 < result["total_results"] <= 2
    assert result["answer"]
    assert all(row["url"].startswith(("https://", "http://")) for row in result["results"])
