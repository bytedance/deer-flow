"""Unit tests for the SearXNG community search tool."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.community.searxng.tools import _coerce_max_results, web_search_tool


def test_returns_value_when_valid_positive_int() -> None:
    assert _coerce_max_results(3, 5) == 3


def test_returns_value_for_numeric_string() -> None:
    assert _coerce_max_results("7", 5) == 7


def test_returns_value_for_integral_float() -> None:
    assert _coerce_max_results(4.0, 5) == 4


@pytest.mark.parametrize(
    "raw",
    [True, False, 3.5, float("inf"), float("-inf"), "oops", None, [], {}, 0, -2],
    ids=["bool-true", "bool-false", "fractional", "inf", "neg-inf", "string", "none", "list", "dict", "zero", "negative"],
)
def test_falls_back_to_default_on_invalid_input(raw) -> None:
    assert _coerce_max_results(raw, 5) == 5


@pytest.mark.parametrize(
    "raw",
    [True, False, 3.5, float("inf"), "oops", None, 0, -2],
    ids=["bool-true", "bool-false", "fractional", "inf", "string", "none", "zero", "negative"],
)
def test_web_search_falls_back_to_default_max_results_on_invalid_config(raw) -> None:
    client = MagicMock()
    client.search = AsyncMock(return_value=[])

    tool_config = MagicMock()
    tool_config.model_extra = {"max_results": raw}

    with (
        patch("deerflow.community.searxng.tools.get_app_config") as mock_config,
        patch("deerflow.community.searxng.tools._get_searxng_client", return_value=client),
    ):
        mock_config.return_value.get_tool_config.return_value = tool_config
        result = asyncio.run(web_search_tool.ainvoke({"query": "documentation"}))

    client.search.assert_called_once_with("documentation", max_results=5)
    assert json.loads(result) == []


def test_web_search_forwards_valid_max_results_through_the_wiring() -> None:
    client = MagicMock()
    client.search = AsyncMock(return_value=[])

    tool_config = MagicMock()
    tool_config.model_extra = {"max_results": 3}

    with (
        patch("deerflow.community.searxng.tools.get_app_config") as mock_config,
        patch("deerflow.community.searxng.tools._get_searxng_client", return_value=client),
    ):
        mock_config.return_value.get_tool_config.return_value = tool_config
        result = asyncio.run(web_search_tool.ainvoke({"query": "documentation"}))

    client.search.assert_called_once_with("documentation", max_results=3)
    assert json.loads(result) == []
