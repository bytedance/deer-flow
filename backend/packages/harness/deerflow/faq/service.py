"""FAQ retrieval service — calls RAGFlow retrieval API and classifies match level."""

import logging
import time

import httpx

from deerflow.faq.types import FaqItem, FaqQuery, FaqResult

logger = logging.getLogger(__name__)


class FaqService:
    """HTTP client for FAQ retrieval via RAGFlow API.

    Parameters control the search behavior:
    - ``similarity_threshold`` — minimum similarity for results
    - ``vector_similarity_weight`` — weight of vector vs keyword similarity
    - ``rerank_id`` — rerank model ID (service-level config)
    - ``tenant_rerank_id`` — tenant rerank ID (service-level config)

    Per-query parameters (doc_ids, use_kg, cross_languages, keyword, etc.)
    are set on ``FaqQuery`` and passed through to the RAGFlow API.

    Errors (connection, timeout, non-200) degrade gracefully:
    ``best_faq=None, all_matches=[]`` with ``error=True`` in metadata.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 10.0,
        similarity_threshold: float = 0.0,
        vector_similarity_weight: float = 1.0,
        rerank_id: str | None = None,
        tenant_rerank_id: int | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._similarity_threshold = similarity_threshold
        self._vector_similarity_weight = vector_similarity_weight
        self._rerank_id = rerank_id
        self._tenant_rerank_id = tenant_rerank_id

    def _build_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _parse_chunks(self, chunks: list[dict]) -> list[FaqItem]:
        items: list[FaqItem] = []
        for chunk in chunks:
            items.append(
                FaqItem(
                    question=chunk.get("docnm_kwd", "") or chunk.get("document_keyword", ""),
                    answer=(chunk.get("content_with_weight", "") or chunk.get("content", "")).strip(),
                    score=float(chunk.get("similarity", 0)),
                    faq_id=chunk.get("doc_id", "") or chunk.get("document_id", ""),
                )
            )
        items.sort(key=lambda x: x.score, reverse=True)
        return items

    def _build_result(
        self,
        query: FaqQuery,
        items: list[FaqItem],
        elapsed_ms: float,
    ) -> FaqResult:
        best = items[0] if items else None

        result_metadata = {"retrieval_time_ms": round(elapsed_ms, 1)}
        if query.metadata:
            result_metadata["request_metadata"] = query.metadata

        return FaqResult(
            user_question=query.question,
            best_faq=best,
            all_matches=items,
            metadata=result_metadata,
        )

    def _build_error_result(self, query: FaqQuery, elapsed_ms: float) -> FaqResult:
        return FaqResult(
            user_question=query.question,
            best_faq=None,
            all_matches=[],
            metadata={"retrieval_time_ms": round(elapsed_ms, 1), "error": True},
        )

    def _build_payload(self, query: FaqQuery) -> dict:
        payload: dict = {
            "question": query.question,
            "dataset_ids": query.dataset_ids,
            "top_k": query.top_k,
            "similarity_threshold": self._similarity_threshold,
            "vector_similarity_weight": self._vector_similarity_weight,
            "page": query.page,
            "size": query.size,
        }
        if query.context:
            payload["question"] = f"{query.context} {query.question}"
        if query.doc_ids:
            payload["doc_ids"] = query.doc_ids
        if query.use_kg:
            payload["use_kg"] = query.use_kg
        if query.cross_languages:
            payload["cross_languages"] = query.cross_languages
        if query.keyword:
            payload["keyword"] = query.keyword
        if query.search_id is not None:
            payload["search_id"] = query.search_id
        if self._rerank_id is not None:
            payload["rerank_id"] = self._rerank_id
        if self._tenant_rerank_id is not None:
            payload["tenant_rerank_id"] = self._tenant_rerank_id
        return payload

    def _build_url(self, query: FaqQuery) -> str:
        dataset_id = query.dataset_ids[0] if query.dataset_ids else ""
        return f"/api/v1/datasets/{dataset_id}/search"

    def search(self, query: FaqQuery) -> FaqResult:
        """Synchronous FAQ search via RAGFlow ``POST /api/v1/datasets/<id>/search``."""
        start = time.monotonic()
        try:
            url = self._build_url(query)
            payload = self._build_payload(query)
            with httpx.Client(
                base_url=self._base_url,
                headers=self._build_headers(),
                timeout=self._timeout,
            ) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()

            data = resp.json()
            if data.get("code") != 0:
                logger.warning("FAQ RAGFlow error: %s", data.get("message", "Unknown"))
                return self._build_error_result(query, (time.monotonic() - start) * 1000)

            chunks = data.get("data", {}).get("chunks", [])
            items = self._parse_chunks(chunks)
            elapsed_ms = (time.monotonic() - start) * 1000
            return self._build_result(query, items, elapsed_ms)

        except Exception:
            logger.exception("FAQ search failed")
            return self._build_error_result(query, (time.monotonic() - start) * 1000)

    async def asearch(self, query: FaqQuery) -> FaqResult:
        """Async FAQ search via RAGFlow ``POST /api/v1/datasets/<id>/search``."""
        start = time.monotonic()
        try:
            url = self._build_url(query)
            payload = self._build_payload(query)
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._build_headers(),
                timeout=self._timeout,
            ) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()

            data = resp.json()
            if data.get("code") != 0:
                logger.warning("FAQ RAGFlow error: %s", data.get("message", "Unknown"))
                return self._build_error_result(query, (time.monotonic() - start) * 1000)

            chunks = data.get("data", {}).get("chunks", [])
            items = self._parse_chunks(chunks)
            elapsed_ms = (time.monotonic() - start) * 1000
            return self._build_result(query, items, elapsed_ms)

        except Exception:
            logger.exception("FAQ async search failed")
            return self._build_error_result(query, (time.monotonic() - start) * 1000)
