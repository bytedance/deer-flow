"""Session-authenticated, owner-scoped UI preferences."""

from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError

from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
from app.gateway.deps import get_current_user_from_request
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.user.preferences import UserPreferencesRepository

router = APIRouter(prefix="/api/v1/auth/preferences", tags=["auth"])


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    notification_enabled: bool | None = None
    model_name: Annotated[str, StringConstraints(max_length=200)] | None = None
    mode: Literal["flash", "thinking", "pro", "ultra"] | None = None
    reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None


async def _owner(request: Request, expected_user: str) -> str:
    user = await get_current_user_from_request(request)
    if getattr(request.state, "auth_source", None) != AUTH_SOURCE_SESSION:
        raise HTTPException(403, "Preferences require an authenticated browser session")
    owner = str(user.id)
    if owner != expected_user:
        raise HTTPException(409, "The signed-in account changed; reload this page")
    return owner


def _repository() -> UserPreferencesRepository:
    sessions = get_session_factory()
    if sessions is None:
        raise HTTPException(503, "Preference persistence is unavailable")
    return UserPreferencesRepository(sessions)


@router.get("", response_model=Preferences)
async def get_preferences(request: Request, x_expected_user_id: str = Header(...)) -> Preferences:
    owner = await _owner(request, x_expected_user_id)
    stored = await _repository().get(owner)
    # An invalid optional cosmetic setting must not hide the rest of the page.
    valid = {}
    for key, value in stored.items():
        try:
            Preferences.model_validate({key: value})
        except ValidationError:
            continue
        valid[key] = value
    return Preferences(**valid)


@router.patch("", status_code=204, response_class=Response)
async def patch_preferences(body: Preferences, request: Request, x_expected_user_id: str = Header(...)) -> Response:
    owner = await _owner(request, x_expected_user_id)
    await _repository().patch(owner, body.model_dump(exclude_unset=True))
    return Response(status_code=204)
