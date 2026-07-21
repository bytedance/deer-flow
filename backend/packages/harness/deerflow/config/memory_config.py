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

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Host-shared MemoryConfig fields (read by every backend / call site / factory).
_SHARED_FIELDS = frozenset({"enabled", "mode", "injection_enabled", "shutdown_flush_timeout_seconds", "manager_class", "backend_config"})

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

    If no config file is on disk (tests, or a minimal deployment running purely
    on defaults / ``set_memory_config``), there is nothing to reload from, so we
    keep the pre-existing behavior of returning the in-memory singleton instead of
    becoming more fragile than before. The catch is deliberately narrow: a config
    file that exists but fails to load (malformed YAML, failed validation) is a
    real error and is surfaced here just as it is at every other unguarded
    ``get_app_config()`` call site, leaving the last-good singleton untouched.
    """
    # Lazy import: app_config imports this module, so a top-level import cycles.
    from .app_config import get_app_config

    try:
        get_app_config()
    except FileNotFoundError:
        pass
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
