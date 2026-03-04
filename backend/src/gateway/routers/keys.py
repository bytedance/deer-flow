import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.gateway.auth.middleware import get_current_user
from src.models.provider_catalog import SUPPORTED_PROVIDERS
from src.security.api_key_store import delete_api_key, has_api_key, set_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["providers"])


class ProviderKeyRequest(BaseModel):
    api_key: str = Field(..., description="API key for the provider")


class ProviderKeyStatusResponse(BaseModel):
    provider: str = Field(..., description="Provider identifier")
    has_key: bool = Field(..., description="Whether a key is stored for this user")


def _normalize_provider(provider: str) -> str:
    normalized = provider.lower()
    if normalized not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")
    return normalized


@router.put(
    "/providers/{provider}/key",
    response_model=ProviderKeyStatusResponse,
    summary="Store Provider API Key",
    description="Store or update a provider API key for the authenticated user.",
)
async def store_provider_key(
    provider: str,
    request: ProviderKeyRequest,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> ProviderKeyStatusResponse:
    normalized = _normalize_provider(provider)
    user_id = current_user["id"]
    try:
        set_api_key(user_id, normalized, request.api_key)
    except ValueError as exc:
        msg = str(exc)
        if "Fernet" in msg or "key must be" in msg:
            logger.error("Server encryption key misconfigured: %s", msg)
            raise HTTPException(status_code=500, detail="Server encryption configuration error") from exc
        raise HTTPException(status_code=400, detail=msg) from exc
    except Exception as exc:
        logger.error("Failed to store API key for provider %s: %s", normalized, exc)
        raise HTTPException(status_code=500, detail="Internal error storing API key") from exc
    return ProviderKeyStatusResponse(provider=normalized, has_key=True)


@router.get(
    "/providers/{provider}/key",
    response_model=ProviderKeyStatusResponse,
    summary="Get Provider API Key Status",
    description="Return whether a provider API key is stored for the authenticated user.",
)
async def get_provider_key_status(
    provider: str,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> ProviderKeyStatusResponse:
    normalized = _normalize_provider(provider)
    user_id = current_user["id"]
    return ProviderKeyStatusResponse(
        provider=normalized,
        has_key=has_api_key(user_id, normalized),
    )


@router.delete(
    "/providers/{provider}/key",
    response_model=ProviderKeyStatusResponse,
    summary="Delete Provider API Key",
    description="Delete a provider API key for the authenticated user.",
)
async def delete_provider_key(
    provider: str,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> ProviderKeyStatusResponse:
    normalized = _normalize_provider(provider)
    user_id = current_user["id"]
    delete_api_key(user_id, normalized)
    return ProviderKeyStatusResponse(provider=normalized, has_key=False)
