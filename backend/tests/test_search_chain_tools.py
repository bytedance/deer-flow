"""Unit tests for the search_chain fallback web_search tool.

Every provider is exercised through the chain's real adapter; only the provider
module's own network boundary is patched (``_brave_get``, the Tavily/Exa client
factories, ``SearxngClient.search`` and the DDGS ``_search_text`` wrapper), so
no test touches the network.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.community.ddg_search.tools import DDGSearchError
from deerflow.community.search_chain import tools as chain
from deerflow.community.search_chain.tools import web_search_tool

PROVIDER_ENV = ("BRAVE_SEARCH_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY", "EXA_BASE_URL")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)


def _config(**extra):
    tool_config = MagicMock()
    tool_config.model_extra = extra
    return patch.object(chain, "get_app_config", return_value=MagicMock(get_tool_config=MagicMock(return_value=tool_config)))


def _brave_payload(*titles):
    return {"web": {"results": [{"title": t, "url": f"https://example.com/{t}", "description": f"{t} body"} for t in titles]}}


def _ddg_rows(*titles):
    return [{"title": t, "href": f"https://example.com/{t}", "body": f"{t} body"} for t in titles]


def _exa_client(*titles, error=None):
    client = MagicMock()
    if error is not None:
        client.search.side_effect = error
    else:
        client.search.return_value = SimpleNamespace(results=[SimpleNamespace(title=t, url=f"https://example.com/{t}", highlights=[f"{t} body"]) for t in titles])
    return client


async def _run(**args):
    return json.loads(await web_search_tool.ainvoke({"query": "deer flow", **args}))


@pytest.mark.anyio
async def test_first_configured_provider_answers_and_is_recorded():
    with (
        _config(providers=["brave", "ddg"], brave={"api_key": "k"}),
        patch("deerflow.community.brave.tools._brave_get", return_value=(_brave_payload("a", "b"), None)) as brave_get,
        patch("deerflow.community.ddg_search.tools._search_text") as ddg,
    ):
        out = await _run()
    assert out["provider"] == "brave"
    assert out["query"] == "deer flow"
    assert out["total_results"] == 2
    assert out["results"][0] == {"title": "a", "url": "https://example.com/a", "content": "a body"}
    brave_get.assert_called_once()
    ddg.assert_not_called()


@pytest.mark.anyio
async def test_order_follows_config_not_default():
    calls = []

    def ddg(**kwargs):
        calls.append("ddg")
        return _ddg_rows("x")

    with (
        _config(providers=["ddg", "brave"], brave={"api_key": "k"}),
        patch("deerflow.community.brave.tools._brave_get", side_effect=lambda *a, **k: calls.append("brave")),
        patch("deerflow.community.ddg_search.tools._search_text", side_effect=ddg),
    ):
        out = await _run()
    assert out["provider"] == "ddg"
    assert calls == ["ddg"]


@pytest.mark.anyio
async def test_providers_missing_key_or_base_url_are_skipped():
    with (
        _config(providers=["brave", "tavily", "exa", "searxng", "ddg"]),
        patch("deerflow.community.brave.tools._brave_get") as brave_get,
        patch("deerflow.community.tavily.tools._get_tavily_client") as tavily,
        patch("deerflow.community.exa.tools._build_exa_client") as exa,
        patch("deerflow.community.searxng.searxng_client.SearxngClient.search", new_callable=AsyncMock) as searxng,
        patch("deerflow.community.ddg_search.tools._search_text", return_value=_ddg_rows("d")),
    ):
        out = await _run()
    assert out["provider"] == "ddg"
    for mocked in (brave_get, tavily, exa, searxng):
        mocked.assert_not_called()
    assert [(a["provider"], a["status"]) for a in out["attempts"]] == [
        ("brave", "skipped"),
        ("tavily", "skipped"),
        ("exa", "skipped"),
        ("searxng", "skipped"),
    ]


@pytest.mark.anyio
async def test_env_key_enables_provider(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "env-key")
    with (
        _config(providers=["brave"]),
        patch("deerflow.community.brave.tools._brave_get", return_value=(_brave_payload("a"), None)) as brave_get,
    ):
        out = await _run()
    assert out["provider"] == "brave"
    assert brave_get.call_args.args[1] == "env-key"


@pytest.mark.anyio
async def test_fails_over_on_errors_rate_limits_and_ddg_errors():
    tavily_client = MagicMock(search=AsyncMock(side_effect=RuntimeError("tavily boom")), close=AsyncMock())
    rate_limited = (None, json.dumps({"error": "Brave Search API error: HTTP 429", "query": "deer flow"}))
    with (
        _config(
            providers=["brave", "tavily", "ddg", "searxng"],
            brave={"api_key": "k"},
            tavily={"api_key": "k"},
            searxng={"base_url": "http://searxng:8080"},
        ),
        patch("deerflow.community.brave.tools._brave_get", return_value=rate_limited),
        patch("deerflow.community.tavily.tools._get_tavily_client", return_value=tavily_client),
        patch("deerflow.community.ddg_search.tools._search_text", side_effect=DDGSearchError("RatelimitException: 202 Ratelimit")),
        patch(
            "deerflow.community.searxng.searxng_client.SearxngClient.search",
            new_callable=AsyncMock,
            return_value=[{"title": "s", "url": "https://example.com/s", "content": "s body"}],
        ),
    ):
        out = await _run()
    assert out["provider"] == "searxng"
    assert out["results"] == [{"title": "s", "url": "https://example.com/s", "content": "s body"}]
    failed = {a["provider"]: a["error"] for a in out["attempts"]}
    assert "HTTP 429" in failed["brave"]
    assert "tavily boom" in failed["tavily"]
    assert "Ratelimit" in failed["ddg"]
    tavily_client.close.assert_awaited_once()


@pytest.mark.anyio
async def test_genuine_empty_result_is_returned_without_failover():
    with (
        _config(providers=["ddg", "brave"], brave={"api_key": "k"}),
        patch("deerflow.community.ddg_search.tools._search_text", return_value=[]),
        patch("deerflow.community.brave.tools._brave_get") as brave_get,
    ):
        out = await _run()
    assert out["error"] == "No results found"
    assert out["provider"] == "ddg"
    brave_get.assert_not_called()


@pytest.mark.anyio
async def test_fallback_on_empty_tries_next_provider():
    with (
        _config(providers=["ddg", "brave"], brave={"api_key": "k"}, fallback_on_empty=True),
        patch("deerflow.community.ddg_search.tools._search_text", return_value=[]),
        patch("deerflow.community.brave.tools._brave_get", return_value=(_brave_payload("b"), None)),
    ):
        out = await _run()
    assert out["provider"] == "brave"
    assert out["attempts"] == [{"provider": "ddg", "status": "empty"}]


@pytest.mark.anyio
async def test_fallback_on_empty_with_no_answer_reports_no_results_not_failure():
    with (
        _config(providers=["ddg", "brave"], brave={"api_key": "k"}, fallback_on_empty=True),
        patch("deerflow.community.ddg_search.tools._search_text", return_value=[]),
        patch("deerflow.community.brave.tools._brave_get", return_value=({"web": {"results": []}}, None)),
    ):
        out = await _run()
    assert out["error"] == "No results found"
    assert [a["status"] for a in out["attempts"]] == ["empty", "empty"]


@pytest.mark.anyio
async def test_all_providers_failing_lists_every_failure():
    with (
        _config(providers=["brave", "exa", "ddg"], exa={"api_key": "secret-exa-key"}),
        patch("deerflow.community.exa.tools._build_exa_client", return_value=_exa_client(error=RuntimeError("bad key secret-exa-key"))),
        patch("deerflow.community.ddg_search.tools._search_text", side_effect=DDGSearchError("TimeoutException: timed out")),
    ):
        raw = await web_search_tool.ainvoke({"query": "deer flow"})
    out = json.loads(raw)
    assert "No results found" not in raw
    assert out["error"].startswith("All web search providers failed")
    assert [(a["provider"], a["status"]) for a in out["attempts"]] == [("brave", "skipped"), ("exa", "failed"), ("ddg", "failed")]
    assert "secret-exa-key" not in raw
    assert "[REDACTED]" in out["attempts"][1]["error"]
    assert "timed out" in out["attempts"][2]["error"]


@pytest.mark.anyio
async def test_unknown_provider_is_reported_and_skipped():
    with (
        _config(providers=["bing", "ddg"]),
        patch("deerflow.community.ddg_search.tools._search_text", return_value=_ddg_rows("d")),
    ):
        out = await _run()
    assert out["provider"] == "ddg"
    assert out["attempts"][0]["provider"] == "bing"
    assert out["attempts"][0]["status"] == "skipped"


@pytest.mark.anyio
async def test_default_order_when_providers_unset():
    assert chain.DEFAULT_PROVIDERS == ("brave", "tavily", "exa", "searxng", "ddg")
    with (
        _config(),
        patch("deerflow.community.ddg_search.tools._search_text", return_value=_ddg_rows("d")),
    ):
        out = await _run()
    assert out["provider"] == "ddg"
    assert [a["provider"] for a in out["attempts"]] == ["brave", "tavily", "exa", "searxng"]


@pytest.mark.anyio
async def test_max_results_from_config_and_time_range_are_forwarded():
    captured = {}

    def ddg(**kwargs):
        captured.update(kwargs)
        return _ddg_rows("a", "b", "c")

    with (
        _config(providers=["ddg"], max_results="2", ddg={"region": "us-en", "backend": "duckduckgo"}),
        patch("deerflow.community.ddg_search.tools._search_text", side_effect=ddg),
    ):
        out = await _run(max_results=9, time_range="week")
    assert captured["max_results"] == 2
    assert captured["time_range"] == "week"
    assert captured["region"] == "us-en"
    assert captured["backend"] == "duckduckgo"
    assert out["total_results"] == 2


@pytest.mark.anyio
async def test_brave_freshness_and_count_cap():
    with (
        _config(providers=["brave"], brave={"api_key": "k"}, max_results=50),
        patch("deerflow.community.brave.tools._brave_get", return_value=(_brave_payload("a"), None)) as brave_get,
    ):
        await _run(time_range="day")
    params = brave_get.call_args.args[3]
    assert params["count"] == 20
    assert params["freshness"] == "pd"


@pytest.mark.anyio
async def test_exa_is_skipped_when_time_range_requested():
    exa_client = _exa_client("e")
    with (
        _config(providers=["exa", "ddg"], exa={"api_key": "k"}),
        patch("deerflow.community.exa.tools._build_exa_client", return_value=exa_client),
        patch("deerflow.community.ddg_search.tools._search_text", return_value=_ddg_rows("d")),
    ):
        out = await _run(time_range="month")
    assert out["provider"] == "ddg"
    assert out["attempts"][0]["status"] == "skipped"
    exa_client.search.assert_not_called()


@pytest.mark.anyio
async def test_exa_and_tavily_results_are_normalized():
    tavily_client = MagicMock(search=AsyncMock(return_value={"results": [{"title": "t", "url": "https://example.com/t", "content": "t body"}]}), close=AsyncMock())
    with (
        _config(providers=["tavily"], tavily={"api_key": "k", "include_domains": ["example.com"]}),
        patch("deerflow.community.tavily.tools._get_tavily_client", return_value=tavily_client),
    ):
        out = await _run()
    assert out["provider"] == "tavily"
    assert out["results"] == [{"title": "t", "url": "https://example.com/t", "content": "t body"}]
    assert tavily_client.search.call_args.kwargs["include_domains"] == ["example.com"]

    with (
        _config(providers=["exa"], exa={"api_key": "k"}),
        patch("deerflow.community.exa.tools._build_exa_client", return_value=_exa_client("e")),
    ):
        out = await _run()
    assert out["provider"] == "exa"
    assert out["results"] == [{"title": "e", "url": "https://example.com/e", "content": "e body"}]


@pytest.mark.anyio
async def test_unsafe_result_urls_are_blanked():
    with (
        _config(providers=["ddg"]),
        patch(
            "deerflow.community.ddg_search.tools._search_text",
            return_value=[{"title": "x", "href": "http://127.0.0.1/admin", "body": "x"}],
        ),
    ):
        out = await _run()
    assert out["results"][0]["url"] == ""


@pytest.mark.anyio
async def test_malformed_provider_payload_fails_over():
    with (
        _config(providers=["brave", "ddg"], brave={"api_key": "k"}),
        patch("deerflow.community.brave.tools._brave_get", return_value=({"web": {"results": "oops"}}, None)),
        patch("deerflow.community.ddg_search.tools._search_text", return_value=_ddg_rows("d")),
    ):
        out = await _run()
    assert out["provider"] == "ddg"
    assert out["attempts"][0]["status"] == "failed"


def test_tool_signature_matches_other_web_search_tools():
    assert web_search_tool.name == "web_search"
    assert set(web_search_tool.args) == {"query", "max_results", "time_range"}
