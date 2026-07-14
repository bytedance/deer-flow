"""Unit tests for the Firecrawl community tools."""

import json
from unittest.mock import MagicMock, patch


class TestWebSearchTool:
    @patch("deerflow.community.firecrawl.tools.Firecrawl")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    def test_search_uses_web_search_config(self, mock_get_app_config, mock_firecrawl_cls):
        search_config = MagicMock()
        search_config.model_extra = {"api_key": "firecrawl-search-key", "max_results": 7}
        mock_get_app_config.return_value.get_tool_config.return_value = search_config

        mock_result = MagicMock()
        mock_result.web = [
            MagicMock(title="Result", url="https://example.com", description="Snippet"),
        ]
        mock_firecrawl_cls.return_value.search.return_value = mock_result

        from deerflow.community.firecrawl.tools import web_search_tool

        result = web_search_tool.invoke({"query": "test query"})

        assert json.loads(result) == [
            {
                "title": "Result",
                "url": "https://example.com",
                "snippet": "Snippet",
            }
        ]
        mock_get_app_config.return_value.get_tool_config.assert_called_with("web_search")
        mock_firecrawl_cls.assert_called_once_with(api_key="firecrawl-search-key")
        mock_firecrawl_cls.return_value.search.assert_called_once_with("test query", limit=7)


class TestWebFetchTool:
    @patch("deerflow.community.firecrawl.tools.Firecrawl")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    def test_fetch_uses_web_fetch_config(self, mock_get_app_config, mock_firecrawl_cls):
        fetch_config = MagicMock()
        fetch_config.model_extra = {
            "api_key": "firecrawl-fetch-key",
            "max_chars": 50,
            "formats": ["markdown", "html"],
        }

        def get_tool_config(name):
            if name == "web_fetch":
                return fetch_config
            return None

        mock_get_app_config.return_value.get_tool_config.side_effect = get_tool_config

        long_content = "This is a much longer markdown content that exceeds fifty characters."
        mock_scrape_result = MagicMock()
        mock_scrape_result.markdown = long_content
        mock_scrape_result.metadata = MagicMock(title="Fetched Page")
        mock_firecrawl_cls.return_value.scrape.return_value = mock_scrape_result

        from deerflow.community.firecrawl.tools import web_fetch_tool

        result = web_fetch_tool.invoke({"url": "https://example.com"})

        # Content should be truncated to max_chars (50)
        expected = "# Fetched Page\n\n" + long_content[:50]
        assert result == expected
        assert len(result) == len("# Fetched Page\n\n") + 50
        mock_get_app_config.return_value.get_tool_config.assert_any_call("web_fetch")
        mock_firecrawl_cls.assert_called_once_with(api_key="firecrawl-fetch-key")
        mock_firecrawl_cls.return_value.scrape.assert_called_once_with(
            "https://example.com",
            formats=["markdown", "html"],
        )


