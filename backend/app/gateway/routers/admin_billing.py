"""Administrator operations for tenant wallets and account status."""

from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.gateway.deps import get_current_user_from_request, require_admin_user
from deerflow.config.app_config import get_app_config
from deerflow.persistence.billing.model import ModelPricePolicyRow, UsageRecordRow, WalletRow
from deerflow.persistence.billing.service import InsufficientCredits, WalletService
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.user.model import UserRow

router = APIRouter(prefix="/api/admin", tags=["admin-billing"])


class CreditAdjustment(BaseModel):
    credits: int = Field(ne=0, ge=-1_000_000, le=1_000_000)
    reason: str = Field(min_length=1, max_length=500)


class ModelPricePolicyRequest(BaseModel):
    model_name: str = Field(min_length=1, max_length=128)
    input_fen_per_million: int = Field(ge=0)
    output_fen_per_million: int = Field(ge=0)
    cache_read_fen_per_million: int | None = Field(default=None, ge=0)
    credit_multiplier_bps: int = Field(default=10_000, ge=1, le=1_000_000)
    max_reservation_credits: int = Field(ge=1, le=1_000_000)


def validate_configured_model(model_name: str) -> None:
    """Ensure pricing can only be created for a model users can select."""
    configured_names = {model.name for model in get_app_config().models}
    if model_name not in configured_names:
        raise HTTPException(status_code=422, detail="Model is not configured")


def validate_admin_freeze(*, target_is_admin: bool, active_admin_count: int) -> None:
    """Keep at least one administrator able to recover the system."""
    if target_is_admin and active_admin_count <= 1:
        raise HTTPException(status_code=409, detail="Cannot freeze the last active administrator")


def _policy_response(policy: ModelPricePolicyRow) -> dict:
    return {
        "id": policy.id,
        "model_name": policy.model_name,
        "input_fen_per_million": policy.input_fen_per_million,
        "output_fen_per_million": policy.output_fen_per_million,
        "cache_read_fen_per_million": policy.cache_read_fen_per_million,
        "credit_multiplier_bps": policy.credit_multiplier_bps,
        "max_reservation_credits": policy.max_reservation_credits,
        "active": policy.active,
        "created_at": policy.created_at,
    }


@router.get("/users")
async def list_users(request: Request) -> list[dict]:
    await require_admin_user(request, detail="Administrator access required")
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="Billing requires a SQL database")
    async with sf() as session:
        rows = (await session.execute(select(UserRow, WalletRow).outerjoin(WalletRow, WalletRow.user_id == UserRow.id).order_by(UserRow.created_at.desc()))).all()
    return [{"id": user.id, "email": user.email, "system_role": user.system_role, "is_frozen": user.is_frozen, "available_credits": wallet.available_credits if wallet else 0} for user, wallet in rows]


@router.get("/usage")
async def list_usage(request: Request, limit: int = 100) -> list[dict]:
    await require_admin_user(request, detail="Administrator access required")
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="Billing requires a SQL database")
    async with sf() as session:
        rows = await session.execute(select(UsageRecordRow, UserRow.email).join(UserRow, UserRow.id == UsageRecordRow.user_id).order_by(UsageRecordRow.created_at.desc()).limit(min(max(limit, 1), 500)))
        return [
            {
                "user_id": usage.user_id,
                "email": email,
                "run_id": usage.run_id,
                "model_name": usage.model_name,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "charged_credits": usage.charged_credits,
                "created_at": usage.created_at,
            }
            for usage, email in rows
        ]


@router.post("/users/{user_id}/credits")
async def adjust_user_credits(user_id: str, body: CreditAdjustment, request: Request) -> dict:
    await require_admin_user(request, detail="Administrator access required")
    actor = await get_current_user_from_request(request)
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="Billing requires a SQL database")
    async with sf() as session:
        if await session.get(UserRow, user_id) is None:
            raise HTTPException(status_code=404, detail="User not found")
    try:
        snapshot = await WalletService(sf).adjust_credits(user_id, body.credits, uuid4().hex, actor_user_id=str(actor.id), reason=body.reason)
    except InsufficientCredits as exc:
        raise HTTPException(status_code=409, detail={"code": "INSUFFICIENT_CREDITS", "available_credits": exc.available_credits}) from exc
    return snapshot.__dict__


@router.post("/users/{user_id}/freeze")
async def set_user_frozen(user_id: str, frozen: bool, request: Request) -> dict:
    await require_admin_user(request, detail="Administrator access required")
    actor = await get_current_user_from_request(request)
    if frozen and actor.id == user_id:
        raise HTTPException(status_code=400, detail="Administrators cannot freeze their own account")
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="Billing requires a SQL database")
    async with sf() as session:
        row = await session.get(UserRow, user_id)
        if row is None:
            raise HTTPException(status_code=404, detail="User not found")
        if frozen:
            active_admin_count = await session.scalar(select(func.count()).select_from(UserRow).where(UserRow.system_role == "admin", UserRow.is_frozen.is_(False)))
            validate_admin_freeze(
                target_is_admin=row.system_role == "admin",
                active_admin_count=int(active_admin_count or 0),
            )
        row.is_frozen = frozen
        row.token_version += 1
        await session.commit()
    return {"user_id": user_id, "is_frozen": frozen}


@router.post("/model-pricing")
async def create_model_price_policy(body: ModelPricePolicyRequest, request: Request) -> dict:
    await require_admin_user(request, detail="Administrator access required")
    validate_configured_model(body.model_name)
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="Billing requires a SQL database")
    async with sf() as session:
        existing = await session.execute(select(ModelPricePolicyRow).where(ModelPricePolicyRow.model_name == body.model_name, ModelPricePolicyRow.active.is_(True)))
        for row in existing.scalars():
            row.active = False
        policy = ModelPricePolicyRow(id=uuid4().hex, **body.model_dump())
        session.add(policy)
        await session.commit()
    return _policy_response(policy)


@router.get("/model-pricing")
async def list_model_price_policies(request: Request) -> list[dict]:
    await require_admin_user(request, detail="Administrator access required")
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="Billing requires a SQL database")
    async with sf() as session:
        rows = await session.scalars(select(ModelPricePolicyRow).order_by(ModelPricePolicyRow.model_name, ModelPricePolicyRow.created_at.desc()))
        return [_policy_response(policy) for policy in rows]
