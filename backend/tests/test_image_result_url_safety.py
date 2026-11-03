"""The image and text-search providers enforce the same string-only result URL policy."""

import importlib
import inspect
import json
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


@pytest.fixture(params=["url_safety", "brave.tools", "serper.tools", "infoquest.infoquest_client"])
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


def _sync(tool):
    return lambda: tool.invoke({"query": "q"})


def _async(tool):
    async def run():
        return await tool.ainvoke({"query": "q"})

    return run


def _stub_tavily(module, url):
    client = MagicMock()
    client.search = AsyncMock(return_value={"results": [{"title": "t", "url": url, "content": "c"}]})
    client.close = AsyncMock()
    return [patch.object(module, "_get_tavily_client", return_value=client)], _async(module.web_search_tool)


def _stub_exa(module, url):
    client = MagicMock()
    client.search.return_value = SimpleNamespace(results=[SimpleNamespace(title="t", url=url, highlights=["c"])])
    return [patch.object(module, "_get_exa_client", return_value=client)], _sync(module.web_search_tool)


def _stub_youcom(module, url):
    data = {"results": {"web": [{"title": "t", "url": url, "description": "c"}]}}
    return [patch.object(module, "_search", new=AsyncMock(return_value=data))], _async(module.web_search_tool)


def _stub_tencent_wsa(module, url):
    data = {"Response": {"Pages": [json.dumps({"title": "t", "url": url, "content": "c"})]}}
    return [patch.object(module, "_get_api_key", return_value="k"), patch.object(module, "_search", return_value=(data, None))], _sync(module.web_search_tool)


def _stub_serply(module, url):
    data = {"results": [{"title": "t", "link": url, "description": "c"}]}
    return [patch.object(module, "_get_api_key", return_value="k"), patch.object(module, "_serply_get", return_value=(data, None))], _sync(module.web_search_tool)


def _stub_groundroute(module, url):
    data = {"results": [{"title": "t", "url": url, "snippet": "c"}]}
    config = SimpleNamespace(get_tool_config=lambda _: SimpleNamespace(model_extra={"api_key": "synthetic-test-key"}))
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=data))
    real_client = httpx.AsyncClient
    return [
        patch.object(module, "get_app_config", return_value=config),
        patch.object(
            module,
            "httpx",
            SimpleNamespace(AsyncClient=lambda **kwargs: real_client(transport=transport, **kwargs), HTTPStatusError=httpx.HTTPStatusError),
        ),
    ], _async(module.web_search_tool)


def _stub_sofya(module, url):
    data = {"results": [{"title": "t", "url": url, "content": "c"}]}
    return [patch.object(module, "_get_api_key", return_value="k"), patch.object(module, "_sofya_post", return_value=(data, None))], _sync(module.web_search_tool)


def _stub_ddg_search(module, url):
    rows = [{"title": "t", "href": url, "body": "c"}]
    return [patch.object(module, "_search_text", return_value=rows)], _sync(module.web_search_tool)


def _sdk_search_result(url):
    return SimpleNamespace(web=[SimpleNamespace(title="t", url=url, description="c")])


def _stub_fastcrw(module, url):
    client = MagicMock()
    client.search.return_value = _sdk_search_result(url)
    return [patch.object(module, "_get_fastcrw_client", return_value=client)], _sync(module.web_search_tool)


def _stub_firecrawl(module, url):
    client = MagicMock()
    client.search = AsyncMock(return_value=_sdk_search_result(url))
    client.close = AsyncMock()
    return [patch.object(module, "_get_firecrawl_client", return_value=client)], _async(module.web_search_tool)


def _stub_searxng(module, url):
    client = MagicMock()
    client.search = AsyncMock(return_value=[{"title": "t", "url": url, "content": "c"}])
    return [patch.object(module, "_get_searxng_client", return_value=client)], _async(module.web_search_tool)


def _stub_brave(module, url):
    data = {"web": {"results": [{"title": "t", "url": url, "description": "c"}]}}
    return [patch.object(module, "_get_api_key", return_value="k"), patch.object(module, "_brave_get", return_value=(data, None))], _sync(module.web_search_tool)


def _stub_serper(module, url):
    data = {"organic": [{"title": "t", "link": url, "snippet": "c"}]}
    return [patch.object(module, "_get_api_key", return_value="k"), patch.object(module, "_serper_post", return_value=(data, None))], _sync(module.web_search_tool)


def _stub_webz(module, url):
    data = {"results": [{"article": {"title": "t", "url": url, "summary": "c", "published_at": ""}}]}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=data))
    real_client = httpx.AsyncClient
    return [
        patch.object(module, "_options", return_value={"api_key": "k"}),
        patch.object(module.httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs)),
    ], _async(module.web_search_tool)


_TEXT_SEARCH_STUBS = {
    "tavily": _stub_tavily,
    "exa": _stub_exa,
    "youcom": _stub_youcom,
    "tencent_wsa": _stub_tencent_wsa,
    "serply": _stub_serply,
    "groundroute": _stub_groundroute,
    "sofya": _stub_sofya,
    "ddg_search": _stub_ddg_search,
    "fastcrw": _stub_fastcrw,
    "firecrawl": _stub_firecrawl,
    "searxng": _stub_searxng,
    "brave": _stub_brave,
    "serper": _stub_serper,
    "webz": _stub_webz,
}


@pytest.mark.anyio
@pytest.mark.parametrize("provider", sorted(_TEXT_SEARCH_STUBS))
@pytest.mark.parametrize(
    ("url", "expected"),
    [(_METADATA_URL, ""), ("http://127.0.0.1:8080/admin", ""), (_PUBLIC_URL, _PUBLIC_URL)],
)
async def test_text_search_providers_screen_result_urls(provider, url, expected):
    """web_search must not hand a non-public provider URL to the model (#7036).

    Only the provider payload varies; the title and snippet stay in the row.
    """
    module = importlib.import_module(f"deerflow.community.{provider}.tools")
    patches, run = _TEXT_SEARCH_STUBS[provider](module, url)
    with ExitStack() as stack:
        config = stack.enter_context(patch.object(module, "get_app_config"))
        config.return_value.get_tool_config.return_value = None
        for p in patches:
            stack.enter_context(p)
        raw = run()
        if inspect.isawaitable(raw):
            raw = await raw
    payload = json.loads(raw)
    # Some providers return a bare list, others a {"results": [...]} envelope.
    rows = payload["results"] if isinstance(payload, dict) else payload
    assert [row["url"] for row in rows] == [expected]
    assert rows[0]["title"] == "t"
    # The snippet key differs by provider ("content" or "snippet").
    assert "c" in (rows[0].get("content"), rows[0].get("snippet"))


@pytest.mark.parametrize(("url", "expected"), [(_METADATA_URL, ""), (_PUBLIC_URL, _PUBLIC_URL)])
def test_serply_scholar_screens_pdf_url(url, expected):
    from deerflow.community.serply.tools import _normalize_row

    row = _normalize_row("scholar", {"title": "t", "link": url, "doc": {"link": url}})
    assert (row["url"], row["pdf_url"]) == (expected, expected)
