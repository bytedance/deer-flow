"""Cost management API router — usage summary, breakdown, and budget control."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.gateway.auth.dependencies import get_current_user, require_admin
from deerflow.config.cost_config import BudgetConfigModel, get_cost_config
from deerflow.cost.budget import BudgetChecker, BudgetStatus
from deerflow.cost.calculator import CostCalculator
from deerflow.cost.notifications import BudgetNotifier
from deerflow.cost.storage import UsageRecord, UsageStorage

router = APIRouter(prefix="/api/cost", tags=["cost"])


class CostSummaryResponse(BaseModel):
    today_cost_usd: float
    month_cost_usd: float
    total_cost_usd: float
    today_tokens: int
    month_tokens: int


class CostBreakdownItem(BaseModel):
    date: str
    model_name: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class BudgetStatusResponse(BaseModel):
    daily_cost: float
    daily_limit: float
    daily_remaining: float
    daily_pct: float
    monthly_cost: float
    monthly_limit: float
    monthly_remaining: float
    monthly_pct: float
    is_exceeded: bool
    alert_triggered: bool


class UpdateBudgetRequest(BaseModel):
    daily_limit_usd: float | None = Field(default=None, description="New daily limit in USD")
    monthly_limit_usd: float | None = Field(default=None, description="New monthly limit in USD")
    alert_threshold_pct: float | None = Field(default=None, description="Alert threshold fraction (0-1)")
    action_on_exceed: str | None = Field(default=None, description="Action: block or warn")


def _get_storage() -> UsageStorage:
    return UsageStorage()


def _get_checker() -> BudgetChecker:
    config = get_cost_config()
    return BudgetChecker(_get_storage(), config.budget)


@router.get("/summary", response_model=CostSummaryResponse)
def get_cost_summary(user=Depends(get_current_user)) -> CostSummaryResponse:
    """Get cost summary: today, this month, and all-time totals."""
    config = get_cost_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Cost management is not enabled")

    storage = _get_storage()
    today_cost = storage.get_today_total()
    month_cost = storage.get_current_month_total()
    today_tokens = storage.get_total_tokens_today()
    month_tokens = storage.get_total_tokens_month()

    all_records = storage.query()
    total_cost = sum(r.cost_usd for r in all_records)

    return CostSummaryResponse(
        today_cost_usd=round(today_cost, 4),
        month_cost_usd=round(month_cost, 4),
        total_cost_usd=round(total_cost, 4),
        today_tokens=today_tokens,
        month_tokens=month_tokens,
    )


@router.get("/breakdown", response_model=list[CostBreakdownItem])
def get_cost_breakdown(
    start_date: str | None = None,
    end_date: str | None = None,
    model: str | None = None,
    user=Depends(get_current_user),
) -> list[CostBreakdownItem]:
    """Get cost breakdown by date and model."""
    config = get_cost_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Cost management is not enabled")

    storage = _get_storage()
    records = storage.query(start_date=start_date, end_date=end_date, model_name=model)

    return [
        CostBreakdownItem(
            date=r.timestamp[:10],
            model_name=r.model_name,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
            cost_usd=r.cost_usd,
        )
        for r in records
    ]


@router.get("/budget", response_model=BudgetStatusResponse)
def get_budget_status(user=Depends(get_current_user)) -> BudgetStatusResponse:
    """Get current budget status."""
    config = get_cost_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Cost management is not enabled")

    checker = _get_checker()
    status = checker.check_budget(user.tenant_id)

    if status.alert_triggered:
        notifier = BudgetNotifier(config.budget)
        notifier.send_alert(user.tenant_id, status)

    return BudgetStatusResponse(
        daily_cost=status.daily_cost,
        daily_limit=status.daily_limit,
        daily_remaining=status.daily_remaining,
        daily_pct=status.daily_pct,
        monthly_cost=status.monthly_cost,
        monthly_limit=status.monthly_limit,
        monthly_remaining=status.monthly_remaining,
        monthly_pct=status.monthly_pct,
        is_exceeded=status.is_exceeded,
        alert_triggered=status.alert_triggered,
    )


@router.put("/budget", response_model=BudgetStatusResponse)
def update_budget(req: UpdateBudgetRequest, user=Depends(require_admin)) -> BudgetStatusResponse:
    """Update budget limits (admin only)."""
    config = get_cost_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Cost management is not enabled")

    if req.daily_limit_usd is not None:
        config.budget.default_daily_limit_usd = req.daily_limit_usd
    if req.monthly_limit_usd is not None:
        config.budget.default_monthly_limit_usd = req.monthly_limit_usd
    if req.alert_threshold_pct is not None:
        config.budget.alert_threshold_pct = req.alert_threshold_pct
    if req.action_on_exceed is not None:
        config.budget.action_on_exceed = req.action_on_exceed

    checker = _get_checker()
    status = checker.check_budget(user.tenant_id)

    if status.alert_triggered:
        notifier = BudgetNotifier(config.budget)
        notifier.send_alert(user.tenant_id, status)

    return BudgetStatusResponse(
        daily_cost=status.daily_cost,
        daily_limit=status.daily_limit,
        daily_remaining=status.daily_remaining,
        daily_pct=status.daily_pct,
        monthly_cost=status.monthly_cost,
        monthly_limit=status.monthly_limit,
        monthly_remaining=status.monthly_remaining,
        monthly_pct=status.monthly_pct,
        is_exceeded=status.is_exceeded,
        alert_triggered=status.alert_triggered,
    )
