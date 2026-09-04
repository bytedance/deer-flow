"""Unit tests for the Tavily community web search tool."""

import json
from unittest.mock import MagicMock, patch

from deerflow.community.tavily.tools import web_search_tool


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
