"""Configuration for the memory mechanism (host-shared fields only).
DeerMem-private fields live in ``backends/deermem/config.py`` (``DeerMemConfig``),
reached via ``backend_config`` (a dict the factory passes to the backend's
``__init__``). This module holds ONLY the host-shared fields every backend /
call site / factory reads: ``enabled`` / ``injection_enabled`` /
``shutdown_flush_timeout_seconds`` / ``manager_class`` / ``backend_config``.
Keeping the shared schema slim is what
makes backends swappable and portable (DeerMem's knobs do not leak onto the
shared contract).
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

# Host-shared MemoryConfig fields (read by every backend / call site / factory).
_SHARED_FIELDS = frozenset({"enabled", "mode", "injection_enabled", "shutdown_flush_timeout_seconds", "manager_class", "backend_config", "prescreen", "signal_classification"})

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


class MemoryPrescreenConfig(BaseModel):
    """Host-shared pre-screen slot: a cost gate over the extraction call.

    ``off`` (default) resolves no class path, constructs nothing and validates no
    credentials, so an unconfigured deployment behaves exactly as before.
    ``shadow`` decides and records without changing anything; ``enforce`` may
    actually skip the extraction call, which requires the measured gate in the
    pre-screening design §5.
    """

    mode: Literal["off", "shadow", "enforce"] = Field(default="off", description="off = no request and no behavior change; shadow = decide + record; enforce = a skip actually saves the extraction call")
    use: str | None = Field(default=None, description="Provider class path, e.g. deerflow.agents.memory.prescreen.typesafe:TypeSafeMemoryPrescreen")
    config: dict[str, Any] = Field(default_factory=dict, description="Provider-specific settings passed as kwargs")


class MemorySignalClassificationConfig(BaseModel):
    """Host-shared signal-classification slot: additive hint labels (and one narrow veto).

    ``hints`` merges the model's labels into the extraction hint text and may veto
    a pre-screen skip under ``prescreen.mode: enforce``. It never decides
    extraction on its own and never drives deletion.
    """

    mode: Literal["off", "shadow", "hints"] = Field(default="off", description="off = no request; shadow = record only; hints = merge labels into the hint text (and, under pre-screen enforce, allow a veto)")
    use: str | None = Field(default=None, description="Provider class path, e.g. deerflow.agents.memory.signals.typesafe:TypeSafeSignalClassifier")
    combine: Literal["auto", "always", "never"] = Field(
        default="auto", description="Request combination with the pre-screen: auto shares when every effective client setting matches, always requires it, never splits every side into its own request"
    )
    config: dict[str, Any] = Field(default_factory=dict, description="Provider-specific settings passed as kwargs")


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

    prescreen: MemoryPrescreenConfig = Field(
        default_factory=MemoryPrescreenConfig,
        description="Pre-extraction cost gate (off by default): decide whether a batch is worth an extraction call.",
    )
    signal_classification: MemorySignalClassificationConfig = Field(
        default_factory=MemorySignalClassificationConfig,
        description="Signal-classification hints (off by default): reinforcement/correction labels from the batch text, plus a narrow veto over a pre-screen skip.",
    )

    @model_validator(mode="after")
    def _check_judging_slots_are_usable(self) -> MemoryConfig:
        """A configured judging slot must name a provider (fail fast, never silently off).

        An enabled mode without ``use`` would look configured while doing nothing.
        The provider's own validation (credentials, thresholds, limits) runs when
        the memory backend is built, so a bad deployment fails there rather than
        on the first batch.
        """
        for name, slot in (("prescreen", self.prescreen), ("signal_classification", self.signal_classification)):
            if slot.mode != "off" and not slot.use:
                raise ValueError(f"memory.{name}.use is required when mode={slot.mode!r}")
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
