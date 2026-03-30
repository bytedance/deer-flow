"""Tests for JinaClient async crawl method."""

import httpx
import pytest

from deerflow.community.jina_ai.jina_client import JinaClient


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
async def test_crawl_no_auth_header_without_api_key(jina_client, monkeypatch):
    """Test that no Authorization header is set when JINA_API_KEY is not available."""
    captured_headers = {}

    async def mock_post(self, url, **kwargs):
        captured_headers.update(kwargs.get("headers", {}))
        return httpx.Response(200, text="ok", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    monkeypatch.delenv("JINA_API_KEY", raising=False)
    await jina_client.crawl("https://example.com")
    assert "Authorization" not in captured_headers
