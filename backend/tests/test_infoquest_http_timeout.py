"""InfoQuest's remote crawl timeout must not leave local HTTP waits unbounded."""

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from deerflow.community.infoquest.infoquest_client import InfoQuestClient

_SEARCH_PAYLOAD = {"search_result": {"results": []}}


def _mock_async_client_cls() -> MagicMock:
    client = MagicMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    client.post = AsyncMock()
    cls = MagicMock()
    cls.return_value = client
    return cls


def _install_response(monkeypatch, response: httpx.Response):
    mock_async_client_cls = _mock_async_client_cls()
    mock_async_client_cls.return_value.post.return_value = response
    monkeypatch.setattr("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient", mock_async_client_cls)
    monkeypatch.setenv("INFOQUEST_API_KEY", "test-placeholder")
    return mock_async_client_cls


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["fetch", "web_search", "image_search"])
async def test_infoquest_sets_transport_timeout(monkeypatch, operation):
    post_url = "https://reader.infoquest.bytepluses.com" if operation == "fetch" else "https://search.infoquest.bytepluses.com"
    if operation == "fetch":
        response = httpx.Response(200, text=json.dumps({"reader_result": "<p>Content</p>"}), request=httpx.Request("POST", post_url))
    else:
        response = httpx.Response(200, json=_SEARCH_PAYLOAD, request=httpx.Request("POST", post_url))
    mock_async_client_cls = _install_response(monkeypatch, response)

    client = InfoQuestClient(fetch_timeout=10, fetch_navigation_timeout=20)
    result = await getattr(client, operation)("https://example.com" if operation == "fetch" else "query")

    assert result == ("<p>Content</p>" if operation == "fetch" else "[]")
    mock_async_client_cls.return_value.post.assert_awaited_once()
    assert mock_async_client_cls.return_value.post.call_args.kwargs["timeout"] == 30
    if operation == "fetch":
        assert mock_async_client_cls.return_value.post.call_args.kwargs["json"]["timeout"] == 10
        assert mock_async_client_cls.return_value.post.call_args.kwargs["json"]["navi_timeout"] == 20


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["fetch", "web_search", "image_search"])
@pytest.mark.parametrize("error_type", [httpx.ConnectTimeout, httpx.ReadTimeout])
async def test_infoquest_transport_timeout_returns_existing_error(monkeypatch, operation, error_type):
    mock_async_client_cls = _mock_async_client_cls()
    mock_async_client_cls.return_value.post.side_effect = error_type("synthetic timeout")
    monkeypatch.setattr("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient", mock_async_client_cls)
    monkeypatch.setenv("INFOQUEST_API_KEY", "test-placeholder")

    result = await getattr(InfoQuestClient(), operation)("https://example.com" if operation == "fetch" else "query")

    assert result.startswith("Error:")
    assert "synthetic timeout" in result
