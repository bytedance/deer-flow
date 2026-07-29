"""Configuration for the memory mechanism (host-shared fields only).

DeerMem-private fields live in ``backends/deermem/config.py`` (``DeerMemConfig``),
reached via ``backend_config`` (a dict the factory passes to the backend's
``__init__``). This module holds ONLY the host-shared fields every backend /
call site / factory reads: ``enabled`` / ``mode`` / ``injection_enabled`` /
``shutdown_flush_timeout_seconds`` / ``manager_class`` / ``backend_config``.
Keeping the shared schema slim is what makes backends swappable and portable
(DeerMem's knobs do not leak onto the shared contract).
"""

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

# Host-shared MemoryConfig fields (read by every backend / call site / factory).
_SHARED_FIELDS = frozenset(
    {
        "enabled",
        "mode",
        "injection_enabled",
        "shutdown_flush_timeout_seconds",
        "manager_class",
        "backend_config",
        # Issue #4495 retrieval-strategy fields: host-shared because they drive
        # both the DeerMem backend *and* prompt.py's prompt-injection ranking
        # (which is backend-agnostic code).
        "retrieval_strategy",
        "retrieval_relevance_weight",
        "retrieval_confidence_weight",
        "retrieval_diversity_weight",
        "retrieval_top_k",
        "retrieval_duplicate_threshold",
    }
)

# DeerMem-private fields that used to live at the top level of `memory:` in
# config.yaml (pre-abstraction). On load they are auto-migrated into
# `backend_config` so an upgrade does NOT silently revert customized settings
# to defaults. `model_name` maps to `backend_config.model.model` (the new nested
# model sub-config); the rest are 1:1.
_LEGACY_DEERMEM_FIELDS = frozenset(
    {
        "storage_path",
        "storage_class",
        "debounce_seconds",
        "max_facts",
        "fact_confidence_threshold",
        "max_injection_tokens",
        "token_counting",
        "guaranteed_categories",
        "guaranteed_token_budget",
        "staleness_review_enabled",
        "staleness_age_days",
        "staleness_min_candidates",
        "staleness_max_removals_per_cycle",
        "staleness_protected_categories",
        "staleness_max_lifetime_multiplier",
        "staleness_max_extension_days",
        "consolidation_enabled",
        "consolidation_min_facts",
        "consolidation_max_groups_per_cycle",
        "consolidation_max_sources",
        "model_name",
    }
)


