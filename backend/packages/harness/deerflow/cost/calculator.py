"""Cost calculator — computes USD cost from token usage and model pricing."""

from __future__ import annotations

from deerflow.config.cost_config import ModelPricing


class CostCalculator:
    """Calculates cost from token usage using model pricing config."""

    def __init__(self, pricing: list[ModelPricing]) -> None:
        self._pricing_map: dict[str, ModelPricing] = {p.model: p for p in pricing}

    def _resolve_pricing(self, model_name: str) -> ModelPricing | None:
        """Resolve pricing for a model name, supporting prefix matching.

        Handles date-suffixed model names like ``gpt-5.4-2026-03-05`` by
        falling back to prefix match against configured pricing entries.
        """
        pricing = self._pricing_map.get(model_name)
        if pricing is not None:
            return pricing
        for key, p in self._pricing_map.items():
            if model_name.startswith(key) or key.startswith(model_name):
                return p
        return None

    def calculate(self, model_name: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost in USD for a single model call."""
        pricing = self._resolve_pricing(model_name)
        if pricing is None:
            return 0.0
        input_cost = (input_tokens / 1000) * pricing.input_per_1k_tokens
        output_cost = (output_tokens / 1000) * pricing.output_per_1k_tokens
        return round(input_cost + output_cost, 6)

    def get_pricing(self, model_name: str) -> ModelPricing | None:
        """Get pricing info for a model."""
        return self._resolve_pricing(model_name)
