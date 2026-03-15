"""Citation memory: persists bibliography across sessions.

Stores verified citations in a separate JSON file that can be
injected into any session where the user references prior work.
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _get_default_store_path() -> Path:
    backend_dir = Path(__file__).resolve().parent.parent.parent
    return backend_dir / ".deer-flow" / "citations.json"


def load_citations(store_path: str | Path | None = None) -> dict[str, Any]:
    """Load citations from the persistent store.

    Args:
        store_path: Path to the citation JSON file. Uses default if None.

    Returns:
        Dictionary with 'citations' and 'tags' keys.
    """
    path = Path(store_path) if store_path else _get_default_store_path()
    if not path.exists():
        return {"citations": {}, "tags": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Failed to load citation store: %s", e)
        return {"citations": {}, "tags": {}}


def save_citation(
    cite_key: str,
    metadata: dict[str, Any],
    tags: list[str] | None = None,
    store_path: str | Path | None = None,
) -> None:
    """Save a citation to the persistent store.

    Args:
        cite_key: BibTeX citation key (e.g., "vaswani2017attention").
        metadata: Citation metadata (title, authors, year, doi, venue, etc.).
        tags: Optional list of tags for categorization.
        store_path: Path to the citation JSON file.
    """
    path = Path(store_path) if store_path else _get_default_store_path()
    store = load_citations(path)
    store["citations"][cite_key] = metadata
    if tags:
        for tag in tags:
            store["tags"].setdefault(tag, [])
            if cite_key not in store["tags"][tag]:
                store["tags"][tag].append(cite_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")


def remove_citation(cite_key: str, store_path: str | Path | None = None) -> bool:
    """Remove a citation from the store.

    Returns:
        True if the citation was found and removed, False otherwise.
    """
    path = Path(store_path) if store_path else _get_default_store_path()
    store = load_citations(path)
    if cite_key not in store["citations"]:
        return False
    del store["citations"][cite_key]
    for tag_list in store["tags"].values():
        if cite_key in tag_list:
            tag_list.remove(cite_key)
    path.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")
    return True


def search_citations(query: str, store_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Search citations by query string.

    Searches across all citation metadata fields and keys.

    Args:
        query: Search string (case-insensitive).
        store_path: Path to the citation JSON file.

    Returns:
        List of matching citations with their keys.
    """
    store = load_citations(store_path)
    results = []
    query_lower = query.lower()
    for key, meta in store["citations"].items():
        searchable = json.dumps(meta, ensure_ascii=False).lower()
        if query_lower in searchable or query_lower in key.lower():
            results.append({"cite_key": key, **meta})
    return results


def get_citations_by_tag(tag: str, store_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Get all citations with a specific tag.

    Args:
        tag: Tag to filter by.
        store_path: Path to the citation JSON file.

    Returns:
        List of citations matching the tag.
    """
    store = load_citations(store_path)
    keys = store["tags"].get(tag, [])
    return [{"cite_key": k, **store["citations"][k]} for k in keys if k in store["citations"]]


def format_for_injection(store_path: str | Path | None = None, max_entries: int = 20) -> str:
    """Format citations for injection into the system prompt.

    Args:
        store_path: Path to the citation JSON file.
        max_entries: Maximum number of citations to include.

    Returns:
        Formatted string wrapped in XML tags, or empty string if no citations.
    """
    store = load_citations(store_path)
    if not store["citations"]:
        return ""
    entries = list(store["citations"].items())[:max_entries]
    lines = [f"- [{key}] {meta.get('title', 'Unknown')} ({meta.get('year', '?')})" for key, meta in entries]
    return "<citation_library>\n" + "\n".join(lines) + "\n</citation_library>"


def get_citation_count(store_path: str | Path | None = None) -> int:
    """Get the total number of stored citations."""
    store = load_citations(store_path)
    return len(store["citations"])
