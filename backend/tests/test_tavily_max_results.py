"""Tavily forwards an invalid configured ``max_results`` to the provider.

``web_search_tool`` read the configured value straight out of
``ToolConfig.model_extra`` and passed it to ``AsyncTavilyClient.search``, so a
boolean, a fractional float, ``.inf``, a non-positive number or a string reached
the provider unchanged. Tavily encodes ``.inf`` as the invalid JSON token
``Infinity`` and rejects the request, ``true`` collapses to a single result, and
``0``/``-2`` are out of the documented range -- all instead of falling back to
the documented default. #5865 audits this family value by value and
``deerflow.community.search_max_results`` owns the answer for the migrated
providers; Tavily only had to join them. No upper bound is applied here: the
clamp-versus-pass-through policy stays per-provider.
"""

from __future__ import annotations

import logging

import pytest

from deerflow.community.search_max_results import DEFAULT_MAX_RESULTS
from deerflow.community.tavily import tools as tavily_tools
from deerflow.config.tool_config import ToolConfig

_UNSET = object()


class _StubTavilyClient:
    """Capture the search keyword arguments the tool hands the SDK."""

    def __init__(self) -> None:
        self.search_kwargs: dict[str, object] = {}

    async def search(self, query: str, **kwargs: object) -> dict[str, list[object]]:
        self.search_kwargs = dict(kwargs)
        return {"results": []}

    async def close(self) -> None:
        pass


def _config(configured: object = _UNSET) -> ToolConfig:
    fields: dict[str, object] = {
        "name": "web_search",
        "group": "web",
        "use": "deerflow.community.tavily.tools:web_search_tool",
    }
    if configured is not _UNSET:
        fields["max_results"] = configured
    return ToolConfig(**fields)


def _install(monkeypatch: pytest.MonkeyPatch, config: ToolConfig) -> _StubTavilyClient:
    client = _StubTavilyClient()

    class _AppConfig:
        def get_tool_config(self, _name: str) -> ToolConfig:
            return config

    monkeypatch.setattr(tavily_tools, "get_app_config", _AppConfig)
    monkeypatch.setattr(tavily_tools, "AsyncTavilyClient", lambda **_kwargs: client)
    return client


@pytest.mark.anyio
@pytest.mark.parametrize(
    "configured",
    [True, False, 3.5, float("inf"), float("-inf"), float("nan"), 0, -2, "abc", "", None],
    ids=["true", "false", "fractional", "inf", "-inf", "nan", "zero", "negative", "text", "empty", "null"],
)
async def test_invalid_configured_max_results_falls_back_to_the_default(monkeypatch, configured, caplog) -> None:
    client = _install(monkeypatch, _config(configured))

    with caplog.at_level(logging.WARNING):
        await tavily_tools.web_search_tool.ainvoke({"query": "docs"})

    assert client.search_kwargs["max_results"] == DEFAULT_MAX_RESULTS
    assert [record.name for record in caplog.records] == ["deerflow.community.tavily.tools"]
    assert f"Invalid Tavily max_results={configured!r}; using default {DEFAULT_MAX_RESULTS}" in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("configured", "expected"),
    [(5, 5), (7, 7), ("5", 5), (4.0, 4), (10_000, 10_000)],
    ids=["default", "configured", "numeric-text", "integral-float", "no-upper-bound"],
)
async def test_valid_configured_max_results_is_forwarded_unchanged(monkeypatch, configured, expected, caplog) -> None:
    client = _install(monkeypatch, _config(configured))

    with caplog.at_level(logging.WARNING):
        await tavily_tools.web_search_tool.ainvoke({"query": "docs"})

    assert client.search_kwargs["max_results"] == expected
    assert caplog.records == []


@pytest.mark.anyio
async def test_absent_max_results_key_keeps_the_documented_default(monkeypatch, caplog) -> None:
    client = _install(monkeypatch, _config())

    with caplog.at_level(logging.WARNING):
        await tavily_tools.web_search_tool.ainvoke({"query": "docs"})

    assert client.search_kwargs["max_results"] == DEFAULT_MAX_RESULTS
    assert caplog.records == []
