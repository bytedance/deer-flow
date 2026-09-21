"""Read-only, manifest-gated access to a published Regional LLM Wiki release.

These tools intentionally run in Gateway, rather than in the general sandbox.
The only mounted input is the maintainer's published release parent.  Callers
never provide filesystem paths: all reads are resolved through validated IDs in
``agent-access-manifest.json``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain.tools import tool

from deerflow.config import get_app_config

_MANIFEST_NAME = "agent-access-manifest.json"
_CURRENT_NAME = "current"
_RELEASES_NAME = "releases"
_MAX_QUERY_CHARS = 500


class _ReleaseError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class _Release:
    root: Path
    release_id: str
    manifest: dict[str, Any]
    max_search_results: int
    max_page_chars: int
    max_evidence_chars: int


def _response(status: str, **payload: object) -> str:
    return json.dumps({"status": status, **payload}, ensure_ascii=False, sort_keys=True)


def _safe_relative_path(value: object, *, required_prefix: str) -> Path:
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        raise _ReleaseError("integrity_failed")
    path = Path(value)
    if any(part in {"", ".", ".."} for part in path.parts) or not path.parts or path.parts[0] != required_prefix:
        raise _ReleaseError("integrity_failed")
    return path


def _read_limited(path: Path, *, expected_sha256: object, max_chars: int) -> str:
    try:
        if path.is_symlink() or not path.is_file():
            raise _ReleaseError("integrity_failed")
        content = path.read_text(encoding="utf-8")
    except _ReleaseError:
        raise
    except (OSError, UnicodeError):
        raise _ReleaseError("integrity_failed") from None
    if not isinstance(expected_sha256, str) or hashlib.sha256(content.encode("utf-8")).hexdigest() != expected_sha256:
        raise _ReleaseError("integrity_failed")
    return content[:max_chars]


def _open_release(release_id: str | None = None) -> _Release:
    config = get_app_config().regional_llm_wiki
    if not config.enabled:
        raise _ReleaseError("release_unavailable")
    try:
        runtime_root = Path(config.runtime_root).resolve(strict=True)
        releases_root = (runtime_root / _RELEASES_NAME).resolve(strict=True)
        if release_id is None:
            current = runtime_root / _CURRENT_NAME
            if not current.is_symlink():
                raise _ReleaseError("integrity_failed")
            release_root = current.resolve(strict=True)
        else:
            if not release_id or "/" in release_id or "\\" in release_id or release_id in {".", ".."}:
                raise _ReleaseError("not_found")
            release_root = (releases_root / release_id).resolve(strict=True)
        release_root.relative_to(releases_root)
        manifest_path = release_root / _MANIFEST_NAME
        if manifest_path.is_symlink():
            raise _ReleaseError("integrity_failed")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except _ReleaseError:
        raise
    except FileNotFoundError:
        if release_id is not None:
            raise _ReleaseError("not_found") from None
        raise _ReleaseError("release_unavailable") from None
    except ValueError:
        raise _ReleaseError("integrity_failed") from None
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise _ReleaseError("release_unavailable") from None

    release_id = manifest.get("release_id")
    if manifest.get("schema_version") != 1 or not isinstance(release_id, str) or not release_id:
        raise _ReleaseError("integrity_failed")
    if release_root.name != release_id:
        raise _ReleaseError("integrity_failed")
    if not isinstance(manifest.get("pages"), list) or not isinstance(manifest.get("evidence"), list):
        raise _ReleaseError("integrity_failed")
    return _Release(
        root=release_root,
        release_id=release_id,
        manifest=manifest,
        max_search_results=config.max_search_results,
        max_page_chars=config.max_page_chars,
        max_evidence_chars=config.max_evidence_chars,
    )


def _release_for_id(release_id: str) -> _Release:
    # A search response pins a version for one answer.  Maintenance retains at
    # least the preceding release, so a publish flip cannot mix old index data
    # with new page content during that answer.
    return _open_release(release_id)


def _page(release: _Release, page_id: str) -> dict[str, Any]:
    for item in release.manifest["pages"]:
        if isinstance(item, dict) and item.get("page_id") == page_id:
            return item
    raise _ReleaseError("not_found")


def _evidence(release: _Release, evidence_id: str) -> dict[str, Any]:
    for item in release.manifest["evidence"]:
        if isinstance(item, dict) and item.get("evidence_id") == evidence_id:
            return item
    raise _ReleaseError("not_found")


def _search(query: str, domain: str | None, limit: int) -> str:
    if not isinstance(query, str) or not query.strip() or len(query) > _MAX_QUERY_CHARS:
        return _response("invalid_request")
    try:
        release = _open_release()
        if domain is not None and (not isinstance(domain, str) or len(domain) > 128):
            return _response("invalid_request")
        requested_limit = min(max(1, limit), release.max_search_results)
        terms = [term for term in query.casefold().split() if term]
        candidates: list[tuple[int, dict[str, Any]]] = []
        for page in release.manifest["pages"]:
            if not isinstance(page, dict) or not isinstance(page.get("page_id"), str):
                raise _ReleaseError("integrity_failed")
            if domain is not None and page.get("domain") != domain:
                continue
            searchable = " ".join(str(page.get(key, "")) for key in ("page_id", "title", "type", "domain", "summary", "keywords")).casefold()
            score = sum(searchable.count(term) for term in terms)
            if score:
                candidates.append((score, page))
        candidates.sort(key=lambda entry: (-entry[0], str(entry[1]["page_id"])))
        return _response(
            "ok",
            release_id=release.release_id,
            pages=[
                {
                    "page_id": page["page_id"],
                    "title": page.get("title", page["page_id"]),
                    "type": page.get("type"),
                    "domain": page.get("domain"),
                }
                for _, page in candidates[:requested_limit]
            ],
        )
    except _ReleaseError as error:
        return _response(error.code)
    except (OSError, UnicodeError, ValueError):
        return _response("integrity_failed")


@tool("search_llm_wiki", parse_docstring=True)
async def search_llm_wiki(query: str, domain: str | None = None, limit: int = 5) -> str:
    """Search the current published Regional LLM Wiki index.

    Args:
        query: The user's knowledge question or concise search terms.
        domain: Optional published first-level domain name.
        limit: Maximum candidate pages to return, from 1 to 5.
    """
    return await asyncio.to_thread(_search, query, domain, limit)


def _read_page(release_id: str, page_id: str) -> str:
    try:
        release = _release_for_id(release_id)
        page = _page(release, page_id)
        relative_path = _safe_relative_path(page.get("path"), required_prefix="llm-wiki")
        file_path = (release.root / relative_path).resolve(strict=True)
        file_path.relative_to(release.root)
        content = _read_limited(file_path, expected_sha256=page.get("sha256"), max_chars=release.max_page_chars)
        evidence_ids = page.get("evidence_ids", [])
        if not isinstance(evidence_ids, list) or not all(isinstance(item, str) for item in evidence_ids):
            raise _ReleaseError("integrity_failed")
        return _response(
            "ok",
            release_id=release.release_id,
            page_id=page_id,
            title=page.get("title", page_id),
            type=page.get("type"),
            domain=page.get("domain"),
            evidence_ids=evidence_ids,
            content=content,
        )
    except _ReleaseError as error:
        return _response(error.code)
    except (OSError, UnicodeError, ValueError):
        return _response("integrity_failed")


@tool("read_llm_wiki_page", parse_docstring=True)
async def read_llm_wiki_page(release_id: str, page_id: str) -> str:
    """Read one manifest-approved LLM Wiki page from the current release.

    Args:
        release_id: The release ID returned by search_llm_wiki.
        page_id: A candidate page ID returned by search_llm_wiki.
    """
    return await asyncio.to_thread(_read_page, release_id, page_id)


def _read_evidence(release_id: str, page_id: str, evidence_id: str, locator: str | None) -> str:
    try:
        release = _release_for_id(release_id)
        page = _page(release, page_id)
        evidence_ids = page.get("evidence_ids", [])
        if not isinstance(evidence_ids, list) or evidence_id not in evidence_ids:
            raise _ReleaseError("not_found")
        evidence = _evidence(release, evidence_id)
        allowed_locations = evidence.get("allowed_locations", [])
        if not isinstance(allowed_locations, list) or not all(isinstance(item, str) for item in allowed_locations):
            raise _ReleaseError("integrity_failed")
        if locator is not None and locator not in allowed_locations:
            raise _ReleaseError("invalid_request")
        relative_path = _safe_relative_path(evidence.get("path"), required_prefix="evidence")
        file_path = (release.root / relative_path).resolve(strict=True)
        file_path.relative_to(release.root)
        content = _read_limited(file_path, expected_sha256=evidence.get("sha256"), max_chars=release.max_evidence_chars)
        return _response(
            "ok",
            release_id=release.release_id,
            page_id=page_id,
            evidence_id=evidence_id,
            locator=locator,
            allowed_locations=allowed_locations,
            tfs_url=evidence.get("tfs_url"),
            content=content,
        )
    except _ReleaseError as error:
        return _response(error.code)
    except (OSError, UnicodeError, ValueError):
        return _response("integrity_failed")


@tool("read_llm_wiki_evidence", parse_docstring=True)
async def read_llm_wiki_evidence(release_id: str, page_id: str, evidence_id: str, locator: str | None = None) -> str:
    """Read one evidence snapshot declared by an already-read LLM Wiki page.

    Args:
        release_id: The release ID returned by search_llm_wiki.
        page_id: The page ID returned by search_llm_wiki and read_llm_wiki_page.
        evidence_id: An evidence ID returned by read_llm_wiki_page for that page.
        locator: Optional declared line, section, or table-range locator.
    """
    return await asyncio.to_thread(_read_evidence, release_id, page_id, evidence_id, locator)


def _release_state() -> str:
    try:
        release = _open_release()
        return _response(
            "ok",
            release_id=release.release_id,
            source_commit=release.manifest.get("source_commit"),
            published_at=release.manifest.get("published_at"),
            fallback_source_count=release.manifest.get("fallback_source_count", 0),
            fallback_table_group_count=release.manifest.get("fallback_table_group_count", 0),
            acceptance_quarantine_count=release.manifest.get("acceptance_quarantine_count", 0),
        )
    except _ReleaseError as error:
        return _response(error.code)


@tool("get_llm_wiki_release_state", parse_docstring=True)
async def get_llm_wiki_release_state() -> str:
    """Return safe metadata about the currently published Regional LLM Wiki release."""
    return await asyncio.to_thread(_release_state)
