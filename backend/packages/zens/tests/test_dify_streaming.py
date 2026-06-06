from unittest.mock import patch

import httpx
import pytest


class FakeAsyncStreamResponse:
    """Async SSE response — mimics httpx.Response inside an ``async with ac.stream(...)`` block."""

    def __init__(self, lines_data, *, is_success=True, json_data=None, status_code=200):
        self._lines = lines_data
        self._is_success = is_success
        self._json_data = json_data
        self.status_code = status_code

    @property
    def is_success(self):
        return self._is_success

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self):
        if self._json_data is not None:
            import json as _json

            return _json.dumps(self._json_data).encode()
        return b'{"message": "error"}'


class _FakeAsyncStreamCtx:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeAsyncClient:
    """Mimics ``httpx.AsyncClient`` — supports ``async with`` and ``.stream(...)`` returning a context manager."""

    def __init__(self, response, **kwargs):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, method, url, **kwargs):
        return _FakeAsyncStreamCtx(self._response)


class FakeStreamResponse:
    def __init__(self, lines_data, is_success=True, json_data=None):
        self._lines = lines_data
        self._iter = iter(lines_data)
        self._is_success = is_success
        self._json_data = json_data

    @property
    def is_success(self):
        return self._is_success

    def iter_lines(self):
        return self._iter

    def json(self):
        if self._json_data is not None:
            return self._json_data
        raise httpx.HTTPError("no json")


def test_chat_stream_yields_chunks_and_conversation_id():
    from zens.community.dify.dify_client import DifyClient

    client = DifyClient(api_key="test-key", base_url="http://localhost:8000")

    mock_lines = [
        b"event: message\n",
        b'data: {"answer": "hel", "conversation_id": "conv-1", "message_id": "msg-1"}\n',
        b"event: message\n",
        b'data: {"answer": "lo", "conversation_id": "conv-1", "message_id": "msg-2"}\n',
        b"event: message\n",
        b'data: {"answer": " world", "conversation_id": "conv-1", "message_id": "msg-3"}\n',
    ]

    with patch("zens.community.dify.dify_client.httpx") as mock_httpx:
        mock_response = FakeStreamResponse(mock_lines)
        mock_httpx.post.return_value = mock_response

        chunks, conv_id = client.chat_stream(query="hello", conversation_id="", user="test")
        assert chunks == ["hel", "lo", " world"]
        assert conv_id == "conv-1"


def test_chat_stream_http_error_raises_dify_api_error():
    from zens.community.dify.dify_client import DifyAPIError, DifyClient

    client = DifyClient(api_key="test-key", base_url="http://localhost:8000")

    with patch("zens.community.dify.dify_client.httpx") as mock_httpx:
        mock_response = FakeStreamResponse([], is_success=False, json_data={"message": "Unauthorized"})
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_httpx.post.return_value = mock_response

        with pytest.raises(DifyAPIError) as exc_info:
            client.chat_stream(query="hello", conversation_id="", user="test")
        assert exc_info.value.status_code == 401


def test_chat_stream_non_message_event_filtered_out():
    from zens.community.dify.dify_client import DifyClient

    client = DifyClient(api_key="test-key", base_url="http://localhost:8000")

    # mixed events: ping (non-message) should be ignored
    mock_lines = [
        b"event: ping\n",
        b"event: message\n",
        b'data: {"answer": "first", "conversation_id": "conv-x", "message_id": "msg-1"}\n',
        b"event: ping\n",
        b"event: message\n",
        b'data: {"answer": "second", "conversation_id": "conv-x", "message_id": "msg-2"}\n',
    ]

    with patch("zens.community.dify.dify_client.httpx") as mock_httpx:
        mock_response = FakeStreamResponse(mock_lines)
        mock_httpx.post.return_value = mock_response

        chunks, conv_id = client.chat_stream(query="hello", conversation_id="", user="test")
        # ping events produce no chunks; only message events do
        assert chunks == ["first", "second"]
        assert conv_id == "conv-x"


def test_chat_stream_timeout_raises_dify_api_error():
    from zens.community.dify.dify_client import DifyAPIError, DifyClient

    client = DifyClient(api_key="test-key", base_url="http://localhost:8000")

    # Patch httpx.post to raise TimeoutException, and patch the TimeoutException
    # reference in dify_client's namespace so the except clause matches
    with (
        patch("zens.community.dify.dify_client.httpx.post") as mock_post,
        patch(
            "zens.community.dify.dify_client.httpx.TimeoutException",
            httpx.TimeoutException,
        ),
    ):
        mock_post.side_effect = httpx.TimeoutException("timed out")

        with pytest.raises(DifyAPIError) as exc_info:
            client.chat_stream(query="hello", conversation_id="", user="test")
        assert exc_info.value.status_code == 0
        assert "timed out" in exc_info.value.message


