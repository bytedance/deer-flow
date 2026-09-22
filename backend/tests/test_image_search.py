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


def _search_kwargs(query="a cat", **kwargs):
    """Invoke image_search_tool and return the kwargs handed to _search_images."""
    fake_results = [{"title": "a cat", "image": "https://example.com/full.jpg", "thumbnail": "https://example.com/thumb.jpg"}]
    cfg = MagicMock()
    cfg.get_tool_config.return_value = None

    with (
        patch("deerflow.community.image_search.tools._search_images", return_value=fake_results) as mock_search,
        patch("deerflow.community.image_search.tools.get_app_config", return_value=cfg),
    ):
        image_search_tool.invoke({"query": query, **kwargs})

    return mock_search.call_args.kwargs


def test_image_search_passes_color_and_license_filters():
    """`color` / `license_image` reach the DDGS call.

    `_search_images` accepts both and forwards them into the `f` filter payload
    that duckduckgo_images builds, but `image_search_tool` never exposed or
    passed them, so they were unreachable: DDGS supports them and the provider
    already declared support for them, yet no caller could set one.
    """
    kwargs = _search_kwargs(color="Monochrome", license_image="ModifyCommercially")

    assert kwargs["color"] == "Monochrome"
    assert kwargs["license_image"] == "ModifyCommercially"


def test_image_search_omits_unset_filters():
    """An unset filter is absent/None, so _search_images leaves it out of the DDGS call.

    `_search_images` only forwards truthy filters, so this pins that the default
    request is unchanged by the newly exposed parameters.
    """
    kwargs = _search_kwargs(size="Large", type_image="photo", layout="Square")

    assert kwargs["size"] == "Large"
    assert kwargs["type_image"] == "photo"
    assert kwargs["layout"] == "Square"
    assert kwargs.get("color") is None
    assert kwargs.get("license_image") is None