class TestWebMapTool:
    @patch("deerflow.community.firecrawl.tools.Firecrawl")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    def test_map_success(self, mock_get_app_config, mock_firecrawl_cls):
        """map returns a list of URLs — they should be serialized as JSON."""
        config = MagicMock()
        config.model_extra = {"api_key": "map-key"}
        mock_get_app_config.return_value.get_tool_config.return_value = config

        mock_result = MagicMock()
        mock_result.links = [
            "https://example.com",
            "https://example.com/about",
            "https://example.com/contact",
        ]
        mock_firecrawl_cls.return_value.map.return_value = mock_result

        from deerflow.community.firecrawl.tools import web_map_tool

        result = web_map_tool.invoke({"url": "https://example.com"})

        parsed = json.loads(result)
        assert parsed["urls"] == [
            "https://example.com",
            "https://example.com/about",
            "https://example.com/contact",
        ]
        assert parsed["total_count"] == 3
        mock_firecrawl_cls.return_value.map.assert_called_once_with(
            "https://example.com",
            limit=100,
            include_subdomains=True,
            sitemap=None,
        )

    @patch("deerflow.community.firecrawl.tools.Firecrawl")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    def test_map_respects_config(self, mock_get_app_config, mock_firecrawl_cls):
        """Config values for limit, ignore_sitemap, include_subdomains pass through to map."""
        config = MagicMock()
        config.model_extra = {
            "api_key": "cfg-key",
            "limit": 42,
            "ignore_sitemap": True,
            "include_subdomains": False,
        }
        mock_get_app_config.return_value.get_tool_config.return_value = config

        mock_result = MagicMock()
        mock_result.links = ["https://example.com/page"]
        mock_firecrawl_cls.return_value.map.return_value = mock_result

        from deerflow.community.firecrawl.tools import web_map_tool

        web_map_tool.invoke({"url": "https://example.com"})

        mock_get_app_config.return_value.get_tool_config.assert_called_with("web_map")
        mock_firecrawl_cls.return_value.map.assert_called_once_with(
            "https://example.com",
            limit=42,
            include_subdomains=False,
            sitemap="skip",
        )

    @patch("deerflow.community.firecrawl.tools.Firecrawl")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    def test_map_empty_site(self, mock_get_app_config, mock_firecrawl_cls):
        """Empty site — no URLs found — returns empty list with count 0."""
        config = MagicMock()
        config.model_extra = {"api_key": "map-key"}
        mock_get_app_config.return_value.get_tool_config.return_value = config

        mock_result = MagicMock()
        mock_result.links = []
        mock_firecrawl_cls.return_value.map.return_value = mock_result

        from deerflow.community.firecrawl.tools import web_map_tool

        result = web_map_tool.invoke({"url": "https://empty.example.com"})

        parsed = json.loads(result)
        assert parsed["urls"] == []
        assert parsed["total_count"] == 0


class TestWebCrawlTool:
    @patch("deerflow.community.firecrawl.tools.Firecrawl")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    def test_crawl_success(self, mock_get_app_config, mock_firecrawl_cls):
        """crawl returns a list of pages — they should be serialized as JSON with url + markdown."""
        config = MagicMock()
        config.model_extra = {"api_key": "crawl-key"}
        mock_get_app_config.return_value.get_tool_config.return_value = config

        mock_doc1 = MagicMock()
        mock_doc1.url = "https://example.com"
        mock_doc1.markdown = "Page 1 content"
        mock_doc2 = MagicMock()
        mock_doc2.url = "https://example.com/page2"
        mock_doc2.markdown = "Page 2 content"
        mock_result = MagicMock()
        mock_result.data = [mock_doc1, mock_doc2]
        mock_firecrawl_cls.return_value.crawl.return_value = mock_result

        from deerflow.community.firecrawl.tools import web_crawl_tool

        result = web_crawl_tool.invoke({"url": "https://example.com"})

        parsed = json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["url"] == "https://example.com"
        assert parsed[0]["markdown"] == "Page 1 content"
        assert parsed[1]["url"] == "https://example.com/page2"
        assert parsed[1]["markdown"] == "Page 2 content"

    @patch("deerflow.community.firecrawl.tools.ScrapeOptions")
    @patch("deerflow.community.firecrawl.tools.Firecrawl")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    def test_crawl_respects_config(self, mock_get_app_config, mock_firecrawl_cls, mock_scrape_options):
        """Config values for max_depth, limit, allow_subdomains, scrape_formats pass through to crawl."""
        config = MagicMock()
        config.model_extra = {
            "api_key": "cfg-key",
            "max_depth": 3,
            "limit": 20,
            "allow_subdomains": False,
            "scrape_formats": ["html"],
        }
        mock_get_app_config.return_value.get_tool_config.return_value = config

        mock_result = MagicMock()
        mock_result.data = []
        mock_firecrawl_cls.return_value.crawl.return_value = mock_result
        mock_scrape_options.return_value = "scrape_opts_mock"

        from deerflow.community.firecrawl.tools import web_crawl_tool

        web_crawl_tool.invoke({"url": "https://example.com"})

        mock_get_app_config.return_value.get_tool_config.assert_called_with("web_crawl")
        mock_scrape_options.assert_called_once_with(formats=["html"])
        mock_firecrawl_cls.return_value.crawl.assert_called_once_with(
            "https://example.com",
            max_discovery_depth=3,
            limit=20,
            allow_subdomains=False,
            scrape_options="scrape_opts_mock",
        )

    @patch("deerflow.community.firecrawl.tools.Firecrawl")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    def test_crawl_error(self, mock_get_app_config, mock_firecrawl_cls):
        """Exceptions from crawl are caught and returned as 'Error: ...' string."""
        config = MagicMock()
        config.model_extra = {"api_key": "crawl-key"}
        mock_get_app_config.return_value.get_tool_config.return_value = config

        mock_firecrawl_cls.return_value.crawl.side_effect = RuntimeError("Crawl failed")

        from deerflow.community.firecrawl.tools import web_crawl_tool

        result = web_crawl_tool.invoke({"url": "https://example.com"})

        assert result == "Error: Crawl failed"


