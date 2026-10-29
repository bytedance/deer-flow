"""Offline recovery through production tools and real HTTPX transports."""

import json
import logging
import time
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from deerflow.community.serper import tools


@pytest.fixture(params=["web_search", "image_search"])
def search(request, monkeypatch):
    name = request.param
    clients = []
    requests = []
    transports = []
    clock = SimpleNamespace(now=0.0, wall=1700000000.0, waits=[], elapsed=0.0, oversleep=0.0, jitter=1.0, ranges=[])
    real_client = httpx.Client

    def sleep(delay):
        clock.waits.append(delay)
        clock.now += delay + clock.oversleep

    monkeypatch.setattr(tools, "time", SimpleNamespace(monotonic=lambda: clock.now, time=lambda: clock.wall, sleep=sleep), raising=False)

    def uniform(low, high):
        clock.ranges.append((low, high))
        return low + (high - low) * clock.jitter

    monkeypatch.setattr(tools, "random", SimpleNamespace(uniform=uniform), raising=False)

    class Transport(httpx.MockTransport):
        closed = False

        def close(self):
            self.closed = True
            super().close()

    def run(outcomes, options=None, configured=True, direct=False):
        extra = {"api_key": "dummy-key", **(options or {})}
        monkeypatch.setenv("SERPER_API_KEY", "dummy-key")
        monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda _: SimpleNamespace(model_extra=extra) if configured else None))

        def handle(req):
            requests.append(req)
            clock.now += clock.elapsed
            outcome = outcomes[min(len(requests) - 1, len(outcomes) - 1)]
            if isinstance(outcome, Exception):
                raise outcome
            if isinstance(outcome, tuple):
                return httpx.Response(outcome[0], headers={"Retry-After": outcome[1]})
            if outcome == 200:
                return httpx.Response(200, json={"organic": [{"link": "https://example.com/a"}, {"link": "https://ads.example.com/a"}], "images": [{"imageUrl": "https://example.com/a"}]})
            if outcome == "bad-json":
                return httpx.Response(200, text="broken")
            return httpx.Response(outcome)

        def client(**kwargs):
            transport = Transport(handle)
            transports.append(transport)
            result = real_client(transport=transport, **kwargs)
            clients.append(result)
            return result

        monkeypatch.setattr(tools.httpx, "Client", client)
        if direct:
            data, error = tools._serper_post("https://google.serper.dev/search", "dummy-key", "news", 5, **(options or {}))
            result = json.loads(error) if error else data
        else:
            arguments = {"query": " news "}
            if name == "web_search":
                arguments["time_range"] = "week"
            result = json.loads(getattr(tools, name + "_tool").invoke(arguments))
        assert all(client.is_closed for client in clients)
        assert all(transport.closed for transport in transports)
        return result

    run.requests = requests
    run.clients = clients
    run.clock = clock
    run.name = name
    return run


@pytest.fixture
def non_utc_timezone(monkeypatch):
    if not hasattr(time, "tzset"):
        yield
        return
    try:
        with monkeypatch.context() as local_timezone:
            local_timezone.setenv("TZ", "GMT-8")
            time.tzset()
            yield
    finally:
        time.tzset()


@pytest.mark.parametrize("outcome", [502, 503, 504, (429, "0"), httpx.ConnectError("connect"), httpx.ConnectTimeout("connect")])
def test_transient_recovers(search, outcome):
    result = search([outcome, 200], {"max_retries": 1})
    assert "error" not in result
    assert len(search.requests) == 2


@pytest.mark.parametrize("configured", [True, False])
@pytest.mark.parametrize("outcome", [503, (429, "0"), httpx.ConnectTimeout("connect")])
def test_default_single_attempt(search, configured, outcome):
    assert "error" in search([outcome, 200], configured=configured)
    assert len(search.requests) == 1
    assert search.clock.waits == []


def test_helper_recovery(search):
    assert "organic" in search([503, 200], {"max_retries": 1}, direct=True)
    assert len(search.requests) == 2


def test_exhaustion(search, caplog):
    assert search([503], {"max_retries": 3}) == {"query": "news", "error": "Serper API error: HTTP 503"}
    assert len(search.requests) == 4
    assert search.clock.waits == [0.5, 1.0, 2.0]
    assert "retry time budget exhausted" not in caplog.text


@pytest.mark.parametrize("outcome", [400, 401, 403, 429, 500, "bad-json", httpx.ReadTimeout("read"), httpx.WriteTimeout("write"), httpx.ReadError("read"), httpx.PoolTimeout("pool")])
def test_terminal(search, outcome):
    assert "error" in search([outcome, 200], {"max_retries": 3})
    assert len(search.requests) == 1


@pytest.mark.parametrize("field,value", [("max_retries", v) for v in [-1, 4, True, 1.0, "1", None]] + [("retry_budget_seconds", v) for v in [0, -1, True, "1", None, float("nan"), float("inf"), 301]])
def test_invalid_configuration(search, field, value):
    assert field in search([200], {field: value})["error"]
    assert not search.requests
    assert not search.clients


