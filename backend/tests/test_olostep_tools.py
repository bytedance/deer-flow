"""Olostep web_search and web_fetch, driven through an offline HTTPX transport."""

import json
import logging
from types import SimpleNamespace

import httpx
import pytest

_LOGGER_NAME = "deerflow.community.olostep.tools"
_FORMAT_ERROR = "Olostep returned an unexpected response format"
_KEY = "synthetic-olostep-key"
_QUERY = "vector databases private-query"
_URL = "https://example.com/private-page"

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def reset_api_key_warned(monkeypatch):
    from deerflow.community.olostep import tools

    monkeypatch.setattr(tools, "_api_key_warned", set())
    monkeypatch.delenv("OLOSTEP_API_KEY", raising=False)


def _set_config(monkeypatch, extra: dict | None):
    from deerflow.community.olostep import tools

    config = SimpleNamespace(get_tool_config=lambda _name: SimpleNamespace(model_extra=dict(extra)) if extra is not None else None)
    monkeypatch.setattr(tools, "get_app_config", lambda: config)


@pytest.fixture
def olostep(monkeypatch):
    """Route the provider's httpx reference to a MockTransport and record each request."""
    from deerflow.community.olostep import tools

    state = SimpleNamespace(requests=[], status=200, payload={}, error=None)
    real_client = httpx.AsyncClient

    def respond(request: httpx.Request) -> httpx.Response:
        state.requests.append(request)
        if state.error is not None:
            raise state.error
        return httpx.Response(state.status, content=json.dumps(state.payload).encode("utf-8"), headers={"Content-Type": "application/json"})

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(
        tools,
        "httpx",
        SimpleNamespace(AsyncClient=lambda **kwargs: real_client(transport=transport, **kwargs), HTTPStatusError=httpx.HTTPStatusError),
    )
    _set_config(monkeypatch, {"api_key": _KEY})
    state.tools = tools
    return state


async def _search(olostep, **args) -> object:
    return json.loads(await olostep.tools.web_search_tool.ainvoke({"query": _QUERY, **args}))


def _body(request: httpx.Request) -> dict:
    return json.loads(request.content)


class TestWebSearchRequest:
    async def test_posts_query_and_default_limit_with_bearer_key(self, olostep):
        olostep.payload = {"result": {"links": []}}

        await _search(olostep)

        [request] = olostep.requests
        assert request.method == "POST"
        assert str(request.url) == "https://api.olostep.com/v1/searches"
        assert request.headers["Authorization"] == f"Bearer {_KEY}"
        assert _body(request) == {"query": _QUERY, "limit": 5}

    async def test_caller_max_results_wins_over_config(self, olostep, monkeypatch):
        _set_config(monkeypatch, {"api_key": _KEY, "max_results": 3})
        olostep.payload = {"result": {"links": []}}

        await _search(olostep, max_results=8)

        assert _body(olostep.requests[0])["limit"] == 8

    async def test_configured_max_results_used_when_omitted(self, olostep, monkeypatch):
        _set_config(monkeypatch, {"api_key": _KEY, "max_results": 3})
        olostep.payload = {"result": {"links": []}}

        await _search(olostep)

        assert _body(olostep.requests[0])["limit"] == 3

    @pytest.mark.parametrize(("value", "expected"), [(100, 25), (25, 25), (1, 1), (0, 5), (True, 5), (3.5, 5), (float("inf"), 5), ("7", 7)])
    async def test_limit_goes_through_the_shared_owner_and_olostep_cap(self, olostep, monkeypatch, value, expected):
        _set_config(monkeypatch, {"api_key": _KEY, "max_results": value})
        olostep.payload = {"result": {"links": []}}

        await _search(olostep)

        assert _body(olostep.requests[0])["limit"] == expected

    async def test_env_key_used_when_config_key_blank(self, olostep, monkeypatch):
        _set_config(monkeypatch, {"api_key": "  "})
        monkeypatch.setenv("OLOSTEP_API_KEY", "env-key\n")
        olostep.payload = {"result": {"links": []}}

        await _search(olostep)

        assert olostep.requests[0].headers["Authorization"] == "Bearer env-key"

    async def test_missing_key_returns_error_without_a_request(self, olostep, monkeypatch, caplog):
        _set_config(monkeypatch, None)

        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            first = await _search(olostep)
            await _search(olostep)

        assert first == {"error": "OLOSTEP_API_KEY is not configured", "query": _QUERY}
        assert olostep.requests == []
        assert sum("OLOSTEP_API_KEY" in record.getMessage() for record in caplog.records) == 1