class MemoryConfig(BaseModel):
    """Host-shared memory configuration (backend-agnostic)."""

    enabled: bool = Field(
        default=True,
        description="Whether to enable the memory mechanism (call-site gate).",
    )
    mode: Literal["middleware", "tool"] = Field(
        default="middleware",
        description=(
            "Memory operation mode. 'middleware': passive LLM summarization after each turn (current behavior). 'tool': model calls memory tools (memory_search, memory_add, etc.) directly. Mutually exclusive — only one mode runs at a time."
        ),
    )
    injection_enabled: bool = Field(
        default=True,
        description="Whether to inject memory into the system prompt (call-site gate).",
    )
    shutdown_flush_timeout_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description=(
            "Hard time budget (seconds) for draining the memory backend's "
            "pending-update buffer during Gateway graceful shutdown. The drain "
            "makes one LLM call per pending item, so large IM batches may need "
            "a higher value. Must fit inside the pod's K8s "
            "terminationGracePeriodSeconds (together with channel/scheduler "
            "stop) or K8s SIGKILLs the drain mid-flight. The drain runs on a "
            "daemon thread, so on timeout the process proceeds to exit and any "
            "unfinished tail is dropped (same failure direction as no flush, "
            "scoped to the tail). Host-shared (not backend-private): the host "
            "owns the lifespan budget and the K8s grace relationship."
        ),
    )
    manager_class: str = Field(
        default="deermem",
        description=(
            "Memory backend selector. Either a registered backend name "
            "(matching a `backends/<name>/` folder that exposes `MANAGER_CLASS`, "
            "e.g. `deermem` / `noop`) or a dotted import path to a "
            "`MemoryManager` subclass. The factory resolves this at "
            "`get_memory_manager()` time and raises `ValueError` on failure "
            "(fail-fast: memory is persistent state, so an unresolved "
            "manager_class is not silently substituted with a different "
            "storage backend)."
        ),
    )
    # ── Issue #4495: relevance-aware retrieval strategy ──────────────────

    retrieval_strategy: Literal["legacy", "relevance"] = Field(
        default="legacy",
        description=(
            "Fact ranking strategy applied to BOTH (a) the `memory_search` tool/backend "
            "search and (b) prompt-injection fact selection. "
            "'legacy' = confidence-descending only (original DeerFlow semantics; fully "
            "backward-compatible; no token-cost change). "
            "'relevance' = lexical-relevance + confidence-weighted composite score with "
            "optional near-duplicate diversification. Deterministic, pure-token-based. "
            "No vector DB, no embedding API, no changes to persisted format."
        ),
    )
    retrieval_relevance_weight: float = Field(
        default=0.6,
        ge=0.0,
        le=100.0,
        description=(
            "Relative weight of the lexical relevance term in the composite rank. "
            "Weights are *ratio* weights and are normalised to sum to 1 at call time, "
            "so `60,40` and `0.6,0.4` both yield the same ranking. Only used when "
            "`retrieval_strategy='relevance'`. Default 0.6 => relevance slightly beats "
            "confidence (matches the score laid out in `docs/MEMORY_IMPROVEMENTS.md` §Planned scoring)."
        ),
    )
    retrieval_confidence_weight: float = Field(
        default=0.4,
        ge=0.0,
        le=100.0,
        description="Relative weight of the fact-confidence term in the composite rank. Only used when `retrieval_strategy='relevance'`.",
    )
    retrieval_diversity_weight: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description=(
            "Relative weight of the greedy near-duplicate penalty. 0.0 disables "
            "diversification entirely (no dedup, backward-compatible token reuse). "
            "Values >0 penalise facts whose token-overlap with already-selected facts "
            "exceeds `retrieval_duplicate_threshold`. Typical range for noticeable "
            "dedup is 0.15–0.3. Only used when `retrieval_strategy='relevance'`."
        ),
    )
    retrieval_top_k: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Optional hard cap on the number of ranked facts BEFORE token-budget "
            "selection in prompt injection, and BEFORE the existing top_k slice in "
            "memory_search. Applied after category filtering + composite ranking. "
            "`None` (default) = no hard cap; existing token-budget / call-site top_k "
            "semantics are unchanged. Lets operators trim tail noise without touching "
            "`max_injection_tokens` or the caller's own `top_k`."
        ),
    )
    retrieval_duplicate_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description=(
            "For strategy='relevance' AND `diversity_weight>0`: normalised Dice "
            "similarity threshold above which two facts are considered near-duplicate "
            "and the later-ranked one is penalised/skipped. 0.7 = 70%+ shared tokens "
            "triggers dedup. Lower = more aggressive dedup. 1.0 = identical tokens "
            "only. Typical range 0.55–0.85."
        ),
    )

    backend_config: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Backend-private config (a dict), passed verbatim to the backend's "
            "`__init__(backend_config=...)` by the factory. Each backend "
            "self-interprets it (DeerMem parses it into `DeerMemConfig`). Values "
            "live in the host config file (`config.yaml` `memory.backend_config`); "
            "they do not belong on the shared `MemoryConfig` schema."
        ),
    )

    @model_validator(mode="after")
    def _normalize_retrieval_weights(self) -> "MemoryConfig":
        """Normalise retrieval weights to a finite ratio.

        The three retrieval weights (*relevance*, *confidence*, *diversity*) are
        ratio weights, not absolute percentage weights. After Pydantic's numeric
        coercions, clamp each to ``>=0`` and, if their sum is strictly positive,
        divide by the sum so downstream code can rely on them summing to 1.0 and
        never producing NaN composites. If every weight is zero (the operator
        explicitly disabled everything) fall back to confidence-only =
        relevance 0 / confidence 1 / diversity 0, which is equivalent to the
        legacy strategy.
        """
        rw = max(0.0, float(self.retrieval_relevance_weight))
        cw = max(0.0, float(self.retrieval_confidence_weight))
        dw = max(0.0, float(self.retrieval_diversity_weight))
        total = rw + cw + dw
        if total <= 0.0:
            object.__setattr__(self, "retrieval_relevance_weight", 0.0)
            object.__setattr__(self, "retrieval_confidence_weight", 1.0)
            object.__setattr__(self, "retrieval_diversity_weight", 0.0)
        else:
            object.__setattr__(self, "retrieval_relevance_weight", rw / total)
            object.__setattr__(self, "retrieval_confidence_weight", cw / total)
            object.__setattr__(self, "retrieval_diversity_weight", dw / total)
        return self


def should_use_memory_tools(config: MemoryConfig) -> bool:
    """Return True when memory should use model-directed tools."""
    return config.enabled and config.mode == "tool"


# Global configuration instance
_memory_config: MemoryConfig = MemoryConfig()


