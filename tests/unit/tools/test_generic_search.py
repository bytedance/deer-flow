from unittest.mock import AsyncMock, Mock, patch

import pytest
from alibabacloud_iqs20241111 import models
from Tea.exceptions import TeaException

from src.tools.generic_search import GenericSearchInput, GenericSearchTool


class TestGenericSearchInput:
    def test_generic_search_input_default_values(self):
        """Test default values of GenericSearchInput"""
        input_data = GenericSearchInput(query="test query")
        assert input_data.query == "test query"
        assert input_data.time_range == "NoLimit"
        assert input_data.industry is None
        assert input_data.page == 1
        assert input_data.return_main_text is True
        assert input_data.return_markdown_text is True
        assert input_data.enable_rerank is True

    def test_generic_search_input_custom_values(self):
        """Test custom values of GenericSearchInput"""
        input_data = GenericSearchInput(
            query="custom query",
            time_range="OneWeek",
            industry="finance",
            page=2,
            return_main_text=False,
            return_markdown_text=False,
            enable_rerank=False,
        )
        assert input_data.query == "custom query"
        assert input_data.time_range == "OneWeek"
        assert input_data.industry == "finance"
        assert input_data.page == 2
        assert input_data.return_main_text is False
        assert input_data.return_markdown_text is False
        assert input_data.enable_rerank is False


