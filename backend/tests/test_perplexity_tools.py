"""Unit tests for the Perplexity Search API community web search tool."""

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

ENDPOINT = "https://api.perplexity.ai/search"

pytestmark = pytest.mark.anyio


@pytest.fixture
def mock_config_with_key():
    with patch("deerflow.community.perplexity.tools.get_app_config") as mock:
        tool_config = MagicMock()
        tool_config.model_extra = {"api_key": "test-pplx-key", "max_results": 5}
        mock.return_value.get_tool_config.return_value = tool_config
        yield mock


@pytest.fixture
def mock_config_no_key():
    with patch("deerflow.community.perplexity.tools.get_app_config") as mock:
        tool_config = MagicMock()
        tool_config.model_extra = {}
        mock.return_value.get_tool_config.return_value = tool_config
        yield mock


def _make_response(payload: object) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.json.return_value = payload
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def _patch_post(mock_resp: MagicMock):
    """Patch httpx.AsyncClient so the context-managed .post returns mock_resp."""
    patcher = patch("deerflow.community.perplexity.tools.httpx.AsyncClient")
    mock_client_cls = patcher.start()
    mock_client_cls.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
    return patcher, mock_client_cls


def _post_call(mock_client_cls):
    return mock_client_cls.return_value.__aenter__.return_value.post.call_args


def _result(**overrides) -> dict:
    result = {"title": "A", "url": "https://ex.com/a", "snippet": "s1", "date": "2026-10-01", "last_updated": "2026-10-02"}
    result.update(overrides)
    return result


def _payload(*results: dict) -> dict:
    return {"id": "req-1", "results": list(results) or [_result()]}


