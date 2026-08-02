"""Tenant-scoped wallet and simulated recharge endpoints."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.gateway.deps import get_current_user
from deerflow.persistence.billing.model import CreditLedgerRow, UsageRecordRow, WalletRow
from deerflow.persistence.billing.service import WalletService
from deerflow.persistence.engine import get_session_factory

router = APIRouter(prefix="/api/billing", tags=["billing"])


class RechargeRequest(BaseModel):
    provider: str = Field(pattern="^(wechat|alipay)$")
    credits: int = Field(gt=0, le=1_000_000)
    idempotency_key: str = Field(min_length=8, max_length=128)


def _service() -> WalletService:
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="Billing requires a SQL database")
    return WalletService(sf)


@router.get("/wallet")
async def wallet(request: Request) -> dict:
    user_id = await get_current_user(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="Billing requires a SQL database")
    async with sf() as session:
        row = await session.get(WalletRow, user_id)
    return {"available_credits": row.available_credits if row else 0, "reserved_credits": row.reserved_credits if row else 0}


@router.get("/ledger")
async def ledger(request: Request, limit: int = 50) -> list[dict]:
    user_id = await get_current_user(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="Billing requires a SQL database")
    async with sf() as session:
        rows = await session.scalars(select(CreditLedgerRow).where(CreditLedgerRow.user_id == user_id).order_by(CreditLedgerRow.created_at.desc()).limit(min(max(limit, 1), 100)))
        return [{"entry_type": row.entry_type, "credit_delta": row.credit_delta, "reason": row.reason, "created_at": row.created_at} for row in rows]


@router.post("/recharge")
async def recharge(body: RechargeRequest, request: Request) -> dict:
    user_id = await get_current_user(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="Billing requires a SQL database")
    result = await _service().create_mock_payment(user_id, provider=body.provider, credits=body.credits, idempotency_key=body.idempotency_key)
    return {"status": result.status, "order_id": result.order_id, "provider": result.provider, "idempotent": result.idempotent, **result.wallet.__dict__}


@router.get("/usage")
async def usage(request: Request, limit: int = 50) -> list[dict]:
    user_id = await get_current_user(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="Billing requires a SQL database")
    async with sf() as session:
        rows = await session.scalars(select(UsageRecordRow).where(UsageRecordRow.user_id == user_id).order_by(UsageRecordRow.created_at.desc()).limit(min(max(limit, 1), 100)))
        return [
            {
                "run_id": row.run_id,
                "model_name": row.model_name,
                "input_tokens": row.input_tokens,
                "output_tokens": row.output_tokens,
                "cache_read_tokens": row.cache_read_tokens,
                "charged_credits": row.charged_credits,
                "price_snapshot": row.price_snapshot,
                "created_at": row.created_at,
            }
            for row in rows
        ]
