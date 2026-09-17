"""Unit tests for the Tavily community search and fetch tools."""

import json
from unittest.mock import MagicMock, patch

import pytest
from tavily import TavilyClient

from deerflow.community.tavily.tools import web_fetch_tool, web_search_tool
from deerflow.config.tool_config import ToolConfig


@pytest.mark.parametrize(
    ("search_provider", "fetch_key", "expected_key"),
    [
        ("serper", "fetch-key", "fetch-key"),
        (None, "fetch-key", "fetch-key"),
        ("tavily", "fetch-key", "fetch-key"),
        ("serper", None, "env-key"),
        ("tavily", None, "env-key"),
        (None, None, "env-key"),
    ],
)
def test_web_fetch_uses_own_credentials(monkeypatch, search_provider, fetch_key, expected_key) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "env-key")
    fetch_config = ToolConfig(name="web_fetch", group="web", use="deerflow.community.tavily.tools:web_fetch_tool", **({"api_key": fetch_key} if fetch_key else {}))
    configs = {"web_fetch": fetch_config}
    if search_provider:
        configs["web_search"] = ToolConfig(name="web_search", group="web", use=f"deerflow.community.{search_provider}.tools:web_search_tool", api_key="search-key")

    with (
        patch("deerflow.community.tavily.tools.get_app_config") as mock_config,
        patch.object(TavilyClient, "extract", autospec=True, return_value={"results": []}) as extract,
    ):
        mock_config.return_value.get_tool_config.side_effect = configs.get
        web_fetch_tool.invoke({"url": "https://example.com/report"})

    client, urls = extract.call_args.args
    assert client.api_key == expected_key
    assert urls == ["https://example.com/report"]


@pytest.mark.parametrize("search_key", ["search-key", None])
def test_web_search_preserves_own_credentials(monkeypatch, search_key) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "env-key")
    configs = {
        "web_search": ToolConfig(name="web_search", group="web", use="deerflow.community.tavily.tools:web_search_tool", api_key=search_key),
        "web_fetch": ToolConfig(name="web_fetch", group="web", use="deerflow.community.tavily.tools:web_fetch_tool", api_key="fetch-key"),
    }
    with (
        patch("deerflow.community.tavily.tools.get_app_config") as mock_config,
        patch.object(TavilyClient, "search", autospec=True, return_value={"results": []}) as search,
    ):
        mock_config.return_value.get_tool_config.side_effect = configs.get
        web_search_tool.invoke({"query": "documentation"})

    client, query = search.call_args.args
    assert client.api_key == (search_key or "env-key")
    assert query == "documentation"


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


def test_web_search_forwards_time_range_to_tavily() -> None:
    client = MagicMock()
    client.search.return_value = _tavily_response()

    with patch("deerflow.community.tavily.tools.get_app_config") as mock_config:
        mock_config.return_value.get_tool_config.return_value = None
        with patch("deerflow.community.tavily.tools._get_tavily_client", return_value=client):
            result = web_search_tool.invoke({"query": "latest releases", "time_range": "month"})

    assert json.loads(result)[0]["title"] == "Release notes"
    client.search.assert_called_once_with("latest releases", max_results=5, time_range="month")


def test_web_search_omits_time_range_from_default_tavily_call() -> None:
    client = MagicMock()
    client.search.return_value = _tavily_response()

    with patch("deerflow.community.tavily.tools.get_app_config") as mock_config:
        mock_config.return_value.get_tool_config.return_value = None
        with patch("deerflow.community.tavily.tools._get_tavily_client", return_value=client):
            web_search_tool.invoke({"query": "stable documentation"})

    client.search.assert_called_once_with("stable documentation", max_results=5)


@pytest.mark.parametrize("title", [None, "", "Report title"])
def test_web_fetch_accepts_extract_results_with_optional_title(title) -> None:
    result = {"url": "https://example.com/report", "raw_content": "Important findings."}
    if title is not None:
        result["title"] = title
    client = MagicMock()
    client.extract.return_value = {"results": [result], "failed_results": []}

    with patch("deerflow.community.tavily.tools._get_tavily_client", return_value=client):
        output = web_fetch_tool.invoke({"url": "https://example.com/requested"})

    assert output == f"# {title or result['url']}\n\nImportant findings."
    client.extract.assert_called_once_with(["https://example.com/requested"])


def test_web_fetch_falls_back_to_requested_url_without_result_metadata() -> None:
    client = MagicMock()
    client.extract.return_value = {"results": [{"title": None, "url": None, "raw_content": "Important findings."}]}

    with patch("deerflow.community.tavily.tools._get_tavily_client", return_value=client):
        output = web_fetch_tool.invoke({"url": "https://example.com/requested"})

    assert output == "# https://example.com/requested\n\nImportant findings."


def test_web_fetch_preserves_content_limit_without_title() -> None:
    client = MagicMock()
    client.extract.return_value = {"results": [{"url": "https://example.com/report", "raw_content": "x" * 5000}]}

    with patch("deerflow.community.tavily.tools._get_tavily_client", return_value=client):
        output = web_fetch_tool.invoke({"url": "https://example.com/report"})

    assert output == "# https://example.com/report\n\n" + "x" * 4096


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ({"failed_results": [{"error": "Extraction failed"}]}, "Error: Extraction failed"),
        ({"results": [], "failed_results": []}, "Error: No results found"),
    ],
)
def test_web_fetch_preserves_unsuccessful_extract_results(response, expected) -> None:
    client = MagicMock()
    client.extract.return_value = response

    with patch("deerflow.community.tavily.tools._get_tavily_client", return_value=client):
        output = web_fetch_tool.invoke({"url": "https://example.com/report"})

    assert output == expected
