"""Unit tests for the Tavily community web search tool."""

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


@pytest.mark.parametrize("title", [None, ""])
def test_web_fetch_uses_url_when_extract_title_is_missing_or_empty(title: str | None) -> None:
    result = {
        "url": "https://example.com/report",
        "raw_content": "Important report findings.",
        "images": [],
    }
    if title is not None:
        result["title"] = title
    client = MagicMock()
    client.extract.return_value = {"results": [result], "failed_results": []}

    with patch("deerflow.community.tavily.tools._get_tavily_client", return_value=client):
        output = web_fetch_tool.invoke({"url": "https://example.com/report"})

    assert output == "# https://example.com/report\n\nImportant report findings."


def test_web_fetch_preserves_failed_result_message() -> None:
    client = MagicMock()
    client.extract.return_value = {"results": [], "failed_results": [{"error": "not found"}]}

    with patch("deerflow.community.tavily.tools._get_tavily_client", return_value=client):
        output = web_fetch_tool.invoke({"url": "https://example.com/missing"})

    assert output == "Error: not found"


def test_web_fetch_preserves_no_results_message() -> None:
    client = MagicMock()
    client.extract.return_value = {"results": [], "failed_results": []}

    with patch("deerflow.community.tavily.tools._get_tavily_client", return_value=client):
        output = web_fetch_tool.invoke({"url": "https://example.com/missing"})

    assert output == "Error: No results found"


def test_web_fetch_preserves_content_limit() -> None:
    client = MagicMock()
    client.extract.return_value = {
        "results": [{"title": "Report", "url": "https://example.com/report", "raw_content": "x" * 5000}],
        "failed_results": [],
    }

    with patch("deerflow.community.tavily.tools._get_tavily_client", return_value=client):
        output = web_fetch_tool.invoke({"url": "https://example.com/report"})

    assert output == f"# Report\n\n{'x' * 4096}"
