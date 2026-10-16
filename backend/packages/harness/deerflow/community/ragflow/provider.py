"""Compatibility adapter for RAGFlow read-only catalog and scope operations."""

from typing import Any

from deerflow.knowledge import KnowledgeRequestContext, RetrievalCatalogItem, RetrievalCatalogPage, RetrievalResult
from deerflow.knowledge.sources import redact_strings

from .client import RAGFlowProtocolError
from .formatting import CAPABILITIES, normalize_retrieval_result
from .tools import (
    _api_key,
    _group_scoped_datasets,
    _retrieve_dataset_groups,
    _validate_document_filters,
    build_ragflow_retrieval_client,
    resolve_ragflow_datasets,
    resolve_ragflow_retrieval_settings,
)


class RAGFlowKnowledgeProvider:
    capabilities = CAPABILITIES

    def __init__(self, app_config: Any):
        # Construction performs no I/O; credentials remain in the adapter.
        self.settings, _ = resolve_ragflow_retrieval_settings(app_config)
        if self.settings is None:
            raise LookupError("Knowledge retrieval is not configured")

    async def search(self, query: str) -> RetrievalResult:
        return await self._search(query, None)

    async def search_scoped(self, query: str, *, context: KnowledgeRequestContext) -> RetrievalResult:
        return await self._search(query, context.scope)

    async def _search(self, query: str, scope: dict | None) -> RetrievalResult:
        from deerflow.knowledge.providers import validate_scope_capabilities

        if scope is not None:
            scope = validate_scope_capabilities(scope, self.capabilities)
            if scope["mode"] == "disabled":
                raise ValueError("Knowledge search is disabled for this turn")
        selected = scope is not None and scope["mode"] == "selected"
        client = build_ragflow_retrieval_client(self.settings)
        datasets, error = await resolve_ragflow_datasets(client, self.settings, scope["dataset_ids"] if selected else None)
        if not datasets or error:
            raise PermissionError("Knowledge scope is unavailable")
        filters, error = await _validate_document_filters(client, list(scope.get("document_filters") or []) if selected else [])
        if error:
            raise PermissionError("Knowledge scope is unavailable")
        groups = _group_scoped_datasets(datasets, filters or {})
        if not groups:
            return RetrievalResult()
        result = await _retrieve_dataset_groups(client, self.settings, query, groups)
        key = _api_key(self.settings)
        return normalize_retrieval_result(redact_strings(result, key), dataset_names_by_id=redact_strings({item.dataset_id: item.name for item in datasets}, key))

    async def catalog(self, *, context: KnowledgeRequestContext, page: int, page_size: int, search: str) -> RetrievalCatalogPage:
        client = build_ragflow_retrieval_client(self.settings)
        datasets, error = await resolve_ragflow_datasets(client, self.settings)
        if datasets is None or error:
            raise ValueError("The configured knowledge-base scope is unavailable")
        needle = search.strip().casefold()
        items = [RetrievalCatalogItem(id=item.dataset_id, name=item.name, selectable=bool(item.embedding_model) and item.chunk_count != 0) for item in datasets if not needle or needle in item.name.casefold()]
        start = (page - 1) * page_size
        return RetrievalCatalogPage(items=items[start : start + page_size], page=page, page_size=page_size, total=len(items))

    async def documents(self, dataset_id: str, *, context: KnowledgeRequestContext, page: int, page_size: int, search: str) -> RetrievalCatalogPage:
        if self.settings.datasets is not None and dataset_id not in self.settings.datasets:
            raise FileNotFoundError("Knowledge base not found")
        client = build_ragflow_retrieval_client(self.settings)
        datasets, error = await resolve_ragflow_datasets(client, self.settings, [dataset_id])
        if not datasets or error:
            raise FileNotFoundError("Knowledge base not found")
        params = [("page", str(page)), ("page_size", str(page_size))]
        if search.strip():
            params.append(("keywords", search.strip()))
        payload = await client.list_documents(dataset_id, params=params)
        data = payload.get("data")
        docs = data.get("docs") if isinstance(data, dict) else None
        if not isinstance(docs, list):
            raise RAGFlowProtocolError("Invalid document list")
        items = []
        for document in docs:
            if not isinstance(document, dict):
                continue
            document_id = document.get("id")
            if not isinstance(document_id, str) or not document_id.strip():
                continue
            count = document.get("chunk_count")
            searchable = isinstance(count, int) and not isinstance(count, bool) and count > 0
            items.append(RetrievalCatalogItem(id=document_id.strip(), name=str(document.get("name") or "Unnamed document"), selectable=document.get("run") == "DONE" and searchable))
        total = data.get("total")
        if not isinstance(total, int) or isinstance(total, bool) or total < 0:
            total = len(items)
        return RetrievalCatalogPage(items=items, page=page, page_size=page_size, total=total)
