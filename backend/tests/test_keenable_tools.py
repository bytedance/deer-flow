"""Unit tests for the Keenable community web search tool."""

import json
import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest

KEYED_ENDPOINT = "https://api.keenable.ai/v1/search"
KEYLESS_ENDPOINT = "https://api.keenable.ai/v1/search/public"
FORMAT_ERROR = "Keenable returned an unexpected response format"


@pytest.fixture
def mock_config_with_key():
    with patch("deerflow.community.keenable.tools.get_app_config") as mock:
        tool_config = MagicMock()
        tool_config.model_extra = {"api_key": "test-keenable-key", "max_results": 5}
        mock.return_value.get_tool_config.return_value = tool_config
        yield mock


@pytest.fixture
def mock_config_no_key():
    with patch("deerflow.community.keenable.tools.get_app_config") as mock:
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
    """Patch httpx.Client so the context-managed .post returns mock_resp."""
    patcher = patch("deerflow.community.keenable.tools.httpx.Client")
    mock_client_cls = patcher.start()
    mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp
    return patcher, mock_client_cls


def _post_call(mock_client_cls):
    return mock_client_cls.return_value.__enter__.return_value.post.call_args


def _hit(**overrides) -> dict:
    result = {"url": "https://ex.com/a", "title": "A", "description": "", "snippet": "s1"}
    result.update(overrides)
    return result


def _invoke(payload: object, args: dict | None = None) -> object:
    patcher, _ = _patch_post(_make_response(payload))
    try:
        from deerflow.community.keenable.tools import web_search_tool

        return json.loads(web_search_tool.invoke(args or {"query": "test"}))
    finally:
        patcher.stop()


