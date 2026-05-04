"""Tests for BudgetChecker."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from deerflow.config.cost_config import BudgetConfigModel
from deerflow.config.tenant import set_current_tenant_id
from deerflow.cost.budget import BudgetChecker, BudgetStatus
from deerflow.cost.storage import UsageRecord, UsageStorage


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def storage(temp_dir):
    set_current_tenant_id("test-tenant")
    return UsageStorage(base_dir=temp_dir)


@pytest.fixture
def budget_config():
    return BudgetConfigModel(
        default_daily_limit_usd=50.0,
        default_monthly_limit_usd=1000.0,
        alert_threshold_pct=0.8,
        action_on_exceed="block",
    )


class TestBudgetStatus:
    def test_fields(self):
        status = BudgetStatus(
            daily_cost=10.0, daily_limit=50.0, daily_remaining=40.0, daily_pct=20.0,
            monthly_cost=100.0, monthly_limit=1000.0, monthly_remaining=900.0, monthly_pct=10.0,
            is_exceeded=False, alert_triggered=False,
        )
        assert status.daily_cost == 10.0
        assert status.daily_limit == 50.0
        assert status.daily_remaining == 40.0
        assert status.daily_pct == 20.0
        assert status.monthly_cost == 100.0
        assert status.monthly_limit == 1000.0
        assert status.monthly_remaining == 900.0
        assert status.monthly_pct == 10.0
        assert status.is_exceeded is False
        assert status.alert_triggered is False


class TestBudgetChecker:
    def test_check_budget_within_limits(self, storage, budget_config):
        checker = BudgetChecker(storage, budget_config)
        status = checker.check_budget("test-tenant")
        assert status.daily_cost == 0.0
        assert status.daily_limit == 50.0
        assert status.daily_remaining == 50.0
        assert status.daily_pct == 0.0
        assert status.is_exceeded is False
        assert status.alert_triggered is False

    def test_check_budget_exceeded(self, storage, budget_config):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        storage.add_record(UsageRecord(
            timestamp=f"{today}T10:30:00", tenant_id="test-tenant", thread_id=None,
            model_name="gpt-4", input_tokens=100000, output_tokens=50000, total_tokens=150000, cost_usd=60.0,
        ))
        checker = BudgetChecker(storage, budget_config)
        status = checker.check_budget("test-tenant")
        assert status.daily_cost == 60.0
        assert status.is_exceeded is True

    def test_check_budget_alert_triggered(self, storage, budget_config):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        storage.add_record(UsageRecord(
            timestamp=f"{today}T10:30:00", tenant_id="test-tenant", thread_id=None,
            model_name="gpt-4", input_tokens=10000, output_tokens=5000, total_tokens=15000, cost_usd=45.0,
        ))
        checker = BudgetChecker(storage, budget_config)
        status = checker.check_budget("test-tenant")
        assert status.daily_pct == 90.0
        assert status.alert_triggered is True
        assert status.is_exceeded is False

    def test_would_exceed_budget_block_mode(self, storage, budget_config):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        storage.add_record(UsageRecord(
            timestamp=f"{today}T10:30:00", tenant_id="test-tenant", thread_id=None,
            model_name="gpt-4", input_tokens=10000, output_tokens=5000, total_tokens=15000, cost_usd=48.0,
        ))
        checker = BudgetChecker(storage, budget_config)
        assert checker.would_exceed_budget("test-tenant", estimated_cost=5.0) is True
        assert checker.would_exceed_budget("test-tenant", estimated_cost=1.0) is False

    def test_would_exceed_budget_warn_mode(self, storage):
        config = BudgetConfigModel(action_on_exceed="warn")
        checker = BudgetChecker(storage, config)
        assert checker.would_exceed_budget("test-tenant", estimated_cost=999.0) is False

    def test_zero_limits(self, storage):
        config = BudgetConfigModel(default_daily_limit_usd=0.0, default_monthly_limit_usd=0.0)
        checker = BudgetChecker(storage, config)
        status = checker.check_budget("test-tenant")
        assert status.daily_pct == 0.0
        assert status.monthly_pct == 0.0
