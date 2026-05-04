"""Cost management configuration — token usage tracking, pricing, and budget control."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModelPricing(BaseModel):
    """Pricing for a specific model."""

    model: str = Field(..., description="Model name")
    input_per_1k_tokens: float = Field(default=0.0, description="Cost per 1000 input tokens in USD")
    output_per_1k_tokens: float = Field(default=0.0, description="Cost per 1000 output tokens in USD")


class BudgetConfigModel(BaseModel):
    """Budget limits and behavior."""

    default_daily_limit_usd: float = Field(default=50.0, description="Default daily cost limit per tenant in USD")
    default_monthly_limit_usd: float = Field(default=1000.0, description="Default monthly cost limit per tenant in USD")
    alert_threshold_pct: float = Field(default=0.8, description="Fraction of budget at which to trigger alerts")
    action_on_exceed: str = Field(default="block", description="Action when budget exceeded: block or warn")
    webhook_url: str = Field(default="", description="Webhook URL for budget alert notifications")


class CostConfig(BaseModel):
    """Configuration for cost management and budget control."""

    enabled: bool = Field(default=False, description="Enable cost tracking and budget control")
    model_pricing: list[ModelPricing] = Field(default_factory=list, description="Per-model pricing configuration")
    budget: BudgetConfigModel = Field(default_factory=BudgetConfigModel, description="Budget limits configuration")
    storage_backend: str = Field(default="json", description="Storage backend: json")


_cost_config: CostConfig | None = None


def get_cost_config() -> CostConfig:
    """Get the current cost config singleton."""
    global _cost_config
    if _cost_config is None:
        _cost_config = CostConfig()
    return _cost_config


def load_cost_config_from_dict(data: dict) -> CostConfig:
    """Load cost config from a dictionary."""
    global _cost_config
    _cost_config = CostConfig.model_validate(data)
    return _cost_config


def reset_cost_config() -> None:
    """Reset the cost config singleton."""
    global _cost_config
    _cost_config = None