@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize("hint,delay", [("0", 0.5), ("2", 2.0), ("Tue, 14 Nov 2023 22:13:22 GMT", 2.0), ("Tue, 14 Nov 2023 22:13:19 GMT", 0.5)])
def test_valid_hints(search, status, hint, delay):
    assert "error" not in search([(status, hint), 200], {"max_retries": 1})
    assert search.clock.waits == [delay]


@pytest.mark.parametrize("hint", ["", "-1", "1.5", "NaN", "inf", "tomorrow", "1, 2"])
@pytest.mark.parametrize("status", [429, 503])
def test_invalid_hints(search, hint, status):
    result = search([(status, hint), 200], {"max_retries": 1})
    assert len(search.requests) == (1 if status == 429 else 2)
    assert ("error" in result) == (status == 429)


@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize("hint", ["31", "9" * 5000, "Tue, 14 Nov 2023 22:14:00 GMT"])
def test_hint_exceeds_budget(search, status, hint):
    assert "error" in search([(status, hint), 200], {"max_retries": 1})
    assert len(search.requests) == 1
    assert search.clock.waits == []


@pytest.mark.parametrize("elapsed,budget,attempts,waits", [(0, 1.5, 2, [0.5]), (1, 2, 2, [0.5]), (2, 1, 1, [])])
def test_single_deadline(search, elapsed, budget, attempts, waits):
    search.clock.elapsed = elapsed
    assert "error" in search([503], {"max_retries": 3, "retry_budget_seconds": budget})
    assert len(search.requests) == attempts
    assert search.clock.waits == waits


def test_oversleep_prevents_request(search):
    search.clock.oversleep = 2
    assert "error" in search([503, 200], {"max_retries": 1, "retry_budget_seconds": 1})
    assert len(search.requests) == 1


@pytest.mark.parametrize("outcome", [503, (429, "0"), httpx.ConnectTimeout("connect")])
@pytest.mark.parametrize("budget,oversleep,stage,waits", [(0.5, 0, "before backoff", []), (1, 2, "after backoff", [0.5])])
def test_budget_exhaustion_diagnostic(search, caplog, outcome, budget, oversleep, stage, waits):
    search.clock.oversleep = oversleep
    result = search([outcome, 200], {"max_retries": 1, "retry_budget_seconds": budget})
    status = outcome[0] if isinstance(outcome, tuple) else outcome
    last_error = "connect" if isinstance(outcome, Exception) else f"Serper API error: HTTP {status}"
    assert result == {"error": last_error, "query": "news"}
    assert len(search.requests) == 1
    assert search.clock.waits == waits
    diagnostics = [record for record in caplog.records if record.name == tools.logger.name and "retry time budget exhausted" in record.getMessage()]
    assert len(diagnostics) == 1
    assert diagnostics[0].levelno == logging.WARNING
    assert stage in diagnostics[0].getMessage()
    assert "dummy-key" not in diagnostics[0].getMessage()
    assert "news" not in diagnostics[0].getMessage()


def test_preserves_request_and_filters(search):
    result = search([503, 200], {"max_retries": 1, "max_results": 1, "include_domains": ["example.com"], "exclude_domains": ["ads.example.com"]})
    assert result["query"] == "news"
    assert result["total_results"] == 1
    first, second = search.requests
    assert first.content == second.content
    assert first.headers == second.headers
    assert first.headers["X-API-KEY"] == "dummy-key"
    expected = {"q": "news", "num": 1}
    if search.name == "web_search":
        expected.update(q="(news) (site:example.com) -site:ads.example.com", tbs="qdr:w")
        assert result["results"][0]["url"] == "https://example.com/a"
    assert json.loads(first.content) == expected


@pytest.mark.parametrize("endpoint_source", ["tool-config", "environment"])
def test_retry_keeps_configured_endpoint_and_key_through_reload(search, monkeypatch, endpoint_source):
    """A retry must not switch providers when config or environment changes."""
    options = {"max_retries": 1}
    if endpoint_source == "tool-config":
        options["base_url"] = " https://first.example/api/// "
        monkeypatch.setenv("SERPER_BASE_URL", "https://fallback.example")
    else:
        monkeypatch.setenv("SERPER_BASE_URL", " https://first.example/api/// ")
    original_sleep = tools.time.sleep

    def reload_during_backoff(delay):
        original_sleep(delay)
        monkeypatch.setenv("SERPER_BASE_URL", "https://second.example/api")
        monkeypatch.setenv("SERPER_API_KEY", "second-provider-key")

        def reloaded_config():
            pytest.fail("Retries must use the captured tool configuration")

        monkeypatch.setattr(tools, "get_app_config", reloaded_config)

    monkeypatch.setattr(tools.time, "sleep", reload_during_backoff)
    result = search([503, 200], options)

    assert "error" not in result
    assert len(search.requests) == 2
    route = "search" if search.name == "web_search" else "images"
    assert {str(request.url) for request in search.requests} == {f"https://first.example/api/{route}"}
    assert {request.headers["X-API-KEY"] for request in search.requests} == {"dummy-key"}
    assert search.requests[0].content == search.requests[1].content


