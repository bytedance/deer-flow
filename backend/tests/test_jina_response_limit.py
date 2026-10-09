"""Offline response budgets exercised through HTTPX's real streaming decoder."""

import asyncio
import gzip
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from deerflow.community.jina_ai.jina_client import JinaClient

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks, failure=None, block=False):
        self.chunks = chunks
        self.failure = failure
        self.block = block
        self.entered = asyncio.Event()
        self.reads = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.reads += 1
            yield chunk
        self.entered.set()
        if self.failure:
            raise self.failure
        if self.block:
            await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


@pytest.fixture
def transport(monkeypatch):
    real_client = httpx.AsyncClient
    responses, requests, options = [], [], []

    def handle(request):
        requests.append(request)
        return responses.pop(0)

    def client(**kwargs):
        options.append(kwargs)
        # Record proxy configuration but keep all traffic on the offline transport.
        return real_client(transport=httpx.MockTransport(handle), trust_env=False)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setenv("JINA_API_KEY", "dummy-test-key")
    return responses, requests, options


def respond(transport, chunks, status=200, headers=None, **kwargs):
    stream = Stream(chunks, **kwargs)
    transport[0].append(httpx.Response(status, headers=headers, stream=stream))
    return stream


@pytest.mark.parametrize("options", [{}, {"max_response_bytes": None}, {"max_response_bytes": 5}])
async def test_default_and_request_compatibility(transport, options):
    stream = respond(transport, [b"hello"])
    assert await JinaClient().crawl("https://example.com", timeout=7, proxy="http://proxy.invalid", trust_env=False, **options) == "hello"
    request = transport[1][0]
    assert request.method == "POST" and str(request.url) == "https://r.jina.ai/"
    assert json.loads(request.content) == {"url": "https://example.com"}
    assert request.headers["authorization"] == "Bearer dummy-test-key"
    assert request.headers["x-return-format"] == "html"
    assert request.headers["x-timeout"] == "7"
    assert request.headers["content-type"] == "application/json"
    assert request.extensions["timeout"]["read"] == 7
    assert transport[2] == [{"proxy": "http://proxy.invalid", "trust_env": False, "follow_redirects": True}]
    assert stream.closed


@pytest.mark.parametrize("limit", [True, False, 0, -1, "5", 1.5, 5.0])
async def test_invalid_before_client_creation(transport, limit):
    result = await JinaClient().crawl("https://example.com", max_response_bytes=limit)
    assert result.startswith("Error:") and "max_response_bytes" in result
    assert not transport[1] and not transport[2]


@pytest.mark.parametrize("length", [None, "1", "999999"])
@pytest.mark.parametrize("status", [200, 400, 429, 502, 503, 504])
async def test_overflow_stops_and_never_retries(transport, length, status):
    headers = {} if length is None else {"content-length": length}
    stream = respond(transport, [b"ab", b"cd", b"e", b"must not read"], status, headers)
    result = await JinaClient().crawl("https://example.com", max_response_bytes=4, max_retries=2)
    assert result.startswith("Error:") and "max_response_bytes" in result
    assert "abcd" not in result and "must not read" not in result
    assert stream.reads == 3 and stream.closed
    assert len(transport[1]) == 1


@pytest.mark.parametrize(
    "chunks,headers,expected",
    [
        ([b"ab", b"cd"], {"content-length": "999"}, "abcd"),
        ([b"\xe2", b"\x82\xac"], {}, "€"),
        ([b"caf\xe9"], {"content-type": "text/html; charset=iso-8859-1"}, "café"),
        ([b"a\xff"], {}, "a�"),
        ([b"a\xff"], {"content-type": "text/html; charset=invalid"}, "a�"),
    ],
)
async def test_exact_limit_and_encoding(transport, chunks, headers, expected):
    stream = respond(transport, chunks, headers=headers)
    assert await JinaClient().crawl("https://example.com", max_response_bytes=sum(map(len, chunks))) == expected
    assert stream.closed


@pytest.mark.parametrize("limit", [999, 1000])
async def test_gzip_counts_decoded_bytes(transport, limit):
    body = b"x" * 1000
    compressed = gzip.compress(body)
    stream = respond(transport, [compressed[:10], compressed[10:]], headers={"content-encoding": "gzip", "content-length": str(len(compressed))})
    result = await JinaClient().crawl("https://example.com", max_response_bytes=limit)
    if limit == 1000:
        assert result == body.decode()
    else:
        assert result.startswith("Error:")
        assert "max_response_bytes" in result
    assert stream.closed


