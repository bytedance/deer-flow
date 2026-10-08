"""Offline completion diagnostics through real HTTPX request paths."""

import asyncio
import logging

import httpx
import pytest

from deerflow.community.jina_ai import jina_client as jina

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.setenv("JINA_API_KEY", "sentinel-key")
    original = httpx.AsyncClient

    def install(handler):
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)))

    return install


def summaries(caplog):
    return [record.getMessage() for record in caplog.records if record.name == jina.__name__ and record.getMessage().startswith("Jina crawl completed ")]


async def test_first_attempt_summary(transport, caplog):
    transport(lambda request: httpx.Response(200, text="content"))
    caplog.set_level(logging.DEBUG, logger=jina.__name__)
    assert await jina.JinaClient().crawl("https://example.invalid") == "content"
    records = summaries(caplog)
    assert len(records) == 1
    assert "outcome=success reason=success attempts=1" in records[0]
    assert "backoff_seconds=0.000000" in records[0]


@pytest.mark.parametrize("limit", [None, 100])
@pytest.mark.parametrize(
    "responses, reason, attempts",
    [
        ([httpx.Response(200, text="ok")], "success", 1),
        ([httpx.Response(503), httpx.Response(200, text="ok")], "success", 2),
        ([httpx.Response(429, headers={"Retry-After": "0"}), httpx.Response(200, text="ok")], "success", 2),
        ([httpx.ConnectError("sentinel-exception"), httpx.Response(200, text="ok")], "success", 2),
        ([httpx.Response(503), httpx.Response(503)], "attempt_exhaustion", 2),
        ([httpx.ConnectError("sentinel-exception")] * 2, "attempt_exhaustion", 2),
        ([httpx.Response(429)], "nonretryable_http", 1),
        ([httpx.Response(429, headers={"Retry-After": "sentinel-header"})], "nonretryable_http", 1),
        ([httpx.Response(503, headers={"Retry-After": "60"})], "retry_after_unfit", 1),
        ([httpx.Response(401, text="sentinel-body")], "nonretryable_http", 1),
        ([httpx.ReadError("sentinel-exception")], "request_failure", 1),
        ([httpx.Response(200, text=" ")], "empty_response", 1),
    ],
)
async def test_branches(transport, caplog, responses, reason, attempts, limit):
    pending = iter(responses)
    seen = []

    def handle(request):
        seen.append(request)
        item = next(pending)
        if isinstance(item, Exception):
            raise item
        return item

    transport(handle)
    caplog.set_level(logging.DEBUG, logger=jina.__name__)
    result = await jina.JinaClient().crawl("https://sentinel-url.invalid", max_retries=1, retry_budget_seconds=10, max_response_bytes=limit)
    assert result == "ok" if reason == "success" else result.startswith("Error:")
    records = summaries(caplog)
    assert len(records) == 1
    assert f"reason={reason} attempts={attempts}" in records[0]
    assert len(seen) == attempts
    assert "sentinel" not in records[0]


@pytest.mark.parametrize(
    "options,reason,attempts",
    [({"max_retries": -1}, "invalid_configuration", 0), ({"retry_budget_seconds": 0}, "invalid_configuration", 0), ({"max_response_bytes": False}, "invalid_configuration", 0), ({"max_response_bytes": 1}, "response_limit", 1)],
)
async def test_validation_and_limit(transport, caplog, options, reason, attempts):
    transport(lambda request: httpx.Response(200, text="sentinel-body"))
    caplog.set_level(logging.DEBUG, logger=jina.__name__)
    assert (await jina.JinaClient().crawl("https://example.invalid", **options)).startswith("Error:")
    assert len(summaries(caplog)) == 1
    assert f"reason={reason} attempts={attempts}" in summaries(caplog)[0]


async def test_info_quiet(transport, caplog):
    transport(lambda request: httpx.Response(200, text="ok"))
    caplog.set_level(logging.INFO, logger=jina.__name__)
    assert await jina.JinaClient().crawl("https://example.invalid") == "ok"
    assert summaries(caplog) == []


