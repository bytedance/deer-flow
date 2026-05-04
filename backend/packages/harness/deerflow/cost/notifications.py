"""Budget alert webhook notifications — sends alerts when spending thresholds are crossed."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import httpx

from deerflow.config.cost_config import BudgetConfigModel
from deerflow.cost.budget import BudgetStatus

logger = logging.getLogger(__name__)

# Track sent alerts to avoid duplicates within the same budget period
_sent_alerts: dict[str, str] = {}


class BudgetNotifier:
    """Sends webhook notifications when budget alerts are triggered.

    Deduplicates alerts so each budget period (daily/monthly) only
    triggers one notification.
    """

    def __init__(self, budget_config: BudgetConfigModel) -> None:
        self._config = budget_config
        self._webhook_url = getattr(budget_config, "webhook_url", "")

    def _alert_key(self, tenant_id: str, period: str) -> str:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        period_value = today if period == "daily" else month
        return f"{tenant_id}:{period}:{period_value}"

    def _should_send(self, tenant_id: str, period: str) -> bool:
        key = self._alert_key(tenant_id, period)
        if _sent_alerts.get(key) == self._webhook_url:
            return False
        _sent_alerts[key] = self._webhook_url
        # Clean up stale keys (older than current period)
        to_remove = [k for k in _sent_alerts if not k.startswith(f"{tenant_id}:{period}:")]
        for k in to_remove:
            _sent_alerts.pop(k, None)
        return True

    def send_alert(self, tenant_id: str, status: BudgetStatus) -> None:
        """Send a budget alert webhook synchronously (fire-and-forget style)."""
        if not self._webhook_url:
            return

        if not status.alert_triggered:
            return

        period = "daily" if status.daily_pct >= status.monthly_pct else "monthly"
        if not self._should_send(tenant_id, period):
            return

        payload = {
            "event": "budget_alert",
            "tenant_id": tenant_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "daily": {
                "cost": status.daily_cost,
                "limit": status.daily_limit,
                "remaining": status.daily_remaining,
                "pct": status.daily_pct,
            },
            "monthly": {
                "cost": status.monthly_cost,
                "limit": status.monthly_limit,
                "remaining": status.monthly_remaining,
                "pct": status.monthly_pct,
            },
            "is_exceeded": status.is_exceeded,
        }

        try:
            resp = httpx.post(
                self._webhook_url,
                json=payload,
                timeout=10.0,
            )
            if resp.status_code >= 400:
                logger.warning("Budget webhook returned %d: %s", resp.status_code, resp.text[:200])
            else:
                logger.info("Budget alert sent to webhook for tenant %s", tenant_id)
        except Exception:
            logger.exception("Failed to send budget alert webhook for tenant %s", tenant_id)

    async def asend_alert(self, tenant_id: str, status: BudgetStatus) -> None:
        """Send a budget alert webhook asynchronously."""
        if not self._webhook_url:
            return

        if not status.alert_triggered:
            return

        period = "daily" if status.daily_pct >= status.monthly_pct else "monthly"
        if not self._should_send(tenant_id, period):
            return

        payload = {
            "event": "budget_alert",
            "tenant_id": tenant_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "daily": {
                "cost": status.daily_cost,
                "limit": status.daily_limit,
                "remaining": status.daily_remaining,
                "pct": status.daily_pct,
            },
            "monthly": {
                "cost": status.monthly_cost,
                "limit": status.monthly_limit,
                "remaining": status.monthly_remaining,
                "pct": status.monthly_pct,
            },
            "is_exceeded": status.is_exceeded,
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self._webhook_url,
                    json=payload,
                    timeout=10.0,
                )
                if resp.status_code >= 400:
                    logger.warning("Budget webhook returned %d: %s", resp.status_code, resp.text[:200])
                else:
                    logger.info("Budget alert sent to webhook for tenant %s", tenant_id)
        except Exception:
            logger.exception("Failed to send budget alert webhook for tenant %s", tenant_id)
