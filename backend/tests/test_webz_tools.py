"""Offline Webz request/response contract using the real httpx serializer."""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
import yaml
from httpx import AsyncClient as RealAsyncClient


@pytest.fixture
def webz(monkeypatch):
    import deerflow.community.webz.tools as module

    options = {"api_key": "synthetic-key"}
    monkeypatch.setattr(module, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda _: SimpleNamespace(model_extra=options)))
    monkeypatch.delenv("WEBZ_API_KEY", raising=False)
    requests = []
    response = {"results": []}
    status = [200]
    client_class = httpx.AsyncClient

    async def handler(request):
        requests.append(request)
        return httpx.Response(status[0], json=response)

    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs))
    return module, options, requests, response, status


@pytest.mark.asyncio
async def test_request_filters_and_normalized_results(webz, monkeypatch):
    module, _, requests, response, _ = webz
    monkeypatch.setenv("WEBZ_API_KEY", "unused-environment-key")
    response["results"] = [
        {
            "score": 8.5,
            "article": {"title": "News", "url": "https://example.com/news", "published_at": "2026-09-20T12:00:00Z", "summary": "Summary"},
            "chunk": {"text": "Matching passage"},
            "metadata": {"domain": "example.com", "language": "english", "country": "US"},
        }
    ]
    result = json.loads(
        await module.web_search_tool.ainvoke(
            {
                "query": "renewable energy",
                "max_results": 3,
                "published_from": "2026-09-01",
                "published_to": "2026-09-20",
                "language": ["english"],
                "country": ["US"],
                "source": ["example.com"],
                "sentiment": ["positive"],
                "category": ["Environment"],
            }
        )
    )
    request = requests[0]
    assert str(request.url) == "https://api.webz.io/api/news/context"
    assert request.headers["authorization"] == "Bearer synthetic-key"
    assert json.loads(request.content) == {
        "query": "renewable energy",
        "k": 3,
        "filters": {"published_from": "2026-09-01", "published_to": "2026-09-20", "language": ["english"], "country": ["US"], "domain": ["example.com"], "sentiment": ["positive"], "category": ["Environment"]},
    }
    assert result == {
        "query": "renewable energy",
        "total_results": 1,
        "results": [{"title": "News", "url": "https://example.com/news", "content": "Matching passage", "published_at": "2026-09-20T12:00:00Z", "source": {"domain": "example.com", "language": "english", "country": "US"}}],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(("window", "start"), [("day", "2026-09-23"), ("week", "2026-09-17"), ("month", "2026-08-25"), ("year", "2025-09-24")])
async def test_relative_window_uses_utc_and_explicit_lower_bound_wins(webz, monkeypatch, window, start):
    module, _, requests, _, _ = webz

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 24, 12, tzinfo=UTC)

    monkeypatch.setattr(module, "datetime", Clock)
    await module.web_search_tool.ainvoke({"query": "news", "time_range": window})
    assert json.loads(requests[-1].content)["filters"] == {"published_from": start}
    await module.web_search_tool.ainvoke({"query": "news", "time_range": window, "published_from": "2026-09-22"})
    assert json.loads(requests[-1].content)["filters"] == {"published_from": "2026-09-22"}


@pytest.mark.asyncio
async def test_environment_key_configured_count_and_no_implicit_filters(webz, monkeypatch):
    module, options, requests, _, _ = webz
    options.update(api_key=" ", max_results="1000")
    monkeypatch.setenv("WEBZ_API_KEY", " env-key ")
    assert json.loads(await module.web_search_tool.ainvoke({"query": " news "})) == {"query": "news", "total_results": 0, "results": []}
    assert requests[0].headers["authorization"] == "Bearer env-key"
    assert json.loads(requests[0].content) == {"query": "news", "k": 100}