class TestResolveToolSettings:
    def test_returns_config_key_when_present(self):
        with patch("deerflow.community.perplexity.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "from-config"}
            mock.return_value.get_tool_config.return_value = tool_config

            from deerflow.community.perplexity.tools import _resolve_tool_settings

            assert _resolve_tool_settings("web_search")[0] == "from-config"

    def test_falls_back_to_env_when_config_key_blank(self):
        with patch("deerflow.community.perplexity.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "   "}
            mock.return_value.get_tool_config.return_value = tool_config
            with patch.dict("os.environ", {"PERPLEXITY_API_KEY": "env-key"}, clear=True):
                from deerflow.community.perplexity.tools import _resolve_tool_settings

                assert _resolve_tool_settings("web_search")[0] == "env-key"

    def test_returns_none_when_no_key_anywhere(self):
        with patch("deerflow.community.perplexity.tools.get_app_config") as mock:
            mock.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {}, clear=True):
                from deerflow.community.perplexity.tools import _resolve_tool_settings

                api_key, max_results, search_type, domain_filter = _resolve_tool_settings("web_search")

        assert api_key is None
        assert max_results is None
        assert search_type == "web"
        assert domain_filter == []

    @pytest.mark.parametrize(("raw", "expected"), [("fast", "fast"), (" Web ", "web"), ("people", "web"), (3, "web")])
    def test_search_type_is_validated(self, raw, expected):
        with patch("deerflow.community.perplexity.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "k", "search_type": raw}
            mock.return_value.get_tool_config.return_value = tool_config

            from deerflow.community.perplexity.tools import _resolve_tool_settings

            assert _resolve_tool_settings("web_search")[2] == expected

    def test_domain_filter_drops_blanks_and_truncates_to_twenty(self):
        with patch("deerflow.community.perplexity.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "k", "search_domain_filter": [" a.com ", "", 7, *[f"d{i}.com" for i in range(25)]]}
            mock.return_value.get_tool_config.return_value = tool_config

            from deerflow.community.perplexity.tools import _resolve_tool_settings

            domain_filter = _resolve_tool_settings("web_search")[3]

        assert domain_filter[0] == "a.com"
        assert len(domain_filter) == 20

    def test_non_list_domain_filter_is_ignored(self):
        with patch("deerflow.community.perplexity.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "k", "search_domain_filter": "a.com"}
            mock.return_value.get_tool_config.return_value = tool_config

            from deerflow.community.perplexity.tools import _resolve_tool_settings

            assert _resolve_tool_settings("web_search")[3] == []


class TestRequestShape:
    async def test_posts_bearer_key_and_attribution_headers(self, mock_config_with_key):
        patcher, mock_client_cls = _patch_post(_make_response(_payload()))
        try:
            from deerflow.community.perplexity.tools import web_search_tool

            await web_search_tool.ainvoke({"query": "test"})
            call = _post_call(mock_client_cls)
        finally:
            patcher.stop()

        assert call.args[0] == ENDPOINT
        headers = call.kwargs["headers"]
        assert headers["Authorization"] == "Bearer test-pplx-key"
        assert headers["X-Pplx-Integration"] == "deer-flow"
        assert headers["User-Agent"].startswith("deerflow-harness/")
        assert "deer-flow/bytedance-deer-flow" in headers["User-Agent"]
        assert call.kwargs["json"] == {"query": "test", "max_results": 5, "search_type": "web"}

    async def test_env_key_is_used_when_config_has_none(self, mock_config_no_key):
        with patch.dict("os.environ", {"PERPLEXITY_API_KEY": "env-key"}, clear=True):
            patcher, mock_client_cls = _patch_post(_make_response(_payload()))
            try:
                from deerflow.community.perplexity.tools import web_search_tool

                await web_search_tool.ainvoke({"query": "test"})
                call = _post_call(mock_client_cls)
            finally:
                patcher.stop()

        assert call.kwargs["headers"]["Authorization"] == "Bearer env-key"

    async def test_missing_key_returns_error_without_request(self, mock_config_no_key):
        with patch.dict("os.environ", {}, clear=True):
            patcher, mock_client_cls = _patch_post(_make_response(_payload()))
            try:
                from deerflow.community.perplexity.tools import web_search_tool

                parsed = json.loads(await web_search_tool.ainvoke({"query": "test"}))
            finally:
                patcher.stop()

        assert "PERPLEXITY_API_KEY" in parsed["error"]
        assert parsed["query"] == "test"
        assert not mock_client_cls.called

    async def test_time_range_maps_to_recency_filter(self, mock_config_with_key):
        patcher, mock_client_cls = _patch_post(_make_response(_payload()))
        try:
            from deerflow.community.perplexity.tools import web_search_tool

            await web_search_tool.ainvoke({"query": "test", "time_range": "week"})
            body = _post_call(mock_client_cls).kwargs["json"]
        finally:
            patcher.stop()

        assert body["search_recency_filter"] == "week"

    async def test_recency_filter_omitted_without_time_range(self, mock_config_with_key):
        patcher, mock_client_cls = _patch_post(_make_response(_payload()))
        try:
            from deerflow.community.perplexity.tools import web_search_tool

            await web_search_tool.ainvoke({"query": "test"})
            body = _post_call(mock_client_cls).kwargs["json"]
        finally:
            patcher.stop()

        assert "search_recency_filter" not in body
        assert "search_domain_filter" not in body

    @pytest.mark.parametrize(
        "domains",
        [["ex.com", "docs.ex.org"], ["-spam.com", "-ads.example"]],
        ids=["inclusion-only", "exclusion-only"],
    )
    async def test_configured_search_type_and_domain_filter_are_sent(self, domains):
        """The API takes one mode per request: all included or all excluded domains."""
        with patch("deerflow.community.perplexity.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "k", "search_type": "fast", "search_domain_filter": domains}
            mock.return_value.get_tool_config.return_value = tool_config
            patcher, mock_client_cls = _patch_post(_make_response(_payload()))
            try:
                from deerflow.community.perplexity.tools import web_search_tool

                await web_search_tool.ainvoke({"query": "test"})
                body = _post_call(mock_client_cls).kwargs["json"]
            finally:
                patcher.stop()

        assert body["search_type"] == "fast"
        assert body["search_domain_filter"] == domains


class TestWebSearchTool:
    async def test_returns_normalized_list(self, mock_config_with_key):
        payload = _payload(
            _result(url="https://ex.com/a", title="A", snippet="s1"),
            _result(url="https://ex.com/b", title="B", snippet="s2"),
        )
        patcher, _ = _patch_post(_make_response(payload))
        try:
            from deerflow.community.perplexity.tools import web_search_tool

            parsed = json.loads(await web_search_tool.ainvoke({"query": "vector databases"}))
        finally:
            patcher.stop()

        assert parsed == [
            {"title": "A", "url": "https://ex.com/a", "snippet": "s1"},
            {"title": "B", "url": "https://ex.com/b", "snippet": "s2"},
        ]

    async def test_tolerates_missing_date_fields(self, mock_config_with_key):
        """`date` and `last_updated` are optional in the API response."""
        payload = _payload({"title": "A", "url": "https://ex.com/a", "snippet": "s"})
        patcher, _ = _patch_post(_make_response(payload))
        try:
            from deerflow.community.perplexity.tools import web_search_tool

            parsed = json.loads(await web_search_tool.ainvoke({"query": "test"}))
        finally:
            patcher.stop()

        assert parsed == [{"title": "A", "url": "https://ex.com/a", "snippet": "s"}]

    async def test_results_trimmed_to_count(self, mock_config_with_key):
        payload = _payload(*[_result(url=f"https://w{i}.com", title=f"W{i}") for i in range(8)])
        patcher, _ = _patch_post(_make_response(payload))
        try:
            from deerflow.community.perplexity.tools import web_search_tool

            parsed = json.loads(await web_search_tool.ainvoke({"query": "test", "max_results": 3}))
        finally:
            patcher.stop()

        assert [r["title"] for r in parsed] == ["W0", "W1", "W2"]

    async def test_agent_max_results_is_honored_over_config(self, mock_config_with_key):
        patcher, mock_client_cls = _patch_post(_make_response(_payload()))
        try:
            from deerflow.community.perplexity.tools import web_search_tool

            await web_search_tool.ainvoke({"query": "test", "max_results": 12})
            body = _post_call(mock_client_cls).kwargs["json"]
        finally:
            patcher.stop()

        assert body["max_results"] == 12

    async def test_config_max_results_used_when_caller_omits(self, mock_config_with_key):
        patcher, mock_client_cls = _patch_post(_make_response(_payload()))
        try:
            from deerflow.community.perplexity.tools import web_search_tool

            await web_search_tool.ainvoke({"query": "test"})
            body = _post_call(mock_client_cls).kwargs["json"]
        finally:
            patcher.stop()

        assert body["max_results"] == 5

    @pytest.mark.parametrize(("max_results", "expected"), [(0, 5), (-2, 5), (1, 1), (20, 20), (50, 20), ("500", 20)])
    async def test_max_results_clamped_to_provider_bounds(self, max_results, expected):
        with patch("deerflow.community.perplexity.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "k", "max_results": max_results}
            mock.return_value.get_tool_config.return_value = tool_config
            patcher, mock_client_cls = _patch_post(_make_response(_payload()))
            try:
                from deerflow.community.perplexity.tools import web_search_tool

                await web_search_tool.ainvoke({"query": "test"})
                body = _post_call(mock_client_cls).kwargs["json"]
            finally:
                patcher.stop()

        assert body["max_results"] == expected

    async def test_invalid_max_results_falls_back_to_default_with_warning(self, caplog):
        with patch("deerflow.community.perplexity.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "k", "max_results": "not-a-number"}
            mock.return_value.get_tool_config.return_value = tool_config
            patcher, mock_client_cls = _patch_post(_make_response(_payload()))
            try:
                from deerflow.community.perplexity.tools import web_search_tool

                with caplog.at_level(logging.WARNING, logger="deerflow.community.perplexity.tools"):
                    await web_search_tool.ainvoke({"query": "test"})
                body = _post_call(mock_client_cls).kwargs["json"]
            finally:
                patcher.stop()

        assert body["max_results"] == 5
        assert any("Invalid Perplexity max_results" in record.message for record in caplog.records)

    async def test_empty_results_returns_error_json(self, mock_config_with_key):
        patcher, _ = _patch_post(_make_response({"id": "req-1", "results": []}))
        try:
            from deerflow.community.perplexity.tools import web_search_tool

            parsed = json.loads(await web_search_tool.ainvoke({"query": "no results"}))
        finally:
            patcher.stop()

        assert parsed["error"] == "No results found"
        assert parsed["query"] == "no results"

    async def test_missing_results_section_returns_error_json(self, mock_config_with_key):
        patcher, _ = _patch_post(_make_response({"id": "req-1"}))
        try:
            from deerflow.community.perplexity.tools import web_search_tool

            parsed = json.loads(await web_search_tool.ainvoke({"query": "test"}))
        finally:
            patcher.stop()

        assert parsed["error"] == "No results found"

    async def test_non_dict_payload_returns_format_error(self, mock_config_with_key):
        patcher, _ = _patch_post(_make_response(["not", "a", "dict"]))
        try:
            from deerflow.community.perplexity.tools import web_search_tool

            parsed = json.loads(await web_search_tool.ainvoke({"query": "test"}))
        finally:
            patcher.stop()

        assert "unexpected response format" in parsed["error"]

    async def test_partial_fields_default_to_empty_string(self, mock_config_with_key):
        patcher, _ = _patch_post(_make_response(_payload({})))
        try:
            from deerflow.community.perplexity.tools import web_search_tool

            parsed = json.loads(await web_search_tool.ainvoke({"query": "test"}))
        finally:
            patcher.stop()

        assert parsed[0] == {"title": "", "url": "", "snippet": ""}

    @pytest.mark.parametrize(
        ("status", "hint"),
        [
            (401, "invalid PERPLEXITY_API_KEY"),
            (422, "validation"),
            (429, "rate limit reached"),
            (500, None),
        ],
    )
    async def test_http_error_returns_structured_error(self, status, hint, mock_config_with_key):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            str(status),
            request=MagicMock(),
            response=MagicMock(status_code=status, text="boom"),
        )
        patcher, _ = _patch_post(mock_resp)
        try:
            from deerflow.community.perplexity.tools import web_search_tool

            parsed = json.loads(await web_search_tool.ainvoke({"query": "test"}))
        finally:
            patcher.stop()

        assert str(status) in parsed["error"]
        if hint:
            assert hint in parsed["error"]

    async def test_network_exception_reports_class_name_only(self, mock_config_with_key):
        patcher, mock_client_cls = _patch_post(MagicMock())
        mock_client_cls.return_value.__aenter__.return_value.post.side_effect = httpx.ConnectTimeout("timed out after 30s")
        try:
            from deerflow.community.perplexity.tools import web_search_tool

            parsed = json.loads(await web_search_tool.ainvoke({"query": "test"}))
        finally:
            patcher.stop()

        assert parsed["error"] == "Perplexity Search API request failed: ConnectTimeout"
        assert "30s" not in parsed["error"]

    async def test_unexpected_exception_reports_class_name_only(self, mock_config_with_key):
        patcher, mock_client_cls = _patch_post(MagicMock())
        mock_client_cls.return_value.__aenter__.return_value.post.side_effect = RuntimeError("Bearer leaked-secret")
        try:
            from deerflow.community.perplexity.tools import web_search_tool

            parsed = json.loads(await web_search_tool.ainvoke({"query": "test"}))
        finally:
            patcher.stop()

        assert parsed["error"] == "Perplexity search failed: RuntimeError"
        assert "leaked-secret" not in parsed["error"]


_SECRET = "sk-sentinel-SECRET-9f8e7d"


class _CaptureHandler(logging.Handler):
    """Collect fully formatted log output from the module logger."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(self.format(record))


@pytest.fixture
def module_log():
    module_logger = logging.getLogger("deerflow.community.perplexity.tools")
    handler = _CaptureHandler()
    previous_level = module_logger.level
    module_logger.addHandler(handler)
    module_logger.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        module_logger.removeHandler(handler)
        module_logger.setLevel(previous_level)


class TestNoKeyOrBodyDisclosure:
    """Neither the key nor upstream response bodies may reach tool output or logs."""

    @pytest.mark.parametrize(
        "bad_key",
        [f"{_SECRET}\nX-Injected: 1", f"{_SECRET}\x00tail", f"{_SECRET}\rtail", f"{_SECRET} tail"],
        ids=["embedded-newline", "embedded-nul", "embedded-cr", "embedded-space"],
    )
    async def test_config_key_with_control_characters_is_rejected_before_any_request(self, bad_key, module_log):
        with patch("deerflow.community.perplexity.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": bad_key}
            mock.return_value.get_tool_config.return_value = tool_config
            patcher, mock_client_cls = _patch_post(_make_response(_payload()))
            try:
                from deerflow.community.perplexity.tools import web_search_tool

                raw = await web_search_tool.ainvoke({"query": "test"})
            finally:
                patcher.stop()

        parsed = json.loads(raw)
        assert parsed == {"error": "Perplexity Search API error: invalid PERPLEXITY_API_KEY format", "query": "test"}
        assert not mock_client_cls.called
        assert _SECRET not in raw
        logged = "\n".join(module_log.lines)
        assert logged, "the rejection must be logged"
        assert _SECRET not in logged
        assert "Bearer" not in logged

    async def test_env_key_with_embedded_newline_is_rejected(self, mock_config_no_key, module_log):
        with patch.dict("os.environ", {"PERPLEXITY_API_KEY": f"{_SECRET}\nX-Injected: 1"}, clear=True):
            patcher, mock_client_cls = _patch_post(_make_response(_payload()))
            try:
                from deerflow.community.perplexity.tools import web_search_tool

                raw = await web_search_tool.ainvoke({"query": "test"})
            finally:
                patcher.stop()

        assert json.loads(raw)["error"] == "Perplexity Search API error: invalid PERPLEXITY_API_KEY format"
        assert not mock_client_cls.called
        assert _SECRET not in raw
        assert _SECRET not in "\n".join(module_log.lines)

    async def test_trailing_whitespace_on_key_is_still_stripped_and_accepted(self, mock_config_no_key):
        with patch.dict("os.environ", {"PERPLEXITY_API_KEY": f"  {_SECRET}\n"}, clear=True):
            patcher, mock_client_cls = _patch_post(_make_response(_payload()))
            try:
                from deerflow.community.perplexity.tools import web_search_tool

                await web_search_tool.ainvoke({"query": "test"})
                call = _post_call(mock_client_cls)
            finally:
                patcher.stop()

        assert call.kwargs["headers"]["Authorization"] == f"Bearer {_SECRET}"

    async def test_local_protocol_error_text_never_reaches_output_or_logs(self, mock_config_with_key, module_log):
        """Defense in depth: even if the transport rejects a header, its message stays internal."""
        patcher, mock_client_cls = _patch_post(MagicMock())
        mock_client_cls.return_value.__aenter__.return_value.post.side_effect = httpx.LocalProtocolError(f"Illegal header value b'Bearer {_SECRET}\\n'")
        try:
            from deerflow.community.perplexity.tools import web_search_tool

            raw = await web_search_tool.ainvoke({"query": "test"})
        finally:
            patcher.stop()

        assert json.loads(raw)["error"] == "Perplexity Search API request failed: LocalProtocolError"
        assert _SECRET not in raw
        logged = "\n".join(module_log.lines)
        assert "LocalProtocolError" in logged
        assert _SECRET not in logged
        assert "Bearer" not in logged

    @pytest.mark.parametrize("status", [422, 500])
    async def test_http_error_body_never_reaches_output_or_logs(self, status, mock_config_with_key, module_log):
        body_sentinel = f"UPSTREAM-BODY-{_SECRET}"
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            body_sentinel,
            request=MagicMock(),
            response=MagicMock(status_code=status, text=body_sentinel),
        )
        patcher, _ = _patch_post(mock_resp)
        try:
            from deerflow.community.perplexity.tools import web_search_tool

            raw = await web_search_tool.ainvoke({"query": "test"})
        finally:
            patcher.stop()

        assert f"HTTP {status}" in json.loads(raw)["error"]
        assert body_sentinel not in raw
        logged = "\n".join(module_log.lines)
        assert f"HTTP {status}" in logged
        assert body_sentinel not in logged


@pytest.mark.parametrize(
    "raw",
    [float("inf"), True, 3.5],
    ids=["yaml-inf", "bool", "non-integral-float"],
)
async def test_invalid_max_results_shapes_fall_back_to_default(raw):
    """Invalid max_results shapes fall back to the default, never crash or truncate.

    The shared ``coerce_max_results`` owns the rejection profile; this provider
    only adds the Search API's 1-20 cap on top.
    """
    with patch("deerflow.community.perplexity.tools.get_app_config") as mock:
        tool_config = MagicMock()
        tool_config.model_extra = {"api_key": "***", "max_results": raw}
        mock.return_value.get_tool_config.return_value = tool_config
        patcher, mock_client_cls = _patch_post(_make_response(_payload()))
        try:
            from deerflow.community.perplexity.tools import web_search_tool

            await web_search_tool.ainvoke({"query": "test"})
            body = _post_call(mock_client_cls).kwargs["json"]
        finally:
            patcher.stop()

    assert body["max_results"] == 5


def test_package_exports_web_search_tool():
    from deerflow.community.perplexity import web_search_tool
    from deerflow.community.perplexity.tools import web_search_tool as direct_web_search_tool

    assert web_search_tool is direct_web_search_tool


class _EchoingHandler(BaseHTTPRequestHandler):
    """Loopback stand-in for api.perplexity.ai that echoes the key in error bodies."""

    status = 200

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        type(self).received += 1
        if self.status == 200:
            body = {"results": [{"title": "ok", "url": "https://example.com", "snippet": "ok"}]}
        else:
            body = {"detail": f"rejected; echoed Authorization: Bearer {_SECRET}"}
        encoded = json.dumps(body).encode()
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *args):
        pass


@pytest.fixture
def loopback_endpoint():
    """Real httpx transport against a loopback server; nothing in httpx is mocked."""
    _EchoingHandler.received = 0
    _EchoingHandler.status = 200
    server = ThreadingHTTPServer(("127.0.0.1", 0), _EchoingHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/search"
    with patch("deerflow.community.perplexity.tools._PERPLEXITY_SEARCH_ENDPOINT", endpoint):
        yield _EchoingHandler
    server.shutdown()
    server.server_close()
    thread.join()


class TestRealTransportDisclosure:
    """Same assertions as above, but through the real httpx/h11 stack."""

    @pytest.mark.parametrize("bad_key", [f"{_SECRET}\ninvalid", f"{_SECRET}\x00invalid"], ids=["newline", "nul"])
    async def test_control_character_key_never_reaches_the_wire_or_logs(self, bad_key, loopback_endpoint, module_log):
        with patch("deerflow.community.perplexity.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": bad_key}
            mock.return_value.get_tool_config.return_value = tool_config
            with patch.dict("os.environ", {"NO_PROXY": "127.0.0.1"}):
                from deerflow.community.perplexity.tools import web_search_tool

                raw = await web_search_tool.ainvoke({"query": "probe"})

        assert json.loads(raw)["error"] == "Perplexity Search API error: invalid PERPLEXITY_API_KEY format"
        assert loopback_endpoint.received == 0
        assert _SECRET not in raw
        assert _SECRET not in "\n".join(module_log.lines)

    @pytest.mark.parametrize("status", [422, 500])
    async def test_error_body_echoing_the_key_stays_out_of_output_and_logs(self, status, loopback_endpoint, module_log):
        loopback_endpoint.status = status
        with patch("deerflow.community.perplexity.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": _SECRET}
            mock.return_value.get_tool_config.return_value = tool_config
            with patch.dict("os.environ", {"NO_PROXY": "127.0.0.1"}):
                from deerflow.community.perplexity.tools import web_search_tool

                raw = await web_search_tool.ainvoke({"query": "probe"})

        assert f"HTTP {status}" in json.loads(raw)["error"]
        assert loopback_endpoint.received == 1
        assert _SECRET not in raw
        logged = "\n".join(module_log.lines)
        assert f"HTTP {status}" in logged
        assert _SECRET not in logged
