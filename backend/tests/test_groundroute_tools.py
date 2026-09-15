"""Unit tests for the GroundRoute community web search + fetch tools."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest


@pytest.fixture(autouse=True)
def reset_api_key_warned():
    """Reset the per-tool warning set before and after each test."""
    import deerflow.community.groundroute.tools as gr_mod

    gr_mod._api_key_warned = set()
    yield
    gr_mod._api_key_warned = set()


@pytest.fixture
def mock_config_with_key():
    with patch("deerflow.community.groundroute.tools.get_app_config") as mock:
        tool_config = MagicMock()
        tool_config.model_extra = {"api_key": "test-gr-key", "max_results": 5}
        mock.return_value.get_tool_config.return_value = tool_config
        yield mock


@pytest.fixture
def mock_config_no_key():
    with patch("deerflow.community.groundroute.tools.get_app_config") as mock:
        tool_config = MagicMock()
        tool_config.model_extra = {}
        mock.return_value.get_tool_config.return_value = tool_config
        yield mock


def _make_search_response(payload: dict) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.json.return_value = payload
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def _patch_post(mock_resp: MagicMock):
    """Patch httpx.Client so the context-managed .post returns mock_resp."""
    patcher = patch("deerflow.community.groundroute.tools.httpx.Client")
    mock_client_cls = patcher.start()
    mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp
    return patcher, mock_client_cls


def _per_tool_config(**by_tool):
    """Build a get_app_config mock whose get_tool_config returns a distinct config per tool name."""
    configs = {}
    for tool_name, extra in by_tool.items():
        cfg = MagicMock()
        cfg.model_extra = extra
        configs[tool_name] = cfg
    app = MagicMock()
    app.get_tool_config.side_effect = lambda name: configs.get(name)
    return app


class TestGetApiKey:
    def test_returns_config_key_when_present(self):
        with patch("deerflow.community.groundroute.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "from-config"}
            mock.return_value.get_tool_config.return_value = tool_config

            from deerflow.community.groundroute.tools import _get_api_key

            assert _get_api_key("web_search") == "from-config"

    def test_falls_back_to_env_when_config_key_empty(self):
        with patch("deerflow.community.groundroute.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "   "}
            mock.return_value.get_tool_config.return_value = tool_config
            with patch.dict("os.environ", {"GROUNDROUTE_API_KEY": "env-key"}, clear=True):
                from deerflow.community.groundroute.tools import _get_api_key

                assert _get_api_key("web_search") == "env-key"

    def test_returns_none_when_no_key_anywhere(self):
        with patch("deerflow.community.groundroute.tools.get_app_config") as mock:
            mock.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {}, clear=True):
                from deerflow.community.groundroute.tools import _get_api_key

                assert _get_api_key("web_search") is None

    def test_reads_the_named_tools_config_block(self):
        """web_fetch must read the web_fetch block, not web_search (multi-engine flows)."""
        with patch("deerflow.community.groundroute.tools.get_app_config") as mock:
            mock.return_value = _per_tool_config(
                web_search={"api_key": "search-key"},
                web_fetch={"api_key": "fetch-key"},
            )
            from deerflow.community.groundroute.tools import _get_api_key

            assert _get_api_key("web_search") == "search-key"
            assert _get_api_key("web_fetch") == "fetch-key"


class TestWebSearchTool:
    def test_basic_search_returns_normalized_list_with_source_engine(self, mock_config_with_key):
        payload = {
            "request_id": "r1",
            "results": [
                {"url": "https://ex.com/a", "title": "A", "snippet": "s1", "source_engine": "serper"},
                {"url": "https://ex.com/b", "title": "B", "snippet": "s2", "source_engine": "exa"},
            ],
        }
        patcher, _ = _patch_post(_make_search_response(payload))
        try:
            from deerflow.community.groundroute.tools import web_search_tool

            result = web_search_tool.invoke({"query": "vector databases"})
            parsed = json.loads(result)
        finally:
            patcher.stop()

        assert isinstance(parsed, list)
        assert len(parsed) == 2
        assert parsed[0] == {
            "title": "A",
            "url": "https://ex.com/a",
            "snippet": "s1",
            "source_engine": "serper",
        }
        assert {r["source_engine"] for r in parsed} == {"serper", "exa"}

    def test_uses_web_search_config_key(self):
        """web_search authenticates with the web_search config block's key."""
        with patch("deerflow.community.groundroute.tools.get_app_config") as mock:
            mock.return_value = _per_tool_config(
                web_search={"api_key": "search-key"},
                web_fetch={"api_key": "fetch-key"},
            )
            payload = {"results": [{"url": "u", "title": "t", "snippet": "s", "source_engine": "exa"}]}
            patcher, mock_client_cls = _patch_post(_make_search_response(payload))
            try:
                from deerflow.community.groundroute.tools import web_search_tool

                web_search_tool.invoke({"query": "hello world"})
                call = mock_client_cls.return_value.__enter__.return_value.post.call_args
            finally:
                patcher.stop()

        assert call.kwargs["headers"]["Authorization"] == "Bearer search-key"
        assert call.kwargs["json"]["query"] == "hello world"

    def test_agent_max_results_is_honored_over_config(self):
        """A caller-supplied max_results wins over the config value (not silently discarded)."""
        with patch("deerflow.community.groundroute.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "k", "max_results": 5}
            mock.return_value.get_tool_config.return_value = tool_config
            payload = {"results": [{"url": "u", "title": "t", "snippet": "s", "source_engine": "exa"}]}
            patcher, mock_client_cls = _patch_post(_make_search_response(payload))
            try:
                from deerflow.community.groundroute.tools import web_search_tool

                web_search_tool.invoke({"query": "test", "max_results": 20})
                body = mock_client_cls.return_value.__enter__.return_value.post.call_args.kwargs["json"]
            finally:
                patcher.stop()

        assert body["max_results"] == 20

    def test_config_max_results_used_when_caller_omits(self, mock_config_with_key):
        """When the caller omits max_results, the configured value is used."""
        payload = {"results": [{"url": "u", "title": "t", "snippet": "s", "source_engine": "exa"}]}
        patcher, mock_client_cls = _patch_post(_make_search_response(payload))
        try:
            from deerflow.community.groundroute.tools import web_search_tool

            web_search_tool.invoke({"query": "test"})
            body = mock_client_cls.return_value.__enter__.return_value.post.call_args.kwargs["json"]
        finally:
            patcher.stop()

        assert body["max_results"] == 5

    def test_max_results_clamped_to_cap(self):
        with patch("deerflow.community.groundroute.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "k", "max_results": "500"}
            mock.return_value.get_tool_config.return_value = tool_config
            payload = {"results": [{"url": "u", "title": "t", "snippet": "s", "source_engine": "exa"}]}
            patcher, mock_client_cls = _patch_post(_make_search_response(payload))
            try:
                from deerflow.community.groundroute.tools import web_search_tool

                web_search_tool.invoke({"query": "test"})
                body = mock_client_cls.return_value.__enter__.return_value.post.call_args.kwargs["json"]
            finally:
                patcher.stop()

        assert body["max_results"] == 50

    def test_empty_results_returns_error_json(self, mock_config_with_key):
        patcher, _ = _patch_post(_make_search_response({"results": []}))
        try:
            from deerflow.community.groundroute.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "no results"}))
        finally:
            patcher.stop()

        assert parsed["error"] == "No results found"
        assert parsed["query"] == "no results"

    def test_missing_api_key_returns_error_json(self, mock_config_no_key):
        with patch.dict("os.environ", {}, clear=True):
            from deerflow.community.groundroute.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))

        assert "error" in parsed
        assert "GROUNDROUTE_API_KEY" in parsed["error"]

    def test_missing_api_key_logs_warning_once(self, mock_config_no_key, caplog):
        import logging

        with patch.dict("os.environ", {}, clear=True):
            from deerflow.community.groundroute.tools import web_search_tool

            with caplog.at_level(logging.WARNING, logger="deerflow.community.groundroute.tools"):
                web_search_tool.invoke({"query": "q1"})
                web_search_tool.invoke({"query": "q2"})

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1

    def test_http_error_returns_structured_error(self, mock_config_with_key):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError("402", request=MagicMock(), response=MagicMock(status_code=402, text="Payment Required"))
        patcher, _ = _patch_post(mock_resp)
        try:
            from deerflow.community.groundroute.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))
        finally:
            patcher.stop()

        assert "error" in parsed
        assert "402" in parsed["error"]

    def test_network_exception_returns_error_json(self, mock_config_with_key):
        patcher, mock_client_cls = _patch_post(MagicMock())
        mock_client_cls.return_value.__enter__.return_value.post.side_effect = Exception("timeout")
        try:
            from deerflow.community.groundroute.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))
        finally:
            patcher.stop()

        assert "error" in parsed

    def test_partial_fields_default_to_empty_string(self, mock_config_with_key):
        patcher, _ = _patch_post(_make_search_response({"results": [{}]}))
        try:
            from deerflow.community.groundroute.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))
        finally:
            patcher.stop()

        assert parsed[0] == {"title": "", "url": "", "snippet": "", "source_engine": ""}


