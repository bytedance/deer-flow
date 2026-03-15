"""Tests for arXiv API tools."""

import json
from unittest.mock import MagicMock, patch

MOCK_ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2301.00001</id>
    <title>Test Paper on Transformers</title>
    <summary>This paper presents a novel transformer architecture.</summary>
    <published>2023-01-15T00:00:00Z</published>
    <author><name>Jane Doe</name></author>
    <author><name>John Smith</name></author>
    <category term="cs.CL"/>
    <category term="cs.AI"/>
    <link title="pdf" href="https://arxiv.org/pdf/2301.00001"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2301.00002</id>
    <title>Another Paper</title>
    <summary>Summary of another paper.</summary>
    <published>2023-01-20T00:00:00Z</published>
    <author><name>Alice Bob</name></author>
    <category term="cs.LG"/>
  </entry>
</feed>"""


def _mock_arxiv_response():
    mock = MagicMock()
    mock.status_code = 200
    mock.text = MOCK_ARXIV_XML
    mock.raise_for_status = MagicMock()
    return mock


def test_arxiv_search_returns_valid_json():
    from src.community.arxiv_search.tools import arxiv_search_tool

    with patch("src.community.arxiv_search.tools.httpx.Client") as mock_client:
        mock_client.return_value.__enter__ = lambda s: s
        mock_client.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.return_value.get = MagicMock(return_value=_mock_arxiv_response())

        result = arxiv_search_tool.invoke({"query": "transformer"})

    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert parsed["source"] == "arxiv_search"
    data = parsed["data"]
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["title"] == "Test Paper on Transformers"
    assert "Jane Doe" in data[0]["authors"]
    assert data[0]["arxiv_id"] == "2301.00001"
    assert "cs.CL" in data[0]["categories"]
    assert data[0]["pdf_url"] == "https://arxiv.org/pdf/2301.00001"


def test_arxiv_search_with_category_filter():
    from src.community.arxiv_search.tools import arxiv_search_tool

    with patch("src.community.arxiv_search.tools.httpx.Client") as mock_client:
        mock_client.return_value.__enter__ = lambda s: s
        mock_client.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.return_value.get = MagicMock(return_value=_mock_arxiv_response())

        arxiv_search_tool.invoke({"query": "attention", "category": "cs.CL"})

    call_args = mock_client.return_value.get.call_args
    params = call_args[1].get("params") or call_args[0][1] if len(call_args[0]) > 1 else call_args[1]["params"]
    assert "cat:cs.CL" in params["search_query"]


def test_arxiv_search_limits_max_results():
    from src.community.arxiv_search.tools import arxiv_search_tool

    with patch("src.community.arxiv_search.tools.httpx.Client") as mock_client:
        mock_client.return_value.__enter__ = lambda s: s
        mock_client.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.return_value.get = MagicMock(return_value=_mock_arxiv_response())

        arxiv_search_tool.invoke({"query": "test", "max_results": 100})

    call_args = mock_client.return_value.get.call_args
    params = call_args[1].get("params") or call_args[0][1] if len(call_args[0]) > 1 else call_args[1]["params"]
    assert params["max_results"] == 50


def test_arxiv_search_enforces_min_results():
    from src.community.arxiv_search.tools import arxiv_search_tool

    with patch("src.community.arxiv_search.tools.httpx.Client") as mock_client:
        mock_client.return_value.__enter__ = lambda s: s
        mock_client.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.return_value.get = MagicMock(return_value=_mock_arxiv_response())

        arxiv_search_tool.invoke({"query": "test", "max_results": 0})

    call_args = mock_client.return_value.get.call_args
    params = call_args[1].get("params") or call_args[0][1] if len(call_args[0]) > 1 else call_args[1]["params"]
    assert params["max_results"] == 1


def test_arxiv_search_handles_api_error():
    from src.community.arxiv_search.tools import arxiv_search_tool

    with patch("src.community.arxiv_search.tools.httpx.Client") as mock_client:
        mock_client.return_value.__enter__ = lambda s: s
        mock_client.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.return_value.get = MagicMock(side_effect=Exception("Network error"))

        result = arxiv_search_tool.invoke({"query": "test"})

    parsed = json.loads(result)
    assert parsed["ok"] is False
    assert parsed["source"] == "arxiv_search"
    assert parsed["error"]["type"] == "tool_error"
    assert "Network error" in parsed["error"]["message"]


def test_arxiv_search_handles_empty_response():
    from src.community.arxiv_search.tools import arxiv_search_tool

    empty_xml = '<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    mock_resp = MagicMock(status_code=200, text=empty_xml)
    mock_resp.raise_for_status = MagicMock()

    with patch("src.community.arxiv_search.tools.httpx.Client") as mock_client:
        mock_client.return_value.__enter__ = lambda s: s
        mock_client.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.return_value.get = MagicMock(return_value=mock_resp)

        result = arxiv_search_tool.invoke({"query": "nonexistent"})

    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert parsed["source"] == "arxiv_search"
    assert parsed["data"] == []
