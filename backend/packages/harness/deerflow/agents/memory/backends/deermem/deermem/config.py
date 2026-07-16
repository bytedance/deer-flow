"""DeerMem backend configuration (parsed from ``MemoryConfig.backend_config``).

DeerMem-private config lives here, NOT on the shared ``MemoryConfig`` (which
only carries host-shared fields: ``enabled`` / ``injection_enabled`` /
``manager_class`` / ``backend_config``). The factory passes ``backend_config``
(a dict) to ``DeerMem.__init__``, which parses it into a ``DeerMemConfig``.
Defaults let DeerMem run with zero ``backend_config``.

Field names mirror the pre-abstraction ``MemoryConfig`` private fields so the
migration is a pure move (config.yaml ``memory.<field>`` ->
``memory.backend_config.<field>``). ``model`` is a nested ``DeerMemModelConfig``
(provider/model/api_key/base_url/temperature) consumed by ``core/llm.py``;
``tracing_callback`` (step 14) and ``should_keep_hidden_message`` (step 15) are
optional host-injected hooks (None = DeerMem defaults).
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class DeerMemModelConfig(BaseModel):
    """DeerMem's memory-update LLM config (langchain ``init_chat_model`` params)."""

    provider: str | None = Field(
        default=None,
        description="langchain model_provider, e.g. 'openai' (default when None). DeepSeek/other OpenAI-compatible gateways use 'openai' + base_url.",
    )
    model: str | None = Field(
        default=None,
        description="Model name. None = no LLM configured (non-LLM ops still work; an update raises).",
    )
    api_key: str | None = Field(default=None, description="API key (or rely on the provider's env var).")
    base_url: str | None = Field(default=None, description="Override base URL (e.g. an OpenAI-compatible gateway).")
    temperature: float | None = Field(default=None, description="Sampling temperature.")


