"""arXiv API integration for preprint search and retrieval."""

import logging
import xml.etree.ElementTree as ET

import httpx
from langchain.tools import tool

from src.community.tool_utils import format_tool_error, format_tool_success

logger = logging.getLogger(__name__)

ARXIV_API = "http://export.arxiv.org/api/query"


@tool("arxiv_search", parse_docstring=True)
def arxiv_search_tool(
    query: str,
    category: str | None = None,
    max_results: int = 10,
    sort_by: str = "relevance",
) -> str:
    """Search arXiv for preprints and papers.

    Ideal for finding cutting-edge research that may not yet be indexed
    by Semantic Scholar. Supports category filtering and sorting.

    Args:
        query: Search query. Supports arXiv query syntax (e.g., "au:Hinton AND ti:attention").
        category: Optional arXiv category filter (e.g., "cs.CL", "stat.ML", "physics.comp-ph").
        max_results: Maximum results to return (1-50).
        sort_by: Sort order — "relevance", "lastUpdatedDate", or "submittedDate".
    """
    search_query = query
    if category:
        search_query = f"cat:{category} AND ({query})"

    params = {
        "search_query": search_query,
        "start": 0,
        "max_results": max(1, min(max_results, 50)),
        "sortBy": sort_by,
        "sortOrder": "descending",
    }

    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(ARXIV_API, params=params)
            response.raise_for_status()

        root = ET.fromstring(response.text)
        ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

        results = []
        for entry in root.findall("atom:entry", ns):
            id_elem = entry.find("atom:id", ns)
            title_elem = entry.find("atom:title", ns)
            summary_elem = entry.find("atom:summary", ns)
            published_elem = entry.find("atom:published", ns)

            if id_elem is None or title_elem is None:
                continue

            arxiv_id = id_elem.text.split("/abs/")[-1]
            title = title_elem.text.strip().replace("\n", " ")
            summary = summary_elem.text.strip()[:500] if summary_elem is not None and summary_elem.text else ""
            authors = [a.find("atom:name", ns).text for a in entry.findall("atom:author", ns) if a.find("atom:name", ns) is not None]
            published = published_elem.text[:10] if published_elem is not None and published_elem.text else ""
            categories = [c.get("term") for c in entry.findall("atom:category", ns) if c.get("term")]

            pdf_link = None
            for link in entry.findall("atom:link", ns):
                if link.get("title") == "pdf":
                    pdf_link = link.get("href")

            results.append(
                {
                    "arxiv_id": arxiv_id,
                    "title": title,
                    "authors": authors,
                    "abstract": summary,
                    "published": published,
                    "categories": categories,
                    "pdf_url": pdf_link or f"https://arxiv.org/pdf/{arxiv_id}",
                    "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
                }
            )

        return format_tool_success("arxiv_search", results)
    except Exception as e:
        return format_tool_error("arxiv_search", f"Error searching arXiv: {e}")