def get_memory_config() -> MemoryConfig:
    """Get the current memory configuration.

    ``_memory_config`` is only refreshed as a side effect of ``get_app_config()``
    reloading (via ``_apply_singleton_configs`` -> ``load_memory_config_from_dict``).
    A reader that reaches memory config without going through ``get_app_config()``
    first -- e.g. the agent factory deciding whether to bind the memory tools --
    would otherwise see a stale ``memory.mode`` after a ``config.yaml`` edit, even
    though ``memory.*`` is documented as hot-reloadable. Trigger the same
    signature-checked reload here so the singleton follows the config file.

    If ``get_app_config()`` has never been called (``_app_config`` is ``None``),
    there is no stale config to refresh, so we keep the pre-existing behaviour
    of returning the in-memory singleton.  This avoids picking up a config file
    as a side effect of the first access to ``get_memory_config()``, which would
    break callers that expect module-level defaults (e.g. unit tests).
    """
    # Lazy import: app_config imports this module, so a top-level import cycles.
    from .app_config import _app_config, get_app_config

    if _app_config is not None:
        try:
            get_app_config()
        except Exception:
            # If the config file is transiently broken (invalid YAML, schema
            # violation, missing env var, etc.), keep the last-good singleton
            # so an in-flight turn completes normally instead of crashing.
            logger.warning(
                "Failed to reload app config from get_memory_config(); falling back to cached memory config.",
                exc_info=True,
            )
    return _memory_config


def set_memory_config(config: MemoryConfig) -> None:
    """Set the memory configuration."""
    global _memory_config
    _memory_config = config


def load_memory_config_from_dict(config_dict: dict) -> None:
    """Load memory configuration from a dictionary.

    Host-shared fields (``enabled`` / ``mode`` / ``injection_enabled`` /
    ``manager_class`` / ``backend_config``) are read directly. DeerMem-private
    fields that used to live at the top level of ``memory:`` in config.yaml
    (pre-abstraction: ``storage_path``, ``max_facts``, ``debounce_seconds``,
    ``model_name``, ``token_counting``, ``staleness_*``, ``consolidation_*``,
    ...) are **auto-migrated into ``backend_config``** with a warning, so an
    upgrade from a pre-abstraction config does NOT silently revert customized
    settings to defaults. Unknown top-level keys (likely typos) are warned and
    ignored.
    """
    global _memory_config
    config_dict = dict(config_dict or {})
    backend_config = dict(config_dict.get("backend_config") or {})
    migrated: list[str] = []
    for key in list(config_dict.keys()):
        if key in _SHARED_FIELDS:
            continue
        if key in _LEGACY_DEERMEM_FIELDS:
            value = config_dict.pop(key)
            if value is None or value == "":
                continue  # default / empty value, no migration needed
            if key == "model_name":
                # old top-level model_name -> backend_config.model.model
                model_cfg = dict(backend_config.get("model") or {})
                if "model" not in model_cfg:
                    model_cfg["model"] = value
                    backend_config["model"] = model_cfg
                    migrated.append(f"{key} -> backend_config.model.model")
            elif key == "storage_path" and str(value).endswith(".json"):
                # Pre-abstraction storage_path was a FILE path (absolute = shared
                # file opting out of per-user; a relative value like the old default
                # "memory.json" was ignored for per-user). DeerMem now treats it as a
                # root DIRECTORY. Carrying a file-style value verbatim would be
                # resolved as a dir and either orphan per-user memory or hit
                # NotADirectoryError on save. Drop it so the factory's zero-config
                # runtime_home kicks in (per-user location unchanged:
                # {base_dir}/users/{uid}/memory.json) and warn the operator.
                logger.warning(
                    "Legacy memory.storage_path=%r looks like a file path; DeerMem now "
                    "treats storage_path as a root DIRECTORY (per-user memory under "
                    "{storage_path}/users/{uid}/memory.json). Dropped -- memory now "
                    "lands under the default root (runtime_home). Set "
                    "memory.backend_config.storage_path to a directory if you want a "
                    "custom location.",
                    value,
                )
            elif key not in backend_config:
                # don't override an explicit backend_config value
                backend_config[key] = value
                migrated.append(f"{key} -> backend_config.{key}")
        else:
            logger.warning(
                "Unknown memory config key %r at top level (not a shared field %s nor a known legacy DeerMem field); ignored.",
                key,
                sorted(_SHARED_FIELDS),
            )
    if migrated:
        logger.warning(
            "Migrated legacy top-level memory fields into backend_config; move them under memory.backend_config in config.yaml to silence this: %s",
            ", ".join(migrated),
        )
    config_dict["backend_config"] = backend_config
    _memory_config = MemoryConfig(**config_dict)