@pytest.mark.asyncio
async def test_missing_key_never_makes_request(webz):
    module, options, requests, _, _ = webz
    options.clear()
    assert "WEBZ_API_KEY" in json.loads(await module.web_search_tool.ainvoke({"query": "news"}))["error"]
    assert not requests


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [{"query": " "}, {"query": "x" * 751}, {"query": "word " * 101}, {"query": "news", "published_from": "yesterday"}, {"query": "news", "published_from": "2026-09-20", "published_to": "2026-09-01"}])
async def test_invalid_input_never_makes_request(webz, arguments):
    module, _, requests, _, _ = webz
    assert "error" in json.loads(await module.web_search_tool.ainvoke(arguments))
    assert not requests


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [302, 401, 429, 500])
async def test_http_errors_do_not_echo_provider_body_or_credentials(webz, status_code, caplog):
    module, _, requests, response, status = webz
    response.update(error="synthetic-key")
    status[0] = status_code
    result = await module.web_search_tool.ainvoke({"query": "news"})
    assert str(status_code) in json.loads(result)["error"]
    assert "synthetic-key" not in result + caplog.text
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"results": None}, {"results": [None]}, {"results": [{"article": []}]}])
async def test_malformed_payload_is_an_error(webz, payload):
    module, _, _, response, _ = webz
    response.clear()
    response.update(payload)
    assert "error" in json.loads(await module.web_search_tool.ainvoke({"query": "news"}))


@pytest.mark.asyncio
async def test_cancellation_propagates(webz, monkeypatch):
    module, _, _, _, _ = webz

    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(RealAsyncClient, "post", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await module.web_search_tool.ainvoke({"query": "news"})


def test_setup_wizard_offers_webz_with_env_key():
    from wizard.providers import SEARCH_PROVIDERS
    from wizard.writer import build_minimal_config

    provider = next(p for p in SEARCH_PROVIDERS if p.name == "webz")
    assert provider.env_var == "WEBZ_API_KEY"
    config = build_minimal_config(provider_use="langchain_openai:ChatOpenAI", model_name="dummy", display_name="Dummy", api_key_field="api_key", env_var="OPENAI_API_KEY", search_use=provider.use, search_extra_config=provider.extra_config)
    assert next(t for t in yaml.safe_load(config)["tools"] if t["name"] == "web_search")["use"] == "deerflow.community.webz.tools:web_search_tool"


@pytest.mark.asyncio
@pytest.mark.parametrize("exception", [httpx.ReadTimeout("synthetic-key"), httpx.ConnectError("synthetic-key")])
async def test_transport_failures_are_sanitized(webz, monkeypatch, exception):
    module, _, _, _, _ = webz

    async def fail(*args, **kwargs):
        raise exception

    monkeypatch.setattr(RealAsyncClient, "post", fail)
    result = await module.web_search_tool.ainvoke({"query": "news"})
    assert "error" in json.loads(result)
    assert "synthetic-key" not in result


@pytest.mark.asyncio
async def test_summary_fallback_and_output_limit(webz):
    module, _, _, response, _ = webz
    response["results"] = [{"article": {"title": "News", "url": "https://example.com", "summary": "Summary"}}] * 3
    result = json.loads(await module.web_search_tool.ainvoke({"query": "news", "max_results": 1}))
    assert result["total_results"] == len(result["results"]) == 1
    assert result["results"][0]["content"] == "Summary"


@pytest.mark.asyncio
@pytest.mark.parametrize("value, expected", [(None, 5), (True, 5), ("invalid", 5), (-1, 1), ("12", 12), (200, 100)])
async def test_configured_result_count(webz, value, expected):
    module, options, requests, _, _ = webz
    options["max_results"] = value
    await module.web_search_tool.ainvoke({"query": "news"})
    assert json.loads(requests[0].content)["k"] == expected


def test_doctor_recognizes_webz_credentials(tmp_path, monkeypatch):
    import doctor

    config = tmp_path / "config.yaml"
    config.write_text("tools:\n  - name: web_search\n    use: deerflow.community.webz.tools:web_search_tool\n", encoding="utf-8")
    monkeypatch.delenv("WEBZ_API_KEY", raising=False)
    missing = doctor.check_web_search(config)
    assert missing.status == "warn"
    assert "WEBZ_API_KEY" in missing.detail
    monkeypatch.setenv("WEBZ_API_KEY", "synthetic-key")
    present = doctor.check_web_search(config)
    assert present.status == "ok"