# ───────────────────────────────────────────────────────────────────────────
# astream_chat (async generator) tests
# ───────────────────────────────────────────────────────────────────────────


def test_astream_chat_yields_dify_chunks_per_message_event():
    """Each ``event: message`` line with a non-empty answer yields one DifyChunk."""
    from zens.community.dify.dify_client import DifyChunk, DifyClient

    client = DifyClient(api_key="test-key", base_url="http://localhost:8000")
    mock_lines = [
        b"event: message\n",
        b'data: {"answer": "hel", "conversation_id": "conv-1", "message_id": "msg-1"}\n',
        b"event: message\n",
        b'data: {"answer": "lo", "conversation_id": "conv-1", "message_id": "msg-2"}\n',
    ]
    fake_response = FakeAsyncStreamResponse(mock_lines)

    async def collect():
        chunks: list[DifyChunk] = []
        with patch("zens.community.dify.dify_client.httpx.AsyncClient", lambda **kwargs: FakeAsyncClient(fake_response)):
            async for chunk in client.astream_chat(query="hi", conversation_id="", user="u"):
                chunks.append(chunk)
        return chunks

    import asyncio

    chunks = asyncio.run(collect())
    assert len(chunks) == 2
    assert all(isinstance(c, DifyChunk) for c in chunks)
    assert [c.answer for c in chunks] == ["hel", "lo"]
    assert chunks[0].conversation_id == "conv-1"
    assert chunks[1].message_id == "msg-2"
    assert "".join(c.answer for c in chunks) == "hello"


def test_astream_chat_filters_ping_events():
    from zens.community.dify.dify_client import DifyClient

    client = DifyClient(api_key="test-key", base_url="http://localhost:8000")
    mock_lines = [
        b"event: ping\n",
        b"event: message\n",
        b'data: {"answer": "x", "conversation_id": "c"}\n',
        b"event: ping\n",
    ]
    fake_response = FakeAsyncStreamResponse(mock_lines)

    import asyncio

    async def collect():
        chunks = []
        with patch("zens.community.dify.dify_client.httpx.AsyncClient", lambda **kwargs: FakeAsyncClient(fake_response)):
            async for chunk in client.astream_chat(query="q", conversation_id="", user="u"):
                chunks.append(chunk)
        return chunks

    chunks = asyncio.run(collect())
    assert [c.answer for c in chunks] == ["x"]


def test_astream_chat_http_error_raises_dify_api_error():
    from zens.community.dify.dify_client import DifyAPIError, DifyClient

    client = DifyClient(api_key="test-key", base_url="http://localhost:8000")
    fake_response = FakeAsyncStreamResponse(
        [],
        is_success=False,
        json_data={"message": "Unauthorized"},
        status_code=401,
    )

    import asyncio

    async def collect():
        with patch("zens.community.dify.dify_client.httpx.AsyncClient", lambda **kwargs: FakeAsyncClient(fake_response)):
            async for _ in client.astream_chat(query="q", conversation_id="", user="u"):
                pass

    with pytest.raises(DifyAPIError) as exc_info:
        asyncio.run(collect())
    assert exc_info.value.status_code == 401
    assert "Unauthorized" in exc_info.value.message


def test_astream_chat_timeout_raises_dify_api_error():
    from zens.community.dify.dify_client import DifyAPIError, DifyClient

    client = DifyClient(api_key="test-key", base_url="http://localhost:8000")

    class _TimeoutAsyncClient(FakeAsyncClient):
        def stream(self, method, url, **kwargs):
            raise httpx.TimeoutException("timed out")

    import asyncio

    async def collect():
        with patch("zens.community.dify.dify_client.httpx.AsyncClient", lambda **kwargs: _TimeoutAsyncClient(None)):
            async for _ in client.astream_chat(query="q", conversation_id="", user="u"):
                pass

    with pytest.raises(DifyAPIError) as exc_info:
        asyncio.run(collect())
    assert exc_info.value.status_code == 0
    assert "timed out" in exc_info.value.message