class TestWebInteractTool:
    @patch("deerflow.community.firecrawl.tools.Firecrawl")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    def test_interact_success(self, mock_get_app_config, mock_firecrawl_cls):
        """scrape() with browser actions returns markdown content — it should be passed through as-is."""
        config = MagicMock()
        config.model_extra = {"api_key": "interact-key"}
        mock_get_app_config.return_value.get_tool_config.return_value = config

        mock_result = MagicMock()
        mock_result.markdown = "# Final Page\n\nContent after interaction."
        mock_firecrawl_cls.return_value.scrape.return_value = mock_result

        from deerflow.community.firecrawl.tools import web_interact_tool

        actions_json = json.dumps(
            [
                {"type": "click", "selector": "#login-btn"},
                {"type": "wait", "milliseconds": 1000},
            ]
        )
        result = web_interact_tool.invoke(
            {
                "url": "https://example.com",
                "actions": actions_json,
            }
        )

        assert result == "# Final Page\n\nContent after interaction."
        mock_get_app_config.return_value.get_tool_config.assert_called_with("web_interact")
        mock_firecrawl_cls.return_value.scrape.assert_called_once()
        call_args, call_kwargs = mock_firecrawl_cls.return_value.scrape.call_args
        assert call_args[0] == "https://example.com"
        assert call_kwargs["formats"] == ["markdown"]
        assert call_kwargs["timeout"] == 30000
        assert call_kwargs["wait_for"] == 2000
        # Verify actions were parsed into dicts
        assert len(call_kwargs["actions"]) == 2
        assert call_kwargs["actions"][0] == {"type": "click", "selector": "#login-btn"}
        assert call_kwargs["actions"][1] == {"type": "wait", "milliseconds": 1000}

    @patch("deerflow.community.firecrawl.tools.Firecrawl")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    def test_interact_actions_pass_through(self, mock_get_app_config, mock_firecrawl_cls):
        """The actions JSON should be parsed into action dicts and passed to scrape()."""
        config = MagicMock()
        config.model_extra = {"api_key": "interact-key"}
        mock_get_app_config.return_value.get_tool_config.return_value = config

        mock_result = MagicMock()
        mock_result.markdown = "Done."
        mock_firecrawl_cls.return_value.scrape.return_value = mock_result

        from deerflow.community.firecrawl.tools import web_interact_tool

        actions_json = json.dumps(
            [
                {"type": "write", "selector": "#search", "text": "hello"},
                {"type": "press", "key": "Enter"},
            ]
        )
        web_interact_tool.invoke(
            {
                "url": "https://example.com",
                "actions": actions_json,
            }
        )

        call_kwargs = mock_firecrawl_cls.return_value.scrape.call_args.kwargs
        assert call_kwargs["actions"] == [
            {"type": "write", "selector": "#search", "text": "hello"},
            {"type": "press", "key": "Enter"},
        ]

    @patch("deerflow.community.firecrawl.tools.Firecrawl")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    def test_interact_error(self, mock_get_app_config, mock_firecrawl_cls):
        """Exceptions from scrape() are caught and returned as 'Error: ...' string."""
        config = MagicMock()
        config.model_extra = {"api_key": "interact-key"}
        mock_get_app_config.return_value.get_tool_config.return_value = config

        mock_firecrawl_cls.return_value.scrape.side_effect = RuntimeError("Browser interaction timed out")

        from deerflow.community.firecrawl.tools import web_interact_tool

        actions_json = json.dumps([{"type": "click", "selector": "#btn"}])
        result = web_interact_tool.invoke(
            {
                "url": "https://example.com",
                "actions": actions_json,
            }
        )

        assert result == "Error: Browser interaction timed out"


