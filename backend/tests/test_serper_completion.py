"""Completion records describe one logical call without retaining provider data."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, local
from types import SimpleNamespace

import httpx
import pytest

from deerflow.community.serper import tools


@pytest.fixture(params=["web_search", "image_search"])
def search(request, monkeypatch):
    name = request.param
    clock = SimpleNamespace(now=10.0, oversleep=0.25)
    requests = []
    options = {"api_key": "sentinel-key", "max_retries": 1}
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.delenv("SERPER_BASE_URL", raising=False)
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda _: SimpleNamespace(model_extra=options)))

    def sleep(delay):
        clock.now += delay + clock.oversleep

    monkeypatch.setattr(tools, "time", SimpleNamespace(monotonic=lambda: clock.now, sleep=sleep))
    monkeypatch.setattr(tools, "random", SimpleNamespace(uniform=lambda low, high: high))
    real_client = httpx.Client

    def run(outcomes):
        def handle(req):
            requests.append(req)
            clock.now += 0.125
            outcome = outcomes[min(len(requests) - 1, len(outcomes) - 1)]
            if isinstance(outcome, Exception):
                raise outcome
            if isinstance(outcome, httpx.Response):
                return outcome
            if outcome != 200:
                return httpx.Response(outcome, text="sentinel-body")
            return httpx.Response(200, json={"organic": [{"title": "sentinel-title", "link": "https://example.com"}], "images": [{"imageUrl": "https://example.com/image"}]})

        monkeypatch.setattr(tools, "httpx", SimpleNamespace(**{**vars(httpx), "Client": lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw)}))
        return json.loads(getattr(tools, name + "_tool").invoke({"query": "sentinel-query"}))

    return SimpleNamespace(run=run, options=options, requests=requests, clock=clock, name=name)


def summaries(caplog):
    return [r for r in caplog.records if r.name == tools.logger.name and r.getMessage().startswith("Serper completion ")]


def summary(caplog):
    records = summaries(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.DEBUG
    fields = dict(part.split("=", 1) for part in records[0].getMessage().split()[2:])
    assert set(fields) == {"tool", "attempts", "elapsed_seconds", "backoff_seconds", "outcome", "stop_reason"}
    assert "sentinel" not in repr(records[0].args)
    assert "sentinel" not in records[0].getMessage()
    return fields


@pytest.mark.parametrize(
    "outcomes,attempts,wait,outcome,reason",
    [
        ([200], 1, 0, "success", "completed"),
        ([503, 200], 2, 0.75, "success", "recovered"),
        ([httpx.Response(429, headers={"Retry-After": "0"}), 200], 2, 0.75, "success", "recovered"),
        ([503, 503], 2, 0.75, "failure", "attempts_exhausted"),
        ([httpx.Response(429, headers={"Retry-After": "999"})], 1, 0, "failure", "budget_before_backoff"),
        ([httpx.ConnectError("sentinel-exception")], 2, 0.75, "failure", "attempts_exhausted"),
        ([httpx.ReadTimeout("sentinel-exception")], 1, 0, "failure", "request_error"),
        ([400], 1, 0, "failure", "non_retryable"),
        ([httpx.Response(200, text="sentinel-body")], 1, 0, "failure", "malformed_response"),
        ([httpx.Response(200, json=[])], 1, 0, "failure", "malformed_response"),
        ([httpx.Response(200, json={"organic": "sentinel-body", "images": "sentinel-body"})], 1, 0, "failure", "malformed_response"),
        ([httpx.Response(200, json={})], 1, 0, "empty", "no_results"),
    ],
)
def test_completion(search, caplog, outcomes, attempts, wait, outcome, reason):
    caplog.set_level(logging.DEBUG, logger=tools.logger.name)
    result = search.run(outcomes)
    record = summary(caplog)
    assert record["tool"] == search.name
    assert int(record["attempts"]) == len(search.requests) == attempts
    assert float(record["backoff_seconds"]) == wait
    assert float(record["elapsed_seconds"]) == attempts * 0.125 + wait
    assert record["outcome"] == outcome
    assert record["stop_reason"] == reason
    assert ("error" not in result) == (outcome == "success")


@pytest.mark.parametrize("options,reason", [({"api_key": ""}, "missing_key"), ({"max_retries": True}, "invalid_config"), ({"base_url": "sentinel-invalid-url"}, "invalid_config")])
def test_zero_attempt_completion(search, caplog, options, reason):
    caplog.set_level(logging.DEBUG, logger=tools.logger.name)
    search.options.update(options)
    assert "error" in search.run([200])
    record = summary(caplog)
    assert not search.requests
    assert record["attempts"] == "0"
    assert float(record["backoff_seconds"]) == 0
    assert record["outcome"] == "failure"
    assert record["stop_reason"] == reason


@pytest.mark.parametrize("status", [400, 429])
def test_non_retryable_with_no_retries(search, caplog, status):
    caplog.set_level(logging.DEBUG, logger=tools.logger.name)
    search.options["max_retries"] = 0
    assert "error" in search.run([status])
    record = summary(caplog)
    assert record["attempts"] == "1"
    assert record["stop_reason"] == "non_retryable"


def test_budget_after_measured_backoff(search, caplog):
    caplog.set_level(logging.DEBUG, logger=tools.logger.name)
    search.options["retry_budget_seconds"] = 1
    search.clock.oversleep = 2
    assert "error" in search.run([503, 200])
    record = summary(caplog)
    assert record["stop_reason"] == "budget_after_backoff"
    assert record["attempts"] == "1"
    assert float(record["backoff_seconds"]) == 2.5


def test_info_has_no_completion(search, caplog):
    caplog.set_level(logging.INFO, logger=tools.logger.name)
    assert "error" not in search.run([503, 200])
    assert not summaries(caplog)


@pytest.mark.parametrize("failure", [False, True])
@pytest.mark.parametrize("breakage", ["logger", "formatter"])
def test_diagnostic_failure_preserves_result(search, monkeypatch, caplog, failure, breakage):
    caplog.set_level(logging.DEBUG, logger=tools.logger.name)

    def broken(*args, **kwargs):
        raise RuntimeError("diagnostic failed")

    class BrokenFormatter(logging.Formatter):
        def format(self, record):
            return broken()

    handler = logging.Handler()
    handler.setFormatter(BrokenFormatter())
    handler.emit = lambda record: handler.format(record) if record.getMessage().startswith("Serper completion ") else None
    if breakage == "logger":
        monkeypatch.setattr(tools.logger, "debug", broken)
    else:
        tools.logger.addHandler(handler)
    try:
        result = search.run([503] if failure else [200])
    finally:
        tools.logger.removeHandler(handler)
    if failure:
        assert result == {"query": "sentinel-query", "error": "Serper API error: HTTP 503"}
    else:
        assert result["total_results"] == 1


def test_parallel_call_counters(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger=tools.logger.name)
    barrier = Barrier(2)
    state = local()
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda _: SimpleNamespace(model_extra={"api_key": "dummy", "max_retries": 1})))
    monkeypatch.delenv("SERPER_BASE_URL", raising=False)
    monkeypatch.setattr(tools, "time", SimpleNamespace(monotonic=lambda: 0, sleep=lambda _: None))
    real_client = httpx.Client

    def handle(req):
        state.attempts = getattr(state, "attempts", 0) + 1
        if state.attempts == 1:
            barrier.wait(timeout=5)
            if req.url.path == "/search":
                return httpx.Response(503)
        return httpx.Response(200, json={"organic": [{"link": "https://example.com"}], "images": [{"imageUrl": "https://example.com/image"}]})

    monkeypatch.setattr(tools, "httpx", SimpleNamespace(**{**vars(httpx), "Client": lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw)}))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(tool.invoke, {"query": "sentinel-query"}) for tool in (tools.web_search_tool, tools.image_search_tool)]
        assert all("results" in json.loads(f.result(timeout=10)) for f in futures)
    records = summaries(caplog)
    assert len(records) == 2
    fields = [dict(p.split("=", 1) for p in r.getMessage().split()[2:]) for r in records]
    assert {(r["tool"], r["attempts"], r["stop_reason"]) for r in fields} == {("web_search", "2", "recovered"), ("image_search", "1", "completed")}


def test_original_exception_survives_completion_failure(search, monkeypatch):
    original = ValueError("original configuration failure")

    def fail_config():
        raise original

    def fail_logging(*args, **kwargs):
        raise RuntimeError("diagnostic failure")

    monkeypatch.setattr(tools, "get_app_config", fail_config)
    monkeypatch.setattr(tools.logger, "debug", fail_logging)
    with pytest.raises(ValueError) as raised:
        search.run([200])
    assert raised.value is original
    assert not search.requests


def test_config_load_failure_is_zero_attempt(search, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger=tools.logger.name)

    def fail_config():
        raise ValueError("sentinel-config")

    monkeypatch.setattr(tools, "get_app_config", fail_config)
    with pytest.raises(ValueError, match="sentinel-config"):
        search.run([200])
    record = summary(caplog)
    assert record["attempts"] == "0"
    assert record["stop_reason"] == "invalid_config"


def test_invalid_domain_configuration(search, caplog):
    if search.name != "web_search":
        pytest.skip("Domain filters apply to web search only")
    caplog.set_level(logging.DEBUG, logger=tools.logger.name)
    search.options["include_domains"] = ["sentinel-invalid"]
    assert "error" in search.run([200])
    record = summary(caplog)
    assert record["attempts"] == "0"
    assert record["stop_reason"] == "invalid_config"


def test_completion_omits_endpoint_and_headers(search, caplog):
    caplog.set_level(logging.DEBUG, logger=tools.logger.name)
    search.options["base_url"] = "https://sentinel-user:sentinel-password@sentinel-host.example/sentinel-path"
    assert "error" not in search.run([httpx.Response(503, headers={"Retry-After": "0", "X-Private": "sentinel-header"}), 200])
    record = summary(caplog)
    assert record["stop_reason"] == "recovered"
    assert len(summaries(caplog)[0].getMessage()) < 256


def test_interrupted_wait_is_measured(search, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger=tools.logger.name)
    interruption = KeyboardInterrupt()

    def interrupted_sleep(delay):
        search.clock.now += 0.0625
        raise interruption

    monkeypatch.setattr(tools.time, "sleep", interrupted_sleep)
    with pytest.raises(KeyboardInterrupt) as raised:
        search.run([503, 200])
    assert raised.value is interruption
    record = summary(caplog)
    assert record["attempts"] == "1"
    assert float(record["backoff_seconds"]) == 0.0625
    assert float(record["elapsed_seconds"]) == 0.1875
    assert record["outcome"] == "failure"


def test_completion_uses_existing_trace_context(search, caplog):
    from deerflow.logging_config import TraceContextFilter
    from deerflow.trace_context import request_trace_context

    caplog.set_level(logging.DEBUG, logger=tools.logger.name)
    trace_filter = TraceContextFilter()
    caplog.handler.addFilter(trace_filter)
    try:
        with request_trace_context("serper-completion-test"):
            search.run([503, 200])
    finally:
        caplog.handler.removeFilter(trace_filter)
    summary(caplog)
    assert summaries(caplog)[0].trace_id == "serper-completion-test"