def test_filtered_error_keeps_original_query(search):
    result = search([503], {"max_retries": 1, "include_domains": ["example.com"]})
    assert result == {"query": "news", "error": "Serper API error: HTTP 503"}
    assert len(search.requests) == 2


@pytest.mark.parametrize("options", [{"max_retries": 0}, {"retry_budget_seconds": 1}])
def test_budget_does_not_enable_retries(search, options):
    assert "error" in search([503, 200], options)
    assert len(search.requests) == 1


def test_jitter_lower_bound(search):
    search.clock.jitter = 0
    search([503], {"max_retries": 3})
    assert search.clock.waits == [0.25, 0.5, 1.0]
    assert search.clock.ranges == [(0.25, 0.5), (0.5, 1), (1, 2)]


def test_direct_invalid_options(search):
    assert "max_retries" in search([200], {"max_retries": True}, direct=True)["error"]
    assert not search.clients


def test_tool_schemas_unchanged():
    assert set(tools.web_search_tool.args_schema.model_json_schema()["properties"]) == {"query", "max_results", "time_range"}
    assert set(tools.image_search_tool.args_schema.model_json_schema()["properties"]) == {"query", "max_results"}


@pytest.mark.parametrize("outcome", [httpx.ConnectError("connect"), httpx.ConnectTimeout("connect")])
def test_connection_exhaustion(search, outcome):
    assert search([outcome], {"max_retries": 1}) == {"error": "connect", "query": "news"}
    assert len(search.requests) == 2


def test_last_status_on_budget_exhaustion(search):
    result = search([503, (429, "30"), 200], {"max_retries": 3})
    assert result == {"error": "Serper API error: HTTP 429", "query": "news"}
    assert len(search.requests) == 2
    assert search.clock.waits == [0.5]


@pytest.mark.parametrize("hint", ["Sun Nov  6 08:49:37 1994", "Sunday, 06-Nov-94 08:49:37 GMT"])
def test_legacy_http_date_is_valid(search, hint):
    result = search([(429, hint), 200], {"max_retries": 1})
    assert "error" not in result
    assert len(search.requests) == 2


@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize(
    "current,hint,delay",
    [
        (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), "Tue Nov 14 22:13:22 2023", 2.0),
        (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), "Tue Nov 14 22:13:19 2023", 0.5),
        (datetime(2023, 11, 5, 8, 49, 37, tzinfo=UTC), "Sun Nov  5 08:49:39 2023", 2.0),
        (datetime(2023, 11, 5, 8, 49, 37, tzinfo=UTC), "Sun Nov  5 08:49:36 2023", 0.5),
    ],
)
def test_asctime_hint_uses_utc_and_server_floor(search, non_utc_timezone, status, current, hint, delay):
    search.clock.wall = current.timestamp()
    assert "error" not in search([(status, hint), 200], {"max_retries": 1})
    assert len(search.requests) == 2
    assert search.clock.waits == [delay]


@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize(
    "hint,resolved",
    [
        ("Tuesday, 14-Nov-23 22:13:22 GMT", datetime(2023, 11, 14, 22, 13, 22, tzinfo=UTC)),
        ("Saturday, 14-Nov-26 22:13:20 GMT", datetime(2026, 11, 14, 22, 13, 20, tzinfo=UTC)),
        ("Sunday, 14-Nov-76 22:13:20 GMT", datetime(1976, 11, 14, 22, 13, 20, tzinfo=UTC)),
        ("Tuesday, 14-Nov-73 22:13:20 GMT", datetime(2073, 11, 14, 22, 13, 20, tzinfo=UTC)),
        ("Wednesday, 14-Nov-73 22:13:21 GMT", datetime(1973, 11, 14, 22, 13, 21, tzinfo=UTC)),
    ],
)
def test_rfc850_hint_year_window_and_scheduling(search, status, hint, resolved):
    floor = max(0.0, resolved.timestamp() - search.clock.wall)
    assert tools._retry_after(httpx.Response(status, headers={"Retry-After": hint})) == floor
    result = search([(status, hint), 200], {"max_retries": 1})
    if floor >= 30:
        assert result == {"error": f"Serper API error: HTTP {status}", "query": "news"}
        assert len(search.requests) == 1
        assert search.clock.waits == []
    else:
        assert "error" not in result
        assert len(search.requests) == 2
        assert search.clock.waits == [max(0.5, floor)]


@pytest.mark.parametrize("hint", ["Wed, 21 Oct 2015 07:28:00 +0100", "Wed, 21 Oct 2015 07:28:00 UTC", "Wed, 21 Oct 2015 07:28 GMT"])
def test_email_dates_do_not_enable_429_retry(search, hint):
    result = search([(429, hint), 200], {"max_retries": 1})
    assert "error" in result
    assert len(search.requests) == 1
