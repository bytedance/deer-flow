"""Unit tests for the fastCRW community tools."""

import ipaddress
import json
import logging
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def public_dns():
    """Keep mocked tool calls offline while exercising the real URL safety check."""
    with patch(
        "deerflow.community.url_safety.resolve_host_addresses",
        return_value=[ipaddress.ip_address("93.184.216.34")],
    ):
        yield


class TestWebSearchTool:
    @patch.dict("os.environ", {}, clear=True)
    @patch("deerflow.community.fastcrw.tools.FirecrawlApp")
    @patch("deerflow.community.fastcrw.tools.get_app_config")
    def test_search_uses_web_search_config(self, mock_get_app_config, mock_fastcrw_cls):
        search_config = MagicMock()
        search_config.model_extra = {"api_key": "fastcrw-search-key", "max_results": 7}
        mock_get_app_config.return_value.get_tool_config.return_value = search_config

        mock_result = MagicMock()
        mock_result.web = [
            MagicMock(title="Result", url="https://example.com", description="Snippet"),
        ]
        mock_fastcrw_cls.return_value.search.return_value = mock_result

        from deerflow.community.fastcrw.tools import web_search_tool

        result = web_search_tool.invoke({"query": "test query"})

        assert json.loads(result) == [
            {
                "title": "Result",
                "url": "https://example.com",
                "snippet": "Snippet",
            }
        ]
        mock_get_app_config.return_value.get_tool_config.assert_called_with("web_search")
        mock_fastcrw_cls.assert_called_once_with(api_key="fastcrw-search-key", api_url="https://fastcrw.com/api")
        mock_fastcrw_cls.return_value.search.assert_called_once_with("test query", limit=7)

    @patch.dict("os.environ", {"CRW_API_KEY": "env-key", "CRW_API_URL": "http://self-hosted:3000"}, clear=True)
    @patch("deerflow.community.fastcrw.tools.FirecrawlApp")
    @patch("deerflow.community.fastcrw.tools.get_app_config")
    def test_search_falls_back_to_env_and_default_max_results(self, mock_get_app_config, mock_fastcrw_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = None

        mock_result = MagicMock()
        mock_result.web = []
        mock_fastcrw_cls.return_value.search.return_value = mock_result

        from deerflow.community.fastcrw.tools import web_search_tool

        result = web_search_tool.invoke({"query": "q"})

        assert result == "[]"
        mock_fastcrw_cls.assert_called_once_with(api_key="env-key", api_url="http://self-hosted:3000")
        mock_fastcrw_cls.return_value.search.assert_called_once_with("q", limit=5)

    @patch.dict("os.environ", {}, clear=True)
    @patch("deerflow.community.fastcrw.tools.FirecrawlApp")
    @patch("deerflow.community.fastcrw.tools.get_app_config")
    def test_search_returns_error_string_on_exception(self, mock_get_app_config, mock_fastcrw_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = None
        mock_fastcrw_cls.return_value.search.side_effect = RuntimeError("boom")

        from deerflow.community.fastcrw.tools import web_search_tool

        assert web_search_tool.invoke({"query": "q"}) == "Error: boom"


class TestWebFetchTool:
    @patch.dict("os.environ", {}, clear=True)
    @patch("deerflow.community.fastcrw.tools.FirecrawlApp")
    @patch("deerflow.community.fastcrw.tools.get_app_config")
    @pytest.mark.usefixtures("public_dns")
    def test_fetch_uses_web_fetch_config(self, mock_get_app_config, mock_fastcrw_cls):
        fetch_config = MagicMock()
        fetch_config.model_extra = {"api_key": "fastcrw-fetch-key", "base_url": "http://localhost:3000"}

        def get_tool_config(name):
            if name == "web_fetch":
                return fetch_config
            return None

        mock_get_app_config.return_value.get_tool_config.side_effect = get_tool_config

        mock_scrape_result = MagicMock()
        mock_scrape_result.markdown = "Fetched markdown"
        mock_scrape_result.metadata = MagicMock(title="Fetched Page")
        mock_fastcrw_cls.return_value.scrape.return_value = mock_scrape_result

        from deerflow.community.fastcrw.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "# Fetched Page\n\nFetched markdown"
        mock_get_app_config.return_value.get_tool_config.assert_any_call("web_fetch")
        mock_fastcrw_cls.assert_called_once_with(api_key="fastcrw-fetch-key", api_url="http://localhost:3000")
        mock_fastcrw_cls.return_value.scrape.assert_called_once_with(
            "https://example.com",
            formats=["markdown"],
        )

    @patch.dict("os.environ", {}, clear=True)
    @patch("deerflow.community.fastcrw.tools.FirecrawlApp")
    @patch("deerflow.community.fastcrw.tools.get_app_config")
    @pytest.mark.usefixtures("public_dns")
    def test_fetch_returns_error_when_no_content(self, mock_get_app_config, mock_fastcrw_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = None

        mock_scrape_result = MagicMock()
        mock_scrape_result.markdown = ""
        mock_scrape_result.metadata = MagicMock(title="Empty")
        mock_fastcrw_cls.return_value.scrape.return_value = mock_scrape_result

        from deerflow.community.fastcrw.tools import web_fetch_tool

        assert web_fetch_tool.invoke({"url": "https://example.com"}) == "Error: No content found"

    @patch.dict("os.environ", {}, clear=True)
    @patch("deerflow.community.fastcrw.tools.FirecrawlApp")
    @patch("deerflow.community.fastcrw.tools.get_app_config")
    @pytest.mark.usefixtures("public_dns")
    def test_fetch_returns_error_string_on_exception(self, mock_get_app_config, mock_fastcrw_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = None
        mock_fastcrw_cls.return_value.scrape.side_effect = RuntimeError("scrape failed")

        from deerflow.community.fastcrw.tools import web_fetch_tool

        assert web_fetch_tool.invoke({"url": "https://example.com"}) == "Error: scrape failed"

    @patch.dict("os.environ", {}, clear=True)
    @patch("deerflow.community.fastcrw.tools.FirecrawlApp")
    @patch("deerflow.community.fastcrw.tools.get_app_config")
    def test_fetch_rejects_metadata_ip(self, mock_get_app_config, mock_fastcrw_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = None

        from deerflow.community.fastcrw.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "http://169.254.169.254/latest/meta-data/"})

        assert "private, loopback, or metadata" in result
        mock_fastcrw_cls.assert_not_called()

    @patch.dict("os.environ", {}, clear=True)
    @patch("deerflow.community.fastcrw.tools.FirecrawlApp")
    @patch("deerflow.community.fastcrw.tools.get_app_config")
    def test_fetch_rejects_dns_resolving_to_private(self, mock_get_app_config, mock_fastcrw_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = None

        from deerflow.community.fastcrw.tools import web_fetch_tool

        with patch(
            "deerflow.community.url_safety.resolve_host_addresses",
            return_value=[ipaddress.ip_address("10.0.0.5")],
        ):
            result = web_fetch_tool.invoke({"url": "https://internal.example.com/"})

        assert "private, loopback, or metadata" in result
        mock_fastcrw_cls.assert_not_called()

    @patch.dict("os.environ", {}, clear=True)
    @patch("deerflow.community.fastcrw.tools.FirecrawlApp")
    @patch("deerflow.community.fastcrw.tools.get_app_config")
    def test_fetch_allows_private_when_opted_in(self, mock_get_app_config, mock_fastcrw_cls):
        fetch_config = MagicMock()
        fetch_config.model_extra = {"allow_private_addresses": True, "base_url": "http://localhost:3000"}
        mock_get_app_config.return_value.get_tool_config.return_value = fetch_config

        mock_scrape_result = MagicMock()
        mock_scrape_result.markdown = "Private markdown"
        mock_scrape_result.metadata = MagicMock(title="Private Page")
        mock_fastcrw_cls.return_value.scrape.return_value = mock_scrape_result

        from deerflow.community.fastcrw.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "http://10.0.0.5/dashboard"})

        assert result == "# Private Page\n\nPrivate markdown"
        mock_fastcrw_cls.return_value.scrape.assert_called_once_with(
            "http://10.0.0.5/dashboard",
            formats=["markdown"],
        )


# `None` is itself a configured value (`max_results:` with nothing after it in YAML), so an absent key
# needs its own sentinel — otherwise the key-present case is never built and never tested.
_OMITTED = object()


@pytest.mark.parametrize(
    ("configured", "expected_limit", "warns"),
    [
        pytest.param(True, 5, True, id="bool"),
        pytest.param(0, 5, True, id="zero"),
        pytest.param(-3, 5, True, id="negative"),
        pytest.param(3.5, 5, True, id="fractional"),
        pytest.param("many", 5, True, id="non-numeric-string"),
        pytest.param("8", 8, False, id="integer-string"),
        pytest.param(7, 7, False, id="plain-int"),
        pytest.param(None, 5, True, id="explicit-null"),
        pytest.param(_OMITTED, 5, False, id="omitted"),
    ],
)
@patch.dict("os.environ", {}, clear=True)
@patch("deerflow.community.fastcrw.tools.FirecrawlApp")
@patch("deerflow.community.fastcrw.tools.get_app_config")
def test_search_normalizes_max_results_before_calling_the_client(mock_get_app_config, mock_fastcrw_cls, caplog, configured, expected_limit, warns):
    search_config = MagicMock()
    extra: dict[str, object] = {"api_key": "fastcrw-search-key"}
    if configured is not _OMITTED:
        extra["max_results"] = configured
    search_config.model_extra = extra
    mock_get_app_config.return_value.get_tool_config.return_value = search_config

    mock_result = MagicMock()
    mock_result.web = []
    mock_fastcrw_cls.return_value.search.return_value = mock_result

    from deerflow.community.fastcrw.tools import web_search_tool

    with caplog.at_level(logging.WARNING, logger="deerflow.community.fastcrw.tools"):
        result = web_search_tool.invoke({"query": "q"})

    assert result == "[]"
    mock_fastcrw_cls.return_value.search.assert_called_once_with("q", limit=expected_limit)
    assert ("Invalid fastCRW max_results" in caplog.text) is warns
