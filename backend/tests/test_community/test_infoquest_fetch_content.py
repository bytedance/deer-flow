"""Exercise InfoQuest fetch decoding through the real client and public tool."""

import json
import logging
from types import SimpleNamespace

import httpx
import pytest

from deerflow.community.infoquest import infoquest_client, tools
from deerflow.logging_config import UrlRedactionFilter

_URL = "https://example.com/article"
_LOG_URL = "https://example.com/<redacted>"
_HTML = "<html><head><title>Example</title></head><body><p>Example article content.</p></body></html>"


@pytest.fixture(autouse=True)
def redact_captured_urls(caplog):
    # Exercise the production log policy even when this module runs in isolation.
    redaction_filter = UrlRedactionFilter()
    caplog.handler.addFilter(redaction_filter)
    try:
        yield
    finally:
        caplog.handler.removeFilter(redaction_filter)


@pytest.fixture
def responses(monkeypatch):
    queued = []
    requests = []
    clients = []

    def respond(request):
        requests.append(request)
        return queued.pop(0)

    def client_factory(**kwargs):
        client = httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
        clients.append(client)
        return client

    # Patch only this provider's module reference, not the shared HTTPX class.
    monkeypatch.setattr(infoquest_client, "httpx", SimpleNamespace(AsyncClient=client_factory))
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda _: None))
    monkeypatch.setenv("INFOQUEST_API_KEY", "synthetic-test-key")
    yield queued, requests
    assert all(client.is_closed for client in clients)


@pytest.mark.anyio
@pytest.mark.parametrize("field", ["reader_result", "content"])
@pytest.mark.parametrize("value", [None, False, 0, [], {}, ["provider-payload"], {"text": "provider-payload"}])
async def test_fetch_tool_contains_non_text_content(responses, caplog, field, value):
    queued, requests = responses
    queued.append(httpx.Response(200, json={field: value}))

    result = await tools.web_fetch_tool.ainvoke({"url": _URL})

    assert result == "Error: InfoQuest returned an unexpected response format"
    assert len(requests) == 1
    assert json.loads(requests[0].content) == {"url": _URL, "format": "HTML"}
    assert f"InfoQuest returned unexpected {field} type: {type(value).__name__} for URL: {_LOG_URL}" in caplog.text
    assert _URL not in caplog.text
    assert "provider-payload" not in caplog.text
    assert "synthetic-test-key" not in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize("field", ["reader_result", "content"])
@pytest.mark.parametrize("value", ["", " \t\n"])
async def test_fetch_tool_reports_empty_extracted_content(responses, caplog, field, value):
    caplog.set_level(logging.DEBUG, logger=infoquest_client.__name__)
    queued, _ = responses
    queued.append(httpx.Response(200, json={field: value}))

    assert await tools.web_fetch_tool.ainvoke({"url": _URL}) == "Error: no result found"
    assert f"InfoQuest returned empty {field} for URL: {_LOG_URL}" in caplog.text
    assert _URL not in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize("payload", [None, False, 0, 1.5, "provider-payload", "reader_result", [], ["content"]])
async def test_fetch_tool_rejects_non_object_json(responses, caplog, payload):
    queued, requests = responses
    # Explicit serialization is needed because httpx treats json=None as no body.
    queued.append(httpx.Response(200, text=json.dumps(payload)))

    assert await tools.web_fetch_tool.ainvoke({"url": _URL}) == "Error: InfoQuest returned an unexpected response format"
    assert len(requests) == 1
    assert f"InfoQuest returned unexpected response type: {type(payload).__name__} for URL: {_LOG_URL}" in caplog.text
    assert _URL not in caplog.text
    assert "provider-payload" not in caplog.text
    assert "synthetic-test-key" not in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    [{"reader_result": _HTML}, {"content": _HTML}, {"reader_result": _HTML, "content": "secondary"}],
)
async def test_fetch_preserves_text_and_field_precedence(responses, payload):
    queued, _ = responses
    queued.append(httpx.Response(200, json=payload))

    assert await infoquest_client.InfoQuestClient().fetch(_URL) == _HTML


@pytest.mark.anyio
async def test_fetch_preserves_raw_html_and_unknown_json(responses):
    queued, _ = responses
    queued.extend([httpx.Response(200, text=_HTML), httpx.Response(200, text='{"other": "value"}')])
    client = infoquest_client.InfoQuestClient()

    assert await client.fetch(_URL) == _HTML
    assert await client.fetch(_URL) == '{"other": "value"}'


@pytest.mark.anyio
async def test_fetch_does_not_hide_invalid_primary_content_with_secondary(responses):
    queued, _ = responses
    queued.append(httpx.Response(200, json={"reader_result": None, "content": _HTML}))

    assert await tools.web_fetch_tool.ainvoke({"url": _URL}) == "Error: InfoQuest returned an unexpected response format"


@pytest.mark.anyio
async def test_fetch_tool_recovers_on_the_next_request(responses):
    queued, requests = responses
    queued.extend([httpx.Response(200, json={"reader_result": None}), httpx.Response(200, json={"content": _HTML})])

    assert await tools.web_fetch_tool.ainvoke({"url": _URL}) == "Error: InfoQuest returned an unexpected response format"
    result = await tools.web_fetch_tool.ainvoke({"url": _URL + "/next"})

    assert result.startswith("# Example\n")
    assert "Example article content." in result
    assert [json.loads(request.content)["url"] for request in requests] == [_URL, _URL + "/next"]
