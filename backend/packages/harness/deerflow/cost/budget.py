"""Budget checker — monitors spending against configured limits."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from deerflow.config.cost_config import BudgetConfigModel
from deerflow.cost.storage import UsageStorage


@dataclass
class BudgetStatus:
    """Current budget status for a tenant."""

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


class BudgetChecker:
    """Checks whether operations are within budget limits."""

    def __init__(self, storage: UsageStorage, budget_config: BudgetConfigModel) -> None:
        self.storage = storage
        self.config = budget_config

    def check_budget(self, tenant_id: str) -> BudgetStatus:
        """Check current budget status for a tenant."""
        daily_cost = self.storage.get_today_total()
        monthly_cost = self.storage.get_current_month_total()

        daily_limit = self.config.default_daily_limit_usd
        monthly_limit = self.config.default_monthly_limit_usd

        daily_remaining = max(0.0, daily_limit - daily_cost)
        monthly_remaining = max(0.0, monthly_limit - monthly_cost)

        daily_pct = (daily_cost / daily_limit * 100) if daily_limit > 0 else 0.0
        monthly_pct = (monthly_cost / monthly_limit * 100) if monthly_limit > 0 else 0.0

        threshold = self.config.alert_threshold_pct
        is_exceeded = daily_cost >= daily_limit or monthly_cost >= monthly_limit
        alert_triggered = daily_pct >= threshold * 100 or monthly_pct >= threshold * 100

        return BudgetStatus(
            daily_cost=round(daily_cost, 4),
            daily_limit=daily_limit,
            daily_remaining=round(daily_remaining, 4),
            daily_pct=round(daily_pct, 1),
            monthly_cost=round(monthly_cost, 4),
            monthly_limit=monthly_limit,
            monthly_remaining=round(monthly_remaining, 4),
            monthly_pct=round(monthly_pct, 1),
            is_exceeded=is_exceeded,
            alert_triggered=alert_triggered,
        )

    def would_exceed_budget(self, tenant_id: str, estimated_cost: float) -> bool:
        """Check if an estimated cost would exceed remaining budget."""
        status = self.check_budget(tenant_id)
        if self.config.action_on_exceed == "block":
            return estimated_cost > status.daily_remaining or estimated_cost > status.monthly_remaining
        return False
