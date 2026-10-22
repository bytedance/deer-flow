"""Preserve the target HTTP status across both Unbrowse MCP payload forms."""

import json
from types import SimpleNamespace

import httpx
import pytest

from deerflow.community.unbrowse import tools


@pytest.mark.parametrize("structured", [False, True], ids=["text", "structured"])
@pytest.mark.parametrize("status", [400, 403, 404, 429, 500, 503, 599])
def test_fetch_warns_about_target_http_failure(monkeypatch, structured, status):
    result = _fetch(monkeypatch, structured, {"title": "Page", "statusCode": status})
    assert result == f"Warning: target page responded with HTTP {status}.\n\n# Page\n\nBody"


@pytest.mark.parametrize("structured", [False, True], ids=["text", "structured"])
@pytest.mark.parametrize("metadata", [None, {}, {"statusCode": 200}, {"statusCode": 301}, {"statusCode": None}, {"statusCode": "404"}, {"statusCode": True}, {"statusCode": 404.5}, {"statusCode": []}, {"statusCode": 600}])
def test_fetch_preserves_response_without_valid_error_status(monkeypatch, structured, metadata):
    assert _fetch(monkeypatch, structured, metadata) == "# Untitled\n\nBody"


def _fetch(monkeypatch, structured, metadata):
    payload = {"markdown": "Body", "metadata": metadata}
    result = {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False}
    if structured:
        result["structuredContent"] = payload
    requests = []

    def respond(request):
        requests.append(request)
        assert json.loads(request.content)["params"]["name"] == "unbrowse.scrape"
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    real_client = httpx.Client
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(tools.httpx, "Client", lambda **kwargs: real_client(transport=transport, **kwargs))
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda _: SimpleNamespace(model_extra={"api_key": "synthetic"})))
    output = tools.web_fetch_tool.invoke({"url": "https://example.invalid/page"})
    assert len(requests) == 1
    return output
