"""Tests for CostCalculator."""

import pytest

from deerflow.config.cost_config import ModelPricing
from deerflow.cost.calculator import CostCalculator


class TestCostCalculator:
    def test_calculate_with_known_model(self):
        pricing = [
            ModelPricing(model="gpt-4", input_per_1k_tokens=0.03, output_per_1k_tokens=0.06),
        ]
        calc = CostCalculator(pricing)
        cost = calc.calculate("gpt-4", input_tokens=1000, output_tokens=500)
        assert cost == pytest.approx(0.06, rel=1e-4)

    def test_calculate_unknown_model_returns_zero(self):
        calc = CostCalculator([])
        cost = calc.calculate("unknown-model", input_tokens=1000, output_tokens=500)
        assert cost == 0.0

    def test_calculate_zero_tokens(self):
        pricing = [
            ModelPricing(model="gpt-4", input_per_1k_tokens=0.03, output_per_1k_tokens=0.06),
        ]
        calc = CostCalculator(pricing)
        cost = calc.calculate("gpt-4", input_tokens=0, output_tokens=0)
        assert cost == 0.0

    def test_calculate_fractional_tokens(self):
        pricing = [
            ModelPricing(model="gpt-4", input_per_1k_tokens=0.03, output_per_1k_tokens=0.06),
        ]
        calc = CostCalculator(pricing)
        cost = calc.calculate("gpt-4", input_tokens=500, output_tokens=250)
        assert cost == pytest.approx(0.03, rel=1e-4)

    def test_get_pricing_known_model(self):
        pricing = [
            ModelPricing(model="gpt-4", input_per_1k_tokens=0.03, output_per_1k_tokens=0.06),
        ]
        calc = CostCalculator(pricing)
        p = calc.get_pricing("gpt-4")
        assert p is not None
        assert p.input_per_1k_tokens == 0.03

    def test_get_pricing_unknown_model(self):
        calc = CostCalculator([])
        assert calc.get_pricing("nonexistent") is None

    def test_multiple_models(self):
        pricing = [
            ModelPricing(model="gpt-4", input_per_1k_tokens=0.03, output_per_1k_tokens=0.06),
            ModelPricing(model="gpt-3.5", input_per_1k_tokens=0.0015, output_per_1k_tokens=0.002),
        ]
        calc = CostCalculator(pricing)
        assert calc.calculate("gpt-4", input_tokens=1000, output_tokens=0) == 0.03
        assert calc.calculate("gpt-3.5", input_tokens=1000, output_tokens=0) == 0.0015
