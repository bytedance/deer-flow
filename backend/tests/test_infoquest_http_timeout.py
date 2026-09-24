"""InfoQuest's remote crawl timeout must not leave local HTTP waits unbounded."""

from unittest.mock import Mock

import pytest
import requests

from deerflow.community.infoquest.infoquest_client import InfoQuestClient


@pytest.mark.parametrize("operation", ["fetch", "web_search", "image_search"])
def test_infoquest_sets_transport_timeout(monkeypatch, operation):
    response = Mock(status_code=200, text='{"reader_result":"<p>Content</p>"}')
    response.json.return_value = {"search_result": {"results": []}}
    post = Mock(return_value=response)
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setenv("INFOQUEST_API_KEY", "test-placeholder")
    client = InfoQuestClient(fetch_timeout=10, fetch_navigation_timeout=20)
    result = getattr(client, operation)("https://example.com" if operation == "fetch" else "query")
    assert result == ("<p>Content</p>" if operation == "fetch" else "[]")
    post.assert_called_once()
    assert post.call_args.kwargs["timeout"] == 30
    if operation == "fetch":
        assert post.call_args.kwargs["json"]["timeout"] == 10
        assert post.call_args.kwargs["json"]["navi_timeout"] == 20


@pytest.mark.parametrize("operation", ["fetch", "web_search", "image_search"])
@pytest.mark.parametrize("error_type", [requests.ConnectTimeout, requests.ReadTimeout])
def test_infoquest_transport_timeout_returns_existing_error(monkeypatch, operation, error_type):
    monkeypatch.setattr(requests, "post", Mock(side_effect=error_type("synthetic timeout")))
    monkeypatch.setenv("INFOQUEST_API_KEY", "test-placeholder")
    result = getattr(InfoQuestClient(), operation)("https://example.com" if operation == "fetch" else "query")
    assert result.startswith("Error:")
    assert "synthetic timeout" in result
