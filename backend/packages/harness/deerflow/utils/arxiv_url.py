"""URL normalization utilities for academic literature sources.

Supports:
- arXiv identifiers (arxiv:XXXX.XXXXX, arxiv.org/pdf/..., arxiv.org/abs/...)
- DOI identifiers (doi:10.XXXX/..., dx.doi.org/...)
- PubMed identifiers (pmid:XXXXXXXX, pubmed.ncbi.nlm.nih.gov/...)
- Plain URLs (returned as-is)

Canonical forms:
- arXiv  → https://arxiv.org/abs/<id>
- DOI    → https://doi.org/<doi>
- PubMed → https://pubmed.ncbi.nlm.nih.gov/<pmid>/
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

_ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5}(v\d+)?)")

# Matches "arxiv:XXXX.XXXXX" or "arXiv:XXXX.XXXXX"
_ARXIV_PREFIX_RE = re.compile(r"^arxiv:(.+)$", re.IGNORECASE)

# Matches arxiv.org/abs/... or arxiv.org/pdf/...
_ARXIV_URL_RE = re.compile(
    r"https?://(?:www\.)?arxiv\.org/(?:abs|pdf|html)/([^\s?#]+)",
    re.IGNORECASE,
)

# Matches "doi:10.XXXX/..."
_DOI_PREFIX_RE = re.compile(r"^doi:(.+)$", re.IGNORECASE)

# Matches dx.doi.org/... or doi.org/...
_DOI_URL_RE = re.compile(
    r"https?://(?:dx\.)?doi\.org/(.+)",
    re.IGNORECASE,
)

# Matches "pmid:XXXXXXXX"
_PMID_PREFIX_RE = re.compile(r"^pmid:(\d+)$", re.IGNORECASE)

# Matches pubmed.ncbi.nlm.nih.gov/XXXXXXXX
_PMID_URL_RE = re.compile(
    r"https?://pubmed\.ncbi\.nlm\.nih\.gov/(\d+)/?",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


class NormalizedURL(NamedTuple):
    url: str
    source_type: str  # "arxiv" | "doi" | "pubmed" | "url"
    identifier: str   # raw ID extracted (arXiv ID, DOI string, PMID, or full URL)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize_literature_url(raw: str) -> NormalizedURL:
    """Normalize a raw literature reference to a canonical URL.

    Args:
        raw: Any of: "arxiv:2310.06825", "https://arxiv.org/pdf/2310.06825",
             "doi:10.1038/s41586-021-03828-1", "pmid:12345678", or a plain URL.

    Returns:
        NormalizedURL with canonical url, source_type, and extracted identifier.
    """
    raw = raw.strip()

    # --- arXiv prefix notation ---
    m = _ARXIV_PREFIX_RE.match(raw)
    if m:
        arxiv_id = _strip_arxiv_id(m.group(1))
        return NormalizedURL(
            url=f"https://arxiv.org/abs/{arxiv_id}",
            source_type="arxiv",
            identifier=arxiv_id,
        )

    # --- arXiv URL (abs or pdf) ---
    m = _ARXIV_URL_RE.match(raw)
    if m:
        arxiv_id = _strip_arxiv_id(m.group(1))
        return NormalizedURL(
            url=f"https://arxiv.org/abs/{arxiv_id}",
            source_type="arxiv",
            identifier=arxiv_id,
        )

    # --- DOI prefix notation ---
    m = _DOI_PREFIX_RE.match(raw)
    if m:
        doi = m.group(1).strip()
        return NormalizedURL(
            url=f"https://doi.org/{doi}",
            source_type="doi",
            identifier=doi,
        )

    # --- DOI URL ---
    m = _DOI_URL_RE.match(raw)
    if m:
        doi = m.group(1).strip().rstrip("/")
        return NormalizedURL(
            url=f"https://doi.org/{doi}",
            source_type="doi",
            identifier=doi,
        )

    # --- PubMed prefix notation ---
    m = _PMID_PREFIX_RE.match(raw)
    if m:
        pmid = m.group(1)
        return NormalizedURL(
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            source_type="pubmed",
            identifier=pmid,
        )

    # --- PubMed URL ---
    m = _PMID_URL_RE.match(raw)
    if m:
        pmid = m.group(1)
        return NormalizedURL(
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            source_type="pubmed",
            identifier=pmid,
        )

    # --- Plain URL (pass through) ---
    return NormalizedURL(url=raw, source_type="url", identifier=raw)


def normalize_literature_urls(raws: list[str]) -> list[NormalizedURL]:
    """Normalize a list of raw references. Skips empty strings."""
    return [normalize_literature_url(r) for r in raws if r.strip()]


def batch_urls(urls: list[NormalizedURL], batch_size: int = 3) -> list[list[NormalizedURL]]:
    """Split a list of normalized URLs into batches for concurrent OV ingestion.

    Args:
        urls: List of NormalizedURL objects.
        batch_size: Max items per batch (default 3, matches OV concurrency limit).

    Returns:
        List of batches, each containing up to batch_size NormalizedURL objects.
    """
    if batch_size < 1:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")
    return [urls[i : i + batch_size] for i in range(0, len(urls), batch_size)]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _strip_arxiv_id(raw_id: str) -> str:
    """Strip trailing .pdf suffix and version suffix if needed; keep vN."""
    # Remove .pdf suffix
    raw_id = re.sub(r"\.pdf$", "", raw_id, flags=re.IGNORECASE)
    return raw_id.strip("/")
