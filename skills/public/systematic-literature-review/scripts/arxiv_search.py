#!/usr/bin/env python3
"""arXiv search client for the systematic-literature-review skill.

Queries the public arXiv API (http://export.arxiv.org/api/query) and
returns structured paper metadata as JSON. No API key required.

Design notes:

- No additional dependencies required. Uses `requests` when available,
  falls back to `urllib` with a requests-compatible shim (same pattern as
  ../../github-deep-research/scripts/github_api.py).
- Query parameters are URL-encoded via `urllib.parse.urlencode` with
  `quote_via=quote_plus`. Hand-rolled `k=v` joining would break on
  multi-word topics like "transformer attention".
- Atom XML is parsed with `xml.etree.ElementTree` using an explicit
  namespace map. Forgetting the namespace prefix is the #1 arXiv API
  parsing bug, so we bake it into NS_MAP.
- The `<id>` field in arXiv responses is a full URL like
  "http://arxiv.org/abs/1706.03762v5". Callers usually want the bare
  id "1706.03762", so we normalise it.
- max_results is clamped to 50 to match the skill's documented upper
  bound. Larger surveys are out of scope for the MVP.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

# Namespace map for arXiv's Atom feed. arXiv extends Atom with its own
# elements (primary_category, comment, journal_ref) under the `arxiv:`
# prefix; the core entry fields live under `atom:`.
NS_MAP = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

ARXIV_ENDPOINT = "http://export.arxiv.org/api/query"
MAX_RESULTS_UPPER_BOUND = 50
DEFAULT_TIMEOUT_SECONDS = 30


# --- HTTP client with requests -> urllib fallback --------------------------

try:
    import requests  # type: ignore
except ImportError:
    import urllib.error
    import urllib.parse
    import urllib.request

    class _UrllibResponse:
        def __init__(self, data: bytes, status: int) -> None:
            self._data = data
            self.status_code = status
            self.text = data.decode("utf-8", errors="replace")
            self.content = data

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

    class _UrllibRequestsShim:
        """Minimal requests-compatible shim using urllib.

        Only supports what arxiv_search needs: GET with query params.
        Params are encoded with quote_plus so multi-word queries work.
        """

        @staticmethod
        def get(
            url: str,
            params: dict | None = None,
            timeout: int = DEFAULT_TIMEOUT_SECONDS,
        ) -> _UrllibResponse:
            if params:
                query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote_plus)
                url = f"{url}?{query}"
            req = urllib.request.Request(url, headers={"User-Agent": "deerflow-slr-skill/0.1"})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return _UrllibResponse(resp.read(), resp.status)
            except urllib.error.HTTPError as e:
                return _UrllibResponse(e.read(), e.code)

    requests = _UrllibRequestsShim()  # type: ignore


# --- Core query + parsing --------------------------------------------------


def _build_search_query(
    query: str,
    category: str | None,
    start_date: str | None,
    end_date: str | None,
) -> str:
    """Build arXiv's `search_query` field.

    arXiv uses its own query grammar: `ti:`, `abs:`, `cat:`, `all:`, with
    `AND`/`OR`/`ANDNOT` combinators. We search `all:` for the user's
    topic (matches title + abstract + authors) and optionally AND it
    with a category filter and a submission date range.
    """
    # Wrap multi-word queries in double quotes so arXiv's Lucene parser
    # treats them as a phrase.  Without quotes, `all:diffusion model` is
    # parsed as `all:diffusion OR model`, pulling in unrelated papers
    # that merely mention the word "model".
    if " " in query:
        parts = [f'all:"{query}"']
    else:
        parts = [f"all:{query}"]
    if category:
        parts.append(f"cat:{category}")
    if start_date or end_date:
        # arXiv date range format: [YYYYMMDDHHMM TO YYYYMMDDHHMM]
        lo = (start_date or "19910101").replace("-", "") + "0000"
        hi = (end_date or "29991231").replace("-", "") + "2359"
        parts.append(f"submittedDate:[{lo} TO {hi}]")
    return " AND ".join(parts)


def _normalise_arxiv_id(raw_id: str) -> str:
    """Convert a full arXiv URL to a bare id.

    Handles both modern and legacy arXiv ID formats:
    - Modern: "http://arxiv.org/abs/1706.03762v5" -> "1706.03762"
    - Legacy: "http://arxiv.org/abs/hep-th/9901001v1" -> "hep-th/9901001"
    """
    # Extract everything after /abs/ to preserve legacy archive prefix
    if "/abs/" in raw_id:
        tail = raw_id.split("/abs/", 1)[1]
    else:
        tail = raw_id.rsplit("/", 1)[-1]
    # Strip version suffix: "1706.03762v5" -> "1706.03762"
    if "v" in tail:
        base, _, suffix = tail.rpartition("v")
        if suffix.isdigit():
            return base
    return tail


def _parse_entry(entry: Any) -> dict:
    """Turn one Atom <entry> element into a paper dict."""
    import xml.etree.ElementTree as ET

    def _text(path: str) -> str:
        node = entry.find(path, NS_MAP)
        return (node.text or "").strip() if node is not None and node.text else ""

    raw_id = _text("atom:id")
    arxiv_id = _normalise_arxiv_id(raw_id)

    authors = [(a.findtext("atom:name", default="", namespaces=NS_MAP) or "").strip() for a in entry.findall("atom:author", NS_MAP)]
    authors = [a for a in authors if a]

    categories = [c.get("term", "") for c in entry.findall("atom:category", NS_MAP) if c.get("term")]

    pdf_url = ""
    abs_url = raw_id  # default
    for link in entry.findall("atom:link", NS_MAP):
        if link.get("title") == "pdf":
            pdf_url = link.get("href", "")
        elif link.get("rel") == "alternate":
            abs_url = link.get("href", abs_url)

    # Dates come as ISO 8601 (2017-06-12T17:57:34Z). Keep the date part.
    published_raw = _text("atom:published")
    updated_raw = _text("atom:updated")
    published = published_raw.split("T", 1)[0] if published_raw else ""
    updated = updated_raw.split("T", 1)[0] if updated_raw else ""

    # Abstract (<summary>) has ragged whitespace from arXiv's formatting.
    # Collapse internal whitespace to make downstream LLM consumption easier.
    abstract = " ".join(_text("atom:summary").split())

    # Silence unused import warning; ET is only needed for type hints above.
    del ET

    return {
        "id": arxiv_id,
        "title": " ".join(_text("atom:title").split()),
        "authors": authors,
        "abstract": abstract,
        "published": published,
        "updated": updated,
        "categories": categories,
        "pdf_url": pdf_url,
        "abs_url": abs_url,
    }


def search(
    query: str,
    max_results: int = 20,
    category: str | None = None,
    sort_by: str = "relevance",
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """Query arXiv and return a list of paper dicts.

    Args:
        query: free-text topic, e.g. "transformer attention".
        max_results: number of papers to return (clamped to 50).
        category: optional arXiv category, e.g. "cs.CL".
        sort_by: "relevance", "submittedDate", or "lastUpdatedDate".
        start_date: YYYY-MM-DD or YYYYMMDD, inclusive.
        end_date: YYYY-MM-DD or YYYYMMDD, inclusive.

    Returns:
        list of dicts, each matching the schema documented in SKILL.md.
    """
    import xml.etree.ElementTree as ET

    if max_results <= 0:
        return []
    max_results = min(max_results, MAX_RESULTS_UPPER_BOUND)

    search_query = _build_search_query(query, category, start_date, end_date)
    params = {
        "search_query": search_query,
        "start": 0,
        "max_results": max_results,
        "sortBy": sort_by,
        "sortOrder": "descending",
    }

    resp = requests.get(ARXIV_ENDPOINT, params=params, timeout=DEFAULT_TIMEOUT_SECONDS)
    resp.raise_for_status()

    # arXiv returns Atom XML, not JSON.
    root = ET.fromstring(resp.text)
    entries = root.findall("atom:entry", NS_MAP)
    return [_parse_entry(e) for e in entries]


# --- CLI -------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Query the arXiv API and emit structured paper metadata as JSON.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            '  python arxiv_search.py "transformer attention" --max-results 10\n'
            '  python arxiv_search.py "diffusion models" --category cs.CV --sort-by submittedDate\n'
            '  python arxiv_search.py "graph neural networks" --start-date 2023-01-01\n'
        ),
    )
    parser.add_argument("query", help="free-text search topic")
    parser.add_argument(
        "--max-results",
        type=int,
        default=20,
        help=f"number of papers to return (default: 20, max: {MAX_RESULTS_UPPER_BOUND})",
    )
    parser.add_argument(
        "--category",
        default=None,
        help="optional arXiv category filter, e.g. cs.CL, cs.CV, stat.ML",
    )
    parser.add_argument(
        "--sort-by",
        default="relevance",
        choices=["relevance", "submittedDate", "lastUpdatedDate"],
        help="sort order (default: relevance)",
    )
    parser.add_argument(
        "--start-date",
        default=None,
        help="earliest submission date, YYYY-MM-DD (inclusive)",
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help="latest submission date, YYYY-MM-DD (inclusive)",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        papers = search(
            query=args.query,
            max_results=args.max_results,
            category=args.category,
            sort_by=args.sort_by,
            start_date=args.start_date,
            end_date=args.end_date,
        )
    except Exception as exc:
        print(f"arxiv_search.py: {exc}", file=sys.stderr)
        return 1

    json.dump(papers, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
