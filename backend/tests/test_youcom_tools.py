"""Unit tests for the You.com community web search tool."""

import json
import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest

KEYED_ENDPOINT = "https://api.you.com/v1/search"
KEYLESS_ENDPOINT = "https://api.you.com/v1/agents/search"


@pytest.fixture
def mock_config_with_key():
    with patch("deerflow.community.youcom.tools.get_app_config") as mock:
        tool_config = MagicMock()
        tool_config.model_extra = {"api_key": "test-ydc-key", "max_results": 5}
        mock.return_value.get_tool_config.return_value = tool_config
        yield mock


@pytest.fixture
def mock_config_no_key():
    with patch("deerflow.community.youcom.tools.get_app_config") as mock:
        tool_config = MagicMock()
        tool_config.model_extra = {}
        mock.return_value.get_tool_config.return_value = tool_config
        yield mock


def _make_response(payload: object) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.json.return_value = payload
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def _patch_get(mock_resp: MagicMock):
    """Patch httpx.Client so the context-managed .get returns mock_resp."""
    patcher = patch("deerflow.community.youcom.tools.httpx.Client")
    mock_client_cls = patcher.start()
    mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
    return patcher, mock_client_cls


def _get_call(mock_client_cls):
    return mock_client_cls.return_value.__enter__.return_value.get.call_args


def _web(**overrides) -> dict:
    result = {"url": "https://ex.com/a", "title": "A", "description": "d1", "snippets": ["s1", "s2"]}
    result.update(overrides)
    return result


