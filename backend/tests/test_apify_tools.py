"""Unit tests for the Apify community tools."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, call, patch


def _make_tool_config(api_key="test-key", **extra):
    """Return a mock tool config with a default test API key and optional field overrides."""
    cfg = MagicMock()
    cfg.model_extra = {"api_key": api_key, **extra}
    return cfg


class TestWebSearchTool:
    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_returns_normalized_json(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config(max_results=3)

        mock_run = {"defaultDatasetId": "dataset-123"}
        mock_apify_cls.return_value.actor.return_value.call.return_value = mock_run
        mock_apify_cls.return_value.dataset.return_value.iterate_items.return_value = iter([{"organicResults": [{"title": "T", "url": "https://example.com", "description": "S"}]}])

        from deerflow.community.apify.tools import web_search_tool

        result = web_search_tool.invoke({"query": "test"})

        assert json.loads(result) == [{"title": "T", "url": "https://example.com", "snippet": "S"}]

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_uses_max_results_from_config(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config(max_results=7)

        mock_run = {"defaultDatasetId": "dataset-123"}
        mock_apify_cls.return_value.actor.return_value.call.return_value = mock_run
        mock_apify_cls.return_value.dataset.return_value.iterate_items.return_value = iter([{"organicResults": []}])

        from deerflow.community.apify.tools import web_search_tool

        web_search_tool.invoke({"query": "test"})

        mock_apify_cls.return_value.actor.return_value.call.assert_called_once_with(run_input={"queries": ["test"], "maxPagesPerQuery": 1, "resultsPerPage": 7})

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_uses_api_key_from_config(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config(api_key="my-apify-key", max_results=5)

        mock_run = {"defaultDatasetId": "dataset-123"}
        mock_apify_cls.return_value.actor.return_value.call.return_value = mock_run
        mock_apify_cls.return_value.dataset.return_value.iterate_items.return_value = iter([{"organicResults": []}])

        from deerflow.community.apify.tools import web_search_tool

        web_search_tool.invoke({"query": "test"})

        mock_apify_cls.assert_called_with("my-apify-key")

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_returns_error_string_on_exception(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.actor.return_value.call.side_effect = RuntimeError("actor failed")

        from deerflow.community.apify.tools import web_search_tool

        result = web_search_tool.invoke({"query": "test"})

        assert result.startswith("Error:")

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_caps_results_at_max_results(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config(max_results=2)

        mock_run = {"defaultDatasetId": "dataset-123"}
        mock_apify_cls.return_value.actor.return_value.call.return_value = mock_run
        organic = [{"title": f"T{i}", "url": f"https://example.com/{i}", "description": "S"} for i in range(5)]
        mock_apify_cls.return_value.dataset.return_value.iterate_items.return_value = iter([{"organicResults": organic}])

        from deerflow.community.apify.tools import web_search_tool

        result = web_search_tool.invoke({"query": "test"})

        assert len(json.loads(result)) == 2

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_uses_defaults_when_config_is_none(self, mock_get_app_config, mock_apify_cls):
        # Omit max_results to verify the default of 5 is used.
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config()

        mock_run = {"defaultDatasetId": "dataset-123"}
        mock_apify_cls.return_value.actor.return_value.call.return_value = mock_run
        mock_apify_cls.return_value.dataset.return_value.iterate_items.return_value = iter([{"organicResults": []}])

        from deerflow.community.apify.tools import web_search_tool

        web_search_tool.invoke({"query": "test"})

        mock_apify_cls.return_value.actor.return_value.call.assert_called_once_with(run_input={"queries": ["test"], "maxPagesPerQuery": 1, "resultsPerPage": 5})


class TestWebFetchTool:
    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_returns_markdown_with_title(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config(crawler_type="cheerio")

        mock_run = {"defaultDatasetId": "dataset-123"}
        mock_apify_cls.return_value.actor.return_value.call.return_value = mock_run
        mock_apify_cls.return_value.dataset.return_value.iterate_items.return_value = iter([{"title": "My Page", "markdown": "Hello world", "text": ""}])

        from deerflow.community.apify.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "# My Page\n\nHello world"

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_uses_crawler_type_from_config(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config(crawler_type="playwright:firefox")

        mock_run = {"defaultDatasetId": "dataset-123"}
        mock_apify_cls.return_value.actor.return_value.call.return_value = mock_run
        mock_apify_cls.return_value.dataset.return_value.iterate_items.return_value = iter([{"title": "Page", "markdown": "content", "text": ""}])

        from deerflow.community.apify.tools import web_fetch_tool

        web_fetch_tool.invoke({"url": "https://example.com"})

        mock_apify_cls.return_value.actor.return_value.call.assert_called_once_with(run_input={"startUrls": [{"url": "https://example.com"}], "maxCrawlPages": 1, "crawlerType": "playwright:firefox"})

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_falls_back_to_text_when_no_markdown(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config()

        mock_run = {"defaultDatasetId": "dataset-123"}
        mock_apify_cls.return_value.actor.return_value.call.return_value = mock_run
        mock_apify_cls.return_value.dataset.return_value.iterate_items.return_value = iter([{"title": "Page", "markdown": "", "text": "plain text fallback"}])

        from deerflow.community.apify.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "# Page\n\nplain text fallback"

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_returns_error_when_no_items(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config()

        mock_run = {"defaultDatasetId": "dataset-123"}
        mock_apify_cls.return_value.actor.return_value.call.return_value = mock_run
        mock_apify_cls.return_value.dataset.return_value.iterate_items.return_value = iter([])

        from deerflow.community.apify.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result == "Error: No content found"

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_truncates_content_to_4096_bytes(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config()

        mock_run = {"defaultDatasetId": "dataset-123"}
        mock_apify_cls.return_value.actor.return_value.call.return_value = mock_run
        long_content = "x" * 5000
        mock_apify_cls.return_value.dataset.return_value.iterate_items.return_value = iter([{"title": "Page", "markdown": long_content, "text": ""}])

        from deerflow.community.apify.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result.endswith("\n\n[Content truncated]")
        # Body is exactly 4096 bytes of ASCII content
        body = result[len("# Page\n\n") : -len("\n\n[Content truncated]")]
        assert len(body.encode("utf-8")) <= 4096

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_no_truncation_marker_when_short(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config()

        mock_run = {"defaultDatasetId": "dataset-123"}
        mock_apify_cls.return_value.actor.return_value.call.return_value = mock_run
        mock_apify_cls.return_value.dataset.return_value.iterate_items.return_value = iter([{"title": "Page", "markdown": "short content", "text": ""}])

        from deerflow.community.apify.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert "[Content truncated]" not in result

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_returns_error_string_on_exception(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.actor.return_value.call.side_effect = RuntimeError("network error")

        from deerflow.community.apify.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "https://example.com"})

        assert result.startswith("Error:")

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_uses_defaults_when_no_optional_config(self, mock_get_app_config, mock_apify_cls):
        # Omit crawler_type to verify the default of "cheerio" is used.
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config()

        mock_run = {"defaultDatasetId": "dataset-123"}
        mock_apify_cls.return_value.actor.return_value.call.return_value = mock_run
        mock_apify_cls.return_value.dataset.return_value.iterate_items.return_value = iter([{"title": "Page", "markdown": "content", "text": ""}])

        from deerflow.community.apify.tools import web_fetch_tool

        web_fetch_tool.invoke({"url": "https://example.com"})

        mock_apify_cls.return_value.actor.return_value.call.assert_called_once_with(run_input={"startUrls": [{"url": "https://example.com"}], "maxCrawlPages": 1, "crawlerType": "cheerio"})


class TestApifyActorDiscoverTool:
    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_store_search_returns_actor_list(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config()
        mock_result = MagicMock()
        mock_result.items = [
            {"username": "apify", "name": "instagram-scraper", "title": "Instagram Scraper", "description": "Scrapes Instagram"},
        ]
        mock_apify_cls.return_value.store.return_value.list.return_value = mock_result

        from deerflow.community.apify.tools import apify_actor_discover_tool

        result = json.loads(apify_actor_discover_tool.invoke({"query": "instagram"}))

        assert result["action"] == "store_search"
        assert result["count"] == 1
        assert result["actors"][0]["actorId"] == "apify/instagram-scraper"
        mock_apify_cls.return_value.store.return_value.list.assert_called_once_with(search="instagram", limit=10)

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_store_search_filters_actors_with_missing_fields(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config()
        mock_result = MagicMock()
        mock_result.items = [
            {"username": "", "name": "test", "title": "T", "description": "D"},
            {"username": "apify", "name": "", "title": "T", "description": "D"},
            {"username": "apify", "name": "valid", "title": "Valid", "description": "OK"},
        ]
        mock_apify_cls.return_value.store.return_value.list.return_value = mock_result

        from deerflow.community.apify.tools import apify_actor_discover_tool

        result = json.loads(apify_actor_discover_tool.invoke({"query": "test"}))

        assert result["count"] == 1
        assert result["actors"][0]["actorId"] == "apify/valid"

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_actor_schema_fetches_via_version_detail(self, mock_get_app_config, mock_apify_cls):
        """inputSchema is fetched from the version detail endpoint, not the version list."""
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.actor.return_value.get.return_value = {"title": "My Actor", "description": "Desc"}
        mock_versions = MagicMock()
        mock_versions.items = [{"versionNumber": "0.1"}]
        mock_apify_cls.return_value.actor.return_value.versions.return_value.list.return_value = mock_versions
        mock_apify_cls.return_value.actor.return_value.version.return_value.get.return_value = {"inputSchema": '{"type": "object", "properties": {}}'}

        from deerflow.community.apify.tools import apify_actor_discover_tool

        result = json.loads(apify_actor_discover_tool.invoke({"actor_id": "apify/my-actor"}))

        assert result["action"] == "actor_schema"
        assert result["actorId"] == "apify/my-actor"
        # JSON string inputSchema is parsed into a dict to avoid double-encoding
        assert result["inputSchema"] == {"type": "object", "properties": {}}
        mock_apify_cls.return_value.actor.return_value.version.assert_called_once_with("0.1")

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_actor_schema_preserves_dict_input_schema(self, mock_get_app_config, mock_apify_cls):
        """inputSchema that is already a dict is returned as-is."""
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.actor.return_value.get.return_value = {"title": "My Actor", "description": "Desc"}
        mock_versions = MagicMock()
        mock_versions.items = [{"versionNumber": "1.0"}]
        mock_apify_cls.return_value.actor.return_value.versions.return_value.list.return_value = mock_versions
        mock_apify_cls.return_value.actor.return_value.version.return_value.get.return_value = {"inputSchema": {"type": "object"}}

        from deerflow.community.apify.tools import apify_actor_discover_tool

        result = json.loads(apify_actor_discover_tool.invoke({"actor_id": "apify/my-actor"}))

        assert result["inputSchema"] == {"type": "object"}

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_actor_schema_returns_none_when_versions_raises(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.actor.return_value.get.return_value = {"title": "My Actor", "description": "Desc"}
        mock_apify_cls.return_value.actor.return_value.versions.return_value.list.side_effect = RuntimeError("API error")

        from deerflow.community.apify.tools import apify_actor_discover_tool

        result = json.loads(apify_actor_discover_tool.invoke({"actor_id": "apify/my-actor"}))

        assert result["action"] == "actor_schema"
        assert result["inputSchema"] is None

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_returns_error_when_actor_not_found(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.actor.return_value.get.return_value = None

        from deerflow.community.apify.tools import apify_actor_discover_tool

        result = apify_actor_discover_tool.invoke({"actor_id": "apify/nonexistent"})

        assert "Error" in result and "not found" in result

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_accepts_plain_actor_id(self, mock_get_app_config, mock_apify_cls):
        """Plain IDs like 'h7sDV53CddomktSi5' are valid — client accepts both formats."""
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.actor.return_value.get.return_value = {"title": "YouTube Scraper", "description": "..."}
        mock_versions = MagicMock()
        mock_versions.items = []
        mock_apify_cls.return_value.actor.return_value.versions.return_value.list.return_value = mock_versions

        from deerflow.community.apify.tools import apify_actor_discover_tool

        result = json.loads(apify_actor_discover_tool.invoke({"actor_id": "h7sDV53CddomktSi5"}))

        assert result["action"] == "actor_schema"
        mock_apify_cls.return_value.actor.assert_called_with("h7sDV53CddomktSi5")

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_returns_error_when_neither_provided(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config()

        from deerflow.community.apify.tools import apify_actor_discover_tool

        result = apify_actor_discover_tool.invoke({"query": "", "actor_id": ""})

        assert result.startswith("Error:")

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_returns_error_when_both_provided(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config()

        from deerflow.community.apify.tools import apify_actor_discover_tool

        result = apify_actor_discover_tool.invoke({"query": "instagram", "actor_id": "apify/test"})

        assert result.startswith("Error:")

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_returns_error_string_on_exception(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.store.return_value.list.side_effect = RuntimeError("network error")

        from deerflow.community.apify.tools import apify_actor_discover_tool

        result = apify_actor_discover_tool.invoke({"query": "test"})

        assert result.startswith("Error:")


class TestApifyActorStartTool:
    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_returns_run_reference_in_array(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.actor.return_value.start.return_value = {"id": "run-123", "defaultDatasetId": "ds-456", "status": "RUNNING"}

        from deerflow.community.apify.tools import apify_actor_start_tool

        result = json.loads(apify_actor_start_tool.invoke({"actor_id": "apify/test", "run_input": "{}"}))

        assert result["action"] == "start"
        assert isinstance(result["runs"], list)
        assert len(result["runs"]) == 1
        ref = result["runs"][0]
        assert ref["runId"] == "run-123"
        assert ref["actorId"] == "apify/test"
        assert ref["datasetId"] == "ds-456"

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_description_included_when_provided(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.actor.return_value.start.return_value = {"id": "run-123", "defaultDatasetId": "ds-456", "status": "RUNNING"}

        from deerflow.community.apify.tools import apify_actor_start_tool

        result = json.loads(apify_actor_start_tool.invoke({"actor_id": "apify/test", "run_input": "{}", "description": "my-run"}))

        assert result["runs"][0]["description"] == "my-run"

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_description_absent_when_not_provided(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.actor.return_value.start.return_value = {"id": "run-123", "defaultDatasetId": "ds-456", "status": "RUNNING"}

        from deerflow.community.apify.tools import apify_actor_start_tool

        result = json.loads(apify_actor_start_tool.invoke({"actor_id": "apify/test", "run_input": "{}"}))

        assert "description" not in result["runs"][0]

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_calls_start_not_call(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.actor.return_value.start.return_value = {"id": "run-123", "defaultDatasetId": "ds-456", "status": "RUNNING"}

        from deerflow.community.apify.tools import apify_actor_start_tool

        apify_actor_start_tool.invoke({"actor_id": "apify/test", "run_input": "{}"})

        mock_apify_cls.return_value.actor.return_value.start.assert_called_once()
        mock_apify_cls.return_value.actor.return_value.call.assert_not_called()

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_uses_timeout_secs_from_config(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config(timeout_secs=60)
        mock_apify_cls.return_value.actor.return_value.start.return_value = {"id": "run-123", "defaultDatasetId": "ds-456", "status": "RUNNING"}

        from deerflow.community.apify.tools import apify_actor_start_tool

        apify_actor_start_tool.invoke({"actor_id": "apify/test", "run_input": "{}"})

        mock_apify_cls.return_value.actor.return_value.start.assert_called_once_with(run_input={}, timeout_secs=60)

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_no_timeout_when_not_in_config(self, mock_get_app_config, mock_apify_cls):
        # Omit timeout_secs and memory_mbytes to verify neither is forwarded to .start().
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.actor.return_value.start.return_value = {"id": "run-123", "defaultDatasetId": "ds-456", "status": "RUNNING"}

        from deerflow.community.apify.tools import apify_actor_start_tool

        apify_actor_start_tool.invoke({"actor_id": "apify/test", "run_input": "{}"})

        mock_apify_cls.return_value.actor.return_value.start.assert_called_once_with(run_input={})

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_uses_memory_mbytes_from_config(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config(memory_mbytes=1024)
        mock_apify_cls.return_value.actor.return_value.start.return_value = {"id": "run-123", "defaultDatasetId": "ds-456", "status": "RUNNING"}

        from deerflow.community.apify.tools import apify_actor_start_tool

        apify_actor_start_tool.invoke({"actor_id": "apify/test", "run_input": "{}"})

        mock_apify_cls.return_value.actor.return_value.start.assert_called_once_with(run_input={}, memory_mbytes=1024)

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_returns_error_for_empty_actor_id(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = None

        from deerflow.community.apify.tools import apify_actor_start_tool

        result = apify_actor_start_tool.invoke({"actor_id": "", "run_input": "{}"})

        assert result.startswith("Error:")

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_accepts_plain_actor_id(self, mock_get_app_config, mock_apify_cls):
        """Plain IDs like 'h7sDV53CddomktSi5' are valid — client accepts both formats."""
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.actor.return_value.start.return_value = {"id": "run-123", "defaultDatasetId": "ds-456", "status": "RUNNING"}

        from deerflow.community.apify.tools import apify_actor_start_tool

        result = json.loads(apify_actor_start_tool.invoke({"actor_id": "h7sDV53CddomktSi5", "run_input": "{}"}))

        assert result["action"] == "start"
        mock_apify_cls.return_value.actor.assert_called_with("h7sDV53CddomktSi5")

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_invalid_json_run_input(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = None

        from deerflow.community.apify.tools import apify_actor_start_tool

        result = apify_actor_start_tool.invoke({"actor_id": "apify/test", "run_input": "not json"})

        assert "Error: run_input is not valid JSON" in result

    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_returns_error_string_on_exception(self, mock_get_app_config, mock_apify_cls):
        mock_get_app_config.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.actor.return_value.start.side_effect = RuntimeError("API error")

        from deerflow.community.apify.tools import apify_actor_start_tool

        result = apify_actor_start_tool.invoke({"actor_id": "apify/test", "run_input": "{}"})

        assert result.startswith("Error:")


class TestApifyActorAwaitTool:
    """Tests for apify_actor_await_tool — single async call, no agent looping."""

    def _run(self, coro):
        """Run a coroutine in a fresh event loop for test isolation."""
        return asyncio.run(coro)

    def _make_mock_writer(self):
        return MagicMock()

    @patch("deerflow.community.apify.tools.get_stream_writer")
    @patch("deerflow.community.apify.tools.asyncio.sleep", new_callable=AsyncMock)
    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_returns_results_when_succeeded_immediately(self, mock_cfg, mock_apify_cls, mock_sleep, mock_writer):
        mock_cfg.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.run.return_value.get.return_value = {"status": "SUCCEEDED", "defaultDatasetId": "ds-1"}
        mock_apify_cls.return_value.dataset.return_value.iterate_items.return_value = iter([{"item": 1}])
        mock_writer.return_value = self._make_mock_writer()

        from deerflow.community.apify.tools import apify_actor_await_tool

        result = json.loads(self._run(apify_actor_await_tool.ainvoke({"run_id": "r1", "dataset_id": "ds-1"})))

        assert result["status"] == "SUCCEEDED"
        assert result["resultCount"] == 1
        assert result["results"] == [{"item": 1}]
        mock_sleep.assert_not_called()  # finished on first check, no sleep needed

    @patch("deerflow.community.apify.tools.get_stream_writer")
    @patch("deerflow.community.apify.tools.asyncio.sleep", new_callable=AsyncMock)
    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_polls_until_succeeded(self, mock_cfg, mock_apify_cls, mock_sleep, mock_writer):
        mock_cfg.return_value.get_tool_config.return_value = _make_tool_config()
        responses = [
            {"status": "RUNNING", "defaultDatasetId": "ds-1"},
            {"status": "RUNNING", "defaultDatasetId": "ds-1"},
            {"status": "SUCCEEDED", "defaultDatasetId": "ds-1"},
        ]
        mock_apify_cls.return_value.run.return_value.get.side_effect = responses
        mock_apify_cls.return_value.dataset.return_value.iterate_items.return_value = iter([])
        mock_writer.return_value = self._make_mock_writer()

        from deerflow.community.apify.tools import apify_actor_await_tool

        result = json.loads(self._run(apify_actor_await_tool.ainvoke({"run_id": "r1", "dataset_id": "ds-1"})))

        assert result["status"] == "SUCCEEDED"
        assert mock_sleep.call_count == 2  # slept after each RUNNING response
        # Every sleep call uses the default poll interval
        mock_sleep.assert_has_calls([call(5), call(5)])

    @patch("deerflow.community.apify.tools.get_stream_writer")
    @patch("deerflow.community.apify.tools.asyncio.sleep", new_callable=AsyncMock)
    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_uses_poll_interval_from_config(self, mock_cfg, mock_apify_cls, mock_sleep, mock_writer):
        mock_cfg.return_value.get_tool_config.return_value = _make_tool_config(poll_interval_secs=10, timeout_secs=300, max_items=50)
        responses = [
            {"status": "RUNNING", "defaultDatasetId": "ds-1"},
            {"status": "SUCCEEDED", "defaultDatasetId": "ds-1"},
        ]
        mock_apify_cls.return_value.run.return_value.get.side_effect = responses
        mock_apify_cls.return_value.dataset.return_value.iterate_items.return_value = iter([])
        mock_writer.return_value = self._make_mock_writer()

        from deerflow.community.apify.tools import apify_actor_await_tool

        self._run(apify_actor_await_tool.ainvoke({"run_id": "r1", "dataset_id": "ds-1"}))

        mock_sleep.assert_called_once_with(10)

    @patch("deerflow.community.apify.tools.get_stream_writer")
    @patch("deerflow.community.apify.tools.asyncio.sleep", new_callable=AsyncMock)
    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_returns_error_when_failed(self, mock_cfg, mock_apify_cls, mock_sleep, mock_writer):
        mock_cfg.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.run.return_value.get.return_value = {"status": "FAILED", "defaultDatasetId": "ds-1"}
        mock_writer.return_value = self._make_mock_writer()

        from deerflow.community.apify.tools import apify_actor_await_tool

        result = json.loads(self._run(apify_actor_await_tool.ainvoke({"run_id": "r1", "dataset_id": "ds-1"})))

        assert result["status"] == "FAILED"
        assert "error" in result
        mock_sleep.assert_not_called()

    @patch("deerflow.community.apify.tools.get_stream_writer")
    @patch("deerflow.community.apify.tools.asyncio.sleep", new_callable=AsyncMock)
    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_returns_error_when_aborted(self, mock_cfg, mock_apify_cls, mock_sleep, mock_writer):
        mock_cfg.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.run.return_value.get.return_value = {"status": "ABORTED", "defaultDatasetId": "ds-1"}
        mock_writer.return_value = self._make_mock_writer()

        from deerflow.community.apify.tools import apify_actor_await_tool

        result = json.loads(self._run(apify_actor_await_tool.ainvoke({"run_id": "r1", "dataset_id": "ds-1"})))

        assert result["status"] == "ABORTED"
        assert "error" in result
        mock_sleep.assert_not_called()

    @patch("deerflow.community.apify.tools.get_stream_writer")
    @patch("deerflow.community.apify.tools.asyncio.sleep", new_callable=AsyncMock)
    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_returns_error_when_apify_timed_out(self, mock_cfg, mock_apify_cls, mock_sleep, mock_writer):
        """TIMED-OUT (hyphen) is an Apify API terminal status — distinct from our local TIMED_OUT."""
        mock_cfg.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.run.return_value.get.return_value = {"status": "TIMED-OUT", "defaultDatasetId": "ds-1"}
        mock_writer.return_value = self._make_mock_writer()

        from deerflow.community.apify.tools import apify_actor_await_tool

        result = json.loads(self._run(apify_actor_await_tool.ainvoke({"run_id": "r1", "dataset_id": "ds-1"})))

        assert result["status"] == "TIMED-OUT"
        assert "error" in result
        mock_sleep.assert_not_called()

    @patch("deerflow.community.apify.tools.get_stream_writer")
    @patch("deerflow.community.apify.tools.asyncio.sleep", new_callable=AsyncMock)
    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_description_included_on_succeeded(self, mock_cfg, mock_apify_cls, mock_sleep, mock_writer):
        mock_cfg.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.run.return_value.get.return_value = {"status": "SUCCEEDED", "defaultDatasetId": "ds-1"}
        mock_apify_cls.return_value.dataset.return_value.iterate_items.return_value = iter([])
        mock_writer.return_value = self._make_mock_writer()

        from deerflow.community.apify.tools import apify_actor_await_tool

        result = json.loads(self._run(apify_actor_await_tool.ainvoke({"run_id": "r1", "dataset_id": "ds-1", "description": "my-run"})))

        assert result["description"] == "my-run"

    @patch("deerflow.community.apify.tools.get_stream_writer")
    @patch("deerflow.community.apify.tools.asyncio.sleep", new_callable=AsyncMock)
    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_description_included_on_failed(self, mock_cfg, mock_apify_cls, mock_sleep, mock_writer):
        mock_cfg.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.run.return_value.get.return_value = {"status": "FAILED", "defaultDatasetId": "ds-1"}
        mock_writer.return_value = self._make_mock_writer()

        from deerflow.community.apify.tools import apify_actor_await_tool

        result = json.loads(self._run(apify_actor_await_tool.ainvoke({"run_id": "r1", "dataset_id": "ds-1", "description": "my-run"})))

        assert result["description"] == "my-run"

    @patch("deerflow.community.apify.tools.get_stream_writer")
    @patch("deerflow.community.apify.tools.asyncio.sleep", new_callable=AsyncMock)
    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_returns_error_when_run_not_found(self, mock_cfg, mock_apify_cls, mock_sleep, mock_writer):
        mock_cfg.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.run.return_value.get.return_value = None
        mock_writer.return_value = self._make_mock_writer()

        from deerflow.community.apify.tools import apify_actor_await_tool

        result = json.loads(self._run(apify_actor_await_tool.ainvoke({"run_id": "r1", "dataset_id": "ds-1"})))

        assert result["status"] == "NOT_FOUND"
        assert "error" in result
        assert result["runId"] == "r1"

    @patch("deerflow.community.apify.tools.get_stream_writer")
    @patch("deerflow.community.apify.tools.asyncio.sleep", new_callable=AsyncMock)
    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_emits_terminal_event_when_run_not_found(self, mock_cfg, mock_apify_cls, mock_sleep, mock_writer):
        mock_cfg.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.run.return_value.get.return_value = None
        writer_fn = self._make_mock_writer()
        mock_writer.return_value = writer_fn

        from deerflow.community.apify.tools import apify_actor_await_tool

        self._run(apify_actor_await_tool.ainvoke({"run_id": "r1", "dataset_id": "ds-1"}))

        event_types = [c.args[0]["type"] for c in writer_fn.call_args_list]
        assert "apify_run_failed" in event_types

    @patch("deerflow.community.apify.tools.get_stream_writer")
    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_returns_error_for_empty_run_id(self, mock_cfg, mock_apify_cls, mock_writer):
        mock_cfg.return_value.get_tool_config.return_value = None
        mock_writer.return_value = self._make_mock_writer()

        from deerflow.community.apify.tools import apify_actor_await_tool

        result = self._run(apify_actor_await_tool.ainvoke({"run_id": "", "dataset_id": "ds-1"}))

        assert result.startswith("Error:")

    @patch("deerflow.community.apify.tools.get_stream_writer")
    @patch("deerflow.community.apify.tools.asyncio.sleep", new_callable=AsyncMock)
    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_uses_fresh_dataset_id_from_run(self, mock_cfg, mock_apify_cls, mock_sleep, mock_writer):
        """Dataset ID from the fresh run object takes precedence over the passed-in value."""
        mock_cfg.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.run.return_value.get.return_value = {"status": "SUCCEEDED", "defaultDatasetId": "fresh-ds"}
        mock_apify_cls.return_value.dataset.return_value.iterate_items.return_value = iter([])
        mock_writer.return_value = self._make_mock_writer()

        from deerflow.community.apify.tools import apify_actor_await_tool

        self._run(apify_actor_await_tool.ainvoke({"run_id": "r1", "dataset_id": "stale-ds"}))

        mock_apify_cls.return_value.dataset.assert_called_with("fresh-ds")

    @patch("deerflow.community.apify.tools.get_stream_writer")
    @patch("deerflow.community.apify.tools.asyncio.sleep", new_callable=AsyncMock)
    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_uses_config_values(self, mock_cfg, mock_apify_cls, mock_sleep, mock_writer):
        mock_cfg.return_value.get_tool_config.return_value = _make_tool_config(poll_interval_secs=10, timeout_secs=60, max_items=5)
        mock_apify_cls.return_value.run.return_value.get.return_value = {"status": "SUCCEEDED", "defaultDatasetId": "ds-1"}
        mock_apify_cls.return_value.dataset.return_value.iterate_items.return_value = iter([])
        mock_writer.return_value = self._make_mock_writer()

        from deerflow.community.apify.tools import apify_actor_await_tool

        self._run(apify_actor_await_tool.ainvoke({"run_id": "r1", "dataset_id": "ds-1"}))

        mock_apify_cls.return_value.dataset.return_value.iterate_items.assert_called_once_with(limit=5)

    @patch("deerflow.community.apify.tools.get_stream_writer")
    @patch("deerflow.community.apify.tools.asyncio.sleep", new_callable=AsyncMock)
    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_returns_error_on_sdk_exception(self, mock_cfg, mock_apify_cls, mock_sleep, mock_writer):
        """Non-CancelledError exceptions from the SDK are caught and returned as error JSON."""
        mock_cfg.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.run.return_value.get.side_effect = RuntimeError("network timeout")
        writer_fn = self._make_mock_writer()
        mock_writer.return_value = writer_fn

        from deerflow.community.apify.tools import apify_actor_await_tool

        result = json.loads(self._run(apify_actor_await_tool.ainvoke({"run_id": "r1", "dataset_id": "ds-1"})))

        assert result["status"] == "ERROR"
        assert "network timeout" in result["error"]
        # An apify_run_failed event must be emitted so the frontend knows the run ended
        event_types = [c.args[0]["type"] for c in writer_fn.call_args_list]
        assert "apify_run_failed" in event_types

    @patch("deerflow.community.apify.tools.get_stream_writer")
    @patch("deerflow.community.apify.tools.asyncio.sleep", new_callable=AsyncMock)
    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_streams_polling_events(self, mock_cfg, mock_apify_cls, mock_sleep, mock_writer):
        mock_cfg.return_value.get_tool_config.return_value = _make_tool_config()
        responses = [
            {"status": "RUNNING", "defaultDatasetId": "ds-1"},
            {"status": "SUCCEEDED", "defaultDatasetId": "ds-1"},
        ]
        mock_apify_cls.return_value.run.return_value.get.side_effect = responses
        mock_apify_cls.return_value.dataset.return_value.iterate_items.return_value = iter([])
        writer_fn = self._make_mock_writer()
        mock_writer.return_value = writer_fn

        from deerflow.community.apify.tools import apify_actor_await_tool

        self._run(apify_actor_await_tool.ainvoke({"run_id": "r1", "dataset_id": "ds-1"}))

        events = [c.args[0] for c in writer_fn.call_args_list]
        event_types = [e["type"] for e in events]
        # First event must be the initial WAITING signal before any polling
        assert events[0] == {"type": "apify_run_polling", "runId": "r1", "status": "WAITING", "elapsed_secs": 0}
        # Intermediate RUNNING event and final completion event must both appear
        assert "apify_run_polling" in event_types
        assert event_types[-1] == "apify_run_completed"

    @patch("deerflow.community.apify.tools.get_stream_writer")
    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_times_out_when_deadline_exceeded(self, mock_cfg, mock_apify_cls, mock_writer):
        """With timeout_secs=0 the deadline is start_time+0. By the time the while
        condition is evaluated, real time has advanced past it, so the tool returns
        TIMED_OUT without needing to patch the event loop."""
        mock_cfg.return_value.get_tool_config.return_value = _make_tool_config(poll_interval_secs=0, timeout_secs=0, max_items=50)
        mock_apify_cls.return_value.run.return_value.get.return_value = {"status": "RUNNING", "defaultDatasetId": "ds-1"}
        mock_writer.return_value = self._make_mock_writer()

        from deerflow.community.apify.tools import apify_actor_await_tool

        result = json.loads(self._run(apify_actor_await_tool.ainvoke({"run_id": "r1", "dataset_id": "ds-1"})))

        assert result["status"] == "TIMED_OUT"
        assert "error" in result

    @patch("deerflow.community.apify.tools.get_stream_writer")
    @patch("deerflow.community.apify.tools.asyncio.sleep", new_callable=AsyncMock)
    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_streams_failure_event(self, mock_cfg, mock_apify_cls, mock_sleep, mock_writer):
        mock_cfg.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.run.return_value.get.return_value = {"status": "FAILED", "defaultDatasetId": "ds-1"}
        writer_fn = self._make_mock_writer()
        mock_writer.return_value = writer_fn

        from deerflow.community.apify.tools import apify_actor_await_tool

        self._run(apify_actor_await_tool.ainvoke({"run_id": "r1", "dataset_id": "ds-1"}))

        event_types = [c.args[0]["type"] for c in writer_fn.call_args_list]
        assert "apify_run_failed" in event_types

    @patch("deerflow.community.apify.tools.get_stream_writer")
    @patch("deerflow.community.apify.tools.asyncio.sleep", new_callable=AsyncMock)
    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_returns_empty_results_when_dataset_empty(self, mock_cfg, mock_apify_cls, mock_sleep, mock_writer):
        mock_cfg.return_value.get_tool_config.return_value = _make_tool_config()
        mock_apify_cls.return_value.run.return_value.get.return_value = {"status": "SUCCEEDED", "defaultDatasetId": "ds-1"}
        mock_apify_cls.return_value.dataset.return_value.iterate_items.return_value = iter([])
        mock_writer.return_value = self._make_mock_writer()

        from deerflow.community.apify.tools import apify_actor_await_tool

        result = json.loads(self._run(apify_actor_await_tool.ainvoke({"run_id": "r1", "dataset_id": "ds-1"})))

        assert result["status"] == "SUCCEEDED"
        assert result["resultCount"] == 0
        assert result["results"] == []

    @patch("deerflow.community.apify.tools.get_stream_writer")
    @patch("deerflow.community.apify.tools.asyncio.to_thread", new_callable=AsyncMock)
    @patch("deerflow.community.apify.tools.ApifyClient")
    @patch("deerflow.community.apify.tools.get_app_config")
    def test_blocking_calls_use_asyncio_to_thread(self, mock_cfg, mock_apify_cls, mock_to_thread, mock_writer):
        """Blocking SDK calls (run.get and dataset.iterate_items) must be offloaded to a thread
        via asyncio.to_thread so the event loop is not blocked during polling."""
        mock_cfg.return_value.get_tool_config.return_value = _make_tool_config()
        mock_writer.return_value = self._make_mock_writer()

        # First to_thread call returns the run status; second returns the dataset items list
        mock_to_thread.side_effect = [
            {"status": "SUCCEEDED", "defaultDatasetId": "ds-1"},
            [{"item": 1}],
        ]

        from deerflow.community.apify.tools import apify_actor_await_tool

        result = json.loads(self._run(apify_actor_await_tool.ainvoke({"run_id": "r1", "dataset_id": "ds-1"})))

        assert result["status"] == "SUCCEEDED"
        # Both blocking SDK calls must go through to_thread, not be called directly
        assert mock_to_thread.call_count == 2
