"""CrossRef API integration for DOI resolution, citation metadata, and reference validation."""

import logging
from typing import Any

import httpx
from langchain.tools import tool

from src.community.tool_utils import format_tool_error, format_tool_success

logger = logging.getLogger(__name__)

BASE_URL = "https://api.crossref.org"


def _format_crossref_item(item: dict) -> dict[str, Any]:
    published = item.get("published-print") or item.get("published-online") or {}
    date_parts = published.get("date-parts", [[None]])
    year = date_parts[0][0] if date_parts and date_parts[0] else None
    return {
        "doi": item.get("DOI"),
        "title": item.get("title", [""])[0] if item.get("title") else "",
        "authors": [f"{a.get('given', '')} {a.get('family', '')}".strip() for a in item.get("author", [])],
        "journal": item.get("container-title", [""])[0] if item.get("container-title") else "",
        "year": year,
        "volume": item.get("volume"),
        "issue": item.get("issue"),
        "pages": item.get("page"),
        "type": item.get("type"),
        "reference_count": item.get("reference-count"),
        "is_referenced_by_count": item.get("is-referenced-by-count"),
        "url": item.get("URL"),
    }


@tool("crossref_lookup", parse_docstring=True)
def crossref_lookup_tool(
    query: str | None = None,
    doi: str | None = None,
    rows: int = 5,
) -> str:
    """Look up academic paper metadata via CrossRef.

    Use for DOI validation, getting accurate citation metadata,
    verifying journal names, and finding reference lists.
    Provide either a search query OR a specific DOI.

    Args:
        query: Search query for papers (used if doi is not provided).
        doi: Specific DOI to look up (takes precedence over query).
        rows: Number of results for search queries (1-20).
    """
    try:
        with httpx.Client(timeout=30) as client:
            if doi:
                response = client.get(f"{BASE_URL}/works/{doi}", headers={"Accept": "application/json"})
                response.raise_for_status()
                item = response.json()["message"]
                return format_tool_success("crossref_lookup", _format_crossref_item(item))
            elif query:
                response = client.get(
                    f"{BASE_URL}/works",
                    params={"query": query, "rows": max(1, min(rows, 20))},
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                items = response.json()["message"]["items"]
                results = [_format_crossref_item(item) for item in items]
                return format_tool_success("crossref_lookup", results)
            else:
                return format_tool_error("crossref_lookup", "Provide either 'query' or 'doi' parameter.", "validation_error")
    except Exception as e:
        return format_tool_error("crossref_lookup", f"Error querying CrossRef: {e}")
