"""Semantic Scholar API integration for academic paper search and citation analysis."""

import logging
from typing import Any

import httpx
from langchain.tools import tool

from src.community.tool_utils import format_tool_error, format_tool_success, get_tool_extra

logger = logging.getLogger(__name__)

BASE_URL = "https://api.semanticscholar.org/graph/v1"


def _get_api_key() -> str | None:
    return get_tool_extra("semantic_scholar_search", "api_key")


def _make_request(endpoint: str, params: dict[str, Any]) -> dict:
    headers = {}
    api_key = _get_api_key()
    if api_key:
        headers["x-api-key"] = api_key
    with httpx.Client(timeout=30) as client:
        response = client.get(f"{BASE_URL}/{endpoint}", params=params, headers=headers)
        response.raise_for_status()
        return response.json()


@tool("semantic_scholar_search", parse_docstring=True)
def semantic_scholar_search_tool(
    query: str,
    fields: str = "title,authors,year,citationCount,abstract,tldr,externalIds,venue,publicationDate",
    limit: int = 10,
    year_range: str | None = None,
    venue: str | None = None,
) -> str:
    """Search academic papers via Semantic Scholar API.

    Use this for literature search, finding related work, citation analysis,
    and author discovery. Supports filtering by year range and venue.

    Args:
        query: Search query (natural language or structured).
        fields: Comma-separated fields to return.
        limit: Maximum number of results (1-100).
        year_range: Optional year filter (e.g., "2020-2024" or "2023-").
        venue: Optional venue filter (e.g., "NeurIPS", "Nature").
    """
    params: dict[str, Any] = {"query": query, "fields": fields, "limit": max(1, min(limit, 100))}
    if year_range:
        params["year"] = year_range
    if venue:
        params["venue"] = venue

    try:
        data = _make_request("paper/search", params)
        papers = data.get("data", [])
        results = []
        for p in papers:
            external_ids = p.get("externalIds") or {}
            tldr_obj = p.get("tldr")
            entry = {
                "title": p.get("title"),
                "authors": [a.get("name") for a in p.get("authors", [])],
                "year": p.get("year"),
                "citations": p.get("citationCount"),
                "venue": p.get("venue"),
                "abstract": (p.get("abstract") or "")[:500],
                "tldr": tldr_obj.get("text") if isinstance(tldr_obj, dict) else None,
                "doi": external_ids.get("DOI"),
                "arxiv_id": external_ids.get("ArXiv"),
                "s2_id": p.get("paperId"),
            }
            results.append(entry)
        return format_tool_success("semantic_scholar_search", results)
    except Exception as e:
        return format_tool_error("semantic_scholar_search", f"Error searching Semantic Scholar: {e}")


@tool("semantic_scholar_paper", parse_docstring=True)
def semantic_scholar_paper_tool(
    paper_id: str,
    fields: str = "title,authors,year,citationCount,referenceCount,abstract,tldr,references,citations,externalIds,venue",
) -> str:
    """Get detailed information about a specific paper, including its references and citations.

    Use this for citation chain analysis, finding a paper's reference list,
    or getting detailed metadata about a known paper.

    Args:
        paper_id: Semantic Scholar paper ID, DOI, ArXiv ID, or corpus ID.
        fields: Comma-separated fields to return.
    """
    try:
        data = _make_request(f"paper/{paper_id}", {"fields": fields})
        return format_tool_success("semantic_scholar_paper", data)
    except Exception as e:
        return format_tool_error("semantic_scholar_paper", f"Error fetching paper details: {e}")


@tool("semantic_scholar_author", parse_docstring=True)
def semantic_scholar_author_tool(
    author_id: str,
    fields: str = "name,affiliations,paperCount,citationCount,hIndex,papers",
) -> str:
    """Get information about an author, including their papers and citation metrics.

    Args:
        author_id: Semantic Scholar author ID.
        fields: Comma-separated fields to return.
    """
    try:
        data = _make_request(f"author/{author_id}", {"fields": fields})
        return format_tool_success("semantic_scholar_author", data)
    except Exception as e:
        return format_tool_error("semantic_scholar_author", f"Error fetching author details: {e}")