class TestGetApiKey:
    def test_returns_config_key_when_present(self):
        with patch("deerflow.community.keenable.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "from-config"}
            mock.return_value.get_tool_config.return_value = tool_config

            from deerflow.community.keenable.tools import _get_api_key

            assert _get_api_key("web_search") == "from-config"

    def test_falls_back_to_env_when_config_key_blank(self):
        with patch("deerflow.community.keenable.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "   "}
            mock.return_value.get_tool_config.return_value = tool_config
            with patch.dict("os.environ", {"KEENABLE_API_KEY": "env-key"}, clear=True):
                from deerflow.community.keenable.tools import _get_api_key

                assert _get_api_key("web_search") == "env-key"

    def test_returns_none_when_no_key_anywhere(self):
        """No key is not an error: it selects the keyless endpoint."""
        with patch("deerflow.community.keenable.tools.get_app_config") as mock:
            mock.return_value.get_tool_config.return_value = None
            with patch.dict("os.environ", {}, clear=True):
                from deerflow.community.keenable.tools import _get_api_key

                assert _get_api_key("web_search") is None


class TestEndpointSelection:
    def test_configured_key_uses_keyed_endpoint_with_header(self, mock_config_with_key):
        patcher, mock_client_cls = _patch_post(_make_response({"results": [_hit()]}))
        try:
            from deerflow.community.keenable.tools import web_search_tool

            web_search_tool.invoke({"query": "test"})
            call = _post_call(mock_client_cls)
        finally:
            patcher.stop()

        assert call.args[0] == KEYED_ENDPOINT
        assert call.kwargs["headers"]["X-API-Key"] == "test-keenable-key"
        assert call.kwargs["json"] == {"query": "test", "max_results": 5}

    def test_no_key_uses_keyless_endpoint_without_auth_header(self, mock_config_no_key):
        """A key is only ever sent to the keyed endpoint."""
        with patch.dict("os.environ", {}, clear=True):
            patcher, mock_client_cls = _patch_post(_make_response({"results": [_hit()]}))
            try:
                from deerflow.community.keenable.tools import web_search_tool

                web_search_tool.invoke({"query": "test"})
                call = _post_call(mock_client_cls)
            finally:
                patcher.stop()

        assert call.args[0] == KEYLESS_ENDPOINT
        assert "X-API-Key" not in call.kwargs["headers"]
        assert call.kwargs["json"] == {"query": "test", "max_results": 5}

    def test_env_key_uses_keyed_endpoint(self, mock_config_no_key):
        with patch.dict("os.environ", {"KEENABLE_API_KEY": "env-key"}, clear=True):
            patcher, mock_client_cls = _patch_post(_make_response({"results": [_hit()]}))
            try:
                from deerflow.community.keenable.tools import web_search_tool

                web_search_tool.invoke({"query": "test"})
                call = _post_call(mock_client_cls)
            finally:
                patcher.stop()

        assert call.args[0] == KEYED_ENDPOINT
        assert call.kwargs["headers"]["X-API-Key"] == "env-key"

    @pytest.mark.parametrize("with_key", [True, False])
    def test_identifies_deerflow_in_app_title_header(self, with_key, mock_config_no_key):
        """The keyless endpoint answers 400 without X-Keenable-Title; both endpoints get it."""
        env = {"KEENABLE_API_KEY": "k"} if with_key else {}
        with patch.dict("os.environ", env, clear=True):
            patcher, mock_client_cls = _patch_post(_make_response({"results": [_hit()]}))
            try:
                from deerflow.community.keenable.tools import web_search_tool

                web_search_tool.invoke({"query": "test"})
                call = _post_call(mock_client_cls)
            finally:
                patcher.stop()

        assert call.kwargs["headers"]["X-Keenable-Title"] == "deer-flow"


class TestWebSearchTool:
    def test_returns_normalized_list(self, mock_config_with_key):
        payload = {
            "query": "vector databases",
            "results": [
                _hit(url="https://ex.com/a", title="A", snippet="s1", published_at="2026-05-21T00:00:00Z"),
                _hit(url="https://ex.com/b", title="B", snippet="s2"),
            ],
        }

        parsed = _invoke(payload, {"query": "vector databases"})

        assert parsed == [
            {"title": "A", "url": "https://ex.com/a", "snippet": "s1", "published_at": "2026-05-21T00:00:00Z"},
            {"title": "B", "url": "https://ex.com/b", "snippet": "s2"},
        ]

    def test_falls_back_to_description_when_snippet_missing(self, mock_config_with_key):
        payload = {"results": [_hit(snippet="", description="desc"), {"url": "https://n.com", "title": "N", "description": "d2"}]}

        parsed = _invoke(payload)

        assert [r["snippet"] for r in parsed] == ["desc", "d2"]

    def test_snippet_is_capped(self, mock_config_with_key):
        from deerflow.community.keenable.tools import _SNIPPET_MAX_CHARS

        parsed = _invoke({"results": [_hit(snippet="x" * (_SNIPPET_MAX_CHARS + 500))]})

        assert len(parsed[0]["snippet"]) == _SNIPPET_MAX_CHARS

    def test_default_search_stays_under_the_externalize_threshold(self, mock_config_with_key):
        """Five capped results must stay inline rather than being persisted to disk."""
        payload = {"results": [_hit(url=f"https://ex.com/{i}", title=f"R{i}", snippet="x" * 20000) for i in range(5)]}
        patcher, _ = _patch_post(_make_response(payload))
        try:
            from deerflow.community.keenable.tools import web_search_tool

            output = web_search_tool.invoke({"query": "test"})
        finally:
            patcher.stop()

        assert len(output) < 12000

    def test_results_trimmed_to_count(self, mock_config_with_key):
        payload = {"results": [_hit(url=f"https://w{i}.com", title=f"W{i}") for i in range(8)]}

        parsed = _invoke(payload)

        assert [r["title"] for r in parsed] == ["W0", "W1", "W2", "W3", "W4"]

    def test_agent_max_results_is_honored_over_config(self, mock_config_with_key):
        patcher, mock_client_cls = _patch_post(_make_response({"results": [_hit()]}))
        try:
            from deerflow.community.keenable.tools import web_search_tool

            web_search_tool.invoke({"query": "test", "max_results": 20})
            body = _post_call(mock_client_cls).kwargs["json"]
        finally:
            patcher.stop()

        assert body["max_results"] == 20

    def test_config_max_results_used_when_caller_omits(self, mock_config_with_key):
        mock_config_with_key.return_value.get_tool_config.return_value.model_extra = {"api_key": "k", "max_results": 8}
        patcher, mock_client_cls = _patch_post(_make_response({"results": [_hit()]}))
        try:
            from deerflow.community.keenable.tools import web_search_tool

            web_search_tool.invoke({"query": "test"})
            body = _post_call(mock_client_cls).kwargs["json"]
        finally:
            patcher.stop()

        assert body["max_results"] == 8

    @pytest.mark.parametrize(("max_results", "expected"), [(0, 5), (-2, 5), (1, 1), (50, 50), (51, 50), ("500", 50)])
    def test_max_results_clamped_to_provider_bounds(self, max_results, expected):
        with patch("deerflow.community.keenable.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "k", "max_results": max_results}
            mock.return_value.get_tool_config.return_value = tool_config
            patcher, mock_client_cls = _patch_post(_make_response({"results": [_hit()]}))
            try:
                from deerflow.community.keenable.tools import web_search_tool

                web_search_tool.invoke({"query": "test"})
                body = _post_call(mock_client_cls).kwargs["json"]
            finally:
                patcher.stop()

        assert body["max_results"] == expected

    def test_invalid_max_results_falls_back_to_default_with_warning(self, caplog):
        with patch("deerflow.community.keenable.tools.get_app_config") as mock:
            tool_config = MagicMock()
            tool_config.model_extra = {"api_key": "k", "max_results": "not-a-number"}
            mock.return_value.get_tool_config.return_value = tool_config
            patcher, mock_client_cls = _patch_post(_make_response({"results": [_hit()]}))
            try:
                from deerflow.community.keenable.tools import web_search_tool

                with caplog.at_level(logging.WARNING, logger="deerflow.community.keenable.tools"):
                    web_search_tool.invoke({"query": "test"})
                body = _post_call(mock_client_cls).kwargs["json"]
            finally:
                patcher.stop()

        assert body["max_results"] == 5
        assert any("Invalid Keenable max_results" in record.message for record in caplog.records)

    @pytest.mark.parametrize("payload", [{"results": []}, {"results": None}, {"query": "q"}])
    def test_empty_or_missing_results_returns_no_results(self, payload, mock_config_with_key):
        parsed = _invoke(payload, {"query": "no results"})

        assert parsed == {"error": "No results found", "query": "no results"}

    def test_non_dict_payload_returns_format_error(self, mock_config_with_key):
        parsed = _invoke(["not", "a", "dict"])

        assert parsed["error"] == FORMAT_ERROR

    def test_unexpected_results_type_returns_format_error(self, mock_config_with_key):
        parsed = _invoke({"results": "nope"})

        assert parsed["error"] == FORMAT_ERROR

    @pytest.mark.parametrize("results", [["a", "b"], [None, None], [1, 2], [[]], [False]])
    def test_results_without_any_objects_returns_format_error(self, mock_config_with_key, results, caplog):
        """A non-empty `results` holding no objects is malformed, not an empty search."""
        with caplog.at_level(logging.ERROR):
            parsed = _invoke({"results": results})

        assert parsed["error"] == FORMAT_ERROR
        assert any("no usable result objects" in r.getMessage() for r in caplog.records if r.levelno == logging.ERROR)

    def test_mixed_results_keep_the_object_entries(self, mock_config_with_key):
        parsed = _invoke({"results": ["junk", _hit(title="Kept"), 7]})

        assert [r["title"] for r in parsed] == ["Kept"]

    def test_partial_or_null_fields_default_to_empty_string(self, mock_config_with_key):
        parsed = _invoke({"results": [{}, {"title": None, "url": None, "snippet": None, "published_at": None}]})

        assert parsed == [{"title": "", "url": "", "snippet": ""}, {"title": "", "url": "", "snippet": ""}]

    @pytest.mark.parametrize(
        ("status", "hint"),
        [
            (401, "invalid or expired KEENABLE_API_KEY"),
            (429, "rate limit reached, set KEENABLE_API_KEY for higher limits"),
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
        patcher, _ = _patch_post(mock_resp)
        try:
            from deerflow.community.keenable.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))
        finally:
            patcher.stop()

        assert str(status) in parsed["error"]
        if hint:
            assert hint in parsed["error"]

    def test_network_exception_returns_error_json(self, mock_config_with_key):
        patcher, mock_client_cls = _patch_post(MagicMock())
        mock_client_cls.return_value.__enter__.return_value.post.side_effect = Exception("timeout")
        try:
            from deerflow.community.keenable.tools import web_search_tool

            parsed = json.loads(web_search_tool.invoke({"query": "test"}))
        finally:
            patcher.stop()

        assert parsed["error"] == "timeout"


@pytest.mark.parametrize(
    "raw",
    [float("inf"), True, 3.5],
    ids=["yaml-inf", "bool", "non-integral-float"],
)
def test_invalid_max_results_shapes_fall_back_to_default(raw):
    """Invalid max_results shapes fall back to the default, never crash or truncate.

    The shared ``coerce_max_results`` owns the rejection profile; this provider
    only adds the 1-50 cap on top.
    """
    with patch("deerflow.community.keenable.tools.get_app_config") as mock:
        tool_config = MagicMock()
        tool_config.model_extra = {"api_key": "k", "max_results": raw}
        mock.return_value.get_tool_config.return_value = tool_config
        patcher, mock_client_cls = _patch_post(_make_response({"results": [_hit()]}))
        try:
            from deerflow.community.keenable.tools import web_search_tool

            web_search_tool.invoke({"query": "test"})
            body = _post_call(mock_client_cls).kwargs["json"]
        finally:
            patcher.stop()

    assert body["max_results"] == 5


def test_package_exports_web_search_tool():
    from deerflow.community.keenable import web_search_tool
    from deerflow.community.keenable.tools import web_search_tool as direct_web_search_tool

    assert web_search_tool is direct_web_search_tool
