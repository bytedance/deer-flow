import json
from unittest.mock import MagicMock, patch

from deerflow.community.image_search.tools import image_search_tool


def test_image_search_uses_full_image_url_not_thumbnail():
    # Regression: `image_url` must expose the full-resolution `image` from the DDGS result,
    # not the low-res `thumbnail` (both fields were previously set to `thumbnail`).
    fake_results = [
        {
            "title": "a cat",
            "image": "https://example.com/full.jpg",
            "thumbnail": "https://example.com/thumb.jpg",
        }
    ]
    cfg = MagicMock()
    cfg.get_tool_config.return_value = None

    with (
        patch("deerflow.community.image_search.tools._search_images", return_value=fake_results),
        patch("deerflow.community.image_search.tools.get_app_config", return_value=cfg),
    ):
        output = json.loads(image_search_tool.invoke({"query": "a cat"}))

    result = output["results"][0]
    assert result["image_url"] == "https://example.com/full.jpg"
    assert result["thumbnail_url"] == "https://example.com/thumb.jpg"
