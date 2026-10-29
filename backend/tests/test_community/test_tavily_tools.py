"""Unit tests for the Tavily community search and fetch tools."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool
from tavily import AsyncTavilyClient

from deerflow.community.tavily.tools import web_fetch_tool, web_search_tool
from deerflow.config.tool_config import ToolConfig


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["search", "extract"])
@pytest.mark.parametrize("outcome", ["success", "error", "cancelled"])
async def test_tool_closes_sdk_client_on_every_request_outcome(monkeypatch, operation, outcome) -> None:
    client = AsyncTavilyClient(api_key="test-key")
    request = AsyncMock(return_value={"results": []})
    if outcome == "error":
        request.side_effect = RuntimeError("request failed")
    elif outcome == "cancelled":
        request.side_effect = asyncio.CancelledError()
    monkeypatch.setattr(client, operation, request)
    tool = web_search_tool if operation == "search" else web_fetch_tool
    arguments = {"query": "documentation"} if operation == "search" else {"url": "https://example.com/report"}
    try:
        with (
            patch("deerflow.community.tavily.tools._get_tavily_client", return_value=client),
            patch("deerflow.community.tavily.tools.get_app_config") as config,
        ):
            config.return_value.get_tool_config.return_value = None
            if outcome == "success":
                await tool.ainvoke(arguments)
            else:
                with pytest.raises(RuntimeError if outcome == "error" else asyncio.CancelledError):
                    await tool.ainvoke(arguments)
        assert client._client.is_closed
    finally:
        await client.close()


@pytest.mark.parametrize(
    ("search_provider", "fetch_key"),
    [
        ("serper", "fetch-key"),
        (None, "fetch-key"),
        ("tavily", "fetch-key"),
        ("serper", None),
        ("tavily", None),
        (None, None),
    ],
)
@pytest.mark.anyio
async def test_web_fetch_uses_own_credentials(monkeypatch, search_provider, fetch_key) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "env-key")
    fetch_config = ToolConfig(name="web_fetch", group="web", use="deerflow.community.tavily.tools:web_fetch_tool", **({"api_key": fetch_key} if fetch_key else {}))
    configs = {"web_fetch": fetch_config}
    if search_provider:
        configs["web_search"] = ToolConfig(name="web_search", group="web", use=f"deerflow.community.{search_provider}.tools:web_search_tool", api_key="search-key")

    with (
        patch("deerflow.community.tavily.tools.get_app_config") as mock_config,
        patch("deerflow.community.tavily.tools.AsyncTavilyClient", autospec=True) as mock_client_cls,
    ):
        mock_client_cls.return_value.extract = AsyncMock(return_value={"results": []})
        mock_config.return_value.get_tool_config.side_effect = configs.get
        await web_fetch_tool.ainvoke({"url": "https://example.com/report"})

    # web_fetch 用自己的 api_key 构造 client；配置缺省时传 None，交由 SDK 读取环境变量
    mock_client_cls.assert_called_once_with(api_key=fetch_key)
    mock_client_cls.return_value.extract.assert_called_once_with(["https://example.com/report"])


@pytest.mark.parametrize("search_key", ["search-key", None])
@pytest.mark.anyio
async def test_web_search_preserves_own_credentials(monkeypatch, search_key) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "env-key")
    configs = {
        "web_search": ToolConfig(name="web_search", group="web", use="deerflow.community.tavily.tools:web_search_tool", api_key=search_key),
        "web_fetch": ToolConfig(name="web_fetch", group="web", use="deerflow.community.tavily.tools:web_fetch_tool", api_key="fetch-key"),
    }
    with (
        patch("deerflow.community.tavily.tools.get_app_config") as mock_config,
        patch("deerflow.community.tavily.tools.AsyncTavilyClient", autospec=True) as mock_client_cls,
    ):
        mock_client_cls.return_value.search = AsyncMock(return_value={"results": []})
        mock_config.return_value.get_tool_config.side_effect = configs.get
        await web_search_tool.ainvoke({"query": "documentation"})

    # web_search 用自己的 api_key（search_key）构造 client，而不是 web_fetch 的 fetch-key
    mock_client_cls.assert_called_once_with(api_key=search_key)
    mock_client_cls.return_value.search.assert_called_once_with("documentation", max_results=5)


def _tavily_response() -> dict:
    return {
        "results": [
            {
                "title": "Release notes",
                "url": "https://example.com/releases",
                "content": "A recent release.",
            }
        ]
    }


@pytest.mark.anyio
async def test_web_search_forwards_time_range_to_tavily() -> None:
    client = MagicMock(spec=AsyncTavilyClient)
    client.search = AsyncMock(return_value=_tavily_response())

    with patch("deerflow.community.tavily.tools.get_app_config") as mock_config:
        mock_config.return_value.get_tool_config.return_value = None
        with patch("deerflow.community.tavily.tools._get_tavily_client", return_value=client):
            result = await web_search_tool.ainvoke({"query": "latest releases", "time_range": "month"})

    assert json.loads(result)[0]["title"] == "Release notes"
    client.search.assert_called_once_with("latest releases", max_results=5, time_range="month")


@pytest.mark.anyio
async def test_web_search_omits_time_range_from_default_tavily_call() -> None:
    client = MagicMock(spec=AsyncTavilyClient)
    client.search = AsyncMock(return_value=_tavily_response())

    with patch("deerflow.community.tavily.tools.get_app_config") as mock_config:
        mock_config.return_value.get_tool_config.return_value = None
        with patch("deerflow.community.tavily.tools._get_tavily_client", return_value=client):
            await web_search_tool.ainvoke({"query": "stable documentation"})

    client.search.assert_called_once_with("stable documentation", max_results=5)


@pytest.mark.parametrize("time_range", [None, "week"])
@pytest.mark.parametrize(
    "domain_config",
    [
        pytest.param({}, id="omitted"),
        pytest.param({"include_domains": ["docs.example.com", "reference.example.org"], "exclude_domains": ["archive.example.com"]}, id="both"),
        pytest.param({"include_domains": ["docs.example.com"]}, id="include-only"),
        pytest.param({"exclude_domains": ["archive.example.com"]}, id="exclude-only"),
        pytest.param({"include_domains": [], "exclude_domains": []}, id="empty-both"),
        pytest.param({"include_domains": []}, id="empty-include"),
        pytest.param({"exclude_domains": []}, id="empty-exclude"),
    ],
)
@pytest.mark.anyio
async def test_web_search_forwards_configured_domains(domain_config, time_range) -> None:
    configs = {
        "web_search": ToolConfig(name="web_search", group="web", use="deerflow.community.tavily.tools:web_search_tool", api_key="search-key", max_results=3, **domain_config),
        "web_fetch": ToolConfig(name="web_fetch", group="web", use="deerflow.community.tavily.tools:web_fetch_tool", include_domains=["fetch.example.com"], exclude_domains=["other.example.org"]),
    }
    tool_args = {"query": "documentation"}
    expected_kwargs = {"max_results": 3, **domain_config}
    if domain_config.get("include_domains"):
        expected_kwargs["include_domains_mode"] = "filter"
    if time_range is not None:
        tool_args["time_range"] = time_range
        expected_kwargs["time_range"] = time_range

    with (
        patch("deerflow.community.tavily.tools.get_app_config") as mock_config,
        patch.object(AsyncTavilyClient, "search", autospec=True, return_value=_tavily_response()) as search,
    ):
        mock_config.return_value.get_tool_config.side_effect = configs.get
        result = await web_search_tool.ainvoke(tool_args)

    client = search.call_args.args[0]
    search.assert_called_once_with(client, "documentation", **expected_kwargs)
    assert json.loads(result) == [{"title": "Release notes", "url": "https://example.com/releases", "snippet": "A recent release."}]


def test_web_search_keeps_domain_filters_out_of_model_schema() -> None:
    parameters = convert_to_openai_tool(web_search_tool)["function"]["parameters"]

    assert set(parameters["properties"]) == {"query", "time_range"}
    assert parameters["required"] == ["query"]


@pytest.mark.parametrize("title", [None, "", "Report title"])
@pytest.mark.anyio
async def test_web_fetch_accepts_extract_results_with_optional_title(title) -> None:
    result = {"url": "https://example.com/report", "raw_content": "Important findings."}
    if title is not None:
        result["title"] = title
    client = MagicMock(spec=AsyncTavilyClient)
    client.extract = AsyncMock(return_value={"results": [result], "failed_results": []})

    with patch("deerflow.community.tavily.tools._get_tavily_client", return_value=client):
        output = await web_fetch_tool.ainvoke({"url": "https://example.com/requested"})

    assert output == f"# {title or result['url']}\n\nImportant findings."
    client.extract.assert_called_once_with(["https://example.com/requested"])


@pytest.mark.anyio
async def test_web_fetch_falls_back_to_requested_url_without_result_metadata() -> None:
    client = MagicMock(spec=AsyncTavilyClient)
    client.extract = AsyncMock(return_value={"results": [{"title": None, "url": None, "raw_content": "Important findings."}]})

    with patch("deerflow.community.tavily.tools._get_tavily_client", return_value=client):
        output = await web_fetch_tool.ainvoke({"url": "https://example.com/requested"})

    assert output == "# https://example.com/requested\n\nImportant findings."


@pytest.mark.anyio
async def test_web_fetch_preserves_content_limit_without_title() -> None:
    client = MagicMock(spec=AsyncTavilyClient)
    client.extract = AsyncMock(return_value={"results": [{"url": "https://example.com/report", "raw_content": "x" * 5000}]})

    with patch("deerflow.community.tavily.tools._get_tavily_client", return_value=client):
        output = await web_fetch_tool.ainvoke({"url": "https://example.com/report"})

    assert output == "# https://example.com/report\n\n" + "x" * 4096


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ({"failed_results": [{"error": "Extraction failed"}]}, "Error: Extraction failed"),
        ({"results": [], "failed_results": []}, "Error: No results found"),
    ],
)
@pytest.mark.anyio
async def test_web_fetch_preserves_unsuccessful_extract_results(response, expected) -> None:
    client = MagicMock(spec=AsyncTavilyClient)
    client.extract = AsyncMock(return_value=response)

    with patch("deerflow.community.tavily.tools._get_tavily_client", return_value=client):
        output = await web_fetch_tool.ainvoke({"url": "https://example.com/report"})

    assert output == expected
