"""Offline source-selection contract; no real Serper requests."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from deerflow.community.serper import tools


@pytest.fixture
def search(monkeypatch):
    post = MagicMock()
    response = post.return_value
    response.json.return_value = {"organic": []}
    client = MagicMock()
    client.return_value.__enter__.return_value.post = post
    monkeypatch.setattr(tools.httpx, "Client", client)

    def run(config=None, urls=(), query="news", **arguments):
        extra = {"api_key": "dummy", **(config or {})}
        monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda _: SimpleNamespace(model_extra=extra)))
        response.json.return_value = {"organic": [{"link": url} for url in urls]}
        return json.loads(tools.web_search_tool.invoke({"query": query, **arguments}))

    run.post = post
    run.client = client
    return run


@pytest.mark.parametrize("config", [{}, {"include_domains": [], "exclude_domains": []}])
def test_empty_preserves_behavior(search, config):
    result = search(config, ["not a URL"], query=" news ")
    assert result["results"][0]["url"] == "not a URL"
    assert search.post.call_args.kwargs["json"] == {"q": "news", "num": 5}


@pytest.mark.parametrize("field", ["include_domains", "exclude_domains"])
@pytest.mark.parametrize(
    "value",
    [
        None,
        "example.com",
        {},
        True,
        [None],
        [1],
        [""],
        [" example.com"],
        ["https://example.com"],
        ["*.example.com"],
        ["example.com/path"],
        ["example.com:443"],
        ["a@b.com"],
        ["a..com"],
        ["-a.com"],
        ["a_.com"],
        ["localhost"],
        ["127.0.0.1"],
        ["example.com OR site:evil.com"],
        ["a" * 64 + ".com"],
        ["a.com"] * 11,
    ],
)
def test_invalid_fails_before_transport(search, field, value):
    result = search({field: value}, ["https://example.com"])
    assert "error" in result
    assert field in result["error"]
    search.client.assert_not_called()


def test_scope_normalization_boundary_and_precedence(search):
    urls = ["https://EXAMPLE.com./a", "https://sub.example.com/a", "https://bad.example.com/a", "https://deep.bad.example.com", "https://notexample.com", "https://example.com.evil.com", "https://bücher.de/a", "https://xn--bcher-kva.de/b"]
    result = search({"include_domains": ["Example.COM.", "bücher.de", "example.com"], "exclude_domains": ["bad.example.com"]}, urls, max_results=10, time_range="week")
    assert [r["url"] for r in result["results"]] == [urls[i] for i in [0, 1, 6, 7]]
    assert result["total_results"] == 4
    assert result["query"] == "news"
    assert search.post.call_args.kwargs["json"] == {"q": "(news) (site:example.com OR site:xn--bcher-kva.de) -site:bad.example.com", "num": 10, "tbs": "qdr:w"}
    search.post.assert_called_once()


@pytest.mark.parametrize(
    "url",
    [
        None,
        42,
        "",
        "example.com",
        "//example.com",
        "ftp://example.com",
        "https://[broken",
        "https://example.com:bad",
        "https://example.com:99999",
        "https://user@example.com",
        "https://example.com\\@evil.com",
        "https://exa\nmple.com",
        "https://example.com..",
        "https://%65xample.com",
        "https://a_.com",
    ],
)
def test_malformed_urls_removed_even_with_deny_only(search, url):
    result = search({"exclude_domains": ["blocked.com"]}, [url])
    assert result == {"query": "news", "total_results": 0, "results": []}


def test_deny_only_and_limit_after_filtering(search):
    result = search({"exclude_domains": ["blocked.com"], "max_results": 1}, ["https://blocked.com", "https://other.com", "https://third.com"])
    assert result["total_results"] == 1
    assert result["results"][0]["url"] == "https://other.com"
    assert search.post.call_args.kwargs["json"] == {"q": "(news) -site:blocked.com", "num": 1}
    search.post.assert_called_once()


@pytest.mark.parametrize("query", ["news OR site:evil.com", "news) OR (site:evil.com", '"unfinished', "-site:example.com"])
def test_query_operators_cannot_bypass_local_filter(search, query):
    result = search({"include_domains": ["example.com"]}, ["https://evil.com", "https://example.com"], query=query)
    assert result["query"] == query
    assert [r["url"] for r in result["results"]] == ["https://example.com"]


def test_query_length_boundary(search):
    suffix = ") (site:example.com)"
    query = "x" * (500 - len(suffix) - 1)
    result = search({"include_domains": ["example.com"]}, ["https://example.com"], query=query)
    assert result["query"] == query
    assert len(search.post.call_args.kwargs["json"]["q"]) == 500
    search.client.reset_mock()
    result = search({"include_domains": ["example.com"]}, query=query + "x")
    assert "error" in result
    search.client.assert_not_called()


def test_filters_alone_exceed_query_budget(search):
    result = search({"include_domains": ["a" * 60 + f".{i}.com" for i in range(10)]})
    assert "error" in result
    search.client.assert_not_called()


def test_filtered_empty_and_schema(search):
    result = search({"include_domains": ["example.com"], "exclude_domains": ["example.com"]}, ["https://example.com"])
    assert result["total_results"] == 0
    assert result["results"] == []
    assert set(tools.web_search_tool.args_schema.model_json_schema()["properties"]) == {"query", "max_results", "time_range"}


def test_image_search_ignores_domain_settings(search):
    search({"include_domains": "invalid"})
    search.post.reset_mock()
    tools.image_search_tool.invoke({"query": "images"})
    assert search.post.call_args.kwargs["json"] == {"q": "images", "num": 5}


@pytest.mark.parametrize("time_range,tbs", [(None, None), ("day", "qdr:d"), ("month", "qdr:m"), ("year", "qdr:y")])
def test_empty_provider_response_and_recency(search, time_range, tbs):
    result = search({"include_domains": ["example.com"]}, time_range=time_range)
    assert result == {"query": "news", "total_results": 0, "results": []}
    payload = search.post.call_args.kwargs["json"]
    assert payload.get("tbs") == tbs
    if tbs is None:
        assert "tbs" not in payload


def test_provider_error_preserves_original_query(search):
    search.post.side_effect = RuntimeError("provider unavailable")
    result = search({"include_domains": ["example.com"]}, query=" news ")
    assert result == {"query": "news", "error": "provider unavailable"}


@pytest.mark.parametrize("domain", ["example.com..", "xn--.com", "a" * 63 + "." + "b" * 63 + "." + "c" * 63 + "." + "d" * 62])
def test_invalid_domain_boundaries(search, domain):
    assert "error" in search({"include_domains": [domain]})
    search.client.assert_not_called()


def test_maximum_domain_length(search):
    domain = ".".join(["a" * 63, "b" * 63, "c" * 63, "d" * 61])
    result = search({"include_domains": [domain]}, ["https://" + domain])
    assert result["total_results"] == 1
