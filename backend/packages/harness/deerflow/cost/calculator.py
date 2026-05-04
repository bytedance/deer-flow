"""Cost calculator — computes USD cost from token usage and model pricing."""

from __future__ import annotations

from deerflow.config.cost_config import ModelPricing


class CostCalculator:
    """Calculates cost from token usage using model pricing config."""

    def __init__(self, pricing: list[ModelPricing]) -> None:
        self._pricing_map: dict[str, ModelPricing] = {p.model: p for p in pricing}

    def calculate(self, model_name: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost in USD for a single model call."""
        pricing = self._pricing_map.get(model_name)
        if pricing is None:
            return 0.0
        input_cost = (input_tokens / 1000) * pricing.input_per_1k_tokens
        output_cost = (output_tokens / 1000) * pricing.output_per_1k_tokens
        return round(input_cost + output_cost, 6)

    def get_pricing(self, model_name: str) -> ModelPricing | None:
        """Get pricing info for a model."""
        return self._pricing_map.get(model_name)
