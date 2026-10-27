"""Authenticated, provider-neutral, read-only retrieval catalog."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import ValidationError

from app.gateway.authz import require_permission
from app.gateway.deps import get_config
from app.gateway.knowledge_scope_admission import assistant_supports_knowledge_scope
from deerflow.config.agents_config import load_agent_config
from deerflow.config.app_config import AppConfig
from deerflow.knowledge import KnowledgeRequestContext, RetrievalCatalogPage
from deerflow.knowledge.providers import get_knowledge_capabilities, resolve_knowledge_provider
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

# Scope IDs are provider-owned opaque strings, not RAGFlow UUIDs.
_DatasetId = Annotated[str, Path(min_length=1, max_length=256)]
_SCOPE_UNAVAILABLE_DETAIL = "Knowledge scope selection is unavailable for this assistant."


async def _catalog_result(operation: Awaitable[Any]) -> dict[str, Any]:
    """Validate the public projection and contain provider exception payloads."""
    try:
        result = await operation
        payload = result.model_dump() if isinstance(result, RetrievalCatalogPage) else result
        return RetrievalCatalogPage.model_validate(payload).model_dump()
    except PermissionError:
        raise HTTPException(status_code=403, detail="Knowledge resource access denied.") from None
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Knowledge base not found.") from None
    except ValidationError:
        raise HTTPException(status_code=502, detail="Knowledge provider returned an invalid catalog.") from None
    except ValueError:
        raise HTTPException(status_code=409, detail="The configured knowledge-base scope is unavailable.") from None
    except Exception as exc:
        logger.warning("Knowledge retrieval-catalog request failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Knowledge provider request failed.") from None


async def _scope_capabilities(config: AppConfig, agent_name: str, extensions: Any = None):
    agent_config = None
    if agent_name != "lead_agent":
        try:
            agent_config = await asyncio.to_thread(load_agent_config, agent_name, user_id=get_effective_user_id())
        except (FileNotFoundError, ValueError):
            raise HTTPException(status_code=404, detail="Custom agent not found.") from None
    if not assistant_supports_knowledge_scope(assistant_id=agent_name, app_config=config, agent_config=agent_config, extensions=extensions):
        raise HTTPException(status_code=409, detail=_SCOPE_UNAVAILABLE_DETAIL)
    return get_knowledge_capabilities(config, extensions=extensions)


async def _scope_catalog(config: AppConfig, agent_name: str, request: Request, operation: str):
    extensions = getattr(request.app.state, "extensions", None)
    capabilities = await _scope_capabilities(config, agent_name, extensions)
    if not config.knowledge_base.scope_selection_enabled or not capabilities.supports(operation):
        raise HTTPException(status_code=409, detail=_SCOPE_UNAVAILABLE_DETAIL)
    try:
        return resolve_knowledge_provider(config, extensions=extensions)
    except LookupError:
        raise HTTPException(status_code=503, detail="Knowledge retrieval is not configured.") from None


@router.get("/capabilities")
@require_permission("threads", "read")
async def knowledge_capabilities(
    request: Request,
    agent_name: Annotated[str, Query(min_length=1, max_length=128)],
    config: AppConfig = Depends(get_config),
) -> dict[str, Any]:
    capabilities = await _scope_capabilities(config, agent_name, getattr(request.app.state, "extensions", None))
    return {
        "operations": sorted(capabilities.operations),
        "scope_selection_enabled": config.knowledge_base.scope_selection_enabled and capabilities.supports("catalog") and capabilities.supports("dataset_filter"),
    }


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
    provider = await _scope_catalog(config, agent_name, request, "catalog")
    return await _catalog_result(provider.catalog(context=KnowledgeRequestContext(user_id=get_effective_user_id(), agent_name=agent_name), page=page, page_size=page_size, search=search))


@router.get("/retrieval-catalog/datasets/{dataset_id:path}/documents")
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
    provider = await _scope_catalog(config, agent_name, request, "documents")
    return await _catalog_result(provider.documents(dataset_id, context=KnowledgeRequestContext(user_id=get_effective_user_id(), agent_name=agent_name), page=page, page_size=page_size, search=search))
