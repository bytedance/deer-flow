"""Keep the Run budget compatible with Jina completion diagnostics."""

import logging

import httpx
import pytest

from deerflow.community.jina_ai import jina_client as jina
from deerflow.community.web_attempt_budget import _Counter


@pytest.mark.asyncio
@pytest.mark.parametrize("stream_limit", [None, 100])
@pytest.mark.parametrize("redirect", [False, True])
async def test_budget_denial_keeps_summary_and_blocks_transport(monkeypatch, caplog, stream_limit, redirect):
    original = httpx.AsyncClient
    sent = []

    def respond(request):
        sent.append(request)
        return httpx.Response(307, headers={"Location": "https://r.jina.ai/final"})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    monkeypatch.setenv("JINA_API_KEY", "sentinel-key")
    caplog.set_level(logging.DEBUG, logger=jina.__name__)
    counter = _Counter(1 if redirect else 0)
    result = await jina.JinaClient().crawl("https://sentinel-url.invalid", trust_env=False, max_response_bytes=stream_limit, attempt_budget=counter)
    assert result.endswith("(web_attempt_budget_exhausted)")
    assert len(sent) == int(redirect)
    assert counter.used == int(redirect)
    summaries = [r.getMessage() for r in caplog.records if r.name == jina.__name__ and r.getMessage().startswith("Jina crawl completed ")]
    assert len(summaries) == 1
    # Existing diagnostics count HTTPX API calls, not dispatched redirect hops.
    assert "outcome=error reason=web_attempt_budget_exhausted attempts=1" in summaries[0]
    assert "sentinel" not in summaries[0]
