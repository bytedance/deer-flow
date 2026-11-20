"""One synthetic corpus exercising the public read-only knowledge contract."""

from deerflow.knowledge import KnowledgeCapabilities, KnowledgeRequestContext, KnowledgeSource, RetrievalCatalogPage, RetrievalHit, RetrievalResult
from deerflow_extension_api import extension

_DATASET = "synthetic-guides"
_DOCUMENT = "demo-note"
_TITLE = "Synthetic knowledge note"
_TEXT = "The fictional Cedar team keeps its invented demonstration notes in a read-only knowledge base. This text is synthetic test evidence."


class SyntheticKnowledgeProvider:
    capabilities = KnowledgeCapabilities(operations={"search", "sources", "catalog", "documents", "dataset_filter", "document_filter"})

    async def search(self, query: str) -> RetrievalResult:
        hits = []
        if query.strip().casefold() in (_TITLE + " " + _TEXT).casefold():
            source = KnowledgeSource(provider="synthetic-example", title=_TITLE, excerpt=_TEXT, dataset_name="Synthetic guides")
            hits.append(RetrievalHit(content=_TEXT, source=source))
        return RetrievalResult(hits=hits)

    async def search_scoped(self, query: str, *, context: KnowledgeRequestContext) -> RetrievalResult:
        scope = context.scope
        if scope is not None:
            if scope["mode"] == "disabled":
                raise ValueError("Knowledge search is disabled")
            if scope["mode"] == "selected":
                if scope["dataset_ids"] != [_DATASET]:
                    raise PermissionError("Selected dataset is unavailable")
                for item in scope.get("document_filters", []):
                    if item["dataset_id"] != _DATASET or item["document_ids"] != [_DOCUMENT]:
                        raise PermissionError("Selected document is unavailable")
        return await self.search(query)

    async def catalog(self, *, context: KnowledgeRequestContext, page: int, page_size: int, search: str) -> RetrievalCatalogPage:
        items = [{"id": _DATASET, "name": "Synthetic guides", "selectable": True}] if search.strip().casefold() in "synthetic guides" else []
        start = (page - 1) * page_size
        return RetrievalCatalogPage(items=items[start : start + page_size], page=page, page_size=page_size, total=len(items))

    async def documents(self, dataset_id: str, *, context: KnowledgeRequestContext, page: int, page_size: int, search: str) -> RetrievalCatalogPage:
        if dataset_id != _DATASET:
            raise FileNotFoundError("Dataset unavailable")
        items = [{"id": _DOCUMENT, "name": _TITLE, "selectable": True}] if search.strip().casefold() in _TITLE.casefold() else []
        start = (page - 1) * page_size
        return RetrievalCatalogPage(items=items[start : start + page_size], page=page, page_size=page_size, total=len(items))


@extension(api="0.2.7", name="knowledge-example")
def install(registry, config):
    if not registry.knowledge_provider("synthetic-example", SyntheticKnowledgeProvider()):
        raise RuntimeError("This host does not support knowledge provider registration")
