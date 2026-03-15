"""Tests for Semantic Scholar API tools."""

import json
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _mock_tool_utils():
    with patch("src.community.semantic_scholar.tools.get_tool_extra", return_value=None):
        yield


def _mock_search_response():
    return {
        "data": [
            {
                "paperId": "abc123",
                "title": "Attention Is All You Need",
                "authors": [{"name": "Ashish Vaswani"}, {"name": "Noam Shazeer"}],
                "year": 2017,
                "citationCount": 90000,
                "venue": "NeurIPS",
                "abstract": "The dominant sequence transduction models...",
                "tldr": {"text": "Proposes the Transformer architecture."},
                "externalIds": {"DOI": "10.5555/3295222.3295349", "ArXiv": "1706.03762"},
                "publicationDate": "2017-06-12",
            }
        ]
    }


def test_semantic_scholar_search_returns_valid_json():
    from src.community.semantic_scholar.tools import semantic_scholar_search_tool

    with patch("src.community.semantic_scholar.tools._make_request", return_value=_mock_search_response()):
        result = semantic_scholar_search_tool.invoke({"query": "transformer attention"})
    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert parsed["source"] == "semantic_scholar_search"
    data = parsed["data"]
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["title"] == "Attention Is All You Need"
    assert data[0]["doi"] == "10.5555/3295222.3295349"
    assert data[0]["citations"] == 90000
    assert "Vaswani" in data[0]["authors"][0]


def test_semantic_scholar_search_handles_api_error():
    from src.community.semantic_scholar.tools import semantic_scholar_search_tool

    with patch("src.community.semantic_scholar.tools._make_request", side_effect=Exception("API rate limit")):
        result = semantic_scholar_search_tool.invoke({"query": "test"})
    parsed = json.loads(result)
    assert parsed["ok"] is False
    assert parsed["source"] == "semantic_scholar_search"
    assert parsed["error"]["type"] == "tool_error"
    assert "API rate limit" in parsed["error"]["message"]


def test_semantic_scholar_search_with_year_range():
    from src.community.semantic_scholar.tools import semantic_scholar_search_tool

    with patch("src.community.semantic_scholar.tools._make_request", return_value={"data": []}) as mock_req:
        semantic_scholar_search_tool.invoke({"query": "llm", "year_range": "2023-2025"})
    call_args = mock_req.call_args
    assert call_args[0][1]["year"] == "2023-2025"


def test_semantic_scholar_search_limits_to_100():
    from src.community.semantic_scholar.tools import semantic_scholar_search_tool

    with patch("src.community.semantic_scholar.tools._make_request", return_value={"data": []}) as mock_req:
        semantic_scholar_search_tool.invoke({"query": "test", "limit": 200})
    call_args = mock_req.call_args
    assert call_args[0][1]["limit"] == 100


def test_semantic_scholar_search_enforces_min_limit():
    from src.community.semantic_scholar.tools import semantic_scholar_search_tool

    with patch("src.community.semantic_scholar.tools._make_request", return_value={"data": []}) as mock_req:
        semantic_scholar_search_tool.invoke({"query": "test", "limit": 0})
    call_args = mock_req.call_args
    assert call_args[0][1]["limit"] == 1


def test_semantic_scholar_search_handles_missing_fields():
    from src.community.semantic_scholar.tools import semantic_scholar_search_tool

    response = {
        "data": [
            {
                "paperId": "xyz",
                "title": "Minimal Paper",
                "authors": [],
                "year": None,
                "citationCount": None,
                "venue": None,
                "abstract": None,
                "tldr": None,
                "externalIds": None,
            }
        ]
    }
    with patch("src.community.semantic_scholar.tools._make_request", return_value=response):
        result = semantic_scholar_search_tool.invoke({"query": "minimal"})
    parsed = json.loads(result)
    assert parsed["ok"] is True
    data = parsed["data"]
    assert data[0]["title"] == "Minimal Paper"
    assert data[0]["doi"] is None
    assert data[0]["tldr"] is None


def test_semantic_scholar_paper_by_doi():
    from src.community.semantic_scholar.tools import semantic_scholar_paper_tool

    mock_data = {"paperId": "abc", "title": "Test Paper", "authors": [], "year": 2023}
    with patch("src.community.semantic_scholar.tools._make_request", return_value=mock_data):
        result = semantic_scholar_paper_tool.invoke({"paper_id": "10.1234/test"})
    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert parsed["source"] == "semantic_scholar_paper"
    assert parsed["data"]["title"] == "Test Paper"


def test_semantic_scholar_author():
    from src.community.semantic_scholar.tools import semantic_scholar_author_tool

    mock_data = {"authorId": "123", "name": "Test Author", "hIndex": 50, "paperCount": 100}
    with patch("src.community.semantic_scholar.tools._make_request", return_value=mock_data):
        result = semantic_scholar_author_tool.invoke({"author_id": "123"})
    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert parsed["source"] == "semantic_scholar_author"
    assert parsed["data"]["name"] == "Test Author"
    assert parsed["data"]["hIndex"] == 50


def test_get_api_key_returns_none_when_not_configured():
    with patch("src.community.semantic_scholar.tools.get_tool_extra", return_value=None):
        from src.community.semantic_scholar.tools import _get_api_key

        assert _get_api_key() is None
