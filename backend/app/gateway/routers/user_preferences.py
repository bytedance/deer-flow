"""Authenticated, server-backed user-level UI preferences."""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator

from app.gateway.auth.repositories.base import (
    UserNotFoundError,
    UserPreferencesInvalidError,
    UserPreferencesNotInitializedError,
    UserPreferencesWriteConflict,
)
from app.gateway.deps import get_current_user_from_request, get_user_repository

router = APIRouter(prefix="/api/user-preferences", tags=["user-preferences"])
logger = logging.getLogger(__name__)

MAX_USER_PREFERENCES_BYTES = 2048
EXPECTED_USER_ID_HEADER = "X-DeerFlow-Expected-User-Id"
ModelName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]


def _is_none(value: object) -> bool:
    return value is None


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class NotificationPreferences(_StrictModel):
    enabled: bool


class TokenUsagePreferences(_StrictModel):
    headerTotal: bool
    inlineMode: Literal["off", "per_turn", "step_debug"]


class ContextPreferences(_StrictModel):
    model_name: ModelName | None = Field(default=None, exclude_if=_is_none)
    mode: Literal["flash", "thinking", "pro", "ultra"] | None = Field(default=None, exclude_if=_is_none)
    reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = Field(
        default=None,
        exclude_if=_is_none,
    )


class UserPreferences(_StrictModel):
    notification: NotificationPreferences
    tokenUsage: TokenUsagePreferences
    context: ContextPreferences

    @model_validator(mode="after")
    def enforce_size_limit(self) -> UserPreferences:
        if len(self.model_dump_json(exclude_none=True).encode("utf-8")) > MAX_USER_PREFERENCES_BYTES:
            raise ValueError("User preferences exceed the size limit")
        return self

    def to_storage_dict(self) -> dict:
        return self.model_dump(exclude_none=True)


class NotificationPreferencesPatch(_StrictModel):
    enabled: bool | None = None

    @model_validator(mode="after")
    def require_field(self) -> NotificationPreferencesPatch:
        if not self.model_fields_set:
            raise ValueError("At least one notification preference is required")
        if self.enabled is None:
            raise ValueError("notification.enabled cannot be null")
        return self


class TokenUsagePreferencesPatch(_StrictModel):
    headerTotal: bool | None = None
    inlineMode: Literal["off", "per_turn", "step_debug"] | None = None

    @model_validator(mode="after")
    def require_field(self) -> TokenUsagePreferencesPatch:
        if not self.model_fields_set:
            raise ValueError("At least one token-usage preference is required")
        if "headerTotal" in self.model_fields_set and self.headerTotal is None:
            raise ValueError("tokenUsage.headerTotal cannot be null")
        if "inlineMode" in self.model_fields_set and self.inlineMode is None:
            raise ValueError("tokenUsage.inlineMode cannot be null")
        return self


class ContextPreferencesPatch(_StrictModel):
    model_name: ModelName | None = None
    mode: Literal["flash", "thinking", "pro", "ultra"] | None = None
    reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None

    @model_validator(mode="after")
    def require_field(self) -> ContextPreferencesPatch:
        if not self.model_fields_set:
            raise ValueError("At least one context preference is required")
        return self


class UserPreferencesPatchRequest(_StrictModel):
    notification: NotificationPreferencesPatch | None = None
    tokenUsage: TokenUsagePreferencesPatch | None = None
    context: ContextPreferencesPatch | None = None

    @model_validator(mode="after")
    def require_patch_and_enforce_size(self) -> UserPreferencesPatchRequest:
        if not self.model_fields_set:
            raise ValueError("At least one preference section is required")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Preference sections cannot be null")
        if len(self.model_dump_json(exclude_unset=True).encode("utf-8")) > MAX_USER_PREFERENCES_BYTES:
            raise ValueError("User preferences patch exceeds the size limit")
        return self

    def to_storage_patch(self) -> dict:
        return self.model_dump(exclude_unset=True)