@pytest.mark.parametrize("status,body,expected", [(400, b"bad", "status 400: bad"), (429, b"busy", "status 429: busy"), (200, b"  ", "empty response"), (200, b"", "empty response")])
async def test_within_limit_errors(transport, status, body, expected):
    stream = respond(transport, [body], status)
    result = await JinaClient().crawl("https://example.com", max_response_bytes=4, max_retries=2)
    assert result.startswith("Error:") and expected in result
    assert stream.closed and len(transport[1]) == 1


async def test_retry_resets_counter(transport, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    streams = [respond(transport, [b"busy"], 503), respond(transport, [b"done"])]
    assert await JinaClient().crawl("https://example.com", max_response_bytes=4, max_retries=1) == "done"
    assert all(stream.closed for stream in streams)
    assert len(transport[1]) == 2


@pytest.mark.parametrize("failure", [httpx.ReadError("offline"), httpx.ReadTimeout("offline")])
async def test_read_failure_closes_without_retry(transport, failure):
    stream = respond(transport, [b"a"], failure=failure)
    result = await JinaClient().crawl("https://example.com", max_response_bytes=4, max_retries=1)
    assert result.startswith("Error:") and type(failure).__name__ in result
    assert stream.closed and len(transport[1]) == 1


async def test_cancellation_closes(transport):
    stream = respond(transport, [b"a"], block=True)
    task = asyncio.create_task(JinaClient().crawl("https://example.com", max_response_bytes=4, max_retries=1))
    try:
        await asyncio.wait_for(stream.entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stream.closed
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_shared_deadline_covers_retry_stream(transport, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    first = respond(transport, [b"busy"], 503)
    second = respond(transport, [b"a"], block=True)
    result = await asyncio.wait_for(JinaClient().crawl("https://example.com", max_response_bytes=4, max_retries=2, retry_budget_seconds=0.05), 1)
    assert "retry time budget exhausted" in result
    assert first.closed and second.closed and second.entered.is_set()
    timeouts = [request.extensions["timeout"]["read"] for request in transport[1]]
    assert len(timeouts) == 2 and 0 < timeouts[1] < timeouts[0] <= 0.05


@pytest.mark.parametrize("limit", [4, "4"])
async def test_tool_error_skips_extraction(transport, monkeypatch, limit):
    from deerflow.community.jina_ai import tools

    config = SimpleNamespace(model_extra={"max_response_bytes": limit})
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda name: config))
    extract = Mock(side_effect=AssertionError("must not extract"))
    monkeypatch.setattr(tools.readability_extractor, "extract_article", extract)
    stream = respond(transport, [b"oversized", b"unread"])
    result = await tools.web_fetch_tool.ainvoke({"url": "https://example.com"})
    assert result.startswith("Error:") and "max_response_bytes" in result
    extract.assert_not_called()
    assert set(tools.web_fetch_tool.args) == {"url"}
    if isinstance(limit, int):
        assert stream.closed and stream.reads == 1
    else:
        assert not transport[2]


async def test_tool_real_extraction_preserves_output_cap(transport, monkeypatch):
    from deerflow.community.jina_ai import tools

    monkeypatch.setattr("readabilipy.simple_json.have_node", lambda: False)
    body = ("<html><title>Example</title><body><article><p>" + "Useful article text. " * 500 + "</p></article></body></html>").encode()
    config = SimpleNamespace(model_extra={"max_response_bytes": len(body)})
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda name: config))
    stream = respond(transport, [body])
    result = await tools.web_fetch_tool.ainvoke({"url": "https://example.com"})
    assert "Useful article text." in result and len(result) == 4096
    assert stream.closed


@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize("budget,limit", [(30, 4), (5, 4), (30, 3)])
async def test_streaming_preserves_retry_after_policy(transport, monkeypatch, status, budget, limit):
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    first = respond(transport, [b"busy"], status, {"Retry-After": "7"})
    second = respond(transport, [b"done"])
    result = await JinaClient().crawl("https://example.com", max_response_bytes=limit, max_retries=1, retry_budget_seconds=budget)
    assert first.closed
    if limit == 3:
        assert "max_response_bytes" in result
        sleep.assert_not_awaited()
        assert len(transport[1]) == 1
    elif budget == 5:
        assert result == f"Error: Jina API returned status {status}: busy"
        sleep.assert_not_awaited()
        assert len(transport[1]) == 1
    else:
        assert result == "done"
        sleep.assert_awaited_once_with(7)
        assert second.closed and len(transport[1]) == 2