@pytest.mark.parametrize("backoff", [False, True])
@pytest.mark.parametrize("budget", [False, True])
async def test_cancellation_and_budget(transport, caplog, monkeypatch, backoff, budget):
    from types import SimpleNamespace

    entered = asyncio.Event()
    clock = [10.0]
    # Replace only the provider's observation clock, never asyncio's clock.
    monkeypatch.setattr(jina, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    loop = asyncio.get_running_loop()

    async def block():
        entered.set()
        clock[0] = 12.0
        await asyncio.Event().wait()

    async def handle(request):
        if not backoff:
            await block()
        return httpx.Response(503)

    async def sleep(delay):
        await block()

    if backoff:
        monkeypatch.setattr(asyncio, "sleep", sleep)
    transport(handle)
    caplog.set_level(logging.DEBUG, logger=jina.__name__)
    task = asyncio.create_task(jina.JinaClient().crawl("https://example.invalid", max_retries=1))
    try:
        await entered.wait()
        if budget:
            # Production classifies budget expiry against its original deadline.
            # Preserve that test by expiring the loop clock too, after admission.
            original_time = loop.time
            monkeypatch.setattr(loop, "time", lambda: original_time() + 31)
            assert "budget exhausted" in await task
        else:
            task.cancel("original-cancellation")
            with pytest.raises(asyncio.CancelledError, match="original-cancellation"):
                await task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    (record,) = summaries(caplog)
    assert f"reason={'budget_exhaustion' if budget else 'cancellation'} attempts=1" in record
    assert "elapsed_seconds=2.000000" in record
    assert f"backoff_seconds={'2.000000' if backoff else '0.000000'}" in record


@pytest.mark.parametrize("mode", ["success", "error", "cancel"])
@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_logging_failure(transport, caplog, mode, failure):
    def handle(request):
        if mode == "cancel":
            raise asyncio.CancelledError("original")
        return httpx.Response(200 if mode == "success" else 403, text="body")

    class BrokenHandler(logging.Handler):
        def emit(self, record):
            if record.levelno == logging.DEBUG:
                raise failure("sentinel-handler")

    transport(handle)
    caplog.set_level(logging.DEBUG, logger=jina.__name__)
    handler = BrokenHandler()
    jina.logger.addHandler(handler)
    try:
        if mode == "cancel":
            with pytest.raises(asyncio.CancelledError, match="original"):
                await jina.JinaClient().crawl("https://example.invalid")
        else:
            result = await jina.JinaClient().crawl("https://example.invalid")
            assert result == "body" if mode == "success" else result == "Error: Jina API returned status 403: body"
    finally:
        jina.logger.removeHandler(handler)


async def test_concurrent_trace_and_formatters(transport, caplog):
    import json

    from deerflow.logging_config import DEFAULT_LOG_FORMAT, TRACE_TEXT_LOG_FORMAT, JsonTraceFormatter, TraceContextFilter, TraceTextFormatter
    from deerflow.trace_context import request_trace_context

    entered = asyncio.Event()
    release = asyncio.Event()
    count = 0

    async def handle(request):
        nonlocal count
        count += 1
        if count == 1:
            entered.set()
            await release.wait()
            return httpx.Response(503, headers={"Retry-After": "0"})
        return httpx.Response(200, text="ok")

    transport(handle)
    caplog.set_level(logging.DEBUG, logger=jina.__name__)
    trace_filter = TraceContextFilter()
    caplog.handler.addFilter(trace_filter)

    async def crawl(trace):
        with request_trace_context(trace):
            return await jina.JinaClient().crawl("https://example.invalid", max_retries=1)

    task = asyncio.create_task(crawl("first"))
    try:
        await entered.wait()
        assert await crawl("second") == "ok"
        release.set()
        assert await task == "ok"
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        caplog.handler.removeFilter(trace_filter)
    records = [r for r in caplog.records if r.getMessage().startswith("Jina crawl completed ")]
    assert len(records) == 2
    assert [(r.trace_id, "attempts=2" in r.getMessage()) for r in records] == [("second", False), ("first", True)]
    for record in records:
        assert record.getMessage() in logging.Formatter(DEFAULT_LOG_FORMAT).format(record)
        assert record.getMessage() in TraceTextFormatter(TRACE_TEXT_LOG_FORMAT).format(record)
        payload = json.loads(JsonTraceFormatter().format(record))
        assert payload["message"] == record.getMessage()
        assert payload["trace_id"] == record.trace_id


async def test_measured_recovery_wait(transport, caplog, monkeypatch):
    from types import SimpleNamespace

    clock = [10.0]
    monkeypatch.setattr(jina, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    responses = iter([httpx.Response(503), httpx.Response(200, text="ok")])
    transport(lambda request: next(responses))
    real_sleep = asyncio.sleep

    async def measured_sleep(delay):
        await real_sleep(0)  # Preserve a cancellation point; no deadline is advanced.
        clock[0] += 0.125

    monkeypatch.setattr(asyncio, "sleep", measured_sleep)
    caplog.set_level(logging.DEBUG, logger=jina.__name__)
    assert await jina.JinaClient().crawl("https://example.invalid", max_retries=1) == "ok"
    (record,) = summaries(caplog)
    assert "elapsed_seconds=0.125000 backoff_seconds=0.125000" in record


async def test_client_creation_failure_has_zero_attempts(caplog, monkeypatch):
    monkeypatch.setenv("JINA_API_KEY", "sentinel-key")

    def fail(**kwargs):
        raise ValueError("sentinel-proxy-credentials")

    monkeypatch.setattr(httpx, "AsyncClient", fail)
    caplog.set_level(logging.DEBUG, logger=jina.__name__)
    assert (await jina.JinaClient().crawl("https://sentinel-url.invalid")).startswith("Error:")
    (record,) = summaries(caplog)
    assert "reason=request_failure attempts=0" in record
    assert "sentinel" not in record


@pytest.mark.parametrize(
    ("status", "body", "options"),
    [
        (200, "ok", {}),
        (200, "", {}),
        (200, "large body", {"max_response_bytes": 3}),
        (403, "denied", {}),
        (503, "unavailable", {}),
        (503, "unavailable", {"max_retries": 1, "retry_budget_seconds": 1}),
    ],
)
async def test_cleanup_failure_overrides_pending_summary(monkeypatch, caplog, status, body, options):
    monkeypatch.setenv("JINA_API_KEY", "sentinel-key")
    original = httpx.AsyncClient

    class BrokenClose(httpx.MockTransport):
        async def aclose(self):
            raise RuntimeError("sentinel-close-failed")

    mock_transport = BrokenClose(lambda request: httpx.Response(status, text=body, headers={"Retry-After": "60"}))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(**kwargs, transport=mock_transport))
    caplog.set_level(logging.DEBUG, logger=jina.__name__)
    result = await jina.JinaClient().crawl("https://example.invalid", **options)
    assert result == "Error: Request to Jina API failed: RuntimeError: sentinel-close-failed"
    (record,) = summaries(caplog)
    assert "outcome=error reason=request_failure attempts=1" in record
    assert "sentinel" not in record
