"""WeKnora v0.8.3 read-only adapter using DeerFlow's phase 2 contracts.

API/validation approach informed by superbuzzy's feat/weknora-integration;
this package uses current contracts, request-local bindings and shared sources.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from typing import Any

import httpx
from deerflow.knowledge import KnowledgeCapabilities, KnowledgeRequestContext, KnowledgeSource, RetrievalCatalogPage, RetrievalHit, RetrievalResult
from deerflow.knowledge_scope import execution_scope

from .config import Settings, Space, native_id

_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class _Binding:
    space: Space
    key: str = field(repr=False)

    def text(self, value: object, limit: int) -> str:
        return value.replace(self.key, "[REDACTED]").strip()[:limit] if isinstance(value, str) else ""


@dataclass(frozen=True)
class _Dataset:
    binding: _Binding
    native_id: str
    name: str

    @property
    def id(self) -> str:
        # Recomputed from authorized catalogs; no reverse-map database, truncation,
        # key material or ambiguous concatenation. Key rotation preserves IDs.
        identity = [str(self.binding.space.base_url).rstrip("/"), self.binding.space.tenant_id, self.native_id]
        return "wk1_" + hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()


def _items(data: object) -> list[dict[str, Any]]:
    # Go nil slices are encoded as null, including an empty search result.
    if data is None:
        return []
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise RuntimeError("Invalid WeKnora list response")
    return data


def _searchable(document: dict[str, Any]) -> bool:
    return document.get("parse_status") in {"completed", "finalizing"} and document.get("enable_status") == "enabled"


def _pagination(page: int, page_size: int) -> None:
    if type(page) is not int or page < 1 or type(page_size) is not int or not 1 <= page_size <= 100:
        raise ValueError("Invalid catalog pagination")


class WeKnoraProvider:
    capabilities = KnowledgeCapabilities(operations={"search", "sources", "catalog", "documents", "dataset_filter", "document_filter"})

    def __init__(self, config: dict[str, Any], *, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = Settings.model_validate(config)
        self._transport = transport

    def _bindings(self, context: KnowledgeRequestContext) -> list[_Binding]:
        bindings = []
        for space in self.settings.spaces:
            if context.user_id not in space.user_ids or (space.agent_names is not None and context.agent_name not in space.agent_names):
                continue
            key = os.getenv(space.api_key_env, "").strip()
            if not key or not key.isascii() or any(ord(char) < 33 or ord(char) == 127 for char in key):
                raise RuntimeError("WeKnora API key environment variable is missing or invalid")
            bindings.append(_Binding(space, key))
        if not bindings:
            raise PermissionError("No WeKnora space is bound to this user and executing agent")
        return bindings

    async def _request(self, binding: _Binding, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        # Client per request prevents tenant/credential mutation across users and
        # event loops. SSL trust loading runs off-loop. Never follow redirects
        # carrying privileged credentials.
        try:
            async with await asyncio.to_thread(
                httpx.AsyncClient,
                base_url=str(binding.space.base_url).rstrip("/"),
                headers={"X-API-Key": binding.key, "X-Tenant-ID": binding.space.tenant_id},
                timeout=self.settings.timeout,
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                async with client.stream(method, path, **kwargs) as response:
                    if response.status_code in {401, 403}:
                        raise PermissionError("WeKnora denied resource access")
                    if response.status_code == 404:
                        raise FileNotFoundError("WeKnora resource is unavailable")
                    if response.status_code != 200:
                        raise RuntimeError("WeKnora request failed")
                    raw = bytearray()
                    async for part in response.aiter_bytes():
                        raw.extend(part)
                        if len(raw) > _MAX_RESPONSE_BYTES:
                            raise RuntimeError("WeKnora response exceeds the supported size")
                    payload = json.loads(raw)
        except (httpx.HTTPError, ValueError):
            # No raw body, URL, request headers or credential-bearing cause.
            raise RuntimeError("WeKnora request failed or returned invalid JSON") from None
        if not isinstance(payload, dict) or payload.get("success") is not True or "data" not in payload:
            raise RuntimeError("WeKnora returned an unsuccessful response")
        return payload

    async def _datasets(self, context: KnowledgeRequestContext) -> dict[str, _Dataset]:
        result: dict[str, _Dataset] = {}
        for binding in self._bindings(context):
            payload = await self._request(binding, "GET", "/api/v1/knowledge-bases")
            bases = _items(payload["data"])
            allowed = binding.space.knowledge_base_ids
            found = {native_id(base.get("id")) for base in bases}
            if allowed is not None and not set(allowed) <= found:
                raise PermissionError("A configured WeKnora knowledge base is unavailable")
            for base in bases:
                base_id = native_id(base.get("id"))
                if allowed is not None and base_id not in allowed:
                    continue
                dataset = _Dataset(binding, base_id, binding.text(base.get("name"), 500) or "Unnamed knowledge base")
                if dataset.id in result:
                    raise RuntimeError("Duplicate WeKnora knowledge base")
                result[dataset.id] = dataset
                if len(result) > 100:
                    raise RuntimeError("Bind at most 100 knowledge bases using knowledge_base_ids")
        return result

    async def catalog(self, *, context: KnowledgeRequestContext, page: int, page_size: int, search: str) -> RetrievalCatalogPage:
        _pagination(page, page_size)
        datasets = await self._datasets(context)
        items = [{"id": ds.id, "name": ds.name, "selectable": True} for ds in datasets.values() if search.strip().casefold() in ds.name.casefold()]
        start = (page - 1) * page_size
        return RetrievalCatalogPage(items=items[start : start + page_size], total=len(items), page=page, page_size=page_size)

    async def documents(self, dataset_id: str, *, context: KnowledgeRequestContext, page: int, page_size: int, search: str) -> RetrievalCatalogPage:
        _pagination(page, page_size)
        datasets = await self._datasets(context)
        if dataset_id not in datasets:
            raise PermissionError("Selected WeKnora knowledge base is unavailable")
        ds = datasets[dataset_id]
        payload = await self._request(ds.binding, "GET", f"/api/v1/knowledge-bases/{ds.native_id}/knowledge", params={"page": page, "page_size": page_size, "keyword": search})
        items = []
        for doc in _items(payload["data"]):
            if doc.get("knowledge_base_id") != ds.native_id:
                raise PermissionError("WeKnora returned a document outside the requested base")
            items.append({"id": native_id(doc.get("id")), "name": ds.binding.text(doc.get("title") or doc.get("file_name"), 500) or "Unnamed document", "selectable": _searchable(doc)})
        total = payload.get("total")
        if type(total) is not int or total < 0:
            raise RuntimeError("Invalid WeKnora document total")
        return RetrievalCatalogPage(items=items, total=total, page=page, page_size=page_size)

    async def _document(self, ds: _Dataset, document_id: str) -> dict[str, Any]:
        payload = await self._request(ds.binding, "GET", f"/api/v1/knowledge/{native_id(document_id)}")
        doc = payload["data"]
        if not isinstance(doc, dict):
            raise RuntimeError("Invalid WeKnora document response")
        if doc.get("id") != document_id or doc.get("knowledge_base_id") != ds.native_id or not _searchable(doc):
            raise PermissionError("Selected WeKnora document is unavailable or not searchable")
        return doc

    async def search(self, query: str) -> RetrievalResult:
        raise PermissionError("WeKnora retrieval requires a trusted KnowledgeRequestContext")

    async def search_scoped(self, query: str, *, context: KnowledgeRequestContext) -> RetrievalResult:
        scope = execution_scope(context.scope) if context.scope is not None else {"mode": "all"}
        if scope["mode"] == "disabled":
            raise ValueError("Knowledge search is disabled for this turn")
        if not query.strip():
            raise ValueError("Knowledge query must not be empty")
        filters = {item["dataset_id"]: item["document_ids"] for item in scope.get("document_filters", [])}
        for ids in filters.values():
            for document_id in ids:
                native_id(document_id)
        datasets = await self._datasets(context)
        selected = scope["dataset_ids"] if scope["mode"] == "selected" else list(datasets)
        if not set(selected) <= datasets.keys():
            raise PermissionError("Selected WeKnora knowledge base is unavailable")
        documents: dict[tuple[str, str], dict[str, Any]] = {}
        # Validate every constrained resource before any search; no partial
        # success and no unfiltered retry if any selection fails.
        for dataset_id, ids in filters.items():
            for document_id in ids:
                documents[dataset_id, document_id] = await self._document(datasets[dataset_id], document_id)
        hits = []
        for dataset_id in selected:
            if len(hits) >= 100:
                break
            ds = datasets[dataset_id]
            body: dict[str, Any] = {"query_text": query, "match_count": self.settings.match_count, "skip_context_enrichment": True}
            # The KB-bound endpoint authorizes restricted API keys and intersects
            # document IDs with this base. The global knowledge-search endpoint
            # rejects knowledge_ids for such keys; adding base targets there
            # would also widen retrieval through its union semantics.
            if dataset_id in filters:
                body["knowledge_ids"] = filters[dataset_id]
            payload = await self._request(ds.binding, "POST", f"/api/v1/knowledge-bases/{ds.native_id}/hybrid-search", json=body)
            results = _items(payload["data"])
            if len(results) > 100:
                raise RuntimeError("WeKnora response exceeds the supported result limit")
            for item in results:
                if len(hits) >= 100:
                    break
                document_id = native_id(item.get("knowledge_id"))
                if dataset_id in filters and document_id not in filters[dataset_id]:
                    raise PermissionError("WeKnora returned evidence outside the selected documents")
                cache_key = (dataset_id, document_id)
                if cache_key not in documents:
                    documents[cache_key] = await self._document(ds, document_id)
                # SearchResult has no knowledge_base_id; the authoritative detail
                # endpoint above verifies membership even for unfiltered search.
                text = ds.binding.text(item.get("content"), 100_000)
                if not text:
                    continue
                title = ds.binding.text(item.get("knowledge_title") or item.get("knowledge_filename") or documents[cache_key].get("title") or documents[cache_key].get("file_name"), 500)
                source = KnowledgeSource(provider="weknora", title=title, excerpt=text, dataset_name=ds.name) if title else None
                # v0.8.3 gives offsets/chunk indexes, not a verified page or public
                # document URL. Leave locators absent instead of synthesizing them.
                score = item.get("score")
                score = score if type(score) in {float, int} and math.isfinite(score) else None
                hits.append(RetrievalHit(content=text, source=source, score=score))
        return RetrievalResult(hits=hits)
