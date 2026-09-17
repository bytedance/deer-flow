"""Unit tests for the Tavily community search and fetch tools."""

import json
from unittest.mock import MagicMock, patch

import pytest

from deerflow.community.tavily.tools import web_fetch_tool, web_search_tool


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


def _config_with_tool_keys() -> MagicMock:
    """App config where web_search and web_fetch carry different api keys."""
    configs = {
        "web_search": MagicMock(model_extra={"api_key": "search-key"}),
        "web_fetch": MagicMock(model_extra={"api_key": "fetch-key"}),
    }
    app_config = MagicMock()
    app_config.get_tool_config.side_effect = lambda name: configs.get(name)
    return app_config


def test_web_fetch_reads_its_own_api_key() -> None:
    """web_fetch must use the web_fetch key, not web_search's (#5495)."""
    extract_result = {"results": [{"url": "https://example.com/r", "raw_content": "x"}], "failed_results": []}
    with patch("deerflow.community.tavily.tools.get_app_config", return_value=_config_with_tool_keys()):
        with patch("deerflow.community.tavily.tools.TavilyClient") as mock_client_cls:
            mock_client_cls.return_value.extract.return_value = extract_result
            web_fetch_tool.invoke({"url": "https://example.com/r"})

    mock_client_cls.assert_called_once_with(api_key="fetch-key")


def test_web_search_keeps_reading_its_own_api_key() -> None:
    """The search side of the split: it reads web_search's key (#5495)."""
    with patch("deerflow.community.tavily.tools.get_app_config", return_value=_config_with_tool_keys()):
        with patch("deerflow.community.tavily.tools.TavilyClient") as mock_client_cls:
            mock_client_cls.return_value.search.return_value = _tavily_response()
            web_search_tool.invoke({"query": "docs"})

    mock_client_cls.assert_called_once_with(api_key="search-key")