class UserPreferencesInitializeRequest(_StrictModel):
    settings: UserPreferences


class UserPreferencesResponse(_StrictModel):
    settings: UserPreferences | None
    revision: int = Field(ge=0)


def _stored_preferences_are_valid(settings: object) -> bool:
    try:
        UserPreferences.model_validate(settings)
    except ValidationError:
        return False
    return True


def _response(settings: object | None, revision: int) -> UserPreferencesResponse:
    try:
        validated = UserPreferences.model_validate(settings) if settings is not None else None
    except ValidationError:
        # A stale deployment or a manual database edit can leave JSON that no
        # longer matches the public allowlist. Treat it like an absent record
        # while preserving the revision; the normal PUT path then repairs it
        # with a revision-CAS instead of trapping this session in a 500 loop.
        logger.warning("Ignoring schema-invalid stored user preferences at revision %s", revision)
        validated = None
    return UserPreferencesResponse(settings=validated, revision=revision)


def _translate_repository_error(exc: Exception) -> HTTPException:
    if isinstance(exc, UserNotFoundError):
        return HTTPException(status_code=404, detail="User not found")
    if isinstance(exc, UserPreferencesNotInitializedError):
        return HTTPException(status_code=409, detail="User preferences must be initialized before partial updates")
    if isinstance(exc, UserPreferencesInvalidError):
        return HTTPException(status_code=409, detail="Stored user preferences are invalid; initialize them before partial updates")
    if isinstance(exc, UserPreferencesWriteConflict):
        return HTTPException(status_code=409, detail="Concurrent user-preference update; retry the request")
    raise exc


async def _get_guarded_user(request: Request):
    """Resolve the authenticated owner and reject a tab with a stale session.

    Browser cookies are origin-wide. If another tab signs into a different
    account, a still-mounted settings controller retains its old user id while
    subsequent requests carry the new cookie. The expected id is only a guard;
    repository ownership always comes from the authenticated request.
    """
    user = await get_current_user_from_request(request)
    expected_user_id = request.headers.get(EXPECTED_USER_ID_HEADER)
    if expected_user_id is not None and expected_user_id != str(user.id):
        raise HTTPException(status_code=409, detail="Authenticated user changed; reload before synchronizing settings")
    return user


@router.get("", response_model=UserPreferencesResponse)
async def get_user_preferences(request: Request) -> UserPreferencesResponse:
    """Return preferences for the authenticated user only."""
    user = await _get_guarded_user(request)
    repository = get_user_repository()
    try:
        settings, revision = await repository.get_user_preferences(str(user.id))
        return _response(settings, revision)
    except Exception as exc:
        raise _translate_repository_error(exc) from exc


@router.put("", response_model=UserPreferencesResponse)
async def initialize_user_preferences(
    body: UserPreferencesInitializeRequest,
    request: Request,
) -> UserPreferencesResponse:
    """First-writer-wins import of the legacy local base settings."""
    user = await _get_guarded_user(request)
    repository = get_user_repository()
    try:
        settings, revision = await repository.initialize_user_preferences(
            str(user.id),
            body.settings.to_storage_dict(),
            existing_is_valid=_stored_preferences_are_valid,
        )
        return _response(settings, revision)
    except Exception as exc:
        raise _translate_repository_error(exc) from exc


@router.patch("", response_model=UserPreferencesResponse)
async def patch_user_preferences(
    body: UserPreferencesPatchRequest,
    request: Request,
) -> UserPreferencesResponse:
    """Deep-merge an allowlisted patch for the authenticated user."""
    user = await _get_guarded_user(request)
    repository = get_user_repository()
    try:
        settings, revision = await repository.merge_user_preferences(
            str(user.id),
            body.to_storage_patch(),
            current_is_valid=_stored_preferences_are_valid,
        )
        return _response(settings, revision)
    except Exception as exc:
        raise _translate_repository_error(exc) from exc
