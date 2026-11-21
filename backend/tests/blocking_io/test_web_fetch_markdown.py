"""Keep HTML-to-Markdown conversion off the web fetch event loop."""

import threading
from unittest.mock import AsyncMock, Mock

import pytest

from deerflow.community.browserless import tools as browserless
from deerflow.community.browserless.browserless_client import BrowserlessFetchResult
from deerflow.community.infoquest import tools as infoquest
from deerflow.community.jina_ai import tools as jina
from deerflow.utils import readability


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", [jina, infoquest, browserless], ids=["jina", "infoquest", "browserless"])
async def test_web_fetch_renders_markdown_off_loop(provider, monkeypatch):
    html = "<html><body><article><p>Example article text</p></article></body></html>"
    loop_thread = threading.get_ident()
    render_threads = []
    render = readability.Article.to_markdown

    def record_render(article):
        render_threads.append(threading.get_ident())
        return render(article)

    monkeypatch.setattr(readability.Article, "to_markdown", record_render)
    monkeypatch.setattr(readability, "_readability_js_available", lambda: False)

    if provider is jina:
        monkeypatch.setattr(jina, "get_app_config", lambda: Mock(get_tool_config=Mock(return_value=None)))
        monkeypatch.setattr(jina.JinaClient, "crawl", AsyncMock(return_value=html))
    elif provider is infoquest:
        client = Mock(fetch=AsyncMock(return_value=html))
        monkeypatch.setattr(infoquest, "_get_infoquest_client", lambda: client)
    else:
        response = BrowserlessFetchResult(html=html, target_status_code="200", target_status="OK")
        client = Mock(fetch_html_with_status=AsyncMock(return_value=response))
        monkeypatch.setattr(browserless, "_get_tool_config", lambda *_: {})
        monkeypatch.setattr(browserless, "_get_browserless_client", lambda *_: client)
        monkeypatch.setattr(browserless, "validate_public_http_url", lambda *_, **__: None)
        monkeypatch.setattr(browserless, "_validate_backend_base_url", lambda *_: None)

    result = await provider.web_fetch_tool.ainvoke({"url": "https://example.com"})
    assert "Example article text" in result
    assert len(render_threads) == 1
    assert render_threads[0] != loop_thread