class TestWebFetchTool:
    def test_fetch_returns_titled_content(self, mock_config_with_key):
        payload = {"results": [{"title": "Page", "content": "Body text", "url": "https://ex.com"}]}
        patcher, mock_client_cls = _patch_post(_make_search_response(payload))
        try:
            from deerflow.community.groundroute.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://ex.com"})
            body = mock_client_cls.return_value.__enter__.return_value.post.call_args.kwargs["json"]
        finally:
            patcher.stop()

        assert result == "# Page\n\nBody text"
        # web_fetch uses mode=page with the URL as the query.
        assert body["mode"] == "page"
        assert body["query"] == "https://ex.com"

    def test_fetch_uses_web_fetch_config_key(self):
        """web_fetch must authenticate with the web_fetch config block's key, not web_search's."""
        with patch("deerflow.community.groundroute.tools.get_app_config") as mock:
            mock.return_value = _per_tool_config(
                web_search={"api_key": "search-key"},
                web_fetch={"api_key": "fetch-key"},
            )
            payload = {"results": [{"title": "P", "content": "b", "url": "https://ex.com"}]}
            patcher, mock_client_cls = _patch_post(_make_search_response(payload))
            try:
                from deerflow.community.groundroute.tools import web_fetch_tool

                web_fetch_tool.invoke({"url": "https://ex.com"})
                call = mock_client_cls.return_value.__enter__.return_value.post.call_args
            finally:
                patcher.stop()

        assert call.kwargs["headers"]["Authorization"] == "Bearer fetch-key"

    def test_fetch_missing_key_returns_error(self, mock_config_no_key):
        with patch.dict("os.environ", {}, clear=True):
            from deerflow.community.groundroute.tools import web_fetch_tool

            parsed = json.loads(web_fetch_tool.invoke({"url": "https://ex.com"}))

        assert "error" in parsed
        assert "GROUNDROUTE_API_KEY" in parsed["error"]

    def test_fetch_no_results_returns_error_string(self, mock_config_with_key):
        patcher, _ = _patch_post(_make_search_response({"results": []}))
        try:
            from deerflow.community.groundroute.tools import web_fetch_tool

            result = web_fetch_tool.invoke({"url": "https://ex.com"})
        finally:
            patcher.stop()

        assert result == "Error: No results found"