class TestGenericSearchTool:
    @pytest.fixture
    def mock_client(self):
        """Create a mock Alibaba Cloud client"""
        return Mock()

    @pytest.fixture
    def search_tool(self, mock_client):
        """Create a GenericSearchTool instance"""
        with patch(
            "src.tools.generic_search.GenericSearchTool._create_client",
            return_value=mock_client,
        ):
            tool = GenericSearchTool(max_results=5)
            return tool

    @pytest.fixture
    def mock_search_response(self):
        """Create a mock search response"""
        mock_response = Mock()
        mock_body = Mock(spec=models.GenericSearchResult)

        # Create a mock search result item
        mock_item = Mock()
        mock_item.title = "Test Title"
        mock_item.link = "https://example.com"
        mock_item.snippet = "Test snippet"
        mock_item.main_text = "Test main text"
        mock_item.markdown_text = "# Test Markdown"
        mock_item.publish_time = "2024-01-01"
        mock_item.score = 0.95
        mock_item.card_type = "web"
        mock_item.page_map = {"hostname": "example.com", "siteLabel": "Example"}
        mock_item.images = []

        mock_body.page_items = [mock_item]
        mock_body.request_id = "test-request-id"

        # Create mock search information
        mock_search_info = Mock()
        mock_search_info.total = 100
        mock_search_info.search_time = 150
        mock_body.search_information = mock_search_info

        mock_response.body = mock_body
        return mock_response

    @pytest.fixture
    async def async_mock_search_response(self):
        """Create a mock async search response"""
        mock_response = AsyncMock()
        mock_body = AsyncMock(spec=models.GenericSearchResult)

        # Create a mock search result item
        mock_item = AsyncMock()
        mock_item.title = "Test Title"
        mock_item.link = "https://example.com"
        mock_item.snippet = "Test snippet"
        mock_item.main_text = "Test main text"
        mock_item.markdown_text = "# Test Markdown"
        mock_item.publish_time = "2024-01-01"
        mock_item.score = 0.95
        mock_item.card_type = "web"
        mock_item.page_map = {"hostname": "example.com", "siteLabel": "Example"}
        mock_item.images = []

        mock_body.page_items = [mock_item]
        mock_body.request_id = "test-request-id"

        # Create mock search information
        mock_search_info = Mock()
        mock_search_info.total = 100
        mock_search_info.search_time = 150
        mock_body.search_information = mock_search_info

        mock_response.body = mock_body
        return mock_response

    def test_init_default_values(self):
        """Test default initialization of GenericSearchTool"""
        with patch("src.tools.generic_search.GenericSearchTool._create_client"):
            tool = GenericSearchTool()
            assert tool.name == "generic_search"
            assert tool.max_results == 10
            assert tool.args_schema == GenericSearchInput

    def test_init_custom_values(self):
        """Test custom initialization of GenericSearchTool"""
        with patch("src.tools.generic_search.GenericSearchTool._create_client"):
            tool = GenericSearchTool(max_results=20)
            assert tool.max_results == 20

    @patch.dict(
        "os.environ",
        {
            "GENERIC_SEARCH_ACCESS_KEY": "test_key",
            "GENERIC_SEARCH_ACCESS_SECRET": "test_secret",
            "GENERIC_SEARCH_ENDPOINT": "test_endpoint",
        },
    )
    @patch("src.tools.generic_search.Client")
    def test_create_client_with_credentials(self, mock_client_class):
        """Test creating client with credentials"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        tool = GenericSearchTool()

        assert tool.client == mock_client
        mock_client_class.assert_called_once()

    @patch.dict("os.environ", {}, clear=True)
    @patch("src.tools.generic_search.logger")
    @patch("src.tools.generic_search.Client")
    def test_create_client_without_credentials(self, mock_client_class, mock_logger):
        """Test creating client without credentials"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        GenericSearchTool()

        mock_logger.warning.assert_called_once()
        assert (
            "Alibaba Cloud access credentials are not configured"
            in mock_logger.warning.call_args[0][0]
        )

    def test_validate_query_empty(self, search_tool):
        """Test empty query validation"""
        result = search_tool._validate_query("")
        assert result == "Error: Search keyword cannot be empty"

    def test_validate_query_too_long(self, search_tool):
        """Test too long query validation"""
        long_query = "a" * 101
        result = search_tool._validate_query(long_query)
        assert result == "Error: Search keyword length cannot exceed 100 characters"

    def test_validate_query_valid(self, search_tool):
        """Test valid query validation"""
        result = search_tool._validate_query("valid query")
        assert result is None

    def test_parse_item_basic(self, search_tool):
        """Test basic item parsing"""
        mock_item = Mock()
        mock_item.title = "Test Title"
        mock_item.link = "https://example.com"
        mock_item.snippet = "Test snippet"
        mock_item.main_text = "Test main text"
        mock_item.markdown_text = None
        mock_item.publish_time = "2024-01-01"
        mock_item.score = 0.95
        mock_item.card_type = "web"
        mock_item.page_map = {"hostname": "example.com"}
        mock_item.images = None

        result = search_tool._parse_item(mock_item)

        assert result["title"] == "Test Title"
        assert result["url"] == "https://example.com"
        assert result["snippet"] == "Test snippet"
        assert result["content"] == "Test main text"
        assert result["publish_time"] == "2024-01-01"
        assert result["score"] == 0.95
        assert result["card_type"] == "web"
        assert result["hostname"] == "example.com"

    def test_parse_item_with_markdown_and_images(self, search_tool):
        """Test item parsing with markdown and images"""
        mock_image = Mock()
        mock_image.image_link = "https://example.com/image.jpg"
        mock_image.width = 800
        mock_image.height = 600

        mock_item = Mock()
        mock_item.title = "Test Title"
        mock_item.link = "https://example.com"
        mock_item.snippet = "Test snippet"
        mock_item.main_text = "Test main text"
        mock_item.markdown_text = "# Test Markdown"
        mock_item.publish_time = "2024-01-01"
        mock_item.score = 0.95
        mock_item.card_type = "web"
        mock_item.page_map = {"hostname": "example.com"}
        mock_item.images = [mock_image]

        result = search_tool._parse_item(mock_item)

        assert result["markdown_content"] == "# Test Markdown"
        assert len(result["images"]) == 1
        assert result["images"][0]["url"] == "https://example.com/image.jpg"
        assert result["images"][0]["width"] == 800
        assert result["images"][0]["height"] == 600

    @patch("src.tools.generic_search.logger")
    def test_handle_search_results(
        self, mock_logger, search_tool, mock_search_response
    ):
        """Test search results handling"""
        result = search_tool._handle_search_results(
            mock_search_response.body, "test search"
        )

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["title"] == "Test Title"
        assert result[0]["url"] == "https://example.com"

        # Verify logger call
        mock_logger.info.assert_called()

    def test_handle_tea_exception(self, search_tool):
        """Test TeaException handling"""
        mock_exception = TeaException({"code": "InvalidParameter"})
        mock_exception.data = {
            "requestId": "test-request-id",
            "message": "Invalid query",
        }

        with patch("src.tools.generic_search.logger") as mock_logger:
            result = search_tool._handle_tea_exception(mock_exception, "test operation")

            assert "test operation API exception" in result
            assert "test-request-id" in result
            assert "InvalidParameter" in result
            assert "Invalid query" in result
            mock_logger.error.assert_called_once()

    def test_handle_general_exception(self, search_tool):
        """Test general exception handling"""
        exception = Exception("General error")

        with patch("src.tools.generic_search.logger") as mock_logger:
            result = search_tool._handle_general_exception(exception, "test operation")

            assert "test operation failed" in result
            assert "General error" in result
            mock_logger.error.assert_called_once()

    def test_run_success(self, search_tool, mock_search_response):
        """Test successful synchronous search"""
        search_tool.client.generic_search.return_value = mock_search_response

        result = search_tool._run("test query")

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["title"] == "Test Title"

        # Verify client call
        search_tool.client.generic_search.assert_called_once()
        call_args = search_tool.client.generic_search.call_args[0][0]
        assert call_args.query == "test query"

    def test_run_with_custom_parameters(self, search_tool, mock_search_response):
        """Test synchronous search with custom parameters"""
        search_tool.client.generic_search.return_value = mock_search_response

        result = search_tool._run(
            query="custom query",
            time_range="OneWeek",
            industry="finance",
            page=2,
            return_main_text=False,
            return_markdown_text=False,
            enable_rerank=False,
        )

        assert isinstance(result, list)

        # Verify parameter passing
        call_args = search_tool.client.generic_search.call_args[0][0]
        assert call_args.query == "custom query"
        assert call_args.time_range == "OneWeek"
        assert call_args.industry == "finance"
        assert call_args.page == 2
        assert call_args.return_main_text is False
        assert call_args.return_markdown_text is False
        assert call_args.enable_rerank is False

    def test_run_validation_error(self, search_tool):
        """Test synchronous search validation error"""
        result = search_tool._run("")

        assert isinstance(result, str)
        assert "Error: Search keyword cannot be empty" in result
        search_tool.client.generic_search.assert_not_called()

    def test_run_tea_exception(self, search_tool):
        """Test synchronous search TeaException"""
        mock_exception = TeaException({"code": "InvalidParameter"})
        mock_exception.data = {"requestId": "test-id", "message": "Invalid query"}
        search_tool.client.generic_search.side_effect = mock_exception

        result = search_tool._run("test query")

        assert isinstance(result, str)
        assert "synchronous search API exception" in result

    def test_run_general_exception(self, search_tool):
        """Test synchronous search general exception"""
        search_tool.client.generic_search.side_effect = Exception("Network error")

        result = search_tool._run("test query")

        assert isinstance(result, str)
        assert "synchronous search failed" in result
        assert "Network error" in result

    @pytest.mark.asyncio
    async def test_arun_success(self, search_tool, async_mock_search_response):
        """Test successful asynchronous search"""
        search_tool.client.generic_search_async.return_value = (
            async_mock_search_response
        )

        result = await search_tool._arun("test query")

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["title"] == "Test Title"

        # Verify client call
        search_tool.client.generic_search_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_arun_validation_error(self, search_tool):
        """Test asynchronous search validation error"""
        result = await search_tool._arun("")

        assert isinstance(result, str)
        assert "Error: Search keyword cannot be empty" in result
        search_tool.client.generic_search_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_arun_tea_exception(self, search_tool):
        """Test asynchronous search TeaException"""
        mock_exception = TeaException({"code": "RateLimitExceeded"})
        mock_exception.data = {
            "requestId": "async-test-id",
            "message": "Rate limit exceeded",
        }
        search_tool.client.generic_search_async.side_effect = mock_exception

        result = await search_tool._arun("test query")

        assert isinstance(result, str)
        assert "asynchronous search API exception" in result

    @pytest.mark.asyncio
    async def test_arun_general_exception(self, search_tool):
        """Test asynchronous search general exception"""
        search_tool.client.generic_search_async.side_effect = Exception(
            "Async network error"
        )

        result = await search_tool._arun("test query")

        assert isinstance(result, str)
        assert "asynchronous generic search failed" in result
        assert "Async network error" in result

    def test_handle_search_results_empty(self, search_tool):
        """Test handling empty search results"""
        mock_result = Mock(spec=models.GenericSearchResult)
        mock_result.page_items = []
        mock_result.request_id = "empty-request-id"
        mock_result.search_information = None

        with patch("src.tools.generic_search.logger") as mock_logger:
            result = search_tool._handle_search_results(
                mock_result, "empty result test"
            )

            assert isinstance(result, list)
            assert len(result) == 0
            mock_logger.info.assert_called()

    def test_handle_search_results_limit_results(self, search_tool):
        """Test limiting number of search results"""
        # Create mock items exceeding max_results
        mock_items = []
        for i in range(10):  # search_tool.max_results = 5
            mock_item = Mock()
            mock_item.title = f"Title {i}"
            mock_item.link = f"https://example{i}.com"
            mock_item.snippet = f"Snippet {i}"
            mock_item.main_text = f"Content {i}"
            mock_item.markdown_text = None
            mock_item.publish_time = "2024-01-01"
            mock_item.score = 0.9
            mock_item.card_type = "web"
            mock_item.page_map = {}
            mock_item.images = None
            mock_items.append(mock_item)

        mock_result = Mock(spec=models.GenericSearchResult)
        mock_result.page_items = mock_items
        mock_result.request_id = "limit-test-id"
        mock_result.search_information = None

        result = search_tool._handle_search_results(mock_result, "limit test")

        # Should only return max_results number of results
        assert len(result) == search_tool.max_results
        assert result[0]["title"] == "Title 0"
        assert result[4]["title"] == "Title 4"
