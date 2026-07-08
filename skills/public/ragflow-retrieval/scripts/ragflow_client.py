"""RAGFlow REST client for retrieval + metadata filtering (v0.26.1 compatible).

Endpoints used:
  - POST /api/v1/retrieval              — SDK-compatible retrieval with metadata_condition
  - POST /api/v1/datasets/search        — multi-dataset search with meta_data_filter
  - POST /api/v1/datasets/{id}/search   — single-dataset search (same body shape)
  - GET  /api/v1/datasets               — list datasets
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from citations import (
    build_citations,
    citations_from_retrieval_file,
    render_citations_markdown,
    write_citation_artifacts,
)
from retry import exponential, retry
from routing_utils import (
    SKILL_ENV_FILE,
    compose_model_id,
    from_sandbox_skill_path,
    load_skill_dotenv,
    resolve_ragflow_credentials,
    resolve_run_retrieval_params,
)

# Auto-load skill .env on import (RAGFLOW_BASE_URL / RAGFLOW_API_KEY).
load_skill_dotenv()


class RAGFlowError(Exception):
    """Raised on top-level code != 0 (HTTP 200 but business-level failure)."""


@dataclass
class RetrievalResponse:
    code: int
    chunks: list[dict] = field(default_factory=list)
    total: int = 0
    doc_aggs: list[dict[str, Any]] | dict[str, Any] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class DatasetSummary:
    id: str
    name: str
    description: str = ""
    chunk_count: int = 0
    document_count: int = 0


_TRANSIENT_HTTP = (
    requests.ConnectionError,
    requests.Timeout,
    requests.HTTPError,
)


def _load_json_file(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


class RealRAGFlowClient:
    """Real RAGFlow REST client (API key auth)."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        *,
        config: dict[str, Any] | None = None,
        timeout: int = 60,
    ) -> None:
        url, key = resolve_ragflow_credentials(
            base_url=base_url,
            api_key=api_key,
            config=config,
        )
        if not url:
            raise RAGFlowError(
                "RAGFLOW_BASE_URL is not set "
                f"(set {SKILL_ENV_FILE.name}, export env, or pass --base-url)"
            )
        if not key:
            raise RAGFlowError(
                "RAGFLOW_API_KEY is not set "
                f"(set {SKILL_ENV_FILE.name}, export env, or pass --api-key)"
            )
        self._base_url = url.rstrip("/")
        self._api_root = f"{self._base_url}/api/v1"
        self._api_key = key
        self._timeout = timeout

    @retry(
        max_attempts=3,
        backoff=exponential(base=1.0, max_delay=8.0),
        retry_on=_TRANSIENT_HTTP,
    )
    def retrieve(
        self,
        *,
        question: str,
        dataset_ids: list[str],
        document_ids: list[str] | None = None,
        metadata_condition: dict[str, Any] | None = None,
        page: int = 1,
        page_size: int = 30,
        similarity_threshold: float = 0.2,
        vector_similarity_weight: float = 0.3,
        top_k: int = 1024,
        rerank_id: str | None = None,
        keyword: bool = False,
        cross_languages: list[str] | None = None,
        use_kg: bool = False,
        toc_enhance: bool = False,
        highlight: bool = False,
    ) -> RetrievalResponse:
        """POST /api/v1/retrieval — SDK-compatible endpoint.

        Uses ``metadata_condition`` (document-level manual filter) before vector search.
        See references/metadata_filter.md § metadata_condition.
        """
        payload: dict[str, Any] = {
            "question": question,
            "dataset_ids": dataset_ids,
            "document_ids": document_ids or [],
            "page": page,
            "page_size": page_size,
            "similarity_threshold": similarity_threshold,
            "vector_similarity_weight": vector_similarity_weight,
            "top_k": top_k,
            "keyword": keyword,
            "use_kg": use_kg,
            "toc_enhance": toc_enhance,
            "highlight": highlight,
        }
        if rerank_id:
            payload["rerank_id"] = rerank_id
        if cross_languages:
            payload["cross_languages"] = cross_languages
        if metadata_condition is not None:
            payload["metadata_condition"] = metadata_condition

        resp = requests.post(
            f"{self._api_root}/retrieval",
            json=payload,
            headers=_auth_headers(self._api_key),
            timeout=self._timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        return _parse_retrieval_body(body)

    @retry(
        max_attempts=3,
        backoff=exponential(base=1.0, max_delay=8.0),
        retry_on=_TRANSIENT_HTTP,
    )
    def search(
        self,
        *,
        question: str,
        dataset_ids: list[str],
        meta_data_filter: dict[str, Any] | None = None,
        doc_ids: list[str] | None = None,
        page: int = 1,
        size: int = 30,
        top_k: int = 1024,
        similarity_threshold: float = 0.0,
        vector_similarity_weight: float = 0.3,
        keyword: bool = False,
        cross_languages: list[str] | None = None,
        use_kg: bool = False,
        search_id: str | None = None,
        rerank_id: str | None = None,
    ) -> RetrievalResponse:
        """POST /api/v1/datasets/search — dataset search UI endpoint.

        Supports ``meta_data_filter`` with auto / semi_auto / manual modes (LLM-assisted).
        See references/metadata_filter.md § meta_data_filter.
        """
        payload: dict[str, Any] = {
            "dataset_ids": dataset_ids,
            "question": question,
            "doc_ids": doc_ids or [],
            "page": page,
            "size": size,
            "top_k": top_k,
            "similarity_threshold": similarity_threshold,
            "vector_similarity_weight": vector_similarity_weight,
            "keyword": keyword,
            "use_kg": use_kg,
        }
        if cross_languages:
            payload["cross_languages"] = cross_languages
        if meta_data_filter is not None:
            payload["meta_data_filter"] = meta_data_filter
        if search_id:
            payload["search_id"] = search_id
        if rerank_id:
            payload["rerank_id"] = rerank_id

        if len(dataset_ids) == 1:
            url = f"{self._api_root}/datasets/{dataset_ids[0]}/search"
            payload.pop("dataset_ids", None)
        else:
            url = f"{self._api_root}/datasets/search"

        resp = requests.post(
            url,
            json=payload,
            headers=_auth_headers(self._api_key),
            timeout=self._timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        return _parse_retrieval_body(body)

    @retry(
        max_attempts=3,
        backoff=exponential(base=1.0, max_delay=8.0),
        retry_on=_TRANSIENT_HTTP,
    )
    def list_datasets(
        self,
        *,
        name: str | None = None,
        page: int = 1,
        page_size: int = 30,
    ) -> list[DatasetSummary]:
        params: dict[str, Any] = {
            "page": page,
            "page_size": page_size,
        }
        if name:
            params["name"] = name

        resp = requests.get(
            f"{self._api_root}/datasets",
            params=params,
            headers=_auth_headers(self._api_key),
            timeout=self._timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        code = body.get("code")
        if code != 0:
            raise RAGFlowError(
                f"list_datasets failed: code={code}, msg={body.get('message')}"
            )
        return [
            DatasetSummary(
                id=str(item.get("id", "")),
                name=str(item.get("name", "")),
                description=str(item.get("description") or ""),
                chunk_count=int(item.get("chunk_count") or 0),
                document_count=int(item.get("document_count") or 0),
            )
            for item in body.get("data", [])
        ]

    def list_default_models(self) -> list[dict[str, Any]]:
        """GET /api/v1/models/default — tenant default models (chat, embedding, rerank, …)."""
        resp = requests.get(
            f"{self._api_root}/models/default",
            headers=_auth_headers(self._api_key),
            timeout=self._timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        code = body.get("code")
        if code != 0:
            raise RAGFlowError(
                f"list_default_models failed: code={code}, msg={body.get('message')}"
            )
        data = body.get("data") or {}
        return list(data.get("models") or [])

    def resolve_default_rerank_id(self) -> str | None:
        """Return tenant default rerank model id in RAGFlow API format, or None."""
        for model in self.list_default_models():
            if str(model.get("model_type") or "").lower() != "rerank":
                continue
            if model.get("enable") is False:
                continue
            model_id = compose_model_id(model)
            if model_id:
                return model_id
        return None


class MockRAGFlowClient:
    """Test double backed by a fixture JSON file."""

    def __init__(self, fixture_path: str) -> None:
        self._fixture: dict[str, Any] = json.loads(
            Path(fixture_path).read_text(encoding="utf-8")
        )

    def retrieve(
        self,
        *,
        question: str,
        dataset_ids: list[str],
        metadata_condition: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> RetrievalResponse:
        chunks = list(self._fixture.get("chunks", []))
        if metadata_condition:
            chunks = _mock_filter_chunks(chunks, metadata_condition)
        return RetrievalResponse(
            code=0,
            chunks=chunks,
            total=len(chunks),
            raw={"question": question, "dataset_ids": dataset_ids},
        )

    def search(
        self,
        *,
        question: str,
        dataset_ids: list[str],
        meta_data_filter: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> RetrievalResponse:
        chunks = list(self._fixture.get("chunks", []))
        if meta_data_filter and meta_data_filter.get("method") == "manual":
            condition = _manual_filter_to_metadata_condition(meta_data_filter)
            chunks = _mock_filter_chunks(chunks, condition)
        return RetrievalResponse(
            code=0,
            chunks=chunks,
            total=len(chunks),
            labels=list(self._fixture.get("labels", [])),
            raw={"question": question, "dataset_ids": dataset_ids},
        )

    def list_datasets(self, *, name: str | None = None, **_kwargs: Any) -> list[DatasetSummary]:
        items = [
            DatasetSummary(
                id=str(item.get("id", "")),
                name=str(item.get("name", "")),
                description=str(item.get("description") or ""),
            )
            for item in self._fixture.get("datasets", [])
        ]
        if name:
            items = [d for d in items if name.lower() in d.name.lower()]
        return items

    def list_default_models(self) -> list[dict[str, Any]]:
        return list(self._fixture.get("default_models") or [])

    def resolve_default_rerank_id(self) -> str | None:
        for model in self.list_default_models():
            if str(model.get("model_type") or "").lower() == "rerank":
                model_id = compose_model_id(model)
                if model_id:
                    return model_id
        return None


DEFAULT_MOCK_FIXTURE = (
    Path(__file__).resolve().parents[1] / "example" / "mock_retrieval" / "chunks.json"
)


def _normalize_doc_aggs(raw: Any) -> list[dict[str, Any]] | dict[str, Any]:
    """Accept RAGFlow doc_aggs as list (retrieval API) or dict (search UI)."""
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return raw
    return []


def _parse_retrieval_body(body: dict[str, Any]) -> RetrievalResponse:
    code = body.get("code")
    if code != 0:
        raise RAGFlowError(
            f"RAGFlow request failed: code={code}, msg={body.get('message')}"
        )
    data = body.get("data") or {}
    return RetrievalResponse(
        code=code,
        chunks=list(data.get("chunks") or []),
        total=int(data.get("total") or 0),
        doc_aggs=_normalize_doc_aggs(data.get("doc_aggs")),
        labels=list(data.get("labels") or []),
        raw=body,
    )


def _manual_filter_to_metadata_condition(meta_data_filter: dict[str, Any]) -> dict[str, Any]:
    op_map = {
        "eq": "=",
        "=": "=",
        "ne": "≠",
        "!=": "≠",
        "≠": "≠",
        "gt": ">",
        ">": ">",
        "lt": "<",
        "<": "<",
        "gte": "≥",
        "ge": "≥",
        "≥": "≥",
        "lte": "≤",
        "le": "≤",
        "≤": "≤",
        "contains": "contains",
        "not contains": "not contains",
        "in": "in",
        "not in": "not in",
    }
    conditions = []
    for item in meta_data_filter.get("manual", []):
        conditions.append(
            {
                "name": item.get("key"),
                "comparison_operator": op_map.get(str(item.get("op", "=")), item.get("op")),
                "value": item.get("value"),
            }
        )
    return {"logic": meta_data_filter.get("logic", "and"), "conditions": conditions}


def _mock_filter_chunks(chunks: list[dict], metadata_condition: dict[str, Any]) -> list[dict]:
    conditions = metadata_condition.get("conditions") or []
    if not conditions:
        return chunks
    logic = metadata_condition.get("logic", "and")
    filtered: list[dict] = []
    for chunk in chunks:
        meta = chunk.get("meta_fields") or chunk.get("metadata") or {}
        matched_flags = []
        for cond in conditions:
            key = cond.get("name")
            op = cond.get("comparison_operator", "=")
            value = cond.get("value")
            actual = meta.get(key)
            matched_flags.append(_compare(actual, op, value))
        if logic == "or":
            if any(matched_flags):
                filtered.append(chunk)
        elif all(matched_flags):
            filtered.append(chunk)
    return filtered


def _compare(actual: Any, op: str, expected: Any) -> bool:
    if op in ("=", "is"):
        return str(actual).lower() == str(expected).lower()
    if op in ("≠", "!=", "not is"):
        return str(actual).lower() != str(expected).lower()
    if op == "contains":
        return str(expected).lower() in str(actual).lower()
    if op == "not contains":
        return str(expected).lower() not in str(actual).lower()
    return False


def _response_to_json(resp: RetrievalResponse) -> dict[str, Any]:
    return {
        "code": resp.code,
        "data": {
            "chunks": resp.chunks,
            "total": resp.total,
            "doc_aggs": resp.doc_aggs,
            "labels": resp.labels,
        },
    }


def _stem_paths(out_path: str | None) -> tuple[Path | None, Path | None, Path | None]:
    if not out_path:
        return None, None, None
    base = Path(out_path)
    return base, base.with_name(f"{base.stem}.citations.json"), base.with_name(f"{base.stem}.citations.md")


def _attach_citations(
    payload: dict[str, Any],
    *,
    question: str,
    max_citations: int,
    max_content_chars: int,
    write_sidecars: bool,
    json_out: str | None,
) -> dict[str, Any]:
    chunks = (payload.get("data") or {}).get("chunks") or []
    citations = build_citations(
        chunks,
        max_content_chars=max_content_chars,
        max_items=max_citations,
    )
    payload["citations"] = citations
    if write_sidecars and json_out:
        _, citations_json, citations_md = _stem_paths(json_out)
        write_citation_artifacts(
            citations=citations,
            question=question,
            json_out=citations_json,
            markdown_out=citations_md,
        )
    return payload


def _build_client(args: argparse.Namespace) -> RealRAGFlowClient | MockRAGFlowClient:
    if args.mock:
        fixture = args.mock_fixture or str(DEFAULT_MOCK_FIXTURE)
        return MockRAGFlowClient(fixture)
    return RealRAGFlowClient(base_url=args.base_url, api_key=args.api_key)


def _load_route_file(path: str) -> dict[str, Any]:
    route = json.loads(Path(path).read_text(encoding="utf-8"))
    if not route.get("ok"):
        raise RAGFlowError(f"route file not ok: {route.get('reason') or route.get('message')}")
    if not route.get("dataset_ids"):
        raise RAGFlowError("route file missing dataset_ids")
    return route


def _is_likely_rerank_error_message(message: str) -> bool:
    msg = message.lower()
    markers = (
        "rerank",
        "doesn't exist",
        "not found for model",
        "provider ",
        "lookuperror",
        "is disabled",
        "cannot be used as rerank",
        "internal server error",
    )
    return any(marker in msg for marker in markers)


def _is_likely_rerank_error(exc: RAGFlowError) -> bool:
    return _is_likely_rerank_error_message(str(exc))


def _http_error_detail(exc: requests.HTTPError) -> str:
    resp = exc.response
    if resp is None:
        return str(exc)
    try:
        body = resp.json()
        return str(body.get("message") or body)
    except Exception:
        try:
            return (resp.text or "")[:500]
        except Exception:
            return str(exc)


def _should_retry_without_rerank(exc: BaseException, *, had_rerank_id: bool) -> bool:
    if not had_rerank_id:
        return False
    if isinstance(exc, RAGFlowError):
        return _is_likely_rerank_error(exc)
    if isinstance(exc, requests.HTTPError):
        detail = _http_error_detail(exc)
        if _is_likely_rerank_error_message(detail):
            return True
        status = exc.response.status_code if exc.response is not None else None
        # RAGFlow 0.26.x often returns HTTP 500 for invalid rerank_id instead of code=102.
        return status is not None and status >= 500
    return False


def _resolve_rerank_from_catalog(
    client: RealRAGFlowClient | MockRAGFlowClient,
    rerank_id: str,
) -> str | None:
    """Match user rerank_id against GET /models/default and return the full API id."""
    try:
        list_fn = getattr(client, "list_default_models", None)
        if not callable(list_fn):
            return None
        value = rerank_id.strip()
        value_lower = value.lower()
        for model in list_fn():
            if str(model.get("model_type") or "").lower() != "rerank":
                continue
            if model.get("enable") is False:
                continue
            full_id = compose_model_id(model)
            if not full_id:
                continue
            if full_id.lower() == value_lower:
                return full_id
            name = str(model.get("model_name") or "").strip()
            provider = str(model.get("model_provider") or "").strip()
            if provider:
                two_part = f"{name}@{provider}"
                if two_part.lower() == value_lower:
                    return full_id
            if name.lower() == value_lower:
                return full_id
    except Exception:
        return None
    return None


def _resolve_runtime_rerank_id(
    client: RealRAGFlowClient | MockRAGFlowClient,
    rerank_id: str | None,
) -> str | None:
    if not rerank_id or rerank_id == "auto":
        resolver = getattr(client, "resolve_default_rerank_id", None)
        if callable(resolver):
            return resolver()
        return None
    value = str(rerank_id).strip()
    resolved = _resolve_rerank_from_catalog(client, value)
    if resolved:
        return resolved
    return value


def _call_retrieval(
    client: RealRAGFlowClient | MockRAGFlowClient,
    *,
    common: dict[str, Any],
    filters: dict[str, Any],
    filter_enabled: bool,
    active_path: str | None,
    active_type: str | None,
    mode: str,
    page: int,
    page_size: int,
    rerank_id: str | None,
    highlight: bool,
) -> RetrievalResponse:
    if filter_enabled and active_type and (filters.get("active_filter") or active_path):
        if filters.get("active_filter"):
            filter_data = dict(filters["active_filter"])
        else:
            filter_file = from_sandbox_skill_path(active_path or "")
            filter_data = _load_json_file(str(filter_file))
        if filter_data is None:
            raise RAGFlowError(f"filter missing or invalid: {active_path}")
        if active_type == "meta_data_filter" or mode == "search":
            return client.search(
                **common,
                meta_data_filter=filter_data,
                page=page,
                size=page_size,
                rerank_id=rerank_id,
            )
        return client.retrieve(
            **common,
            metadata_condition=filter_data,
            page=page,
            page_size=page_size,
            rerank_id=rerank_id,
            highlight=highlight,
        )
    if mode == "search":
        return client.search(
            **common,
            page=page,
            size=page_size,
            rerank_id=rerank_id,
        )
    return client.retrieve(
        **common,
        page=page,
        page_size=page_size,
        rerank_id=rerank_id,
        highlight=highlight,
    )


def execute_run(
    route: dict[str, Any],
    *,
    question: str | None = None,
    client: RealRAGFlowClient | MockRAGFlowClient | None = None,
    mock: bool = False,
    mock_fixture: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    page: int = 1,
    page_size: int | None = None,
    recall_top_k: int | None = None,
    top_k: int | None = None,
    similarity_threshold: float | None = None,
    vector_similarity_weight: float = 0.3,
    rerank_id: str | None = None,
    keyword: bool = False,
    use_kg: bool = False,
    highlight: bool = False,
    max_citations: int | None = None,
    citation_content_chars: int = 800,
    write_citation_sidecars: bool = True,
    json_out: str | None = None,
) -> dict[str, Any]:
    """Run retrieval/search from a resolved route payload (no route.json file required)."""
    if not route.get("ok"):
        raise RAGFlowError(f"route not ok: {route.get('reason') or route.get('message')}")
    if not route.get("dataset_ids"):
        raise RAGFlowError("route missing dataset_ids")

    resolved_question = question or route.get("question") or ""
    if not resolved_question:
        raise RAGFlowError("question is required")

    retrieval_params = resolve_run_retrieval_params(
        route,
        recall_top_k=recall_top_k if recall_top_k is not None else top_k,
        page_size=page_size,
        max_citations=max_citations,
        similarity_threshold=similarity_threshold,
    )
    effective_recall_top_k = int(retrieval_params["recall_top_k"])
    effective_page_size = int(retrieval_params["page_size"])
    effective_max_citations = int(retrieval_params["max_citations"])
    effective_similarity_threshold = float(retrieval_params["similarity_threshold"])

    if client is None:
        if mock:
            fixture = mock_fixture or str(DEFAULT_MOCK_FIXTURE)
            client = MockRAGFlowClient(fixture)
        else:
            client = RealRAGFlowClient(base_url=base_url, api_key=api_key)

    dataset_ids = list(route["dataset_ids"])
    filters = route.get("filters") or {}
    filter_enabled = bool(filters.get("filter_enabled"))
    active_path = filters.get("active_filter_path")
    active_type = filters.get("active_filter_type")
    mode = filters.get("mode", "retrieve")

    common = {
        "question": resolved_question,
        "dataset_ids": dataset_ids,
        "top_k": effective_recall_top_k,
        "similarity_threshold": effective_similarity_threshold,
        "vector_similarity_weight": vector_similarity_weight,
        "keyword": keyword,
        "use_kg": use_kg,
    }

    effective_rerank_id = _resolve_runtime_rerank_id(
        client,
        rerank_id or route.get("rerank_id"),
    )
    rerank_fallback = False
    requested_rerank_id = effective_rerank_id

    try:
        resp = _call_retrieval(
            client,
            common=common,
            filters=filters,
            filter_enabled=filter_enabled,
            active_path=active_path,
            active_type=active_type,
            mode=mode,
            page=page,
            page_size=effective_page_size,
            rerank_id=effective_rerank_id,
            highlight=highlight,
        )
    except (RAGFlowError, requests.HTTPError) as exc:
        if _should_retry_without_rerank(exc, had_rerank_id=bool(effective_rerank_id)):
            resp = _call_retrieval(
                client,
                common=common,
                filters=filters,
                filter_enabled=filter_enabled,
                active_path=active_path,
                active_type=active_type,
                mode=mode,
                page=page,
                page_size=effective_page_size,
                rerank_id=None,
                highlight=highlight,
            )
            rerank_fallback = True
            effective_rerank_id = None
        else:
            raise

    payload = _response_to_json(resp)
    payload["route"] = {
        "intent": route.get("intent"),
        "label": route.get("label"),
        "rerank_id": effective_rerank_id,
        "requested_rerank_id": requested_rerank_id,
        "rerank_fallback": rerank_fallback,
        "recall_top_k": effective_recall_top_k,
        "page_size": effective_page_size,
        "filters": filters,
    }
    return _attach_citations(
        payload,
        question=resolved_question,
        max_citations=effective_max_citations,
        max_content_chars=citation_content_chars,
        write_sidecars=write_citation_sidecars,
        json_out=json_out,
    )


def build_run_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Compact stdout payload for agent (avoids dumping full chunk bodies)."""
    route = payload.get("route") or {}
    filters = route.get("filters") or {}
    dept_sel = filters.get("department_selection") or {}
    selected = dept_sel.get("selected_departments") or []
    dept_labels = [str(d.get("label") or d.get("id", "")) for d in selected]
    citations = payload.get("citations") or []
    return {
        "ok": payload.get("code") == 0,
        "intent": route.get("intent"),
        "label": route.get("label"),
        "departments": dept_labels or ["全库"],
        "rerank_id": route.get("rerank_id"),
        "recall_top_k": route.get("recall_top_k"),
        "page_size": route.get("page_size"),
        "total": (payload.get("data") or {}).get("total", 0),
        "citation_count": len(citations),
        "citations": citations,
    }


def _cmd_run(args: argparse.Namespace) -> int:
    """Run retrieval using dataset + filter paths from route.json (no manual filter paths)."""
    route = _load_route_file(args.route)
    question = args.question or route.get("question") or ""
    payload = execute_run(
        route,
        question=question,
        mock=args.mock,
        mock_fixture=args.mock_fixture,
        base_url=args.base_url,
        api_key=args.api_key,
        page=args.page,
        page_size=args.page_size,
        recall_top_k=args.recall_top_k if args.recall_top_k is not None else args.top_k,
        similarity_threshold=args.similarity_threshold,
        vector_similarity_weight=args.vector_similarity_weight,
        rerank_id=args.rerank_id or route.get("rerank_id"),
        keyword=args.keyword,
        use_kg=args.use_kg,
        highlight=args.highlight,
        max_citations=args.max_citations,
        citation_content_chars=args.citation_content_chars,
        write_citation_sidecars=not args.no_citation_files,
        json_out=args.out,
    )
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    if args.print_citations_md and payload.get("citations"):
        print("\n--- citations markdown ---\n")
        print(render_citations_markdown(payload["citations"], question=question))
    if args.quiet:
        print(json.dumps(build_run_summary(payload), ensure_ascii=False, indent=2))
    else:
        print(text)
    return 0


def _cmd_retrieve(args: argparse.Namespace) -> int:
    client = _build_client(args)
    metadata_condition = _load_json_file(args.metadata_condition)
    resp = client.retrieve(
        question=args.question,
        dataset_ids=args.dataset_ids,
        document_ids=args.document_ids,
        metadata_condition=metadata_condition,
        page=args.page,
        page_size=args.page_size,
        top_k=args.top_k,
        similarity_threshold=args.similarity_threshold,
        vector_similarity_weight=args.vector_similarity_weight,
        keyword=args.keyword,
        rerank_id=args.rerank_id,
        use_kg=args.use_kg,
        toc_enhance=args.toc_enhance,
        highlight=args.highlight,
    )
    payload = _response_to_json(resp)
    payload = _attach_citations(
        payload,
        question=args.question,
        max_citations=args.max_citations or 10,
        max_content_chars=args.citation_content_chars,
        write_sidecars=not args.no_citation_files,
        json_out=args.out,
    )
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    client = _build_client(args)
    meta_data_filter = _load_json_file(args.meta_data_filter)
    resp = client.search(
        question=args.question,
        dataset_ids=args.dataset_ids,
        meta_data_filter=meta_data_filter,
        doc_ids=args.doc_ids,
        page=args.page,
        size=args.page_size,
        top_k=args.top_k,
        similarity_threshold=args.similarity_threshold,
        vector_similarity_weight=args.vector_similarity_weight,
        keyword=args.keyword,
        search_id=args.search_id,
        rerank_id=args.rerank_id,
        use_kg=args.use_kg,
    )
    payload = _response_to_json(resp)
    payload = _attach_citations(
        payload,
        question=args.question,
        max_citations=args.max_citations or 10,
        max_content_chars=args.citation_content_chars,
        write_sidecars=not args.no_citation_files,
        json_out=args.out,
    )
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


def _cmd_format_citations(args: argparse.Namespace) -> int:
    citations = citations_from_retrieval_file(
        args.input,
        max_content_chars=args.citation_content_chars,
        max_items=args.max_citations or 10,
    )
    write_citation_artifacts(
        citations=citations,
        question=args.question or "",
        json_out=args.citations_json_out,
        markdown_out=args.citations_md_out or (args.out if args.out and str(args.out).endswith(".md") else None),
    )
    payload = {"citations": citations}
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out and args.out.endswith(".json"):
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


def _cmd_list_datasets(args: argparse.Namespace) -> int:
    client = _build_client(args)
    datasets = client.list_datasets(name=args.name, page=args.page, page_size=args.page_size)
    payload = {
        "code": 0,
        "data": [
            {
                "id": d.id,
                "name": d.name,
                "description": d.description,
                "chunk_count": d.chunk_count,
                "document_count": d.document_count,
            }
            for d in datasets
        ],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


def _cmd_list_models(args: argparse.Namespace) -> int:
    client = _build_client(args)
    models = client.list_default_models()
    rerank_id = client.resolve_default_rerank_id()
    payload = {
        "code": 0,
        "data": {
            "models": models,
            "default_rerank_id": rerank_id,
        },
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


def _add_citation_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--max-citations",
        type=int,
        default=None,
        help="Max citation items extracted from retrieval chunks",
    )
    parser.add_argument(
        "--citation-content-chars",
        type=int,
        default=800,
        help="Max chars per citation snippet",
    )
    parser.add_argument(
        "--no-citation-files",
        action="store_true",
        help="Do not write *.citations.json / *.citations.md sidecars",
    )


def _add_global_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mock", action="store_true", help="Use bundled mock fixture")
    parser.add_argument(
        "--mock-fixture",
        help="Path to mock fixture JSON (default: example/mock_retrieval/chunks.json)",
    )
    parser.add_argument("--base-url", help="Override RAGFLOW_BASE_URL")
    parser.add_argument("--api-key", help="Override RAGFLOW_API_KEY")
    parser.add_argument("--out", help="Write JSON output to this path")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RAGFlow retrieval + metadata filter client")
    _add_global_args(parser)

    sub = parser.add_subparsers(dest="command", required=True)

    p_retrieve = sub.add_parser("retrieve", help="POST /api/v1/retrieval (metadata_condition)")
    _add_global_args(p_retrieve)
    p_retrieve.add_argument("--question", required=True)
    p_retrieve.add_argument("--dataset-ids", nargs="+", required=True)
    p_retrieve.add_argument("--document-ids", nargs="*", default=[])
    p_retrieve.add_argument(
        "--metadata-condition",
        help="JSON file with metadata_condition (manual document filter)",
    )
    p_retrieve.add_argument("--page", type=int, default=1)
    p_retrieve.add_argument("--page-size", type=int, default=30)
    p_retrieve.add_argument("--top-k", type=int, default=1024)
    p_retrieve.add_argument("--similarity-threshold", type=float, default=0.2)
    p_retrieve.add_argument("--vector-similarity-weight", type=float, default=0.3)
    p_retrieve.add_argument("--rerank-id")
    p_retrieve.add_argument("--keyword", action="store_true")
    p_retrieve.add_argument("--use-kg", action="store_true")
    p_retrieve.add_argument("--toc-enhance", action="store_true")
    p_retrieve.add_argument("--highlight", action="store_true")
    _add_citation_args(p_retrieve)
    p_retrieve.set_defaults(func=_cmd_retrieve)

    p_search = sub.add_parser("search", help="POST /api/v1/datasets/search (meta_data_filter)")
    _add_global_args(p_search)
    p_search.add_argument("--question", required=True)
    p_search.add_argument("--dataset-ids", nargs="+", required=True)
    p_search.add_argument(
        "--meta-data-filter",
        help="JSON file with meta_data_filter (auto/semi_auto/manual)",
    )
    p_search.add_argument("--doc-ids", nargs="*", default=[])
    p_search.add_argument("--page", type=int, default=1)
    p_search.add_argument("--page-size", type=int, default=30)
    p_search.add_argument("--top-k", type=int, default=1024)
    p_search.add_argument("--similarity-threshold", type=float, default=0.0)
    p_search.add_argument("--vector-similarity-weight", type=float, default=0.3)
    p_search.add_argument("--search-id")
    p_search.add_argument("--rerank-id")
    p_search.add_argument("--keyword", action="store_true")
    p_search.add_argument("--use-kg", action="store_true")
    _add_citation_args(p_search)
    p_search.set_defaults(func=_cmd_search)

    p_run = sub.add_parser(
        "run",
        help="Retrieve/search using route.json (auto dataset + metadata filter paths)",
    )
    _add_global_args(p_run)
    p_run.add_argument(
        "--route",
        required=True,
        help="Path to route.json from route_intent.py resolve",
    )
    p_run.add_argument("--question", help="Override question in route.json")
    p_run.add_argument("--page", type=int, default=1)
    p_run.add_argument(
        "--page-size",
        type=int,
        default=None,
        help="Final chunks returned after rerank (default: route.json page_size or 10)",
    )
    p_run.add_argument(
        "--recall-top-k",
        type=int,
        default=None,
        help="Vector recall candidate pool before rerank (default: route.json recall_top_k or 64)",
    )
    p_run.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="Alias for --recall-top-k",
    )
    p_run.add_argument("--similarity-threshold", type=float, default=None)
    p_run.add_argument("--vector-similarity-weight", type=float, default=0.3)
    p_run.add_argument("--rerank-id")
    p_run.add_argument("--keyword", action="store_true")
    p_run.add_argument("--use-kg", action="store_true")
    p_run.add_argument("--highlight", action="store_true")
    p_run.add_argument(
        "--print-citations-md",
        action="store_true",
        help="Also print citations markdown to stdout",
    )
    p_run.add_argument(
        "--quiet",
        action="store_true",
        help="Print compact summary + citations only (not full retrieval JSON)",
    )
    _add_citation_args(p_run)
    p_run.set_defaults(func=_cmd_run)

    p_format = sub.add_parser(
        "format-citations",
        help="Extract citations markdown/json from an existing retrieval output file",
    )
    _add_global_args(p_format)
    p_format.add_argument("--input", required=True, help="Retrieval JSON from run/retrieve/search")
    p_format.add_argument("--question", default="", help="Original question for citations header")
    p_format.add_argument("--citations-json-out", help="Write citations JSON path")
    p_format.add_argument("--citations-md-out", help="Write citations markdown path")
    _add_citation_args(p_format)
    p_format.set_defaults(func=_cmd_format_citations)

    p_list = sub.add_parser("list-datasets", help="GET /api/v1/datasets")
    _add_global_args(p_list)
    p_list.add_argument("--name")
    p_list.add_argument("--page", type=int, default=1)
    p_list.add_argument("--page-size", type=int, default=30)
    p_list.set_defaults(func=_cmd_list_datasets)

    p_models = sub.add_parser("list-models", help="GET /api/v1/models/default (incl. rerank id)")
    _add_global_args(p_models)
    p_models.set_defaults(func=_cmd_list_models)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except RAGFlowError as exc:
        print(json.dumps({"code": -1, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
