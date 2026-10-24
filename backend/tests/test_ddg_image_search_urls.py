import json
from unittest.mock import patch

import pytest

from deerflow.community.image_search import tools
from deerflow.community.url_safety import safe_public_result_url


@pytest.mark.asyncio
async def test_image_search_drops_unsafe_result_urls() -> None:
    rows = [
        {"title": "safe", "image": "https://images.example/full.jpg", "thumbnail": "https://images.example/thumb.jpg", "url": "https://images.example/page"},
        {"title": "unsafe original", "image": "http://127.0.0.1/private", "thumbnail": "https://images.example/thumb2.jpg", "url": "http://10.0.0.1/page"},
        {"title": "unsafe thumbnail", "image": "https://images.example/full3.jpg", "thumbnail": "javascript:alert(1)"},
        {"title": "both unsafe", "image": "http://2130706433/private", "thumbnail": "http://localhost/thumb"},
    ]
    with patch.object(tools, "_search_images", return_value=rows), patch.object(tools, "get_app_config") as config:
        config.return_value.get_tool_config.return_value = None
        result = json.loads(await tools.image_search_tool.ainvoke({"query": "reference"}))

    assert result["total_results"] == 3
    assert result["results"] == [
        {"title": "safe", "image_url": "https://images.example/full.jpg", "thumbnail_url": "https://images.example/thumb.jpg", "source_url": "https://images.example/page"},
        {"title": "unsafe original", "image_url": "", "thumbnail_url": "https://images.example/thumb2.jpg", "source_url": ""},
        {"title": "unsafe thumbnail", "image_url": "https://images.example/full3.jpg", "thumbnail_url": "", "source_url": ""},
    ]


@pytest.mark.asyncio
async def test_image_search_reports_when_all_urls_are_unsafe() -> None:
    with patch.object(tools, "_search_images", return_value=[{"title": "local", "image": "http://[::1]/image"}]), patch.object(tools, "get_app_config") as config:
        config.return_value.get_tool_config.return_value = None
        result = json.loads(await tools.image_search_tool.ainvoke({"query": "reference"}))

    assert result == {"error": "No safe image URLs found", "query": "reference"}


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://127.0.0.1/image",
        "http://0177.0.0.1/image",
        "http://0x7f000001/image",
        "http://[::ffff:127.0.0.1]/image",
        "http://[64:ff9b::7f00:1]/image",
    ],
)
def test_image_search_rejects_local_result_url_spellings(url: str) -> None:
    assert safe_public_result_url(url) == ""