class DeerMemConfig(BaseModel):
    """DeerMem-private configuration (self-contained, host-agnostic)."""

    # ── Storage ──────────────────────────────────────────────────────────
    storage_path: str = Field(
        default="",
        description=("DeerMem data root. Empty = default (``$DEERMEM_DATA_DIR`` or ``~/.deermem/``); per-user memory at ``{root}/users/{user_id}/memory.json``. Any value (absolute or relative) is used as the root directory."),
    )
    storage_class: str = Field(
        default="",
        description="Dotted class path for an alternative storage provider; empty (default) = FileMemoryStorage (no importlib, portable).",
    )
    # ── Queue ────────────────────────────────────────────────────────────
    debounce_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Seconds to wait before processing queued updates (debounce).",
    )
    # ── Facts ────────────────────────────────────────────────────────────
    max_facts: int = Field(default=100, ge=10, le=500, description="Maximum number of facts to store.")
    fact_confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold for storing facts.",
    )
    # ── Injection ────────────────────────────────────────────────────────
    max_injection_tokens: int = Field(
        default=2000,
        ge=100,
        le=8000,
        description="Maximum tokens to use for memory injection.",
    )
    token_counting: Literal["tiktoken", "char"] = Field(
        default="tiktoken",
        description=("Token counting strategy for memory-injection budgeting. 'tiktoken' is accurate but may download BPE data on first use; 'char' is network-free CJK-aware estimation."),
    )
    guaranteed_categories: list[str] = Field(
        default_factory=lambda: ["correction"],
        description="Fact categories always injected regardless of the regular token budget.",
    )
    guaranteed_token_budget: int = Field(
        default=500,
        ge=50,
        le=2000,
        description="Token ceiling for guaranteed-category facts.",
    )
    # ── Staleness review ─────────────────────────────────────────────────
    staleness_review_enabled: bool = Field(
        default=True,
        description="Enable staleness review for aged facts.",
    )
    staleness_age_days: int = Field(
        default=90,
        ge=30,
        le=365,
        description="Facts older than this become staleness-review candidates.",
    )
    staleness_min_candidates: int = Field(
        default=3,
        ge=1,
        le=50,
        description="Minimum stale facts required to trigger a review cycle.",
    )
    staleness_max_removals_per_cycle: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum facts the staleness review can remove per cycle.",
    )
    staleness_protected_categories: list[str] = Field(
        default_factory=lambda: ["correction"],
        description="Fact categories exempt from staleness review.",
    )
    # ── Memory consolidation ────────────────────────────────────────────
    consolidation_enabled: bool = Field(
        default=False,
        description=(
            "Enable memory consolidation. When enabled, the LLM reviews "
            "fragmented fact categories during the normal memory-update call "
            "(same invocation - no extra API call) and decides whether groups "
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
    # ── LLM (step 13: structured model sub-config consumed by core/llm.py build_llm) ──
    model: DeerMemModelConfig = Field(
        default_factory=DeerMemModelConfig,
        description=(
            "Memory-update LLM config (provider/model/api_key/base_url/temperature). "
            "Empty = the host factory injects its default chat model as ``host_llm`` "
            "(zero-config UX, mirrors pre-abstraction ``model_name: null``); "
            "when ``host_llm`` is also absent (standalone DeerMem) an update raises "
            "but non-LLM ops still work."
        ),
    )
    # ── Hooks (steps 14-15: optional host-injected callables; None = DeerMem defaults) ──
    tracing_callback: Any = Field(
        default=None,
        description=(
            "Optional observability callback (e.g. langfuse) invoked before the "
            "memory-update LLM call as "
            "``callback(invoke_config, *, thread_id, user_id, trace_id, model_name)``. "
            "None = no tracing (langfuse not hard-required). Set programmatically "
            "(callables cannot come from YAML)."
        ),
    )
    should_keep_hidden_message: Any = Field(
        default=None,
        description=("Optional ``hook(additional_kwargs) -> bool``; when set, ``hide_from_ui`` messages are kept if it returns True. None = skip all ``hide_from_ui`` (host-agnostic safe default). Set programmatically."),
    )
    host_llm: Any = Field(
        default=None,
        description=(
            "Host-injected pre-built chat model for memory extraction (zero-config "
            "UX). The deer-flow factory injects its default model here when "
            "``model`` is empty, mirroring pre-abstraction ``model_name: null`` -> "
            "app default. Takes precedence over ``build_llm(model)``. None = build "
            "from ``model`` (or no LLM when ``model`` is also empty). Set "
            "programmatically (an instance cannot come from YAML)."
        ),
    )
    trace_context_manager: Any = Field(
        default=None,
        description=(
            "Host-injected context-manager callable ``cm(trace_id)`` that binds "
            "``trace_id`` into the host request-trace ContextVar for the memory-"
            "update worker thread (Timer / executor), restoring structured-log "
            "trace correlation. None = no binding (DeerMem standalone; trace_id "
            "still reaches ``tracing_callback`` and the log message text). Set "
            "programmatically."
        ),
    )

    @classmethod
    def from_backend_config(cls, backend_config: dict[str, Any] | None) -> DeerMemConfig:
        """Parse a ``backend_config`` dict.

        Unknown keys are ignored (forward-compat) but logged at WARNING so a
        typo (e.g. ``storage_pat`` missing the ``h``) does not silently fall
        back to the default and write memory to an unintended location --
        mirrors the host layer's ``load_memory_config_from_dict`` warning.

        ``None`` values are dropped so they fall back to the field default:
        YAML renders an empty key (``model:`` with only commented children, as
        shipped in ``config.example.yaml``) as ``None``, which non-Optional
        fields like ``model`` would otherwise reject even though omitting the
        key entirely is valid.
        """
        if not backend_config:
            return cls()
        known = {k: v for k, v in backend_config.items() if k in cls.model_fields and v is not None}
        unknown = sorted(k for k in backend_config if k not in cls.model_fields)
        if unknown:
            logger.warning(
                "Unknown backend_config keys ignored by DeerMem; check for typos: %s",
                unknown,
            )
        return cls(**known)
