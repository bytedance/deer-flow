"""GroundRoute web_search/web_fetch must contain malformed HTTP-success payloads."""

import json
import logging
from types import SimpleNamespace

import httpx
import pytest

_LOGGER_NAME = "deerflow.community.groundroute.tools"
_FORMAT_ERROR = "GroundRoute returned an unexpected response format"
_SEARCH_QUERY = "文档 search"
_FETCH_URL = "https://example.com/文档"


@pytest.fixture(autouse=True)
def reset_api_key_warned():
    import deerflow.community.groundroute.tools as gr_mod

    gr_mod._api_key_warned = set()
    yield
    gr_mod._api_key_warned = set()


def _invoker(monkeypatch, tool_name):
    """Patch the provider's httpx reference with a local MockTransport client factory."""
    from deerflow.community.groundroute import tools

    config = SimpleNamespace(get_tool_config=lambda _: SimpleNamespace(model_extra={"api_key": "synthetic-test-key"}))
    monkeypatch.setattr(tools, "get_app_config", lambda: config)
    real_client = httpx.Client

    def invoke(payload, *, status_code=200):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(status_code, content=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})

        transport = httpx.MockTransport(respond)
        monkeypatch.setattr(
            tools,
            "httpx",
            SimpleNamespace(Client=lambda **kwargs: real_client(transport=transport, **kwargs), HTTPStatusError=httpx.HTTPStatusError),
        )
        if tool_name == "web_search":
            result = tools.web_search_tool.invoke({"query": _SEARCH_QUERY})
        else:
            result = tools.web_fetch_tool.invoke({"url": _FETCH_URL})
        assert len(requests) == 1
        return result

    return invoke


@pytest.fixture
def invoke_search(monkeypatch):
    return _invoker(monkeypatch, "web_search")


@pytest.fixture
def invoke_fetch(monkeypatch):
    return _invoker(monkeypatch, "web_fetch")


def _search(invoke_search, payload, *, status_code=200):
    return json.loads(invoke_search(payload, status_code=status_code))


def _error_logs(caplog):
    return [record.getMessage() for record in caplog.records if record.name == _LOGGER_NAME and record.levelno == logging.ERROR]


def _assert_no_payload_values_leaked(caplog):
    assert "文档 search" not in caplog.text
    assert "example.com" not in caplog.text
    assert "synthetic-test-key" not in caplog.text
    assert "provider-private-payload" not in caplog.text


@pytest.mark.parametrize("payload", [None, False, 0, "invalid", [], ["provider-private-payload"]])
def test_malformed_top_level_payload_returns_format_error(invoke_search, payload, caplog):
    assert _search(invoke_search, payload) == {"error": _FORMAT_ERROR, "query": "文档 search"}
    assert _error_logs(caplog) == [f"GroundRoute returned unexpected payload type: {type(payload).__name__}"]
    _assert_no_payload_values_leaked(caplog)


@pytest.mark.parametrize("results", [False, 0, "", "provider-private-payload", {}, {"title": "provider-private-payload"}])
def test_malformed_results_container_returns_format_error(invoke_search, results, caplog):
    assert _search(invoke_search, {"results": results}) == {"error": _FORMAT_ERROR, "query": "文档 search"}
    assert _error_logs(caplog) == [f"GroundRoute returned unexpected 'results' payload type: {type(results).__name__}"]
    _assert_no_payload_values_leaked(caplog)


@pytest.mark.parametrize("results", [[None], [False, 0, "provider-private-payload", []]])
def test_all_malformed_entries_return_format_error(invoke_search, results, caplog):
    assert _search(invoke_search, {"results": results}) == {"error": _FORMAT_ERROR, "query": "文档 search"}
    assert _error_logs(caplog) == ["GroundRoute returned 'results' with no usable result objects"]
    _assert_no_payload_values_leaked(caplog)


