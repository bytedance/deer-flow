"""Read-only Agent tool for operator-scoped RAGFlow knowledge retrieval."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from langchain_core.tools import StructuredTool
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

from deerflow.config import get_app_config
from deerflow.knowledge_scope import (
    KNOWLEDGE_SCOPE_RUNTIME_KEY,
    canonicalize_knowledge_scope,
    execution_scope,
)
from deerflow.tools.types import Runtime

from .client import RAGFlowAPIError, RAGFlowClient, RAGFlowConnectionError, RAGFlowProtocolError
from .formatting import format_retrieval_result

logger = logging.getLogger(__name__)

_warned: set[str] = set()
_RAGFLOW_UUID_PATTERN = re.compile(r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{32}|[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12})(?![0-9A-Fa-f])")
_MAX_PARALLEL_RAGFLOW_REQUESTS = 4
_NO_RELEVANT_CONTENT = "No relevant content found."


@dataclass(frozen=True, slots=True)
class _ResolvedDataset:
    dataset_id: str
    name: str
    embedding_model: str
    chunk_count: int | None


@dataclass(frozen=True, slots=True)
class _RetrievalGroup:
    embedding_model: str
    dataset_ids: list[str]
    document_ids: list[str] | None


class _RAGFlowRetrievalSettings(BaseModel):
    """Validated provider settings stored on the knowledge_search tool entry."""

    model_config = ConfigDict(validate_default=True)

    datasets: list[str] | None = Field(default=None, max_length=100)
    base_url: AnyHttpUrl = Field(default="http://localhost:9380")
    api_key: SecretStr | None = Field(default=None)
    timeout: float = Field(default=30, gt=0, le=600)
    page_size: int = Field(default=8, ge=1, le=100)
    similarity_threshold: float = Field(default=0.2, ge=0, le=1)
    vector_similarity_weight: float = Field(default=0.3, ge=0, le=1)
    top_k: int = Field(default=256, ge=1, le=1024)
    max_chars_per_chunk: int = Field(default=800, ge=1, le=100_000)
    max_total_chars: int = Field(default=8000, ge=1, le=1_000_000)

    @field_validator("datasets")
    @classmethod
    def _normalize_dataset_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("datasets must not be empty when configured; omit it to search all accessible datasets")
        normalized: list[str] = []
        seen: set[str] = set()
        for dataset_id in value:
            clean_id = dataset_id.strip()
            if not clean_id or len(clean_id) > 256:
                raise ValueError("dataset IDs must contain between 1 and 256 characters")
            if clean_id not in seen:
                normalized.append(clean_id)
                seen.add(clean_id)
        return normalized

    @field_validator("base_url")
    @classmethod
    def _reject_url_userinfo(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.username is not None or value.password is not None:
            raise ValueError("base_url must not contain username or password information")
        return value


def _api_key(settings: _RAGFlowRetrievalSettings) -> str | None:
    value = settings.api_key
    if isinstance(value, SecretStr):
        value = value.get_secret_value()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _redact_api_key(value: object, api_key: str | None) -> str:
    text = str(value)
    if api_key:
        text = text.replace(api_key, "[REDACTED]")
    return text


def _redact_error(value: object, api_key: str | None) -> str:
    """Redact provider credentials and opaque dataset IDs on error paths."""
    return _RAGFLOW_UUID_PATTERN.sub("[DATASET_ID]", _redact_api_key(value, api_key))


def _settings_from_extra(extra: Mapping[str, object]) -> _RAGFlowRetrievalSettings:
    return _RAGFlowRetrievalSettings.model_validate(dict(extra))


def _settings_or_error(app_config: Any | None = None) -> tuple[_RAGFlowRetrievalSettings | None, str | None]:
    app_config = app_config or get_app_config()
    get_tool_config = getattr(app_config, "get_tool_config", lambda _name: None)
    tool_config = get_tool_config("knowledge_search")
    if tool_config is None:
        return None, "Error: knowledge_search is not configured; add its RAGFlow settings to the tools list in config.yaml."
    tool_values = dict(getattr(tool_config, "model_extra", None) or {})
    try:
        settings = _settings_from_extra(tool_values)
    except ValidationError:
        logger.warning("RAGFlow knowledge_search tool configuration is invalid")
        return None, "Error: Invalid RAGFlow settings for knowledge_search; check config.yaml."
    if not _api_key(settings):
        if "api_key" not in _warned:
            _warned.add("api_key")
            logger.warning("RAGFlow API key is not configured; set knowledge_search.api_key in config.yaml, preferably via $RAGFLOW_API_KEY.")
        return None, "Error: RAGFlow API key is not configured; set knowledge_search.api_key in config.yaml (prefer $RAGFLOW_API_KEY)."
    return settings, None


def _build_client(settings: _RAGFlowRetrievalSettings) -> RAGFlowClient:
    api_key = _api_key(settings)
    if api_key is None:  # Guarded by _settings_or_error; keeps this helper total.
        raise ValueError("RAGFlow API key is missing")
    return RAGFlowClient(
        base_url=str(settings.base_url).rstrip("/"),
        api_key=api_key,
        timeout=settings.timeout,
    )


def _tool_error(exc: Exception, settings: _RAGFlowRetrievalSettings) -> str:
    key = _api_key(settings)
    safe_detail = _redact_error(exc, key)
    base_url = _redact_error(str(settings.base_url).rstrip("/"), key)

    if isinstance(exc, RAGFlowAPIError):
        logger.warning("RAGFlow API rejected a read-only tool request (code=%s)", exc.code)
        return f"Error: {safe_detail}"
    if isinstance(exc, RAGFlowConnectionError):
        logger.warning("RAGFlow connection failed for %s (%s)", base_url, type(exc).__name__)
        return f"Error: Unable to connect to RAGFlow ({base_url}): {safe_detail}"
    if isinstance(exc, RAGFlowProtocolError):
        logger.warning("RAGFlow returned an invalid response for a read-only tool request (%s)", type(exc).__name__)
        return f"Error: RAGFlow request failed: {safe_detail}"

    logger.warning("Unexpected RAGFlow read-only tool failure (%s)", type(exc).__name__)
    return "Error: An unexpected RAGFlow retrieval error occurred; try again later."


def _resolved_dataset(dataset: Mapping[str, object], *, expected_id: str | None = None) -> _ResolvedDataset | None:
    dataset_id = dataset.get("id")
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        return None
    clean_id = dataset_id.strip()
    if expected_id is not None and clean_id != expected_id:
        return None

    name = dataset.get("name")
    raw_chunk_count = dataset.get("chunk_count")
    chunk_count = raw_chunk_count if isinstance(raw_chunk_count, int) and not isinstance(raw_chunk_count, bool) and raw_chunk_count >= 0 else None
    embedding_model = dataset.get("embedding_model")
    if not isinstance(embedding_model, str) or not embedding_model.strip():
        if chunk_count == 0:
            warning_key = f"empty_embedding:{clean_id}"
            if warning_key not in _warned:
                _warned.add(warning_key)
                logger.warning("Skipping empty RAGFlow dataset without embedding model metadata (dataset_id=%s)", clean_id)
            embedding_model = ""
        else:
            raise RAGFlowProtocolError("RAGFlow returned a searchable dataset without embedding model metadata.")
    return _ResolvedDataset(
        dataset_id=clean_id,
        name=str(name).strip() if name else "Unknown dataset",
        embedding_model=embedding_model.strip(),
        chunk_count=chunk_count,
    )


def _current_dataset(datasets: list[dict], bound_id: str) -> _ResolvedDataset | None:
    for dataset in datasets:
        resolved = _resolved_dataset(dataset, expected_id=bound_id)
        if resolved is not None:
            return resolved
    return None


def _ordinal(value: int) -> str:
    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def _missing_dataset_error(position: int) -> str:
    return f"Error: The {_ordinal(position)} entry of knowledge_search.datasets was not found or is inaccessible; check config.yaml."


def _log_missing_dataset(*, position: int, dataset_id: str, code: object = None) -> None:
    logger.warning(
        "Configured RAGFlow dataset binding could not be resolved (position=%d, dataset_id=%s, code=%s)",
        position,
        dataset_id,
        code,
    )


async def _bounded_gather[InputT, ResultT](
    items: list[InputT],
    operation: Callable[[InputT], Awaitable[ResultT]],
) -> list[ResultT]:
    """Run provider requests concurrently while preserving input order."""
    semaphore = asyncio.Semaphore(_MAX_PARALLEL_RAGFLOW_REQUESTS)

    async def run(item: InputT) -> ResultT:
        async with semaphore:
            return await operation(item)

    raw_results = await asyncio.gather(
        *(run(item) for item in items),
        return_exceptions=True,
    )
    results: list[ResultT] = []
    for result in raw_results:
        if isinstance(result, BaseException):
            raise result
        results.append(cast(ResultT, result))
    return results


async def _list_datasets_by_id(
    client: RAGFlowClient,
    dataset_ids: list[str],
) -> list[list[dict]]:
    async def list_dataset(dataset_id: str) -> list[dict]:
        return await client.list_datasets(dataset_id=dataset_id)

    return await _bounded_gather(dataset_ids, list_dataset)


async def _resolve_datasets(
    client: RAGFlowClient,
    settings: _RAGFlowRetrievalSettings,
    requested_dataset_ids: list[str] | None = None,
) -> tuple[list[_ResolvedDataset] | None, str | None]:
    if requested_dataset_ids is not None:
        if settings.datasets is not None:
            operator_allowlist = set(settings.datasets)
            if any(dataset_id not in operator_allowlist for dataset_id in requested_dataset_ids):
                logger.warning("Selected RAGFlow scope contains a dataset outside the operator allowlist")
                return (
                    None,
                    "Error: The selected knowledge scope is no longer available; choose the knowledge bases again.",
                )
        dataset_results = await _list_datasets_by_id(client, requested_dataset_ids)
        resolved_datasets: list[_ResolvedDataset] = []
        for dataset_id, datasets in zip(requested_dataset_ids, dataset_results, strict=True):
            resolved = _current_dataset(datasets, dataset_id)
            if resolved is None:
                logger.warning("Selected RAGFlow dataset is missing or inaccessible (dataset_id=%s)", dataset_id)
                return (
                    None,
                    "Error: The selected knowledge scope is no longer available; choose the knowledge bases again.",
                )
            resolved_datasets.append(resolved)
        return resolved_datasets, None

    if settings.datasets is None:
        datasets = await client.list_datasets()
        resolved_by_id: dict[str, _ResolvedDataset] = {}
        for dataset in datasets:
            resolved = _resolved_dataset(dataset)
            if resolved is None:
                continue
            resolved_by_id.setdefault(resolved.dataset_id, resolved)

        if not resolved_by_id:
            return (
                None,
                "Error: No accessible RAGFlow datasets were found; configure knowledge_search.datasets or add a dataset in RAGFlow.",
            )
        return list(resolved_by_id.values()), None

    dataset_results = await _list_datasets_by_id(client, settings.datasets)
    resolved_datasets: list[_ResolvedDataset] = []
    for position, (bound_id, datasets) in enumerate(
        zip(settings.datasets, dataset_results, strict=True),
        start=1,
    ):
        resolved = _current_dataset(datasets, bound_id)
        if resolved is None:
            _log_missing_dataset(position=position, dataset_id=bound_id)
            return None, _missing_dataset_error(position)
        resolved_datasets.append(resolved)

    return resolved_datasets, None


def resolve_ragflow_retrieval_settings(
    app_config: Any,
) -> tuple[_RAGFlowRetrievalSettings | None, str | None]:
    """Resolve the provider settings shared by tools and safe catalog APIs."""
    return _settings_or_error(app_config)


def build_ragflow_retrieval_client(
    settings: _RAGFlowRetrievalSettings,
) -> RAGFlowClient:
    return _build_client(settings)


async def resolve_ragflow_datasets(
    client: RAGFlowClient,
    settings: _RAGFlowRetrievalSettings,
    requested_dataset_ids: list[str] | None = None,
) -> tuple[list[_ResolvedDataset] | None, str | None]:
    """Apply the operator allowlist and live RAGFlow dataset resolution."""
    return await _resolve_datasets(client, settings, requested_dataset_ids)


def _group_searchable_datasets(datasets: list[_ResolvedDataset]) -> list[tuple[str, list[str]]]:
    groups: dict[str, list[str]] = {}
    for dataset in datasets:
        if dataset.chunk_count == 0:
            continue
        groups.setdefault(dataset.embedding_model, []).append(dataset.dataset_id)
    return sorted(groups.items())


async def _validate_document_filters(
    client: RAGFlowClient,
    document_filters: list[dict[str, Any]],
) -> tuple[dict[str, list[str]] | None, str | None]:
    async def list_documents(item: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Mapping[str, object]]]:
        dataset_id = item["dataset_id"]
        document_ids = list(item["document_ids"])
        params = [
            ("page", "1"),
            ("page_size", str(len(document_ids))),
            *(("ids", document_id) for document_id in document_ids),
        ]
        payload = await client.list_documents(dataset_id, params=params)
        data = payload.get("data")
        documents = data.get("docs") if isinstance(data, Mapping) else None
        if not isinstance(documents, list):
            raise RAGFlowProtocolError("RAGFlow returned an invalid document list.")
        by_id = {str(document.get("id")): document for document in documents if isinstance(document, Mapping) and document.get("id") is not None}
        return item, by_id

    document_results = await _bounded_gather(document_filters, list_documents)
    validated: dict[str, list[str]] = {}
    for item, by_id in document_results:
        dataset_id = item["dataset_id"]
        document_ids = list(item["document_ids"])
        for document_id in document_ids:
            document = by_id.get(document_id)
            chunk_count = document.get("chunk_count") if document is not None else None
            run = str(document.get("run") or "").upper() if document is not None else ""
            if document is None or run != "DONE" or not isinstance(chunk_count, int) or isinstance(chunk_count, bool) or chunk_count <= 0:
                logger.warning(
                    "Selected RAGFlow document is missing or not searchable (dataset_id=%s, document_id=%s)",
                    dataset_id,
                    document_id,
                )
                return (
                    None,
                    "Error: The selected knowledge scope is no longer available; choose the knowledge bases or files again.",
                )
        validated[dataset_id] = document_ids
    return validated, None


def _group_scoped_datasets(
    datasets: list[_ResolvedDataset],
    document_filters: Mapping[str, list[str]],
) -> list[_RetrievalGroup]:
    grouped: dict[tuple[str, bool], _RetrievalGroup] = {}
    for dataset in datasets:
        if dataset.chunk_count == 0:
            continue
        document_ids = document_filters.get(dataset.dataset_id)
        key = (dataset.embedding_model, document_ids is not None)
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = _RetrievalGroup(
                embedding_model=dataset.embedding_model,
                dataset_ids=[dataset.dataset_id],
                document_ids=list(document_ids) if document_ids is not None else None,
            )
            continue
        existing.dataset_ids.append(dataset.dataset_id)
        if document_ids is not None and existing.document_ids is not None:
            existing.document_ids.extend(document_ids)
    return [grouped[key] for key in sorted(grouped)]


def _result_chunks(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    chunks = result.get("chunks")
    if not isinstance(chunks, list):
        return []
    return [chunk for chunk in chunks if isinstance(chunk, Mapping)]


def _result_document_aggregates(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    aggregates = result.get("doc_aggs")
    if isinstance(aggregates, list):
        return [aggregate for aggregate in aggregates if isinstance(aggregate, Mapping)]
    if isinstance(aggregates, Mapping):
        return [aggregate for aggregate in aggregates.values() if isinstance(aggregate, Mapping)]
    return []


def _merge_group_results(results: list[dict[str, Any]], *, page_size: int) -> dict[str, Any]:
    chunk_groups = [_result_chunks(result) for result in results]
    merged_chunks: list[Mapping[str, Any]] = []
    max_group_size = max((len(chunks) for chunks in chunk_groups), default=0)
    hide_cross_group_scores = len(results) > 1
    # Similarity scores from different embedding spaces are not globally
    # calibrated. Preserve each provider-ranked list and interleave equal rank
    # positions instead of comparing raw scores across models.
    for rank in range(max_group_size):
        for chunks in chunk_groups:
            if rank < len(chunks):
                chunk = chunks[rank]
                if hide_cross_group_scores and "similarity" in chunk:
                    chunk = {key: value for key, value in chunk.items() if key != "similarity"}
                merged_chunks.append(chunk)
                if len(merged_chunks) >= page_size:
                    break
        if len(merged_chunks) >= page_size:
            break

    selected_document_ids: list[str] = []
    for chunk in merged_chunks:
        document_id = chunk.get("document_id")
        if document_id is not None:
            clean_id = str(document_id)
            if clean_id not in selected_document_ids:
                selected_document_ids.append(clean_id)

    aggregates_by_document_id: dict[str, Mapping[str, Any]] = {}
    for result in results:
        for aggregate in _result_document_aggregates(result):
            document_id = aggregate.get("doc_id")
            if document_id is not None:
                aggregates_by_document_id.setdefault(str(document_id), aggregate)

    total = 0
    for result in results:
        value = result.get("total")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            total += value
    return {
        "chunks": merged_chunks,
        "doc_aggs": [aggregates_by_document_id[document_id] for document_id in selected_document_ids if document_id in aggregates_by_document_id],
        "total": total,
    }


async def _retrieve_dataset_groups(
    client: RAGFlowClient,
    settings: _RAGFlowRetrievalSettings,
    query: str,
    groups: list[_RetrievalGroup],
) -> dict[str, Any]:
    semaphore = asyncio.Semaphore(_MAX_PARALLEL_RAGFLOW_REQUESTS)

    async def retrieve_group(group: _RetrievalGroup) -> dict[str, Any]:
        async with semaphore:
            kwargs: dict[str, Any] = {
                "dataset_ids": group.dataset_ids,
                "page_size": settings.page_size,
                "similarity_threshold": settings.similarity_threshold,
                "vector_similarity_weight": settings.vector_similarity_weight,
                "top_k": settings.top_k,
            }
            if group.document_ids is not None:
                kwargs["document_ids"] = group.document_ids
            return await client.retrieve(query, **kwargs)

    results = await asyncio.gather(*(retrieve_group(group) for group in groups), return_exceptions=True)
    successful_results: list[dict[str, Any]] = []
    for result in results:
        if isinstance(result, BaseException):
            raise result
        successful_results.append(result)

    return _merge_group_results(successful_results, page_size=settings.page_size)


def _runtime_knowledge_scope(runtime: Runtime | None) -> object | None:
    context = runtime.context if runtime is not None else None
    if not isinstance(context, Mapping):
        return None
    return context.get(KNOWLEDGE_SCOPE_RUNTIME_KEY)


async def knowledge_search(
    query: str,
    *,
    knowledge_scope: object | None = None,
    runtime: Runtime | None = None,
) -> str:
    """Search the configured RAGFlow scope, defaulting to every accessible dataset."""
    query = query.strip()
    if not query:
        return "Error: query must not be empty."

    scope_value = knowledge_scope if knowledge_scope is not None else _runtime_knowledge_scope(runtime)
    resolved_scope: dict[str, Any] | None = None
    if scope_value is not None:
        try:
            resolved_scope = execution_scope(canonicalize_knowledge_scope(scope_value))
        except ValidationError:
            return "Error: Invalid knowledge scope for this turn."
        if resolved_scope["mode"] == "disabled":
            return "Error: Knowledge search is disabled for this turn."

    settings, error = _settings_or_error()
    if settings is None:
        return error or "Error: Invalid RAGFlow settings for knowledge_search; check config.yaml."

    client = _build_client(settings)
    try:
        selected_dataset_ids = resolved_scope.get("dataset_ids") if resolved_scope is not None and resolved_scope["mode"] == "selected" else None
        datasets, resolution_error = await _resolve_datasets(
            client,
            settings,
            requested_dataset_ids=selected_dataset_ids,
        )
        if resolution_error is not None:
            return resolution_error
        if not datasets:  # Defensive; both resolution paths return a non-empty scope.
            return "Error: No RAGFlow datasets could be resolved; check knowledge_search in config.yaml."

        document_filters: dict[str, list[str]] = {}
        if resolved_scope is not None and resolved_scope["mode"] == "selected":
            validated_filters, filter_error = await _validate_document_filters(
                client,
                list(resolved_scope.get("document_filters") or []),
            )
            if filter_error is not None:
                return filter_error
            document_filters = validated_filters or {}
        groups = _group_scoped_datasets(datasets, document_filters)
        if not groups:
            return _NO_RELEVANT_CONTENT

        result = await _retrieve_dataset_groups(client, settings, query, groups)
        names_by_id = {dataset.dataset_id: dataset.name for dataset in datasets}
        formatted = format_retrieval_result(
            result,
            dataset_names_by_id=names_by_id,
            max_chars_per_chunk=settings.max_chars_per_chunk,
            max_total_chars=settings.max_total_chars,
        )
        # API-key redaction remains mandatory on success. UUID redaction is
        # deliberately error-only so valid checksums and trace IDs survive.
        return _redact_api_key(formatted, _api_key(settings))
    except Exception as exc:
        return _tool_error(exc, settings)


async def list_knowledge_bases() -> str:
    """List accessible RAGFlow knowledge-base names without exposing UUIDs."""
    settings, error = _settings_or_error()
    if settings is None:
        return error or "Error: Invalid RAGFlow settings for knowledge_search; check config.yaml."

    client = _build_client(settings)
    try:
        datasets, resolution_error = await _resolve_datasets(client, settings)
        if resolution_error is not None:
            return resolution_error
        if not datasets:
            return "No accessible RAGFlow datasets were found."
        lines = ["Available knowledge bases:"]
        for dataset in datasets:
            lines.append(f"- {dataset.name}")
        return _redact_api_key("\n".join(lines), _api_key(settings))
    except Exception as exc:
        return _tool_error(exc, settings)


def _tool_description() -> str:
    base = "Search the operator-approved RAGFlow datasets and return compact, citation-numbered source chunks."
    return f"{base} If knowledge_search.datasets is omitted, all datasets accessible to the configured RAGFlow API key are searched. Dataset IDs are never shown to the model."


async def _knowledge_search_entrypoint(query: str, runtime: Runtime) -> str:
    """Search the configured RAGFlow datasets, or every accessible dataset by default.

    Args:
        query: Specific question or search terms to retrieve from the configured private documents.
    """
    return await knowledge_search(query, runtime=runtime)


knowledge_search_tool = StructuredTool.from_function(
    coroutine=_knowledge_search_entrypoint,
    name="knowledge_search",
    description=_tool_description(),
    parse_docstring=True,
)


async def _list_knowledge_bases_entrypoint() -> str:
    """List the operator-approved RAGFlow knowledge bases by name.

    Dataset UUIDs and other provider metadata are intentionally omitted.
    """
    return await list_knowledge_bases()


list_knowledge_bases_tool = StructuredTool.from_function(
    coroutine=_list_knowledge_bases_entrypoint,
    name="list_knowledge_bases",
    description="List the names of accessible RAGFlow knowledge bases without exposing dataset IDs.",
    parse_docstring=True,
)
