"""Confi for token budget middleware."""

from pydantic import BaseModel, Field, model_validator


class TokenBudgetConfig(BaseModel):
    """Configuration for per-run token budget enforcement."""

    enabled: bool = Field(default=False, description="Whether to enable per-run token budget enforcement.")
    max_tokens: int = Field(default=200000, ge=1000, description="Maximum total tokens (input + output) allowed per run.")
    max_input_tokens: int | None = Field(default=None, description="Optional seperate limit for input tokens only.")
    max_output_tokens: int | None = Field(default=None, description="Optional seperate limit for output tokens only.")
    warn_threshold: float = Field(default=0.8, ge=0.0, le=1.0, description="Fraction of max_tokens at which a soft warning is injected. E.g., 0.8 means warn at 80% of max_tokens")
    hard_stop_threshold: float = Field(default=1.0, ge=0.0, le=1.0, description=("Fraction of max_tokens at which tool calls are stipped and the agent is forced to produce a final answer.E.g., 1.0 means stop at 100% of max_tokens."))

    @model_validator(mode="after")
    def validate_thresholds(self) -> "TokenBudgetConfig":
        """Ensure hard stop cannot trigger before the warning."""
        if self.hard_stop_threshold < self.warn_threshold:
            raise ValueError("hard_stop_threshold must be >= warn_threshold")
        return self


_token_budget_config: TokenBudgetConfig = TokenBudgetConfig()


def get_token_budget_config() -> TokenBudgetConfig:
    """Get the current token budget configuration."""
    return _token_budget_config


def set_token_budget_config(config: TokenBudgetConfig) -> None:
    """Set the token budget configuration."""
    global _token_budget_config
    _token_budget_config = config


def load_token_budget_config_from_dict(config_dict: dict) -> None:
    """Load token budget configuration from a dictionary."""
    global _token_budget_config
    _token_budget_config = TokenBudgetConfig(**config_dict)