def test_mixed_entries_preserve_valid_results_in_order(invoke_search, caplog):
    payload = {"results": [None, {"title": "文档", "url": "https://other.example/one", "snippet": "概述", "source_engine": "serper"}, "invalid", {}, [], {"title": "Second"}]}
    assert _search(invoke_search, payload) == [
        {"title": "文档", "url": "https://other.example/one", "snippet": "概述", "source_engine": "serper"},
        {"title": "", "url": "", "snippet": "", "source_engine": ""},
        {"title": "Second", "url": "", "snippet": "", "source_engine": ""},
    ]
    assert _error_logs(caplog) == []


@pytest.mark.parametrize("payload", [{}, {"results": None}, {"request_id": "r1"}, {"results": []}])
def test_missing_or_empty_results_keep_no_results_response(invoke_search, payload, caplog):
    assert _search(invoke_search, payload) == {"error": "No results found", "query": "文档 search"}
    assert _error_logs(caplog) == []


def test_valid_results_keep_existing_normalization(invoke_search, caplog):
    payload = {"results": [{"title": "T", "url": "https://other.example", "snippet": "s", "source_engine": "exa"}, {}]}
    assert _search(invoke_search, payload) == [
        {"title": "T", "url": "https://other.example", "snippet": "s", "source_engine": "exa"},
        {"title": "", "url": "", "snippet": "", "source_engine": ""},
    ]
    assert _error_logs(caplog) == []


@pytest.mark.parametrize("payload", [None, False, [], "provider-private-payload", {"results": {"0": "provider-private-payload"}}, {"results": [None]}])
def test_fetch_malformed_payload_returns_format_error(invoke_fetch, payload, caplog):
    assert invoke_fetch(payload) == "Error: GroundRoute returned an unexpected response format"
    assert len(_error_logs(caplog)) == 1
    _assert_no_payload_values_leaked(caplog)


def test_fetch_missing_or_empty_results_keep_no_results_error(invoke_fetch, caplog):
    assert invoke_fetch({"results": []}) == "Error: No results found"
    assert invoke_fetch({}) == "Error: No results found"
    assert _error_logs(caplog) == []


def test_fetch_skips_malformed_entries_and_returns_the_first_usable_result(invoke_fetch):
    assert invoke_fetch({"results": [None, {"title": "Page", "content": "Body text", "url": "https://other.example"}]}) == "# Page\n\nBody text"


def test_valid_fetch_keeps_existing_response(invoke_fetch, caplog):
    assert invoke_fetch({"results": [{"title": "Page", "content": "Body text"}]}) == "# Page\n\nBody text"
    assert _error_logs(caplog) == []


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"results": [{"title": "Page", "content": 12345}]}, "# Page\n\n12345"),
        ({"results": [{"title": "Page", "content": True}]}, "# Page\n\nTrue"),
        ({"results": [{"title": "Page", "content": {"a": 1}}]}, "# Page\n\n{'a': 1}"),
        ({"results": [{"title": "Page", "snippet": 6789}]}, "# Page\n\n6789"),
        ({"results": [{"title": None, "content": "Body text"}]}, "# \n\nBody text"),
    ],
)
def test_fetch_coerces_non_string_fields(invoke_fetch, payload, expected, caplog):
    assert invoke_fetch(payload) == expected
    assert _error_logs(caplog) == []


def test_http_transport_patch_does_not_replace_global_client(invoke_search):
    real_client = httpx.Client
    invoke_search({"results": []})
    assert httpx.Client is real_client
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(204))) as client:
        assert client.get("https://unrelated.invalid/probe").status_code == 204


@pytest.mark.parametrize("status_code", [402, 503])
def test_search_http_error_keeps_existing_structured_response(invoke_search, status_code):
    assert _search(invoke_search, {"error": "synthetic-denial"}, status_code=status_code) == {"error": f"GroundRoute API error: HTTP {status_code}", "query": "文档 search"}


def test_fetch_http_error_keeps_existing_error_string(invoke_fetch):
    assert invoke_fetch({"error": "synthetic-denial"}, status_code=402) == "Error: GroundRoute API error: HTTP 402"
