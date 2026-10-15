"""Image result screening must classify the host clients use after IDNA."""

import importlib
import json
from unittest.mock import patch

import httpx
import pytest

from deerflow.community.image_search import tools


@pytest.fixture(params=["url_safety", "brave.tools", "serper.tools"])
def screen(request):
    module = importlib.import_module(f"deerflow.community.{request.param}")
    return module.safe_public_result_url if request.param == "url_safety" else module._safe_public_url


@pytest.mark.parametrize(
    ("url", "normalized_host"),
    [
        ("http://127\u30020\u30020\u30021/image", "127.0.0.1"),
        ("http://127\uff0e0\uff0e0\uff0e1/image", "127.0.0.1"),
        ("http://127\uff610\uff610\uff611/image", "127.0.0.1"),
        ("http://169\u3002254\u3002169\u3002254/image", "169.254.169.254"),
        ("http://10\u30020\u30020\u30021/image", "10.0.0.1"),
        ("http://localhost\u3002/image", "localhost."),
        ("http://metadata\u3002google\u3002internal/image", "metadata.google.internal"),
    ],
)
def test_image_results_reject_idna_normalized_private_hosts(screen, url, normalized_host):
    # Parse with the real client, without connecting, to pin the normalization
    # that makes these spellings equivalent to the blocked ASCII hosts.
    assert httpx.URL(url).host == normalized_host
    assert screen(url) == ""


@pytest.mark.parametrize("url", ["https://images\u3002example/full.jpg", "https://\u4f8b\u3048.\u30c6\u30b9\u30c8/full.jpg", "https://images.example/full.jpg"])
def test_public_idna_result_urls_keep_the_original_string_without_dns(screen, url):
    with patch("socket.getaddrinfo", side_effect=AssertionError("Result screening must not resolve DNS")):
        assert screen(url) == url


@pytest.mark.asyncio
async def test_ddg_image_search_keeps_safe_thumbnail_when_idna_image_is_private():
    rows = [{"title": "reference", "image": "http://127\u30020\u30020\u30021/full.jpg", "thumbnail": "https://images.example/thumb.jpg"}]
    with patch.object(tools, "_search_images", return_value=rows), patch.object(tools, "get_app_config") as config:
        config.return_value.get_tool_config.return_value = None
        result = json.loads(await tools.image_search_tool.ainvoke({"query": "reference"}))

    assert result["total_results"] == 1
    assert result["results"] == [{"title": "reference", "image_url": "", "thumbnail_url": "https://images.example/thumb.jpg", "source_url": ""}]
