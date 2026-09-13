"""Authenticated, read-only RAGFlow catalog for custom-agent chat scope."""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from app.gateway.authz import require_permission
from app.gateway.deps import get_config
from app.gateway.knowledge_scope_admission import custom_agent_supports_knowledge_scope
from deerflow.community.ragflow.client import (
    RAGFlowAPIError,
    RAGFlowConnectionError,
    RAGFlowProtocolError,
)
from deerflow.community.ragflow.tools import (
    build_ragflow_retrieval_client as _build_retrieval_client,
)
from deerflow.community.ragflow.tools import (
    resolve_ragflow_datasets,
    resolve_ragflow_retrieval_settings,
)
from deerflow.config.agents_config import load_agent_config
from deerflow.config.app_config import AppConfig
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

_DatasetId = Annotated[
    str,
    Path(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$"),
]
_SCOPE_UNAVAILABLE_DETAIL = "Knowledge scope selection is unavailable for this custom agent."


async def _catalog_result[Result](operation: Awaitable[Result]) -> Result:
    """Normalize provider failures without exposing credentials or raw payloads."""
    try:
        return await operation
    except RAGFlowAPIError as exc:
        logger.warning("RAGFlow rejected a retrieval-catalog request (code=%s)", exc.code)
        raise HTTPException(
            status_code=502,
            detail="RAGFlow rejected the retrieval-catalog request.",
        ) from None
    except RAGFlowConnectionError:
        logger.warning("RAGFlow retrieval catalog could not connect")
        raise HTTPException(status_code=502, detail="Unable to connect to RAGFlow.") from None
    except RAGFlowProtocolError:
        logger.warning("RAGFlow returned an invalid retrieval-catalog response")
        raise HTTPException(
            status_code=502,
            detail="RAGFlow returned an invalid retrieval-catalog response.",
        ) from None
    except Exception as exc:
        logger.error("Unexpected RAGFlow retrieval-catalog failure (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail="RAGFlow request failed.") from None


def _scope_catalog(config: AppConfig, agent_name: str):
    knowledge_base = config.knowledge_base
    try:
        agent_config = load_agent_config(
            agent_name,
            user_id=get_effective_user_id(),
        )
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="Custom agent not found.") from None
    if (
        not knowledge_base.enabled
        or not knowledge_base.scope_selection_enabled
        or not custom_agent_supports_knowledge_scope(
            assistant_id=agent_name,
            app_config=config,
            agent_config=agent_config,
        )
    ):
        raise HTTPException(status_code=409, detail=_SCOPE_UNAVAILABLE_DETAIL)
    settings, error = resolve_ragflow_retrieval_settings(config)
    if settings is None:
        logger.warning(
            "RAGFlow retrieval catalog settings are unavailable (%s)",
            error,
        )
        raise HTTPException(
            status_code=503,
            detail="Knowledge retrieval is not configured.",
        )
    return settings


def _catalog_page(
    items: list[dict[str, Any]],
    *,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int]:
    total = len(items)
    start = (page - 1) * page_size
    return items[start : start + page_size], total


@router.get("/retrieval-catalog/datasets")
@require_permission("threads", "read")
async def list_retrieval_catalog_datasets(
    request: Request,
    agent_name: Annotated[str, Query(min_length=1, max_length=128)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[str, Query(max_length=256)] = "",
    config: AppConfig = Depends(get_config),
) -> dict[str, Any]:
    """Return only datasets that the operator permits this agent to retrieve."""
    settings = _scope_catalog(config, agent_name)
    client = _build_retrieval_client(settings)
    datasets, error = await _catalog_result(
        resolve_ragflow_datasets(client, settings),
    )
    if datasets is None:
        logger.warning(
            "RAGFlow retrieval catalog could not resolve operator scope (%s)",
            error,
        )
        raise HTTPException(
            status_code=409,
            detail="The configured knowledge-base scope is unavailable.",
        )

    needle = search.strip().casefold()
    entries = [
        {
            "id": dataset.dataset_id,
            "name": dataset.name,
            "selectable": bool(dataset.embedding_model) and dataset.chunk_count != 0,
        }
        for dataset in datasets
        if not needle or needle in dataset.name.casefold()
    ]
    selected, total = _catalog_page(entries, page=page, page_size=page_size)
    return {
        "items": selected,
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/retrieval-catalog/datasets/{dataset_id}/documents")
@require_permission("threads", "read")
async def list_retrieval_catalog_documents(
    dataset_id: _DatasetId,
    request: Request,
    agent_name: Annotated[str, Query(min_length=1, max_length=128)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[str, Query(max_length=256)] = "",
    config: AppConfig = Depends(get_config),
) -> dict[str, Any]:
    """Return a normalized, read-only document page inside operator scope."""
    settings = _scope_catalog(config, agent_name)
    if settings.datasets is not None and dataset_id not in set(settings.datasets):
        raise HTTPException(status_code=404, detail="Knowledge base not found.")
    client = _build_retrieval_client(settings)
    resolved, error = await _catalog_result(
        resolve_ragflow_datasets(client, settings, [dataset_id]),
    )
    if not resolved:
        logger.warning(
            "RAGFlow retrieval catalog dataset is unavailable (dataset_id=%s, reason=%s)",
            dataset_id,
            error,
        )
        raise HTTPException(status_code=404, detail="Knowledge base not found.")

    params = [("page", str(page)), ("page_size", str(page_size))]
    if search.strip():
        params.append(("keywords", search.strip()))
    payload = await _catalog_result(
        client.list_documents(dataset_id, params=params),
    )
    data = payload.get("data")
    docs = data.get("docs") if isinstance(data, dict) else None
    if not isinstance(docs, list):
        raise HTTPException(
            status_code=502,
            detail="RAGFlow returned an invalid document list.",
        )
    items = []
    for document in docs:
        if not isinstance(document, dict):
            continue
        document_id = document.get("id")
        if not isinstance(document_id, str) or not document_id.strip():
            continue
        chunk_count = document.get("chunk_count")
        searchable = isinstance(chunk_count, int) and not isinstance(chunk_count, bool) and chunk_count > 0
        parsed = document.get("run") == "DONE"
        items.append(
            {
                "id": document_id.strip(),
                "name": str(document.get("name") or "Unnamed document"),
                "selectable": parsed and searchable,
            }
        )
    total = data.get("total")
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        total = len(items)
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
    }
