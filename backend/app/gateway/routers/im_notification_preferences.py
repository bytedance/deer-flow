"""Owner-scoped proactive IM opt-outs, independent of browser notifications."""

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.user.im_notifications import ImNotificationPreferencesRepository

router = APIRouter(prefix="/api/channels/notification-preferences", tags=["channel-connections"])


class ImNotificationPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    feishu: bool | None = None
    wecom: bool | None = None
    wechat: bool | None = None
    qq: bool | None = None
    run_completed: bool | None = None
    run_failed: bool | None = None
    human_input_requested: bool | None = None


def _owner(request: Request, expected_user_id: str) -> str:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(401, "Authentication required")
    owner = str(user.id)
    if owner != expected_user_id:
        raise HTTPException(409, "The signed-in account changed; reload this page")
    return owner


def _repository() -> ImNotificationPreferencesRepository:
    sessions = get_session_factory()
    if sessions is None:
        raise HTTPException(503, "Notification preference persistence is unavailable")
    return ImNotificationPreferencesRepository(sessions)


@router.get("", response_model=ImNotificationPreferences, response_model_exclude_none=True)
async def get_preferences(request: Request, x_expected_user_id: str = Header(...)) -> dict[str, bool]:
    owner = _owner(request, x_expected_user_id)
    return await _repository().get(owner)


@router.patch("", response_model=ImNotificationPreferences, response_model_exclude_none=True)
async def patch_preferences(body: ImNotificationPreferences, request: Request, x_expected_user_id: str = Header(...)) -> dict[str, bool]:
    owner = _owner(request, x_expected_user_id)
    return await _repository().patch(owner, body.model_dump(exclude_unset=True))
