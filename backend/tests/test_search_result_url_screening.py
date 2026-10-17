"""Every bundled web_search provider must screen result URLs through the shared owner.

#6740 made `community/url_safety.py::safe_public_result_url` the single owner for
result-URL screening; each case below feeds the provider a link-local metadata URL
through its own (stubbed) client seam and asserts the model-visible JSON never
carries it. The stubs replace only the HTTP/SDK boundary; the normalization code
under test runs for real.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

LEAK = "http://169.254.169.254/latest/meta-data/"


def _assert_screened(result: str) -> None:
    parsed = json.loads(result)
    rows = parsed.get("results") if isinstance(parsed, dict) else parsed
    assert isinstance(rows, list), parsed
    assert LEAK not in result
    urls = [row.get("url") for row in rows if isinstance(row, dict)]
    assert urls and all(u == "" for u in urls)


def test_exa_screens_result_urls():
    from deerflow.community.exa import tools

    client = MagicMock()
    client.search.return_value = SimpleNamespace(results=[SimpleNamespace(title="t", url=LEAK, highlights=["h"])])
    with (
        patch.object(tools, "_get_exa_client", return_value=client),
        patch.object(tools, "get_app_config", return_value=_mock_app_config()),
    ):
        _assert_screened(tools.web_search_tool.invoke({"query": "q"}))


def test_tavily_screens_result_urls():
    from deerflow.community.tavily import tools

    client = MagicMock()
    client.search = _async_return({"results": [{"title": "t", "url": LEAK, "content": "c"}]})
    client.close = _async_return(None)
    with (
        patch.object(tools, "_get_tavily_client", return_value=client),
        patch.object(tools, "get_app_config", return_value=_mock_app_config()),
    ):
        result = _run(tools.web_search_tool.ainvoke({"query": "q"}))
    _assert_screened(result)


def test_youcom_screens_result_urls():
    from deerflow.community.youcom import tools

    payload = {"results": {"web": [{"title": "t", "url": LEAK, "snippets": ["s"]}]}}
    with (
        patch.object(tools, "get_app_config", return_value=_mock_app_config()),
        patch.object(tools, "_get_api_key", return_value=None),
        patch.object(tools, "_search", return_value=payload),
    ):
        _assert_screened(tools.web_search_tool.invoke({"query": "q"}))


def test_tencent_wsa_screens_result_urls():
    from deerflow.community.tencent_wsa import tools

    page = {"title": "t", "url": LEAK, "content": "c"}
    with (
        patch.object(tools, "_get_api_key", return_value="test"),
        patch.object(tools, "_get_tool_extras", return_value={}),
        patch.object(tools, "get_app_config", return_value=_mock_app_config()),
        patch.object(tools, "_search", return_value=({"Response": {"Pages": [page]}}, None)),
    ):
        _assert_screened(tools.web_search_tool.invoke({"query": "q"}))


def test_serply_screens_result_urls():
    from deerflow.community.serply import tools

    payload = {"results": [{"title": "t", "link": LEAK, "description": "d"}]}
    with (
        patch.object(tools, "_get_api_key", return_value="test"),
        patch.object(tools, "_serply_get", return_value=(payload, None)),
        patch.object(tools, "get_app_config", return_value=_mock_app_config()),
    ):
        _assert_screened(tools.web_search_tool.invoke({"query": "q"}))


def test_groundroute_screens_result_urls():
    from deerflow.community.groundroute import tools

    payload = {"results": [{"title": "t", "url": LEAK, "snippet": "s", "source_engine": "g"}]}
    with (
        patch.object(tools, "get_app_config", return_value=_mock_app_config()),
        patch.object(tools, "_get_api_key", return_value="test"),
        patch.object(tools, "_post_search", return_value=payload),
    ):
        _assert_screened(tools.web_search_tool.invoke({"query": "q"}))


def test_sofya_screens_result_urls():
    from deerflow.community.sofya import tools

    payload = {"results": [{"title": "t", "url": LEAK, "content": "c"}]}
    with (
        patch.object(tools, "_get_api_key", return_value="test"),
        patch.object(tools, "_sofya_post", return_value=(payload, None)),
        patch.object(tools, "get_app_config", return_value=_mock_app_config()),
    ):
        _assert_screened(tools.web_search_tool.invoke({"query": "q"}))


def test_ddg_search_screens_result_urls():
    from deerflow.community.ddg_search import tools

    app_config = MagicMock()
    app_config.get_tool_config.return_value = None
    with (
        patch.object(tools, "get_app_config", return_value=app_config),
        patch.object(tools, "_search_text", return_value=[{"title": "t", "href": LEAK, "body": "b"}]),
    ):
        _assert_screened(tools.web_search_tool.invoke({"query": "q"}))


def test_fastcrw_screens_result_urls():
    from deerflow.community.fastcrw import tools

    client = MagicMock()
    client.search.return_value = SimpleNamespace(web=[SimpleNamespace(title="t", url=LEAK, description="d")])
    with (
        patch.object(tools, "_get_fastcrw_client", return_value=client),
        patch.object(tools, "get_app_config", return_value=_mock_app_config()),
    ):
        _assert_screened(tools.web_search_tool.invoke({"query": "q"}))


def test_firecrawl_screens_result_urls():
    from deerflow.community.firecrawl import tools

    client = MagicMock()
    client.search = _async_return(SimpleNamespace(web=[SimpleNamespace(title="t", url=LEAK, description="d")]))
    app_config = MagicMock()
    app_config.get_tool_config.return_value = None
    with (
        patch.object(tools, "_get_firecrawl_client", return_value=client),
        patch.object(tools, "get_app_config", return_value=app_config),
        patch.object(tools, "_aclose_firecrawl_client", new=_async_return(None)),
    ):
        result = _run(tools.web_search_tool.ainvoke({"query": "q"}))
    _assert_screened(result)


def test_searxng_screens_result_urls():
    from deerflow.community.searxng import tools

    client = MagicMock()
    client.search = _async_return([{"title": "t", "url": LEAK, "content": "c"}])
    with (
        patch.object(tools, "_get_searxng_client", return_value=client),
        patch.object(tools, "_get_tool_config", return_value=None),
    ):
        result = _run(tools.web_search_tool.ainvoke({"query": "q"}))
    _assert_screened(result)


def _mock_app_config():
    app_config = MagicMock()
    app_config.get_tool_config.return_value = None
    return app_config


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


def _run(coro):
    import asyncio

    return asyncio.run(coro)
