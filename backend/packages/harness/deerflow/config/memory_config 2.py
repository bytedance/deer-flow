"""Configuration for memory mechanism."""

from typing import Literal

from pydantic import BaseModel, Field


class MemoryConfig(BaseModel):
    """Configuration for global memory mechanism."""

    enabled: bool = Field(
        default=True,
        description="Whether to enable memory mechanism",
    )
    storage_path: str = Field(
        default="",
        description=(
            "Path to store memory data. "
            "If empty, defaults to per-user memory at `{base_dir}/users/{user_id}/memory.json`. "
            "Absolute paths are used as-is and opt out of per-user isolation "
            "(all users share the same file). "
            "Relative paths are resolved against `Paths.base_dir` "
            "(not the backend working directory). "
            "Note: if you previously set this to `.deer-flow/memory.json`, "
            "the file will now be resolved as `{base_dir}/.deer-flow/memory.json`; "
            "migrate existing data or use an absolute path to preserve the old location."
        ),
    )
    storage_class: str = Field(
        default="deerflow.agents.memory.storage.FileMemoryStorage",
        description="The class path for memory storage provider",
    )
    debounce_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Seconds to wait before processing queued updates (debounce)",
    )
    model_name: str | None = Field(
        default=None,
        description="Model name to use for memory updates (None = use default model)",
    )
    max_facts: int = Field(
        default=100,
        ge=10,
        le=500,
        description="Maximum number of facts to store",
    )
    fact_confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold for storing facts",
    )
    mode: Literal["middleware", "tool"] = Field(
        default="middleware",
        description=(
            "Memory operation mode. 'middleware': passive LLM summarization after each turn (current behavior). 'tool': model calls memory tools (memory_search, memory_add, etc.) directly. Mutually exclusive — only one mode runs at a time."
        ),
    )
    injection_enabled: bool = Field(
        default=True,
        description="Whether to inject memory into system prompt",
    )
    max_injection_tokens: int = Field(
        default=2000,
        ge=100,
        le=8000,
        description="Maximum tokens to use for memory injection",
    )
    token_counting: Literal["tiktoken", "char"] = Field(
        default="tiktoken",
        description=(
            "Token counting strategy for memory-injection budgeting. "
            "'tiktoken' is accurate but the encoding's BPE data may be "
            "downloaded from a public network endpoint on first use, which "
            "can block for a long time in network-restricted environments "
            "(see issue #3402/#3429). 'char' uses a network-free "
            "CJK-aware character-based estimate and never touches tiktoken."
        ),
    )
    guaranteed_categories: list[str] = Field(
        default_factory=lambda: ["correction"],
        description=(
            "Fact categories that are always injected into the prompt regardless "
            "of the regular token budget. These facts are allocated from a "
            "separate reserved budget (``guaranteed_token_budget``). "
            "This ensures high-value facts such as explicit user corrections "
            "are never silently dropped when the token budget is tight."
        ),
    )
    guaranteed_token_budget: int = Field(
        default=500,
        ge=50,
        le=2000,
        description=(
            "Token ceiling for guaranteed-category facts. "
            "Guaranteed facts are selected first from this budget and placed at "
            "the front of the Facts block so they cannot be evicted by regular "
            "facts. In the common case the total output still fits within "
            "``max_injection_tokens`` (guaranteed lines displace regular ones); "
            "the budget becomes additive only when guaranteed lines alone push "
            "the output past ``max_injection_tokens``, in which case the "
            "safety-truncation ceiling is raised accordingly."
        ),
    )
    # ── Staleness review ────────────────────────────────────────────────
    staleness_review_enabled: bool = Field(
        default=True,
        description=(
            "Enable staleness review for aged facts. When enabled, facts older "
            "than ``staleness_age_days`` are surfaced in the memory-update prompt "
            "so the LLM can semantically judge whether each is still valid or "
            "should be removed. This solves the 'silent staleness' problem where "
            "outdated facts persist because no future conversation explicitly "
            "contradicts them."
        ),
    )
    staleness_age_days: int = Field(
        default=90,
        ge=30,
        le=365,
        description=("Facts older than this many days become candidates for staleness review. 90 days (~one quarter) balances between catching genuine changes (job switches, tech-stack migrations) and avoiding noise on stable facts."),
    )
    staleness_min_candidates: int = Field(
        default=3,
        ge=1,
        le=50,
        description=("Minimum number of stale facts required to trigger a review cycle. Below this threshold the prompt overhead is not justified."),
    )
    staleness_max_removals_per_cycle: int = Field(
        default=10,
        ge=1,
        le=50,
        description=("Maximum number of facts the staleness review can remove in a single update cycle. Prevents the LLM from over-pruning when reviewing a large backlog of aged facts."),
    )
    staleness_protected_categories: list[str] = Field(
        default_factory=lambda: ["correction"],
        description=("Fact categories exempt from staleness review. Correction facts represent explicit user feedback and should not be auto-pruned based on age alone."),
    )

    # ── Memory consolidation ────────────────────────────────────────────
    consolidation_enabled: bool = Field(
        default=False,
        description=(
            "Enable memory consolidation. When enabled, the LLM reviews "
            "fragmented fact categories during the normal memory-update call "
            "(same invocation — no extra API call) and decides whether groups "
            "of related facts can be synthesized into a single richer fact. "
            "Defaults to False because consolidation is lossy (source content "
            "is not preserved, only consolidatedFrom IDs). Opt in explicitly "
            "once the memory-file backup / audit story is in place."
        ),
    )
    consolidation_min_facts: int = Field(
        default=8,
        ge=3,
        le=30,
        description=("Minimum number of facts in a single category to trigger consolidation review. Below this threshold the overhead of surfacing the group is not justified."),
    )
    consolidation_max_groups_per_cycle: int = Field(
        default=3,
        ge=1,
        le=10,
        description=("Maximum number of consolidation groups the LLM can merge in a single update cycle. Prevents over-consolidation."),
    )
    consolidation_max_sources: int = Field(
        default=8,
        ge=2,
        le=20,
        description=("Maximum number of source facts per consolidation group. Prevents the LLM from merging too many facts into one and losing important details."),
    )


def should_use_memory_tools(config: MemoryConfig) -> bool:
    """Return True when memory should use model-directed tools."""
    return config.enabled and config.mode == "tool"


# Global configuration instance
_memory_config: MemoryConfig = MemoryConfig()


def get_memory_config() -> MemoryConfig:
    """Get the current memory configuration."""
    return _memory_config


def set_memory_config(config: MemoryConfig) -> None:
    """Set the memory configuration."""
    global _memory_config
    _memory_config = config


def load_memory_config_from_dict(config_dict: dict) -> None:
    """Load memory configuration from a dictionary."""
    global _memory_config
    _memory_config = MemoryConfig(**config_dict)
