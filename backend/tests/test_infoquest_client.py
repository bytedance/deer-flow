"""Tests for InfoQuest client and tools."""

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from deerflow.community.infoquest import tools
from deerflow.community.infoquest.infoquest_client import InfoQuestClient


def _mock_async_client(response: httpx.Response) -> MagicMock:
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


class TestInfoQuestClient:
    def test_infoquest_client_initialization(self):
        """Test InfoQuestClient initialization with different parameters."""
        # Test with default parameters
        client = InfoQuestClient()
        assert client.fetch_time == -1
        assert client.fetch_timeout == -1
        assert client.fetch_navigation_timeout == -1
        assert client.search_time_range == -1

        # Test with custom parameters
        client = InfoQuestClient(fetch_time=10, fetch_timeout=30, fetch_navigation_timeout=60, search_time_range=24)
        assert client.fetch_time == 10
        assert client.fetch_timeout == 30
        assert client.fetch_navigation_timeout == 60
        assert client.search_time_range == 24

    @patch("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_fetch_success(self, mock_async_client_cls):
        """Test successful fetch operation."""
        mock_response = httpx.Response(200, text=json.dumps({"reader_result": "<html><body>Test content</body></html>"}), request=httpx.Request("POST", "https://reader.infoquest.bytepluses.com"))
        mock_async_client_cls.return_value = _mock_async_client(mock_response)

        client = InfoQuestClient()
        result = await client.fetch("https://example.com")

        assert result == "<html><body>Test content</body></html>"
        mock_async_client_cls.return_value.post.assert_called_once()
        args, kwargs = mock_async_client_cls.return_value.post.call_args
        assert args[0] == "https://reader.infoquest.bytepluses.com"
        assert kwargs["json"]["url"] == "https://example.com"
        assert kwargs["json"]["format"] == "HTML"

    @patch("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_fetch_non_200_status(self, mock_async_client_cls):
        """Test fetch operation with non-200 status code."""
        mock_response = httpx.Response(404, text="Not Found", request=httpx.Request("POST", "https://reader.infoquest.bytepluses.com"))
        mock_async_client_cls.return_value = _mock_async_client(mock_response)

        client = InfoQuestClient()
        result = await client.fetch("https://example.com")

        assert result == "Error: fetch API returned status 404: Not Found"

    @patch("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_fetch_empty_response(self, mock_async_client_cls):
        """Test fetch operation with empty response."""
        mock_response = httpx.Response(200, text="", request=httpx.Request("POST", "https://reader.infoquest.bytepluses.com"))
        mock_async_client_cls.return_value = _mock_async_client(mock_response)

        client = InfoQuestClient()
        result = await client.fetch("https://example.com")

        assert result == "Error: no result found"

    @patch("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_web_search_raw_results_success(self, mock_async_client_cls):
        """Test successful web_search_raw_results operation."""
        mock_response = httpx.Response(
            200,
            json={"search_result": {"results": [{"content": {"results": {"organic": [{"title": "Test Result", "desc": "Test description", "url": "https://example.com"}]}}}], "images_results": []}},
            request=httpx.Request("POST", "https://search.infoquest.bytepluses.com"),
        )
        mock_async_client_cls.return_value = _mock_async_client(mock_response)

        client = InfoQuestClient()
        result = await client.web_search_raw_results("test query", "")

        assert "search_result" in result
        mock_async_client_cls.return_value.post.assert_called_once()
        args, kwargs = mock_async_client_cls.return_value.post.call_args
        assert args[0] == "https://search.infoquest.bytepluses.com"
        assert kwargs["json"]["query"] == "test query"

    @patch("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_web_search_success(self, mock_async_client_cls):
        """Test successful web_search operation."""
        mock_response = httpx.Response(
            200,
            json={"search_result": {"results": [{"content": {"results": {"organic": [{"title": "Test Result", "desc": "Test description", "url": "https://example.com"}]}}}], "images_results": []}},
            request=httpx.Request("POST", "https://search.infoquest.bytepluses.com"),
        )
        mock_async_client_cls.return_value = _mock_async_client(mock_response)

        client = InfoQuestClient()
        result = await client.web_search("test query")

        # Check if result is a valid JSON string with expected content
        result_data = json.loads(result)
        assert len(result_data) == 1
        assert result_data[0]["title"] == "Test Result"
        assert result_data[0]["url"] == "https://example.com"

    def test_clean_results(self):
        """Test clean_results method with sample raw results."""
        raw_results = [
            {
                "content": {
                    "results": {
                        "organic": [{"title": "Test Page", "desc": "Page description", "url": "https://example.com/page1"}],
                        "top_stories": {"items": [{"title": "Test News", "source": "Test Source", "time_frame": "2 hours ago", "url": "https://example.com/news1"}]},
                    }
                }
            }
        ]

        cleaned = InfoQuestClient.clean_results(raw_results)

        assert len(cleaned) == 2
        assert cleaned[0]["type"] == "page"
        assert cleaned[0]["title"] == "Test Page"
        assert cleaned[1]["type"] == "news"
        assert cleaned[1]["title"] == "Test News"

    @patch("deerflow.community.infoquest.tools._get_infoquest_client")
    @pytest.mark.anyio
    async def test_web_search_tool(self, mock_get_client):
        """Test web_search_tool function."""
        mock_client = MagicMock()
        mock_client.web_search = AsyncMock(return_value=json.dumps([]))
        mock_get_client.return_value = mock_client

        result = await tools.web_search_tool.ainvoke("test query")

        assert result == json.dumps([])
        mock_get_client.assert_called_once()
        mock_client.web_search.assert_awaited_once_with("test query")

    @patch("deerflow.community.infoquest.tools._get_infoquest_client")
    @pytest.mark.anyio
    async def test_web_fetch_tool(self, mock_get_client):
        """Test web_fetch_tool function."""
        mock_client = MagicMock()
        mock_client.fetch = AsyncMock(return_value="<html><body>Test content</body></html>")
        mock_get_client.return_value = mock_client

        result = await tools.web_fetch_tool.ainvoke("https://example.com")

        assert result == "# Untitled\n\nTest content"
        mock_get_client.assert_called_once()
        mock_client.fetch.assert_awaited_once_with("https://example.com")

    @patch("deerflow.community.infoquest.tools.get_app_config")
    def test_get_infoquest_client(self, mock_get_app_config):
        """Test _get_infoquest_client function with config."""
        mock_config = MagicMock()
        # Add image_search config to the side_effect
        mock_config.get_tool_config.side_effect = [
            MagicMock(model_extra={"search_time_range": 24}),  # web_search config
            MagicMock(model_extra={"fetch_time": 10, "timeout": 30, "navigation_timeout": 60}),  # web_fetch config
            MagicMock(model_extra={"image_search_time_range": 7, "image_size": "l"}),  # image_search config
        ]
        mock_get_app_config.return_value = mock_config

        client = tools._get_infoquest_client()

        assert client.search_time_range == 24
        assert client.fetch_time == 10
        assert client.fetch_timeout == 30
        assert client.fetch_navigation_timeout == 60
        assert client.image_search_time_range == 7
        assert client.image_size == "l"

    @patch("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_web_search_api_error(self, mock_async_client_cls):
        """Test web_search operation with API error."""
        mock_async_client_cls.return_value = _mock_async_client(httpx.Response(200, text="ok", request=httpx.Request("POST", "https://search.infoquest.bytepluses.com")))
        mock_async_client_cls.return_value.post.side_effect = Exception("Connection error")

        client = InfoQuestClient()
        result = await client.web_search("test query")

        assert "Error" in result

    def test_clean_results_with_image_search(self):
        """Test clean_results_with_image_search method with sample raw results."""
        raw_results = [{"content": {"results": {"images_results": [{"original": "https://example.com/image1.jpg", "title": "Test Image 1", "url": "https://example.com/page1"}]}}}]
        cleaned = InfoQuestClient.clean_results_with_image_search(raw_results)

        assert len(cleaned) == 1
        assert cleaned[0]["image_url"] == "https://example.com/image1.jpg"
        assert cleaned[0]["title"] == "Test Image 1"

    def test_clean_results_with_image_search_empty(self):
        """Test clean_results_with_image_search method with empty results."""
        raw_results = [{"content": {"results": {"images_results": []}}}]
        cleaned = InfoQuestClient.clean_results_with_image_search(raw_results)

        assert len(cleaned) == 0

    def test_clean_results_with_image_search_no_images(self):
        """Test clean_results_with_image_search method with no images_results field."""
        raw_results = [{"content": {"results": {"organic": [{"title": "Test Page"}]}}}]
        cleaned = InfoQuestClient.clean_results_with_image_search(raw_results)

        assert len(cleaned) == 0


class TestImageSearch:
    @patch("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_image_search_raw_results_success(self, mock_async_client_cls):
        """Test successful image_search_raw_results operation."""
        mock_response = httpx.Response(
            200,
            json={"search_result": {"results": [{"content": {"results": {"images_results": [{"original": "https://example.com/image1.jpg", "title": "Test Image", "url": "https://example.com/page1"}]}}}]}},
            request=httpx.Request("POST", "https://search.infoquest.bytepluses.com"),
        )
        mock_async_client_cls.return_value = _mock_async_client(mock_response)

        client = InfoQuestClient()
        result = await client.image_search_raw_results("test query")

        assert "search_result" in result
        mock_async_client_cls.return_value.post.assert_called_once()
        args, kwargs = mock_async_client_cls.return_value.post.call_args
        assert args[0] == "https://search.infoquest.bytepluses.com"
        assert kwargs["json"]["query"] == "test query"

    @patch("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_image_search_raw_results_with_parameters(self, mock_async_client_cls):
        """Test image_search_raw_results with all parameters."""
        mock_response = httpx.Response(
            200,
            json={"search_result": {"results": [{"content": {"results": {"images_results": [{"original": "https://example.com/image1.jpg"}]}}}]}},
            request=httpx.Request("POST", "https://search.infoquest.bytepluses.com"),
        )
        mock_async_client_cls.return_value = _mock_async_client(mock_response)

        client = InfoQuestClient(image_search_time_range=30, image_size="l")
        await client.image_search_raw_results(query="cat", site="unsplash.com", output_format="JSON")

        mock_async_client_cls.return_value.post.assert_called_once()
        args, kwargs = mock_async_client_cls.return_value.post.call_args
        assert kwargs["json"]["query"] == "cat"
        assert kwargs["json"]["time_range"] == 30
        assert kwargs["json"]["site"] == "unsplash.com"
        assert kwargs["json"]["image_size"] == "l"
        assert kwargs["json"]["format"] == "JSON"

    @patch("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_image_search_raw_results_invalid_time_range(self, mock_async_client_cls):
        """Test image_search_raw_results with invalid time_range parameter."""
        mock_response = httpx.Response(
            200,
            json={"search_result": {"results": [{"content": {"results": {"images_results": []}}}]}},
            request=httpx.Request("POST", "https://search.infoquest.bytepluses.com"),
        )
        mock_async_client_cls.return_value = _mock_async_client(mock_response)

        # Create client with invalid time_range (should be ignored)
        client = InfoQuestClient(image_search_time_range=400, image_size="x")
        await client.image_search_raw_results(
            query="test",
            site="",
        )

        mock_async_client_cls.return_value.post.assert_called_once()
        args, kwargs = mock_async_client_cls.return_value.post.call_args
        assert kwargs["json"]["query"] == "test"
        assert "time_range" not in kwargs["json"]
        assert "image_size" not in kwargs["json"]

    @patch("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_image_search_success(self, mock_async_client_cls):
        """Test successful image_search operation."""
        mock_response = httpx.Response(
            200,
            json={"search_result": {"results": [{"content": {"results": {"images_results": [{"original": "https://example.com/image1.jpg", "title": "Test Image", "url": "https://example.com/page1"}]}}}]}},
            request=httpx.Request("POST", "https://search.infoquest.bytepluses.com"),
        )
        mock_async_client_cls.return_value = _mock_async_client(mock_response)

        client = InfoQuestClient()
        result = await client.image_search("cat")

        # Check if result is a valid JSON string with expected content
        result_data = json.loads(result)

        assert len(result_data) == 1

        assert result_data[0]["image_url"] == "https://example.com/image1.jpg"

        assert result_data[0]["title"] == "Test Image"

    @patch("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_image_search_with_all_parameters(self, mock_async_client_cls):
        """Test image_search with all optional parameters."""
        mock_response = httpx.Response(
            200,
            json={"search_result": {"results": [{"content": {"results": {"images_results": [{"original": "https://example.com/image1.jpg"}]}}}]}},
            request=httpx.Request("POST", "https://search.infoquest.bytepluses.com"),
        )
        mock_async_client_cls.return_value = _mock_async_client(mock_response)

        # Create client with image search parameters
        client = InfoQuestClient(image_search_time_range=7, image_size="m")
        await client.image_search(query="dog", site="flickr.com", output_format="JSON")

        mock_async_client_cls.return_value.post.assert_called_once()
        args, kwargs = mock_async_client_cls.return_value.post.call_args
        assert kwargs["json"]["query"] == "dog"
        assert kwargs["json"]["time_range"] == 7
        assert kwargs["json"]["site"] == "flickr.com"
        assert kwargs["json"]["image_size"] == "m"

    @patch("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_image_search_api_error(self, mock_async_client_cls):
        """Test image_search operation with API error."""
        mock_async_client_cls.return_value = _mock_async_client(httpx.Response(200, text="ok", request=httpx.Request("POST", "https://search.infoquest.bytepluses.com")))
        mock_async_client_cls.return_value.post.side_effect = Exception("Connection error")

        client = InfoQuestClient()
        result = await client.image_search("test query")

        assert "Error" in result

    @patch("deerflow.community.infoquest.tools._get_infoquest_client")
    @pytest.mark.anyio
    async def test_image_search_tool(self, mock_get_client):
        """Test image_search_tool function."""
        mock_client = MagicMock()
        mock_client.image_search = AsyncMock(return_value=json.dumps([{"image_url": "https://example.com/image1.jpg"}]))
        mock_get_client.return_value = mock_client

        result = await tools.image_search_tool.ainvoke({"query": "test query"})

        # Check if result is a valid JSON string
        result_data = json.loads(result)
        assert len(result_data) == 1
        assert result_data[0]["image_url"] == "https://example.com/image1.jpg"
        mock_get_client.assert_called_once()
        mock_client.image_search.assert_awaited_once_with("test query")

    @patch("deerflow.community.infoquest.tools._get_infoquest_client")
    @pytest.mark.anyio
    async def test_image_search_tool_with_parameters(self, mock_get_client):
        """Test image_search_tool function with all parameters (extra parameters will be ignored)."""
        mock_client = MagicMock()
        mock_client.image_search = AsyncMock(return_value=json.dumps([{"image_url": "https://example.com/image1.jpg"}]))
        mock_get_client.return_value = mock_client

        # Pass all parameters as a dictionary (extra parameters will be ignored)
        await tools.image_search_tool.ainvoke({"query": "sunset", "time_range": 30, "site": "unsplash.com", "image_size": "l"})

        mock_get_client.assert_called_once()
        # image_search_tool only passes query to client.image_search
        # site parameter is empty string by default
        mock_client.image_search.assert_awaited_once_with("sunset")


class TestRedirectParity:
    """The sync `requests.post` client followed redirects by default; the
    httpx migration must keep that behavior or a 3xx answer from the
    reader/search endpoints surfaces as an error instead of the content.

    Review note on #5782: httpx.AsyncClient defaults to
    follow_redirects=False, unlike requests.
    """

    @patch("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_fetch_client_follows_redirects(self, mock_async_client_cls):
        mock_response = httpx.Response(200, text=json.dumps({"reader_result": "<html>ok</html>"}), request=httpx.Request("POST", "https://reader.infoquest.bytepluses.com"))
        mock_async_client_cls.return_value = _mock_async_client(mock_response)

        await InfoQuestClient().fetch("https://example.com")

        mock_async_client_cls.assert_called_once_with(follow_redirects=True)

    @patch("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_web_search_client_follows_redirects(self, mock_async_client_cls):
        payload = {"type": "search", "results": []}
        mock_response = httpx.Response(200, text=json.dumps(payload), request=httpx.Request("POST", "https://search.infoquest.bytepluses.com"))
        mock_async_client_cls.return_value = _mock_async_client(mock_response)

        await InfoQuestClient().web_search_raw_results("query", site="")

        mock_async_client_cls.assert_called_once_with(follow_redirects=True)

    @patch("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient")
    @pytest.mark.anyio
    async def test_image_search_client_follows_redirects(self, mock_async_client_cls):
        payload = {"type": "Images", "results": []}
        mock_response = httpx.Response(200, text=json.dumps(payload), request=httpx.Request("POST", "https://search.infoquest.bytepluses.com"))
        mock_async_client_cls.return_value = _mock_async_client(mock_response)

        await InfoQuestClient().image_search_raw_results("query")

        mock_async_client_cls.assert_called_once_with(follow_redirects=True)


class TestInfoQuestMalformedSearchPayloads:
    """A malformed 200 search payload is a format error, not an empty search.

    InfoQuest answers HTTP 200 with a ``search_result`` envelope as its only
    contract. An error document delivered with the same status used to either
    end the research loop as "the query matched nothing" or surface a raw
    Python error string, so the contraction rule the sibling bundled providers
    already follow applies here too.
    """

    @staticmethod
    def _client(payload):
        if payload is None:
            # `json=None` omits the body entirely; a literal `null` document is
            # what actually reaches the outer "is it an object" guard.
            response = httpx.Response(200, text="null", request=httpx.Request("POST", "https://search.infoquest.bytepluses.com"))
        else:
            response = httpx.Response(200, json=payload, request=httpx.Request("POST", "https://search.infoquest.bytepluses.com"))
        return _mock_async_client(response)

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "payload",
        [
            {"search_result": {"results": "maintenance window"}},
            {"search_result": {"results": {"organic": "x"}}},
            {"search_result": {"results": [1, 2]}},
            {"search_result": {"results": [{"content": "x"}]}},
            {"search_result": {"results": [{"content": {"results": {"organic": "x"}}}]}},
            {"search_result": {"results": [{"content": {"results": {"organic": {"a": 1}}}}]}},
            {"search_result": {"results": [{"content": {"results": {"top_stories": {"items": "x"}}}}]}},
        ],
        ids=[
            "results-is-a-string",
            "organic-is-a-string",
            "results-entries-not-objects",
            "content-is-not-an-object",
            "organic-container-is-not-a-list",
            "organic-container-is-a-populated-dict",
            "top-stories-items-is-not-a-list",
        ],
    )
    async def test_web_search_reports_a_format_error(self, payload, monkeypatch):
        """Each malformed container returns the provider's format error."""
        monkeypatch.setattr("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient", MagicMock(return_value=self._client(payload)))

        result = await InfoQuestClient().web_search("test query")

        assert result == "Error: InfoQuest returned an unexpected response format"

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "payload",
        [
            ["not-an-object"],
            "maintenance window",
            7,
            None,
            {"search_result": "not-an-object"},
            {"search_result": []},
            {"search_result": [1, 2]},
            {"search_result": None},
        ],
        ids=[
            "payload-is-a-list",
            "payload-is-a-string",
            "payload-is-an-int",
            "payload-is-null",
            "search-result-is-a-string",
            "search-result-is-a-list",
            "search-result-is-a-populated-list",
            "search-result-is-null",
        ],
    )
    async def test_web_search_rejects_non_object_envelopes(self, payload, monkeypatch):
        """A top-level payload or ``search_result`` that is not an object is malformed.

        The two outermost ``isinstance`` guards were the last uncovered branches:
        a top-level list/scalar used to reach ``"search_result" in raw_results``
        and a non-object ``search_result`` used to reach ``.get``, neither of
        which is the provider's format error.
        """
        monkeypatch.setattr("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient", MagicMock(return_value=self._client(payload)))

        result = await InfoQuestClient().web_search("test query")

        assert result == "Error: InfoQuest returned an unexpected response format"

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "payload",
        [
            ["not-an-object"],
            "maintenance window",
            None,
            {"search_result": "not-an-object"},
            {"search_result": []},
            {"search_result": None},
        ],
        ids=[
            "payload-is-a-list",
            "payload-is-a-string",
            "payload-is-null",
            "search-result-is-a-string",
            "search-result-is-a-list",
            "search-result-is-null",
        ],
    )
    async def test_image_search_rejects_non_object_envelopes(self, payload, monkeypatch):
        """The image vertical shares the outer-envelope guards."""
        monkeypatch.setattr("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient", MagicMock(return_value=self._client(payload)))

        result = await InfoQuestClient().image_search("test query")

        assert result == "Error: InfoQuest returned an unexpected response format"

    @pytest.mark.anyio
    async def test_web_search_logs_the_container_and_index_of_a_skipped_row(self, monkeypatch, caplog):
        """A dropped non-object row is reported with its container and position.

        ``_envelope_entries`` already warned this way; ``_rows`` shed the same
        kind of drift silently, so a payload like ``{"organic": [1, {"url": ...}]}``
        lost entries with no trace. The README documents logging the container
        name and entry position only, never the payload values.
        """
        payload = {
            "search_result": {
                "results": [
                    {
                        "content": {
                            "results": {
                                "organic": [
                                    1,
                                    {"title": "Kept", "desc": "d", "url": "https://example.com/1"},
                                ]
                            }
                        }
                    }
                ]
            }
        }
        monkeypatch.setattr("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient", MagicMock(return_value=self._client(payload)))

        with caplog.at_level(logging.WARNING, logger="deerflow.community.infoquest.infoquest_client"):
            result = await InfoQuestClient().web_search("test query")

        assert [row["title"] for row in json.loads(result)] == ["Kept"]
        warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
        assert any("organic[0]" in message for message in warnings), warnings
        assert not any("example.com" in message for message in warnings), warnings

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "payload",
        [
            {"search_result": {}},
            {"search_result": {"results": None}},
            {"search_result": {"results": []}},
            {"search_result": {"results": [{"content": {"results": {"organic": []}}}]}},
        ],
        ids=["search-result-is-empty", "results-is-null", "results-is-empty-list", "organic-is-empty"],
    )
    async def test_web_search_keeps_an_empty_search_empty(self, payload, monkeypatch):
        """A missing, null or empty container stays an empty search."""
        monkeypatch.setattr("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient", MagicMock(return_value=self._client(payload)))

        result = await InfoQuestClient().web_search("test query")

        assert json.loads(result) == []

    @pytest.mark.anyio
    async def test_web_search_keeps_the_valid_rows_of_a_mixed_payload(self, monkeypatch):
        """A payload with usable rows still answers with those rows."""
        payload = {
            "search_result": {
                "results": [
                    {"content": {"results": {"organic": [{"title": "Test Page", "desc": "d", "url": "https://example.com/1"}]}}},
                    "malformed",
                ]
            }
        }
        monkeypatch.setattr("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient", MagicMock(return_value=self._client(payload)))

        result = await InfoQuestClient().web_search("test query")

        rows = json.loads(result)
        assert [row["title"] for row in rows] == ["Test Page"]

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "payload",
        [
            {"search_result": {"results": "maintenance window"}},
            {"search_result": {"results": [{"content": {"results": {"images_results": "x"}}}]}},
            {"search_result": {"results": [{"content": {"results": {"images_results": [1, 2]}}}]}},
        ],
        ids=["results-is-a-string", "images-container-is-not-a-list", "images-entries-not-objects"],
    )
    async def test_image_search_reports_a_format_error(self, payload, monkeypatch):
        """The image vertical shares the containment rule."""
        monkeypatch.setattr("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient", MagicMock(return_value=self._client(payload)))

        result = await InfoQuestClient().image_search("test query")

        assert result == "Error: InfoQuest returned an unexpected response format"

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "payload",
        [
            {"search_result": {"results": []}},
            {"search_result": {"results": [{"content": {"results": {"images_results": []}}}]}},
        ],
        ids=["results-is-empty-list", "images-is-empty"],
    )
    async def test_image_search_keeps_an_empty_search_empty(self, payload, monkeypatch):
        """The image vertical keeps empty containers empty as well."""
        monkeypatch.setattr("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient", MagicMock(return_value=self._client(payload)))

        result = await InfoQuestClient().image_search("test query")

        assert json.loads(result) == []

    @pytest.mark.anyio
    async def test_web_search_keeps_other_failures_as_their_own_errors(self, monkeypatch):
        """Transport failures keep their existing error text."""
        client = MagicMock()
        client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient", MagicMock(return_value=client))

        result = await InfoQuestClient().web_search("test query")

        assert result.startswith("Error: ")
        assert "unexpected response format" not in result