class TestStructuredExtractTool:
    @patch("deerflow.community.firecrawl.tools.Firecrawl")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    def test_extract_with_schema(self, mock_get_app_config, mock_firecrawl_cls):
        """extract() with a schema returns the structured data as JSON."""
        config = MagicMock()
        config.model_extra = {"api_key": "extract-key"}
        mock_get_app_config.return_value.get_tool_config.return_value = config

        extracted_data = {
            "products": [
                {"name": "Widget", "price": 9.99, "rating": 4.5},
                {"name": "Gadget", "price": 19.99, "rating": 4.2},
            ]
        }
        mock_result = MagicMock()
        mock_result.data = extracted_data
        mock_firecrawl_cls.return_value.extract.return_value = mock_result

        from deerflow.community.firecrawl.tools import structured_extract_tool

        schema = {
            "type": "object",
            "properties": {
                "products": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "price": {"type": "number"},
                            "rating": {"type": "number"},
                        },
                    },
                }
            },
        }
        result = structured_extract_tool.invoke(
            {
                "urls": ["https://shop.example.com"],
                "prompt": "Extract product name, price, and rating",
                "schema": schema,
            }
        )

        parsed = json.loads(result)
        assert parsed == extracted_data
        mock_get_app_config.return_value.get_tool_config.assert_called_with("structured_extract")
        mock_firecrawl_cls.return_value.extract.assert_called_once_with(
            urls=["https://shop.example.com"],
            prompt="Extract product name, price, and rating",
            schema=schema,
        )

    @patch("deerflow.community.firecrawl.tools.Firecrawl")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    def test_extract_no_schema(self, mock_get_app_config, mock_firecrawl_cls):
        """extract() without a schema (prompt-only) infers structure from the prompt."""
        config = MagicMock()
        config.model_extra = {"api_key": "extract-key"}
        mock_get_app_config.return_value.get_tool_config.return_value = config

        extracted_data = {"title": "Example", "summary": "A test summary"}
        mock_result = MagicMock()
        mock_result.data = extracted_data
        mock_firecrawl_cls.return_value.extract.return_value = mock_result

        from deerflow.community.firecrawl.tools import structured_extract_tool

        result = structured_extract_tool.invoke(
            {
                "urls": ["https://example.com"],
                "prompt": "Extract the title and summary",
            }
        )

        parsed = json.loads(result)
        assert parsed == extracted_data
        # Schema should NOT be passed when omitted
        mock_firecrawl_cls.return_value.extract.assert_called_once_with(
            urls=["https://example.com"],
            prompt="Extract the title and summary",
        )

    @patch("deerflow.community.firecrawl.tools.Firecrawl")
    @patch("deerflow.community.firecrawl.tools.get_app_config")
    def test_extract_error(self, mock_get_app_config, mock_firecrawl_cls):
        """Exceptions from extract() are caught and returned as 'Error: ...' string."""
        config = MagicMock()
        config.model_extra = {"api_key": "extract-key"}
        mock_get_app_config.return_value.get_tool_config.return_value = config

        mock_firecrawl_cls.return_value.extract.side_effect = ValueError("Invalid URL format")

        from deerflow.community.firecrawl.tools import structured_extract_tool

        result = structured_extract_tool.invoke(
            {
                "urls": ["not-a-url"],
                "prompt": "Extract data",
            }
        )

        assert result == "Error: Invalid URL format"


