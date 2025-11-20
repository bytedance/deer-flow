# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Integration test for Bocha Web Search.

This test performs a *real* HTTP call to the Bocha Web Search API when
BOCHA_API_KEY is configured in the environment.

It is marked as `integration` so that normal unit-test-only runs can
exclude it via `-m "not integration"`.
"""

import os

import pytest

from src.tools.bocha_search.bocha_search_api_wrapper import BochaSearchAPIWrapper


@pytest.mark.integration
def test_bocha_search_real_call():
    api_key = os.getenv("BOCHA_API_KEY")
    if not api_key:
        pytest.skip("BOCHA_API_KEY not set; skipping real Bocha integration test")

    wrapper = BochaSearchAPIWrapper(api_key=api_key)

    # Use a simple Chinese query that is unlikely to be harmful and is
    # representative of real-world usage.
    raw = wrapper.raw_results("阿里巴巴 2024 年 ESG 报告亮点", max_results=2)
    cleaned = wrapper.clean_results(raw)

    # Log raw and cleaned results (truncated) for debugging real API behavior
    print("[Bocha integration] raw response (truncated):", str(raw)[:5000])
    if cleaned:
        print("[Bocha integration] first cleaned item:", cleaned[0])
    else:
        print("[Bocha integration] cleaned results is empty")

    # Basic sanity checks on cleaned results

    # Basic sanity checks on cleaned results
    assert isinstance(cleaned, list)
    assert len(cleaned) > 0

    first = cleaned[0]
    assert isinstance(first, dict)
    assert first.get("type") == "page"
    assert first.get("title")
    assert first.get("url")
    # content 可能较短或为空，但一般应存在一些文本
    assert isinstance(first.get("content", ""), str)
