"""Tests for JinaClient async crawl method."""

import logging
from unittest.mock import MagicMock

import httpx
import pytest

import deerflow.community.jina_ai.jina_client as jina_client_module
from deerflow.community.jina_ai.jina_client import JinaClient
from deerflow.community.jina_ai.tools import (
    _coerce_bool,
    _coerce_proxy,
    _coerce_timeout,
    web_fetch_tool,
)


@pytest.fixture
def jina_client():
    return JinaClient()


@pytest.mark.anyio
async def test_crawl_success(jina_client, monkeypatch):
    """Test successful crawl returns response text."""

    async def mock_post(self, url, **kwargs):
        return httpx.Response(200, text="<html><body>Hello</body></html>", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    result = await jina_client.crawl("https://example.com")
    assert result == "<html><body>Hello</body></html>"


@pytest.mark.anyio
async def test_crawl_non_200_status(jina_client, monkeypatch):
    """Test that non-200 status returns error message."""

    async def mock_post(self, url, **kwargs):
        return httpx.Response(429, text="Rate limited", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    result = await jina_client.crawl("https://example.com")
    assert result.startswith("Error:")
    assert "429" in result


@pytest.mark.anyio
async def test_crawl_empty_response(jina_client, monkeypatch):
    """Test that empty response returns error message."""

    async def mock_post(self, url, **kwargs):
        return httpx.Response(200, text="", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    result = await jina_client.crawl("https://example.com")
    assert result.startswith("Error:")
    assert "empty" in result.lower()


@pytest.mark.anyio
async def test_crawl_whitespace_only_response(jina_client, monkeypatch):
    """Test that whitespace-only response returns error message."""

    async def mock_post(self, url, **kwargs):
        return httpx.Response(200, text="   \n  ", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    result = await jina_client.crawl("https://example.com")
    assert result.startswith("Error:")
    assert "empty" in result.lower()


@pytest.mark.anyio
async def test_crawl_network_error(jina_client, monkeypatch):
    """Test that network errors are handled gracefully."""

    async def mock_post(self, url, **kwargs):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    result = await jina_client.crawl("https://example.com")
    assert result.startswith("Error:")
    assert "failed" in result.lower()


@pytest.mark.anyio
async def test_crawl_transient_failure_logs_without_traceback(jina_client, monkeypatch, caplog):
    """Transient network failures must log at WARNING without a traceback and include the exception type."""

    async def mock_post(self, url, **kwargs):
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    with caplog.at_level(logging.DEBUG, logger="deerflow.community.jina_ai.jina_client"):
        result = await jina_client.crawl("https://example.com")

    jina_records = [r for r in caplog.records if r.name == "deerflow.community.jina_ai.jina_client"]
    assert len(jina_records) == 1, f"expected exactly one log record, got {len(jina_records)}"
    record = jina_records[0]
    assert record.levelno == logging.WARNING, f"expected WARNING, got {record.levelname}"
    assert record.exc_info is None, "transient failures must not attach a traceback"
    assert "ConnectTimeout" in record.getMessage()
    assert result.startswith("Error:")
    assert "ConnectTimeout" in result


@pytest.mark.anyio
async def test_crawl_passes_headers(jina_client, monkeypatch):
    """Test that correct headers are sent."""
    captured_headers = {}

    async def mock_post(self, url, **kwargs):
        captured_headers.update(kwargs.get("headers", {}))
        return httpx.Response(200, text="ok", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    await jina_client.crawl("https://example.com", return_format="markdown", timeout=30)
    assert captured_headers["X-Return-Format"] == "markdown"
    assert captured_headers["X-Timeout"] == "30"


@pytest.mark.anyio
async def test_crawl_passes_proxy_to_httpx_client(jina_client, monkeypatch):
    """Explicit proxy config should be passed to httpx.AsyncClient."""
    captured_client_kwargs = {}

    class MockAsyncClient:
        def __init__(self, **kwargs):
            captured_client_kwargs.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, **kwargs):
            return httpx.Response(200, text="ok", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    result = await jina_client.crawl("https://example.com", proxy="http://127.0.0.1:7890")

    assert result == "ok"
    assert captured_client_kwargs["proxy"] == "http://127.0.0.1:7890"
    assert captured_client_kwargs["trust_env"] is True


@pytest.mark.anyio
async def test_crawl_can_disable_trust_env(jina_client, monkeypatch):
    """Callers can disable environment proxy lookup for deterministic networking."""
    captured_client_kwargs = {}

    class MockAsyncClient:
        def __init__(self, **kwargs):
            captured_client_kwargs.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, **kwargs):
            return httpx.Response(200, text="ok", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    result = await jina_client.crawl("https://example.com", trust_env=False)

    assert result == "ok"
    assert captured_client_kwargs == {"trust_env": False}


@pytest.mark.anyio
async def test_crawl_includes_api_key_when_set(jina_client, monkeypatch):
    """Test that Authorization header is set when JINA_API_KEY is available."""
    captured_headers = {}

    async def mock_post(self, url, **kwargs):
        captured_headers.update(kwargs.get("headers", {}))
        return httpx.Response(200, text="ok", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    monkeypatch.setenv("JINA_API_KEY", "test-key-123")
    await jina_client.crawl("https://example.com")
    assert captured_headers["Authorization"] == "Bearer test-key-123"


@pytest.mark.anyio
async def test_crawl_warns_once_when_api_key_missing(jina_client, monkeypatch, caplog):
    """Test that the missing API key warning is logged only once."""
    jina_client_module._api_key_warned = False

    async def mock_post(self, url, **kwargs):
        return httpx.Response(200, text="ok", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    monkeypatch.delenv("JINA_API_KEY", raising=False)

    with caplog.at_level(logging.WARNING, logger="deerflow.community.jina_ai.jina_client"):
        await jina_client.crawl("https://example.com")
        await jina_client.crawl("https://example.com")

    warning_count = sum(1 for record in caplog.records if "Jina API key is not set" in record.message)
    assert warning_count == 1


@pytest.mark.anyio
async def test_crawl_no_auth_header_without_api_key(jina_client, monkeypatch):
    """Test that no Authorization header is set when JINA_API_KEY is not available."""
    jina_client_module._api_key_warned = False
    captured_headers = {}

    async def mock_post(self, url, **kwargs):
        captured_headers.update(kwargs.get("headers", {}))
        return httpx.Response(200, text="ok", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    monkeypatch.delenv("JINA_API_KEY", raising=False)
    await jina_client.crawl("https://example.com")
    assert "Authorization" not in captured_headers


@pytest.mark.anyio
async def test_web_fetch_tool_returns_error_on_crawl_failure(monkeypatch):
    """Test that web_fetch_tool short-circuits and returns the error string when crawl fails."""

    async def mock_crawl(self, url, **kwargs):
        return "Error: Jina API returned status 429: Rate limited"

    mock_config = MagicMock()
    mock_config.get_tool_config.return_value = None
    monkeypatch.setattr("deerflow.community.jina_ai.tools.get_app_config", lambda: mock_config)
    monkeypatch.setattr(JinaClient, "crawl", mock_crawl)
    result = await web_fetch_tool.ainvoke("https://example.com")
    assert result.startswith("Error:")
    assert "429" in result


@pytest.mark.anyio
async def test_web_fetch_tool_returns_markdown_on_success(monkeypatch):
    """Test that web_fetch_tool returns extracted markdown on successful crawl."""

    async def mock_crawl(self, url, **kwargs):
        return "<html><body><p>Hello world</p></body></html>"

    mock_config = MagicMock()
    mock_config.get_tool_config.return_value = None
    monkeypatch.setattr("deerflow.community.jina_ai.tools.get_app_config", lambda: mock_config)
    monkeypatch.setattr(JinaClient, "crawl", mock_crawl)
    result = await web_fetch_tool.ainvoke("https://example.com")
    assert "Hello world" in result
    assert not result.startswith("Error:")


@pytest.mark.anyio
async def test_web_fetch_tool_forwards_proxy_and_trust_env(monkeypatch):
    """web_fetch tool config should be forwarded to JinaClient.crawl."""
    captured_crawl_kwargs = {}

    async def mock_crawl(self, url, **kwargs):
        captured_crawl_kwargs.update(kwargs)
        return "<html><body><p>Hello world</p></body></html>"

    mock_config = MagicMock()
    mock_tool_config = MagicMock()
    mock_tool_config.model_extra = {
        "timeout": "20",
        "proxy": "http://host.docker.internal:7890",
        "trust_env": "false",
    }
    mock_config.get_tool_config.return_value = mock_tool_config
    monkeypatch.setattr("deerflow.community.jina_ai.tools.get_app_config", lambda: mock_config)
    monkeypatch.setattr(JinaClient, "crawl", mock_crawl)

    result = await web_fetch_tool.ainvoke("https://example.com")

    assert "Hello world" in result
    assert captured_crawl_kwargs == {
        "return_format": "html",
        "timeout": 20,
        "proxy": "http://host.docker.internal:7890",
        "trust_env": False,
    }


@pytest.mark.anyio
async def test_web_fetch_tool_ignores_empty_proxy(monkeypatch):
    """Empty proxy values from unresolved env vars should not be passed to httpx."""
    captured_crawl_kwargs = {}

    async def mock_crawl(self, url, **kwargs):
        captured_crawl_kwargs.update(kwargs)
        return "<html><body><p>Hello world</p></body></html>"

    mock_config = MagicMock()
    mock_tool_config = MagicMock()
    mock_tool_config.model_extra = {"proxy": "   ", "trust_env": True}
    mock_config.get_tool_config.return_value = mock_tool_config
    monkeypatch.setattr("deerflow.community.jina_ai.tools.get_app_config", lambda: mock_config)
    monkeypatch.setattr(JinaClient, "crawl", mock_crawl)

    result = await web_fetch_tool.ainvoke("https://example.com")

    assert "Hello world" in result
    assert captured_crawl_kwargs["proxy"] is None
    assert captured_crawl_kwargs["trust_env"] is True


@pytest.mark.anyio
async def test_web_fetch_tool_offloads_extraction_to_thread(monkeypatch):
    """Test that readability extraction is offloaded via asyncio.to_thread to avoid blocking the event loop."""
    import asyncio

    async def mock_crawl(self, url, **kwargs):
        return "<html><body><p>threaded</p></body></html>"

    mock_config = MagicMock()
    mock_config.get_tool_config.return_value = None
    monkeypatch.setattr("deerflow.community.jina_ai.tools.get_app_config", lambda: mock_config)
    monkeypatch.setattr(JinaClient, "crawl", mock_crawl)

    to_thread_called = False
    original_to_thread = asyncio.to_thread

    async def tracking_to_thread(func, *args, **kwargs):
        nonlocal to_thread_called
        to_thread_called = True
        return await original_to_thread(func, *args, **kwargs)

    monkeypatch.setattr("deerflow.community.jina_ai.tools.asyncio.to_thread", tracking_to_thread)
    result = await web_fetch_tool.ainvoke("https://example.com")
    assert to_thread_called, "extract_article must be called via asyncio.to_thread to avoid blocking the event loop"
    assert "threaded" in result


@pytest.mark.parametrize(
    ("value", "default", "expected"),
    [
        (True, False, True),
        (False, True, False),
        ("true", False, True),
        ("YES", False, True),
        (" on ", False, True),
        ("1", False, True),
        ("false", True, False),
        ("No", True, False),
        ("off", True, False),
        ("0", True, False),
        ("maybe", True, True),
        ("maybe", False, False),
        (None, True, True),
        (123, False, False),
    ],
)
def test_coerce_bool(value, default, expected):
    """_coerce_bool normalizes booleans, known strings, and falls back to the default."""
    assert _coerce_bool(value, default) is expected


@pytest.mark.parametrize(
    ("value", "default", "expected"),
    [
        (30, 10, 30),
        ("45", 10, 45),
        ("not-a-number", 10, 10),
        (True, 10, 10),
        (False, 10, 10),
        (None, 10, 10),
        (1.5, 10, 10),
    ],
)
def test_coerce_timeout(value, default, expected):
    """_coerce_timeout accepts ints and numeric strings, rejecting bools and junk."""
    assert _coerce_timeout(value, default) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("http://127.0.0.1:7890", "http://127.0.0.1:7890"),
        ("  http://proxy:8080  ", "http://proxy:8080"),
        ("", None),
        ("   ", None),
        (None, None),
        (123, None),
    ],
)
def test_coerce_proxy(value, expected):
    """_coerce_proxy trims strings and treats empty/non-string values as None."""
    assert _coerce_proxy(value) == expected
