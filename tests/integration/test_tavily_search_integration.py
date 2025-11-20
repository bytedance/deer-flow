# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Integration test for Tavily Web Search.

This test performs a *real* HTTP call to the Tavily Search API when
TAVILY_API_KEY is configured in the environment.

It is marked as `integration` so that normal unit-test-only runs can
exclude it via `-m "not integration"`.
"""

import os

import pytest

from src.tools.tavily_search.tavily_search_api_wrapper import (
    EnhancedTavilySearchAPIWrapper,
)


@pytest.mark.integration
def test_tavily_search_real_call():
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        pytest.skip("TAVILY_API_KEY not set; skipping real Tavily integration test")

    # EnhancedTavilySearchAPIWrapper reads TAVILY_API_KEY from environment
    wrapper = EnhancedTavilySearchAPIWrapper()

    # Use a simple Chinese query similar to the Bocha integration test
    raw = wrapper.raw_results(
        "阿里巴巴 2024 年 ESG 报告亮点",
        max_results=2,
        search_depth="advanced",
        include_domains=[],
        exclude_domains=[],
        include_answer=False,
        include_raw_content=True,
        include_images=True,
        include_image_descriptions=True,
    )
    cleaned = wrapper.clean_results_with_images(raw)

    # Log raw and cleaned results (truncated) for debugging real API behavior
    print("[TAVILY integration] raw response (truncated):", str(raw)[:5000])
    if cleaned:
        print("[TAVILY integration] first cleaned item:", cleaned[0])
    else:
        print("[TAVILY integration] cleaned results is empty")

    # Basic sanity checks on cleaned results
    assert isinstance(cleaned, list)
    assert len(cleaned) > 0

    first = cleaned[0]
    assert isinstance(first, dict)
    # We expect either a page or an image_url item
    assert first.get("type") in {"page", "image_url"}
    if first["type"] == "page":
        assert first.get("title")
        assert first.get("url")
        assert isinstance(first.get("content", ""), str)
