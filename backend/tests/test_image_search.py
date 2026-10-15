import json
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from deerflow.community.image_search import tools
from deerflow.community.image_search.tools import image_search_tool


@pytest.mark.anyio
async def test_image_search_uses_full_image_url_not_thumbnail():
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
        output = json.loads(await image_search_tool.ainvoke({"query": "a cat"}))

    result = output["results"][0]
    assert result["image_url"] == "https://example.com/full.jpg"
    assert result["thumbnail_url"] == "https://example.com/thumb.jpg"


async def _search_kwargs(query="a cat", **kwargs):
    """Invoke image_search_tool and return the kwargs handed to _search_images."""
    fake_results = [{"title": "a cat", "image": "https://example.com/full.jpg", "thumbnail": "https://example.com/thumb.jpg"}]
    cfg = MagicMock()
    cfg.get_tool_config.return_value = None

    with (
        patch("deerflow.community.image_search.tools._search_images", return_value=fake_results) as mock_search,
        patch("deerflow.community.image_search.tools.get_app_config", return_value=cfg),
    ):
        await image_search_tool.ainvoke({"query": query, **kwargs})

    return mock_search.call_args.kwargs


@pytest.mark.anyio
async def test_image_search_passes_color_and_license_filters():
    """`color` / `license_image` reach the DDGS call.

    `_search_images` accepts both and forwards them into the `f` filter payload
    that duckduckgo_images builds, but `image_search_tool` never exposed or
    passed them, so they were unreachable: DDGS supports them and the provider
    already declared support for them, yet no caller could set one.
    """
    kwargs = await _search_kwargs(color="Monochrome", license_image="ModifyCommercially")

    assert kwargs["color"] == "Monochrome"
    assert kwargs["license_image"] == "ModifyCommercially"


@pytest.mark.anyio
async def test_image_search_omits_unset_filters():
    """An unset filter is absent/None, so _search_images leaves it out of the DDGS call.

    `_search_images` only forwards truthy filters, so this pins that the default
    request is unchanged by the newly exposed parameters.
    """
    kwargs = await _search_kwargs(size="Large", type_image="photo", layout="Square")

    assert kwargs["size"] == "Large"
    assert kwargs["type_image"] == "photo"
    assert kwargs["layout"] == "Square"
    assert kwargs.get("color") is None
    assert kwargs.get("license_image") is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("configured_limit", "env_value", "call_args", "expected_count", "warns"),
    [
        pytest.param("$IMAGE_SEARCH_TEST_MAX_RESULTS", "3", {"max_results": 2}, 3, False, id="environment-variable"),
        pytest.param("3", "3", {"max_results": 2}, 3, False, id="numeric-string"),
        pytest.param(3, "3", {"max_results": 2}, 3, False, id="integer-config"),
        pytest.param(None, "3", {"max_results": 2}, 2, False, id="call-argument"),
        pytest.param(None, "3", {}, 5, False, id="default"),
        pytest.param("$IMAGE_SEARCH_TEST_MAX_RESULTS", "abc", {"max_results": 2}, 5, True, id="invalid-env"),
        pytest.param("$IMAGE_SEARCH_TEST_MAX_RESULTS", "", {"max_results": 2}, 5, True, id="empty-env"),
        pytest.param("$IMAGE_SEARCH_TEST_MAX_RESULTS", "3.5", {"max_results": 2}, 5, True, id="fractional-env"),
        pytest.param(3.5, "3", {"max_results": 2}, 5, True, id="fractional-config"),
        pytest.param(True, "3", {"max_results": 2}, 5, True, id="boolean-config"),
        pytest.param("$IMAGE_SEARCH_TEST_MAX_RESULTS", "0", {"max_results": 2}, 5, True, id="zero-env"),
        pytest.param(-2, "3", {}, 5, True, id="negative-config"),
        pytest.param(None, "3", {"max_results": 0}, 5, True, id="zero-call-argument"),
    ],
)
async def test_image_search_max_results_with_real_ddgs(monkeypatch, caplog, configured_limit, env_value, call_args, expected_count, warns):
    """Exercise DDGS image count arithmetic and slicing without contacting search engines.

    Environment substitution keeps `max_results: $VAR` as a string; DDGS then raised
    `TypeError` while sizing its workers and the tool reported "No images found".
    """
    from ddgs.ddgs import DDGS
    from ddgs.results import ImagesResult

    from deerflow.config.app_config import AppConfig
    from deerflow.config.tool_config import ToolConfig

    monkeypatch.setenv("IMAGE_SEARCH_TEST_MAX_RESULTS", env_value)
    caplog.set_level(logging.WARNING, logger=tools.__name__)
    raw_config = {"name": "image_search", "group": "web", "use": "deerflow.community.image_search.tools:image_search_tool"}
    if configured_limit is not None:
        raw_config["max_results"] = configured_limit
    tool_config = ToolConfig.model_validate(AppConfig.resolve_env_variables(raw_config))
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda name: tool_config))

    rows = [
        ImagesResult(
            title=f"Image {i}",
            image=f"https://example.com/{i}.jpg",
            thumbnail=f"https://example.com/{i}-thumb.jpg",
            url=f"https://example.com/{i}",
            height=100,
            width=100,
            source="offline",
        )
        for i in range(10)
    ]
    engine = SimpleNamespace(provider="offline", name="offline", search=MagicMock(return_value=rows))
    monkeypatch.setattr(DDGS, "_get_network_client", lambda self: None)
    monkeypatch.setattr(DDGS, "_get_engines", lambda self, category, backend: [engine])

    parsed = json.loads(await image_search_tool.ainvoke({"query": "Image", **call_args}))

    assert "error" not in parsed
    assert parsed["total_results"] == len(parsed["results"]) == expected_count
    assert all(result["image_url"].startswith("https://example.com/") for result in parsed["results"])
    engine.search.assert_called_once()
    warnings = [record for record in caplog.records if record.name == tools.__name__ and record.levelno == logging.WARNING]
    assert len(warnings) == int(warns)
    if warns:
        assert "max_results" in warnings[0].getMessage()
        assert "using default 5" in warnings[0].getMessage()
