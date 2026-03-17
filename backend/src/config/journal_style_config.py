"""Configuration for journal-specific writing style alignment."""

from pydantic import BaseModel, Field


class JournalStyleConfig(BaseModel):
    """Configuration for journal style few-shot collection and alignment."""

    enabled: bool = Field(
        default=False,
        description="Whether to enable journal-specific style alignment for manuscript compilation.",
    )
    sample_size: int = Field(
        default=5,
        ge=1,
        le=10,
        description="How many high-citation recent papers to collect as few-shot samples.",
    )
    recent_year_window: int = Field(
        default=5,
        ge=1,
        le=15,
        description="How many recent years to search when collecting journal samples.",
    )
    cache_ttl_hours: int = Field(
        default=24,
        ge=1,
        le=168,
        description="Cache TTL in hours for fetched journal style bundles.",
    )
    request_timeout_seconds: int = Field(
        default=12,
        ge=3,
        le=60,
        description="HTTP timeout in seconds for OpenAlex requests.",
    )
    max_excerpt_chars: int = Field(
        default=420,
        ge=120,
        le=2000,
        description="Maximum characters kept from each abstract excerpt in few-shot prompts.",
    )


_journal_style_config: JournalStyleConfig = JournalStyleConfig()


def get_journal_style_config() -> JournalStyleConfig:
    """Get current journal style configuration."""
    return _journal_style_config


def set_journal_style_config(config: JournalStyleConfig) -> None:
    """Set journal style configuration."""
    global _journal_style_config
    _journal_style_config = config


def load_journal_style_config_from_dict(config_dict: dict) -> None:
    """Load journal style configuration from dictionary."""
    global _journal_style_config
    _journal_style_config = JournalStyleConfig(**config_dict)
