"""Top-level ``typesafe:`` defaults shared by every TypeSafe (Jev) consumer.

The block supplies connection, model and timeout defaults; each consumer
overrides what it needs in its own ``config``. Precedence is consumer ``config``
> this block > built-in defaults (design §4 rule 1), applied by
``deerflow.typesafe.connection.resolve_connection``.

Deliberately absent, because they are adapter policy and not connection
defaults (design §4 rule 5): failure policy, cache semantics, thresholds, and the
question content. ``mode`` is a consumer's own switch, not a property of the
shared connection.

The block is optional. With no ``typesafe:`` key the built-in defaults apply and
every consumer behaves exactly as it did before this block existed.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TypeSafeConfig(BaseModel):
    """Defaults for the shared TypeSafe client; every field is optional."""

    api_key: str | None = Field(default=None, description="API key. Prefer api_key_env: a key here lives in config.yaml")
    api_key_env: str | None = Field(default=None, description="Environment variable holding the API key (default: TYPESAFE_API_KEY)")
    base_url: str | None = Field(default=None, description="API base URL (default: https://api.typesafe.ai)")
    model: str | None = Field(default=None, description="Model to ask for; TypeSafe returns the version it actually served")
    timeout: float | None = Field(default=None, description="Per-request timeout in seconds")
    deadline_seconds: float | None = Field(default=None, description="Whole-evaluation budget in seconds")
    max_attempts: int | None = Field(default=None, description="Attempts per evaluation, including the first (429/529 and transport errors only)")
    retry_backoff: float | None = Field(default=None, description="Base seconds of exponential backoff between attempts")

    def connection_defaults(self) -> dict[str, object]:
        """Only the fields this block actually sets; ``None`` means "not configured"."""
        return self.model_dump(exclude_none=True)


_typesafe_config: TypeSafeConfig = TypeSafeConfig()


def get_typesafe_config() -> TypeSafeConfig:
    """Get the top-level ``typesafe:`` defaults, returning an empty block when unset."""
    return _typesafe_config


def load_typesafe_config_from_dict(data: dict) -> TypeSafeConfig:
    """Load the top-level ``typesafe:`` block (called during AppConfig loading)."""
    global _typesafe_config
    _typesafe_config = TypeSafeConfig.model_validate(data)
    return _typesafe_config


def reset_typesafe_config() -> None:
    """Reset the cached block. Used in tests to prevent singleton leaks."""
    global _typesafe_config
    _typesafe_config = TypeSafeConfig()
