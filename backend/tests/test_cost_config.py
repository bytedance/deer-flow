"""Tests for CostConfig singleton pattern and defaults."""

import pytest

from deerflow.config.cost_config import (
    BudgetConfigModel,
    CostConfig,
    ModelPricing,
    get_cost_config,
    load_cost_config_from_dict,
    reset_cost_config,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_cost_config()
    yield
    reset_cost_config()


class TestCostConfigDefaults:
    def test_default_disabled(self):
        cfg = get_cost_config()
        assert cfg.enabled is False

    def test_default_storage_backend(self):
        cfg = get_cost_config()
        assert cfg.storage_backend == "json"

    def test_default_model_pricing_empty(self):
        cfg = get_cost_config()
        assert cfg.model_pricing == []

    def test_default_budget_limits(self):
        cfg = get_cost_config()
        assert cfg.budget.default_daily_limit_usd == 50.0
        assert cfg.budget.default_monthly_limit_usd == 1000.0
        assert cfg.budget.alert_threshold_pct == 0.8
        assert cfg.budget.action_on_exceed == "block"


class TestCostConfigLoad:
    def test_load_enables_cost(self):
        load_cost_config_from_dict({
            "enabled": True,
            "model_pricing": [
                {"model": "gpt-4", "input_per_1k_tokens": 0.03, "output_per_1k_tokens": 0.06}
            ],
            "budget": {
                "default_daily_limit_usd": 100.0,
                "default_monthly_limit_usd": 2000.0,
                "alert_threshold_pct": 0.9,
                "action_on_exceed": "warn",
            },
            "storage_backend": "json",
        })
        cfg = get_cost_config()
        assert cfg.enabled is True
        assert len(cfg.model_pricing) == 1
        assert cfg.model_pricing[0].model == "gpt-4"
        assert cfg.model_pricing[0].input_per_1k_tokens == 0.03
        assert cfg.budget.default_daily_limit_usd == 100.0
        assert cfg.budget.action_on_exceed == "warn"

    def test_singleton_persists(self):
        load_cost_config_from_dict({"enabled": True})
        assert get_cost_config().enabled is True

    def test_reset_clears_singleton(self):
        load_cost_config_from_dict({"enabled": True})
        reset_cost_config()
        assert get_cost_config().enabled is False


class TestModelPricing:
    def test_create_pricing(self):
        p = ModelPricing(model="test-model", input_per_1k_tokens=0.01, output_per_1k_tokens=0.02)
        assert p.model == "test-model"
        assert p.input_per_1k_tokens == 0.01
        assert p.output_per_1k_tokens == 0.02

    def test_default_zero_cost(self):
        p = ModelPricing(model="free-model")
        assert p.input_per_1k_tokens == 0.0
        assert p.output_per_1k_tokens == 0.0


class TestBudgetConfigModel:
    def test_defaults(self):
        b = BudgetConfigModel()
        assert b.default_daily_limit_usd == 50.0
        assert b.default_monthly_limit_usd == 1000.0
        assert b.alert_threshold_pct == 0.8
        assert b.action_on_exceed == "block"
