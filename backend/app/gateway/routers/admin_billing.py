"""Administrator operations for tenant wallets and account status."""

import logging
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from app.gateway.deps import get_current_user_from_request, require_admin_user
from deerflow.config.app_config import get_app_config
from deerflow.persistence.billing.model import ModelPricePolicyRow, PaymentOrderRow, UsageRecordRow, WalletRow
from deerflow.persistence.billing.service import InsufficientCredits, WalletService
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.safety.model import RiskEventRow
from deerflow.persistence.safety.service import ContentSafetyService
from deerflow.persistence.user.model import UserRow

router = APIRouter(prefix="/api/admin", tags=["admin-billing"])
logger = logging.getLogger(__name__)


class CreditAdjustment(BaseModel):
    credits: int = Field(ge=-1_000_000, le=1_000_000)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("credits")
    @classmethod
    def credits_must_not_be_zero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("credits must not be zero")
        return value


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


async def _record_admin_operation(
    *,
    session_factory,
    action: str,
    target_type: str,
    target_id: str,
    actor_user_id: str,
    reason: str | None = None,
    before_summary: dict | None = None,
    after_summary: dict | None = None,
) -> None:
    """Audit an operation without adding sensitive tenant content to the log."""
    try:
        await ContentSafetyService(session_factory).record_admin_action(
            action=action,
            target_type=target_type,
            target_id=target_id,
            actor_user_id=actor_user_id,
            reason=reason,
            before_summary=before_summary,
            after_summary=after_summary,
        )
    except Exception:
        logger.exception("Failed to write admin audit entry for %s", action)


@router.get("/overview")
async def get_operations_overview(request: Request) -> dict:
    """Small, platform-wide numbers for the dedicated operations landing page."""
    await require_admin_user(request, detail="Administrator access required")
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="Billing requires a SQL database")
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    async with sf() as session:
        tenant_count = int(await session.scalar(select(func.count()).select_from(UserRow)) or 0)
        available_credits = int(await session.scalar(select(func.coalesce(func.sum(WalletRow.available_credits), 0))) or 0)
        today_recharge = int(await session.scalar(select(func.coalesce(func.sum(PaymentOrderRow.credits), 0)).where(PaymentOrderRow.status == "paid", PaymentOrderRow.created_at >= today)) or 0)
        today_consumption = int(await session.scalar(select(func.coalesce(func.sum(UsageRecordRow.charged_credits), 0)).where(UsageRecordRow.created_at >= today)) or 0)
        open_risk_events = int(await session.scalar(select(func.count()).select_from(RiskEventRow).where(RiskEventRow.status == "open")) or 0)
    return {
        "tenant_count": tenant_count,
        "available_credits": available_credits,
        "today_recharge_credits": today_recharge,
        "today_consumption_credits": today_consumption,
        "open_risk_events": open_risk_events,
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


@router.get("/orders")
async def list_payment_orders(request: Request, limit: int = 100) -> list[dict]:
    await require_admin_user(request, detail="Administrator access required")
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="Billing requires a SQL database")
    async with sf() as session:
        rows = await session.execute(select(PaymentOrderRow, UserRow.email).join(UserRow, UserRow.id == PaymentOrderRow.user_id).order_by(PaymentOrderRow.created_at.desc()).limit(min(max(limit, 1), 500)))
        return [
            {
                "id": order.id,
                "user_id": order.user_id,
                "email": email,
                "provider": order.provider,
                "package_id": order.package_id,
                "amount_fen": order.amount_fen,
                "credits": order.credits,
                "status": order.status,
                "created_at": order.created_at,
            }
            for order, email in rows
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
    await _record_admin_operation(
        session_factory=sf,
        action="billing.credits_adjusted",
        target_type="tenant",
        target_id=user_id,
        actor_user_id=str(actor.id),
        reason=body.reason,
        after_summary={"credit_delta": body.credits, **snapshot.__dict__},
    )
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
    await _record_admin_operation(
        session_factory=sf,
        action="tenant.freeze_changed",
        target_type="tenant",
        target_id=user_id,
        actor_user_id=str(actor.id),
        before_summary={"is_frozen": not frozen},
        after_summary={"is_frozen": frozen},
    )
    return {"user_id": user_id, "is_frozen": frozen}


@router.post("/model-pricing")
async def create_model_price_policy(body: ModelPricePolicyRequest, request: Request) -> dict:
    await require_admin_user(request, detail="Administrator access required")
    actor = await get_current_user_from_request(request)
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
    await _record_admin_operation(
        session_factory=sf,
        action="billing.model_policy_created",
        target_type="model_price_policy",
        target_id=policy.id,
        actor_user_id=str(actor.id),
        after_summary={"model_name": policy.model_name, "active": policy.active},
    )
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