class TestRealFirecrawlAppContract:
    """Verify that the methods called by tools.py actually exist on the real
    firecrawl-py FirecrawlApp with the parameter names we expect.

    This guards against SDK upgrades changing signatures without our tools
    being updated.
    """

    @staticmethod
    def test_client_methods_exist():
        """All methods used by tools.py must be present on a Firecrawl instance."""
        from firecrawl import Firecrawl

        client = Firecrawl(api_key="test-contract-key")

        expected_methods = ["map", "crawl", "scrape", "search", "extract"]
        for name in expected_methods:
            method = getattr(client, name, None)
            assert method is not None, f"Firecrawl instance is missing '{name}' method — tools.py will fail at runtime"

    @staticmethod
    def test_map_signature():
        """map() must accept url, limit, include_subdomains, sitemap."""
        import inspect

        from firecrawl import Firecrawl

        client = Firecrawl(api_key="test-contract-key")
        sig = inspect.signature(client.map)
        params = sig.parameters

        assert "url" in params, f"map() missing 'url' param; sig={sig}"
        assert "limit" in params, f"map() missing 'limit' param; sig={sig}"
        assert "include_subdomains" in params, f"map() missing 'include_subdomains' param; sig={sig}"
        assert "sitemap" in params, f"map() missing 'sitemap' param; sig={sig}"

    @staticmethod
    def test_crawl_signature():
        """crawl() must accept url, max_discovery_depth, limit, allow_subdomains, scrape_options."""
        import inspect

        from firecrawl import Firecrawl

        client = Firecrawl(api_key="test-contract-key")
        sig = inspect.signature(client.crawl)
        params = sig.parameters

        assert "url" in params, f"crawl() missing 'url' param; sig={sig}"
        assert "max_discovery_depth" in params, f"crawl() missing 'max_discovery_depth' param; sig={sig}"
        assert "limit" in params, f"crawl() missing 'limit' param; sig={sig}"
        assert "allow_subdomains" in params, f"crawl() missing 'allow_subdomains' param; sig={sig}"
        assert "scrape_options" in params, f"crawl() missing 'scrape_options' param; sig={sig}"

    @staticmethod
    def test_scrape_signature():
        """scrape() must accept url, formats, actions, timeout, wait_for."""
        import inspect

        from firecrawl import Firecrawl

        client = Firecrawl(api_key="test-contract-key")
        sig = inspect.signature(client.scrape)
        params = sig.parameters

        assert "url" in params, f"scrape() missing 'url' param; sig={sig}"
        assert "formats" in params, f"scrape() missing 'formats' param; sig={sig}"
        assert "actions" in params, f"scrape() missing 'actions' param; sig={sig}"
        assert "timeout" in params, f"scrape() missing 'timeout' param; sig={sig}"
        assert "wait_for" in params, f"scrape() missing 'wait_for' param; sig={sig}"

    @staticmethod
    def test_search_signature():
        """search() must accept query and limit."""
        import inspect

        from firecrawl import Firecrawl

        client = Firecrawl(api_key="test-contract-key")
        sig = inspect.signature(client.search)
        params = sig.parameters

        assert "query" in params, f"search() missing 'query' param; sig={sig}"
        assert "limit" in params, f"search() missing 'limit' param; sig={sig}"

    @staticmethod
    def test_extract_signature():
        """extract() must accept urls, prompt, and schema."""
        import inspect

        from firecrawl import Firecrawl

        client = Firecrawl(api_key="test-contract-key")
        sig = inspect.signature(client.extract)
        params = sig.parameters

        assert "urls" in params, f"extract() missing 'urls' param; sig={sig}"
        assert "prompt" in params, f"extract() missing 'prompt' param; sig={sig}"
        assert "schema" in params, f"extract() missing 'schema' param; sig={sig}"