class TestGetApiKey:
    def test_returns_config_key_when_present(self):
        with patch("deerflow.community.youcom.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "from-config"}
            mock.return_value.get_tool_config.return_value = tool_config

            from deerflow.community.youcom.tools import _get_api_key

            assert _get_api_key("web_search") == "from-config"

    def test_falls_back_to_env_when_config_key_blank(self):
        with patch("deerflow.community.youcom.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "   "}
            mock.return_value.get_tool_config.return_value = tool_config
            with patch.dict("os.environ", {"YDC_API_KEY": "env-key"}, clear=True):
                from deerflow.community.youcom.tools import _get_api_key

                assert _get_api_key("web_search") == "env-key"

    def test_returns_none_when_no_key_anywhere(self):
        """No key is not an error: it selects the keyless endpoint."""
        with patch("deerflow.community.youcom.tools.get_app_config") as mock:
            mock.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {}, clear=True):
                from deerflow.community.youcom.tools import _get_api_key

                assert _get_api_key("web_search") is None


class TestEndpointSelection:
    def test_configured_key_uses_keyed_endpoint_with_header(self, mock_config_with_key):
        patcher, mock_client_cls = _patch_get(_make_response({"results": {"web": [_web()]}}))
        try:
            from deerflow.community.youcom.tools import web_search_tool

            web_search_tool.invoke({"query": "test"})
            call = _get_call(mock_client_cls)
        finally:
            patcher.stop()

        assert call.args[0] == KEYED_ENDPOINT
        assert call.kwargs["headers"]["X-API-Key"] == "test-ydc-key"
        assert call.kwargs["params"] == {"query": "test", "count": 5}

    def test_no_key_uses_keyless_endpoint_without_auth_header(self, mock_config_no_key):
        """The keyless endpoint rejects an auth header, so none may be sent."""
        with patch.dict("os.environ", {}, clear=True):
            patcher, mock_client_cls = _patch_get(_make_response({"results": {"web": [_web()]}}))
            try:
                from deerflow.community.youcom.tools import web_search_tool

                web_search_tool.invoke({"query": "test"})
                call = _get_call(mock_client_cls)
            finally:
                patcher.stop()

        assert call.args[0] == KEYLESS_ENDPOINT
        assert "X-API-Key" not in call.kwargs["headers"]

    def test_env_key_uses_keyed_endpoint(self, mock_config_no_key):
        with patch.dict("os.environ", {"YDC_API_KEY": "env-key"}, clear=True):
            patcher, mock_client_cls = _patch_get(_make_response({"results": {"web": [_web()]}}))
            try:
                from deerflow.community.youcom.tools import web_search_tool

                web_search_tool.invoke({"query": "test"})
                call = _get_call(mock_client_cls)
            finally:
                patcher.stop()

        assert call.args[0] == KEYED_ENDPOINT
        assert call.kwargs["headers"]["X-API-Key"] == "env-key"

    @pytest.mark.parametrize("with_key", [True, False])
    def test_identifies_deerflow_in_user_agent(self, with_key, mock_config_no_key):
        """Both endpoints identify DeerFlow so You.com can attribute the traffic."""
        env = {"YDC_API_KEY": "k"} if with_key else {}
        with patch.dict("os.environ", env, clear=True):
            patcher, mock_client_cls = _patch_get(_make_response({"results": {"web": [_web()]}}))
            try:
                from deerflow.community.youcom.tools import web_search_tool

                web_search_tool.invoke({"query": "test"})
                call = _get_call(mock_client_cls)
            finally:
                patcher.stop()

        user_agent = call.kwargs["headers"]["User-Agent"]
        assert user_agent.startswith("deerflow-harness/")
        assert "youdotcom-integration/bytedance-deer-flow" in user_agent


class TestWebSearchTool:
    def test_returns_normalized_list_with_joined_snippets(self, mock_config_with_key):
        payload = {
            "results": {
                "web": [
                    _web(url="https://ex.com/a", title="A", snippets=["s1", "s2"]),
                    _web(url="https://ex.com/b", title="B", snippets=["s3"]),
                ]
            }
        }
        patcher, _ = _patch_get(_make_response(payload))
        try:
            from deerflow.community.youcom.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "vector databases"}))
        finally:
            patcher.stop()

        assert parsed == [
            {"title": "A", "url": "https://ex.com/a", "snippet": "s1\ns2"},
            {"title": "B", "url": "https://ex.com/b", "snippet": "s3"},
        ]

    def test_falls_back_to_description_when_no_snippets(self, mock_config_with_key):
        """News hits carry only a description; web hits with empty snippets do too."""
        payload = {
            "results": {
                "web": [_web(snippets=[], description="web-desc")],
                "news": [{"url": "https://n.com", "title": "N", "description": "news-desc"}],
            }
        }
        patcher, _ = _patch_get(_make_response(payload))
        try:
            from deerflow.community.youcom.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "news"}))
        finally:
            patcher.stop()

        assert [r["snippet"] for r in parsed] == ["web-desc", "news-desc"]

    def test_web_and_news_merged_and_trimmed_to_count(self, mock_config_with_key):
        """`count` applies per section, so the merged list can overshoot it."""
        payload = {
            "results": {
                "web": [_web(url=f"https://w{i}.com", title=f"W{i}") for i in range(5)],
                "news": [{"url": f"https://n{i}.com", "title": f"N{i}", "description": "d"} for i in range(5)],
            }
        }
        patcher, _ = _patch_get(_make_response(payload))
        try:
            from deerflow.community.youcom.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))
        finally:
            patcher.stop()

        assert len(parsed) == 5
        assert [r["title"] for r in parsed] == ["W0", "W1", "W2", "W3", "W4"]

    def test_agent_max_results_is_honored_over_config(self, mock_config_with_key):
        patcher, mock_client_cls = _patch_get(_make_response({"results": {"web": [_web()]}}))
        try:
            from deerflow.community.youcom.tools import web_search_tool

            web_search_tool.invoke({"query": "test", "max_results": 20})
            params = _get_call(mock_client_cls).kwargs["params"]
        finally:
            patcher.stop()

        assert params["count"] == 20

    def test_config_max_results_used_when_caller_omits(self, mock_config_with_key):
        patcher, mock_client_cls = _patch_get(_make_response({"results": {"web": [_web()]}}))
        try:
            from deerflow.community.youcom.tools import web_search_tool

            web_search_tool.invoke({"query": "test"})
            params = _get_call(mock_client_cls).kwargs["params"]
        finally:
            patcher.stop()

        assert params["count"] == 5

    def test_max_results_clamped_to_cap(self):
        with patch("deerflow.community.youcom.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "k", "max_results": "500"}
            mock.return_value.get_tool_config.return_value = tool_config
            patcher, mock_client_cls = _patch_get(_make_response({"results": {"web": [_web()]}}))
            try:
                from deerflow.community.youcom.tools import web_search_tool

                web_search_tool.invoke({"query": "test"})
                params = _get_call(mock_client_cls).kwargs["params"]
            finally:
                patcher.stop()

        assert params["count"] == 100

    def test_invalid_max_results_falls_back_to_default_with_warning(self, caplog):
        with patch("deerflow.community.youcom.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "k", "max_results": "not-a-number"}
            mock.return_value.get_tool_config.return_value = tool_config
            patcher, mock_client_cls = _patch_get(_make_response({"results": {"web": [_web()]}}))
            try:
                from deerflow.community.youcom.tools import web_search_tool

                with caplog.at_level(logging.WARNING, logger="deerflow.community.youcom.tools"):
                    web_search_tool.invoke({"query": "test"})
                params = _get_call(mock_client_cls).kwargs["params"]
            finally:
                patcher.stop()

        assert params["count"] == 5
        assert any("Invalid You.com max_results" in record.message for record in caplog.records)

    def test_empty_results_returns_error_json(self, mock_config_with_key):
        patcher, _ = _patch_get(_make_response({"results": {"web": []}}))
        try:
            from deerflow.community.youcom.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "no results"}))
        finally:
            patcher.stop()

        assert parsed["error"] == "No results found"
        assert parsed["query"] == "no results"

    def test_missing_results_section_returns_error_json(self, mock_config_with_key):
        patcher, _ = _patch_get(_make_response({"metadata": {"latency": 0.1}}))
        try:
            from deerflow.community.youcom.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))
        finally:
            patcher.stop()

        assert parsed["error"] == "No results found"

    def test_non_dict_payload_returns_format_error(self, mock_config_with_key):
        patcher, _ = _patch_get(_make_response(["not", "a", "dict"]))
        try:
            from deerflow.community.youcom.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))
        finally:
            patcher.stop()

        assert "unexpected response format" in parsed["error"]

    def test_partial_fields_default_to_empty_string(self, mock_config_with_key):
        patcher, _ = _patch_get(_make_response({"results": {"web": [{}]}}))
        try:
            from deerflow.community.youcom.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))
        finally:
            patcher.stop()

        assert parsed[0] == {"title": "", "url": "", "snippet": ""}

    @pytest.mark.parametrize(
        ("status", "hint"),
        [
            (401, "invalid or expired YDC_API_KEY"),
            (402, "You.com credit balance depleted"),
            (500, None),
        ],
    )
    def test_http_error_returns_structured_error(self, status, hint, mock_config_with_key):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            str(status),
            request=MagicMock(),
            response=MagicMock(status_code=status, text="boom"),
        )
        patcher, _ = _patch_get(mock_resp)
        try:
            from deerflow.community.youcom.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))
        finally:
            patcher.stop()

        assert str(status) in parsed["error"]
        if hint:
            assert hint in parsed["error"]

    def test_network_exception_returns_error_json(self, mock_config_with_key):
        patcher, mock_client_cls = _patch_get(MagicMock())
        mock_client_cls.return_value.__enter__.return_value.get.side_effect = Exception("timeout")
        try:
            from deerflow.community.youcom.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))
        finally:
            patcher.stop()

        assert parsed["error"] == "timeout"


def test_package_exports_web_search_tool():
    from deerflow.community.youcom import web_search_tool
    from deerflow.community.youcom.tools import web_search_tool as direct_web_search_tool

    assert web_search_tool is direct_web_search_tool
