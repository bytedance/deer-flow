"""The image providers enforce the same string-only result URL policy."""

import importlib
from unittest.mock import patch

import pytest


@pytest.fixture(params=["url_safety", "brave.tools", "serper.tools"])
def screen(request):
    module = importlib.import_module(f"deerflow.community.{request.param}")
    return module.safe_public_result_url if request.param == "url_safety" else module._safe_public_url


@pytest.mark.parametrize(
    "url",
    [
        "http://metadata.google.internal/image",
        "http://[64:ff9b::7f00:1]/image",
        "http://[::ffff:127.0.0.1]/image",
        "http://[2002:7f00:1::]/image",
        "http://[::10.0.0.1]/image",
        "http://224.0.0.1/image",
        "http://3758096385/image",
        "http://[ff02::1]/image",
        "http://[2002:e000:1::]/image",
        "http://240.0.0.1/image",
        "http://127.0.0.1/image",
        "http://0x7f000001/image",
        "http://0177.0.0.1/image",
        "http://localhost./image",
        "file:///etc/passwd",
    ],
)
def test_image_providers_reject_non_public_results(screen, url):
    assert screen(url) == ""


@pytest.mark.parametrize(
    "url",
    ["https://images.example/image", "http://8.8.8.8/image", "http://134744072/image", "http://[2606:4700:4700::1111]/image"],
)
def test_image_providers_keep_public_results_without_dns(screen, url):
    with patch("socket.getaddrinfo", side_effect=AssertionError("Result screening must not perform DNS")):
        assert screen(url) == url


_METADATA_URL = "http://169.254.169.254/latest/meta-data/"
_PUBLIC_URL = "https://example.com/report"


@pytest.mark.anyio
@pytest.mark.parametrize("provider", ["tavily", "exa"])
@pytest.mark.parametrize(
    ("url", "expected"),
    [(_METADATA_URL, ""), (_PUBLIC_URL, _PUBLIC_URL)],
)
async def test_text_search_providers_screen_result_urls(provider, url, expected):
    """tavily and exa must not hand non-public provider URLs to the model (#7036)."""
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    module = importlib.import_module(f"deerflow.community.{provider}.tools")
    with patch.object(module, "get_app_config") as config:
        config.return_value.get_tool_config.return_value = None
        if provider == "tavily":
            client = MagicMock()
            client.search = AsyncMock(return_value={"results": [{"title": "t", "url": url, "content": "c"}]})
            client.close = AsyncMock()
            with patch.object(module, "_get_tavily_client", return_value=client):
                raw = await module.web_search_tool.ainvoke({"query": "q"})
        else:
            result = SimpleNamespace(title="t", url=url, highlights=["c"])
            client = MagicMock()
            client.search.return_value = SimpleNamespace(results=[result])
            with patch.object(module, "_get_exa_client", return_value=client):
                raw = module.web_search_tool.invoke({"query": "q"})
    assert [row["url"] for row in json.loads(raw)] == [expected]
