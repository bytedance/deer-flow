"""Tests for CrossRef API tools."""

import json
from unittest.mock import MagicMock, patch


def _mock_doi_response():
    return MagicMock(
        status_code=200,
        json=lambda: {
            "message": {
                "DOI": "10.1038/s41586-021-03819-2",
                "title": ["Highly accurate protein structure prediction with AlphaFold"],
                "author": [
                    {"given": "John", "family": "Jumper"},
                    {"given": "Richard", "family": "Evans"},
                ],
                "container-title": ["Nature"],
                "published-print": {"date-parts": [[2021, 7]]},
                "volume": "596",
                "issue": "7873",
                "page": "583-589",
                "type": "journal-article",
                "reference-count": 95,
                "is-referenced-by-count": 20000,
                "URL": "https://doi.org/10.1038/s41586-021-03819-2",
            }
        },
    )


def _mock_search_response():
    return MagicMock(
        status_code=200,
        json=lambda: {
            "message": {
                "items": [
                    {
                        "DOI": "10.1234/test",
                        "title": ["Test Paper"],
                        "author": [{"given": "Test", "family": "Author"}],
                        "container-title": ["Test Journal"],
                        "published-online": {"date-parts": [[2023]]},
                        "volume": None,
                        "issue": None,
                        "page": None,
                        "type": "journal-article",
                        "reference-count": 10,
                        "is-referenced-by-count": 5,
                        "URL": "https://doi.org/10.1234/test",
                    }
                ]
            }
        },
    )


def test_crossref_doi_lookup_returns_valid_json():
    from src.community.crossref.tools import crossref_lookup_tool

    mock_resp = _mock_doi_response()
    mock_resp.raise_for_status = MagicMock()

    with patch("src.community.crossref.tools.httpx.Client") as mock_client:
        mock_client.return_value.__enter__ = lambda s: s
        mock_client.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.return_value.get = MagicMock(return_value=mock_resp)

        result = crossref_lookup_tool.invoke({"doi": "10.1038/s41586-021-03819-2"})

    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert parsed["source"] == "crossref_lookup"
    data = parsed["data"]
    assert data["doi"] == "10.1038/s41586-021-03819-2"
    assert "AlphaFold" in data["title"]
    assert "Jumper" in data["authors"][0]
    assert data["journal"] == "Nature"
    assert data["year"] == 2021


def test_crossref_query_search():
    from src.community.crossref.tools import crossref_lookup_tool

    mock_resp = _mock_search_response()
    mock_resp.raise_for_status = MagicMock()

    with patch("src.community.crossref.tools.httpx.Client") as mock_client:
        mock_client.return_value.__enter__ = lambda s: s
        mock_client.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.return_value.get = MagicMock(return_value=mock_resp)

        result = crossref_lookup_tool.invoke({"query": "test paper"})

    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert parsed["source"] == "crossref_lookup"
    assert isinstance(parsed["data"], list)
    assert len(parsed["data"]) == 1
    assert parsed["data"][0]["doi"] == "10.1234/test"


def test_crossref_no_params_returns_error():
    from src.community.crossref.tools import crossref_lookup_tool

    result = crossref_lookup_tool.invoke({})
    parsed = json.loads(result)
    assert parsed["ok"] is False
    assert parsed["source"] == "crossref_lookup"
    assert parsed["error"]["type"] == "validation_error"
    assert "Provide either 'query' or 'doi' parameter." in parsed["error"]["message"]


def test_crossref_handles_api_error():
    from src.community.crossref.tools import crossref_lookup_tool

    with patch("src.community.crossref.tools.httpx.Client") as mock_client:
        mock_client.return_value.__enter__ = lambda s: s
        mock_client.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.return_value.get = MagicMock(side_effect=Exception("Connection timeout"))

        result = crossref_lookup_tool.invoke({"doi": "10.1234/bad"})

    parsed = json.loads(result)
    assert parsed["ok"] is False
    assert parsed["source"] == "crossref_lookup"
    assert parsed["error"]["type"] == "tool_error"
    assert "timeout" in parsed["error"]["message"].lower() or "Connection" in parsed["error"]["message"]


def test_crossref_rows_has_minimum_bound():
    from src.community.crossref.tools import crossref_lookup_tool

    mock_resp = _mock_search_response()
    mock_resp.raise_for_status = MagicMock()

    with patch("src.community.crossref.tools.httpx.Client") as mock_client:
        mock_client.return_value.__enter__ = lambda s: s
        mock_client.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.return_value.get = MagicMock(return_value=mock_resp)

        crossref_lookup_tool.invoke({"query": "test", "rows": -5})

    params = mock_client.return_value.get.call_args.kwargs["params"]
    assert params["rows"] == 1


def test_format_crossref_item_handles_missing_fields():
    from src.community.crossref.tools import _format_crossref_item

    item = {"DOI": "10.1234/minimal", "type": "journal-article"}
    result = _format_crossref_item(item)
    assert result["doi"] == "10.1234/minimal"
    assert result["title"] == ""
    assert result["authors"] == []
    assert result["year"] is None
