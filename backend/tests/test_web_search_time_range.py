"""Shared contract tests for provider-native web-search recency filtering."""

import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool

from deerflow.community.brave.tools import web_search_tool as brave_web_search
from deerflow.community.ddg_search.tools import web_search_tool as ddg_web_search
from deerflow.community.searxng.tools import web_search_tool as searxng_web_search
from deerflow.community.tavily.tools import web_search_tool as tavily_web_search

EXPECTED_TIME_RANGES = {"day", "week", "month", "year"}


@pytest.mark.parametrize(
    "tool_obj",
    [ddg_web_search, brave_web_search, tavily_web_search, searxng_web_search],
    ids=["ddg", "brave", "tavily", "searxng"],
)
def test_web_search_time_range_schema_is_consistent(tool_obj) -> None:
    parameters = convert_to_openai_tool(tool_obj)["function"]["parameters"]
    time_range_schema = parameters["properties"]["time_range"]
    branches = time_range_schema.get("anyOf", [time_range_schema])
    enum_values = next(branch["enum"] for branch in branches if "enum" in branch)

    assert set(enum_values) == EXPECTED_TIME_RANGES
    assert "time_range" not in parameters.get("required", [])
