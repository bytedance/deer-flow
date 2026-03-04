from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.gateway.auth.middleware import get_current_user
from src.security.model_preference_store import get_model_preferences, set_model_preferences

router = APIRouter(prefix="/api", tags=["preferences"])


class UserModelPreferenceRequest(BaseModel):
    model_name: str | None = Field(default=None, description="Selected model identifier")
    thinking_effort: str | None = Field(default=None, description="Selected thinking effort")
    provider_enabled: dict[str, bool] | None = Field(default=None, description="Per-provider enabled flags")
    enabled_models: dict[str, bool] | None = Field(default=None, description="Per-model enabled flags")


class UserModelPreferenceResponse(BaseModel):
    model_name: str | None = Field(default=None, description="Persisted selected model identifier")
    thinking_effort: str | None = Field(default=None, description="Persisted selected thinking effort")
    provider_enabled: dict[str, bool] = Field(default_factory=dict, description="Per-provider enabled flags")
    enabled_models: dict[str, bool] = Field(default_factory=dict, description="Per-model enabled flags")
    updated_at: str | None = Field(default=None, description="ISO timestamp of latest update")


@router.get(
    "/user/preferences/models",
    response_model=UserModelPreferenceResponse,
    summary="Get persisted model preferences",
    description="Return account-wide model and thinking effort preferences for the authenticated user.",
)
async def get_user_model_preferences(
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> UserModelPreferenceResponse:
    user_id = current_user["id"]
    data = get_model_preferences(user_id)
    if data is None:
        return UserModelPreferenceResponse()
    return UserModelPreferenceResponse(**data)


@router.put(
    "/user/preferences/models",
    response_model=UserModelPreferenceResponse,
    summary="Set persisted model preferences",
    description="Persist account-wide model and thinking effort preferences for the authenticated user.",
)
async def set_user_model_preferences(
    request: UserModelPreferenceRequest,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> UserModelPreferenceResponse:
    user_id = current_user["id"]
    payload = request.model_dump(exclude_unset=True)
    update_kwargs: dict[str, object] = {}
    if "model_name" in payload:
        update_kwargs["model_name"] = payload["model_name"]
    if "thinking_effort" in payload:
        update_kwargs["thinking_effort"] = payload["thinking_effort"]
    if "provider_enabled" in payload:
        update_kwargs["provider_enabled"] = payload["provider_enabled"]
    if "enabled_models" in payload:
        update_kwargs["enabled_models"] = payload["enabled_models"]
    try:
        data = set_model_preferences(user_id=user_id, **update_kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UserModelPreferenceResponse(**data)

