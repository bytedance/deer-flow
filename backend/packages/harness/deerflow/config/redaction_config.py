from typing import Any

from pydantic import BaseModel, Field


class RedactionConfig(BaseModel):
    """Configuration for the redaction middleware."""

    enabled: bool = Field(default=False, description="Enable or disable redaction middleware.")
    redact_string: str = Field(default="[REDACTED]", description="String used to replace matched sensitive tokens.")
    patterns: list[str] = Field(
        default_factory=lambda: [
            r"(?i)bearer\s+[A-Za-z0-9\-\._~\+/]+",  # Bearer tokens
            r"(?i)api[_-]?key\s*[:=]\s*['\"]?[A-Za-z0-9\-\._]+['\"]?",  # API Keys
            r"(?i)sk-[a-zA-Z0-9]{32,}",  # OpenAI style secret keys
            r"gh[po]_[a-zA-Z0-9]{36}",  # GitHub tokens
            r"(?i)password\s*[:=]\s*['\"]?[^'\"]+['\"]?",  # Passwords
            r"eyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_.+/=]*",  # JWT tokens
        ],
        description="List of regex patterns to identify and redact sensitive information.",
    )


_redaction_config: RedactionConfig | None = None


def get_redaction_config() -> RedactionConfig:
    """Get the global redaction configuration."""
    global _redaction_config
    if _redaction_config is None:
        return RedactionConfig()
    return _redaction_config


def load_redaction_config_from_dict(config_data: dict[str, Any] | None) -> RedactionConfig:
    """Load and set the global redaction configuration from a dictionary.

    Args:
        config_data: The dictionary containing the redaction configuration.

    Returns:
        The loaded RedactionConfig.
    """
    global _redaction_config
    if config_data is None:
        _redaction_config = RedactionConfig()
    else:
        _redaction_config = RedactionConfig(**config_data)

    return _redaction_config
