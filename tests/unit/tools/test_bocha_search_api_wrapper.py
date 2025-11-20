# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from unittest.mock import Mock, patch

import pytest

from src.tools.bocha_search.bocha_search_api_wrapper import BochaSearchAPIWrapper


class TestBochaSearchAPIWrapper:
    @pytest.fixture
    def wrapper(self):
        return BochaSearchAPIWrapper(api_key="dummy-key")

    @pytest.fixture
    def mock_response_data(self):
        return {
            "code": 200,
            "data": {
                "webPages": {
                    "value": [
                        {
                            "name": "Test Title",
                            "url": "https://example.com",
                            "summary": "Test summary",
                            "siteName": "Example",
                            "siteIcon": "https://example.com/favicon.ico",
                            "dateLastCrawled": "2024-01-01T00:00:00Z",
                            "score": 0.9,
                        }
                    ]
                }
            },
        }

    @patch("src.tools.bocha_search.bocha_search_api_wrapper.requests.post")
    def test_raw_results_success(self, mock_post, wrapper, mock_response_data):
        mock_resp = Mock()
        mock_resp.json.return_value = mock_response_data
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        result = wrapper.raw_results("test query", max_results=3, freshness="oneWeek", summary=False)

        assert result == mock_response_data
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "json" in call_args.kwargs
        body = call_args.kwargs["json"]
        assert body["query"] == "test query"
        assert body["count"] == 3
        assert body["freshness"] == "oneWeek"
        assert body["summary"] is False

    @patch("src.tools.bocha_search.bocha_search_api_wrapper.requests.post")
    def test_raw_results_http_error(self, mock_post, wrapper):
        from requests import HTTPError

        mock_resp = Mock()
        mock_resp.raise_for_status.side_effect = HTTPError("API Error")
        mock_post.return_value = mock_resp

        with pytest.raises(HTTPError):
            wrapper.raw_results("test query")

    def test_clean_results_success(self, wrapper, mock_response_data):
        results = wrapper.clean_results(mock_response_data)

        assert len(results) == 1
        item = results[0]
        assert item["type"] == "page"
        assert item["title"] == "Test Title"
        assert item["url"] == "https://example.com"
        assert item["content"] == "Test summary"
        assert item["score"] == pytest.approx(0.9)
        assert item["site_name"] == "Example"
        assert item["site_icon"] == "https://example.com/favicon.ico"
        assert item["date_last_crawled"] == "2024-01-01T00:00:00Z"

    def test_clean_results_non_200_code(self, wrapper):
        data = {"code": 500, "data": {}}
        results = wrapper.clean_results(data)
        assert results == []

    def test_clean_results_handles_non_list_value(self, wrapper):
        data = {"code": 200, "data": {"webPages": {"value": {}}}}
        results = wrapper.clean_results(data)
        assert results == []