class TestWebSearchResponse:
    async def test_normalizes_links_and_screens_urls(self, olostep):
        olostep.payload = {
            "id": "search_1",
            "result": {
                "links": [
                    {"url": "https://ex.com/a", "title": "A", "description": "first"},
                    "not-an-object",
                    {"url": "http://169.254.169.254/latest/meta-data/", "title": "M", "description": "metadata"},
                    {"url": "https://ex.com/b", "title": None, "description": 3},
                ]
            },
        }

        assert await _search(olostep) == [
            {"title": "A", "url": "https://ex.com/a", "snippet": "first"},
            {"title": "M", "url": "", "snippet": "metadata"},
            {"title": "", "url": "https://ex.com/b", "snippet": ""},
        ]

    async def test_trims_to_the_requested_limit(self, olostep):
        olostep.payload = {"result": {"links": [{"url": f"https://ex.com/{i}", "title": str(i), "description": ""} for i in range(4)]}}

        parsed = await _search(olostep, max_results=2)

        assert [row["title"] for row in parsed] == ["0", "1"]

    @pytest.mark.parametrize("payload", [{}, {"result": None}, {"result": {}}, {"result": {"links": None}}, {"result": {"links": []}}])
    async def test_empty_search(self, olostep, payload):
        olostep.payload = payload

        assert await _search(olostep) == {"error": "No results found", "query": _QUERY}

    @pytest.mark.parametrize(
        ("payload", "container"),
        [([], "list"), ({"result": []}, "list"), ({"result": {"links": {}}}, "dict"), ({"result": {"links": ["x", 1]}}, None)],
        ids=["top-level-list", "result-list", "links-dict", "links-without-objects"],
    )
    async def test_malformed_payload_is_a_format_error(self, olostep, payload, container, caplog):
        olostep.payload = payload

        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            assert await _search(olostep) == {"error": _FORMAT_ERROR, "query": _QUERY}

        errors = [record.getMessage() for record in caplog.records if record.name == _LOGGER_NAME]
        assert errors
        if container:
            assert container in errors[0]
        assert _QUERY not in caplog.text

    async def test_http_error_reports_status_and_keeps_body_out_of_logs(self, olostep, caplog):
        olostep.status = 401
        olostep.payload = {"detail": "provider-private-payload"}

        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            parsed = await _search(olostep)

        assert parsed == {"error": "Olostep API error: HTTP 401 (invalid or missing OLOSTEP_API_KEY)", "query": _QUERY}
        assert "provider-private-payload" not in caplog.text
        assert _KEY not in caplog.text

    async def test_transport_error_is_returned_without_the_key(self, olostep, caplog):
        olostep.error = httpx.ConnectError(f"connection refused for {_KEY}")

        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            parsed = await _search(olostep)

        assert parsed["error"].startswith("Olostep request failed: ConnectError")
        assert _KEY not in parsed["error"]
        assert _KEY not in caplog.text
        assert _QUERY not in caplog.text


class TestWebFetch:
    async def _fetch(self, olostep) -> str:
        return await olostep.tools.web_fetch_tool.ainvoke({"url": _URL})

    async def test_posts_scrape_request_and_returns_markdown(self, olostep):
        olostep.payload = {"result": {"markdown_content": "# Body\n\ntext", "page_metadata": {"status_code": 200, "title": "Page"}}}

        result = await self._fetch(olostep)

        [request] = olostep.requests
        assert str(request.url) == "https://api.olostep.com/v1/scrapes"
        assert request.headers["Authorization"] == f"Bearer {_KEY}"
        assert _body(request) == {"url_to_scrape": _URL, "formats": ["markdown"]}
        assert result == "# Page\n\n# Body\n\ntext"

    async def test_reads_the_web_fetch_config_section(self, olostep, monkeypatch):
        from deerflow.community.olostep import tools

        sections = {"web_fetch": SimpleNamespace(model_extra={"api_key": "fetch-key"})}
        monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=sections.get))
        olostep.payload = {"result": {"markdown_content": "text"}}

        await self._fetch(olostep)

        assert olostep.requests[0].headers["Authorization"] == "Bearer fetch-key"

    @pytest.mark.parametrize("metadata", [None, {}, {"title": ""}, {"title": 7}, "x"])
    async def test_untitled_when_metadata_has_no_title(self, olostep, metadata):
        olostep.payload = {"result": {"markdown_content": "text", "page_metadata": metadata}}

        assert await self._fetch(olostep) == "# Untitled\n\ntext"

    async def test_content_capped_at_4096_chars(self, olostep):
        olostep.payload = {"result": {"markdown_content": "x" * 5000}}

        result = await self._fetch(olostep)

        assert result == "# Untitled\n\n" + "x" * 4096

    @pytest.mark.parametrize("payload", [{}, {"result": {}}, {"result": {"markdown_content": None}}, {"result": {"markdown_content": "  "}}])
    async def test_no_content(self, olostep, payload):
        olostep.payload = payload

        assert await self._fetch(olostep) == "Error: No content found"

    @pytest.mark.parametrize("payload", [[], {"result": "x"}])
    async def test_malformed_payload_is_a_format_error(self, olostep, payload, caplog):
        olostep.payload = payload

        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            assert await self._fetch(olostep) == f"Error: {_FORMAT_ERROR}"

        assert "example.com" not in caplog.text

    async def test_http_error(self, olostep, caplog):
        olostep.status = 500
        olostep.payload = {"detail": "provider-private-payload"}

        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            assert await self._fetch(olostep) == "Error: Olostep API error: HTTP 500"

        assert "provider-private-payload" not in caplog.text
        assert "example.com" not in caplog.text

    async def test_missing_key(self, olostep, monkeypatch):
        _set_config(monkeypatch, {})

        assert await self._fetch(olostep) == "Error: OLOSTEP_API_KEY is not configured"
        assert olostep.requests == []
