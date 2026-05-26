"""Configuration for domain memory mechanism."""

from pydantic import BaseModel, Field


class DomainDecayConfig(BaseModel):
    """Decay configuration for a specific domain."""

    policy: str = Field(
        default="never",
        description="Decay policy: 'never', 'linear', or 'exponential'",
    )
    half_life_days: float = Field(
        default=90.0,
        ge=1.0,
        le=3650.0,
        description="Half-life in days for decay calculation",
    )


class DomainMemoryConfig(BaseModel):
    """Configuration for domain-scoped memory with semantic search."""

    enabled: bool = Field(
        default=False,
        description="Whether to enable domain memory mechanism",
    )
    model_name: str | None = Field(
        default=None,
        description="Model name to use for domain fact extraction (None = use default model)",
    )
    debounce_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Seconds to wait before processing queued domain updates (debounce)",
    )
    fact_confidence_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold for storing domain facts",
    )
    injection_enabled: bool = Field(
        default=True,
        description="Whether to inject domain memory into system prompt",
    )
    max_injection_tokens: int = Field(
        default=1000,
        ge=100,
        le=8000,
        description="Maximum tokens to use for domain memory injection",
    )
    min_retrieval_score: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score for domain fact retrieval",
    )
    domains: dict[str, DomainDecayConfig] = Field(
        default_factory=dict,
        description="Per-domain decay configuration",
    )

    def get_domain_decay(self, domain: str) -> DomainDecayConfig:
        """Get decay config for a domain, returning default if not configured."""
        return self.domains.get(domain, DomainDecayConfig())


# Global configuration instance
_domain_memory_config: DomainMemoryConfig = DomainMemoryConfig()


def get_domain_memory_config() -> DomainMemoryConfig:
    """Get the current domain memory configuration."""
    return _domain_memory_config


def set_domain_memory_config(config: DomainMemoryConfig) -> None:
    """Set the domain memory configuration."""
    global _domain_memory_config
    _domain_memory_config = config


def load_domain_memory_config_from_dict(config_dict: dict) -> None:
    """Load domain memory configuration from a dictionary."""
    global _domain_memory_config
    _domain_memory_config = DomainMemoryConfig(**config_dict)
