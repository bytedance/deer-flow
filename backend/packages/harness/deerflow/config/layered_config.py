"""LayeredAppConfig — deep-merge YAML config files across identity layers.

Merge order: global → dept → user → agent (last value wins).
"""
from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig
    from deerflow.identity.agent_identity import AgentIdentity

logger = logging.getLogger(__name__)


# ── Deep merge helpers ────────────────────────────────────────────────────────


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into *base*, returning a new dict.

    - Scalar values in *override* replace those in *base*.
    - Nested dicts are merged recursively.
    - Lists are handled by `_merge_named_list` if elements have a ``name`` key,
      otherwise the override list replaces the base list entirely.
    """
    result: dict[str, Any] = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        elif key in result and isinstance(result[key], list) and isinstance(value, list):
            result[key] = _merge_named_list(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _merge_named_list(base: list[Any], override: list[Any]) -> list[Any]:
    """Merge two lists of dicts by the ``name`` key (last override wins for each name).

    Items in *override* whose ``name`` matches an existing item replace that item.
    Items with new names are appended.  Items without a ``name`` key cause the
    entire override list to replace the base list (fallback to simple replace).
    """
    # If any element lacks a 'name' key, fall back to simple replacement
    all_have_name = all(isinstance(item, dict) and "name" in item for item in base + override)
    if not all_have_name:
        return copy.deepcopy(override)

    result_map: dict[str, Any] = {item["name"]: copy.deepcopy(item) for item in base}
    for item in override:
        name = item["name"]
        if name in result_map:
            result_map[name] = _deep_merge(result_map[name], item)
        else:
            result_map[name] = copy.deepcopy(item)
    # Preserve original ordering (base items first, then new items from override)
    base_names = [item["name"] for item in base]
    new_names = [item["name"] for item in override if item["name"] not in result_map or item["name"] not in base_names]
    ordered_names = base_names + [n for n in new_names if n not in base_names]
    # Any name from override that's not already in ordered_names
    for item in override:
        if item["name"] not in ordered_names:
            ordered_names.append(item["name"])
    return [result_map[n] for n in ordered_names if n in result_map]


# ── YAML loading helpers ──────────────────────────────────────────────────────


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file, returning an empty dict if it doesn't exist."""
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("Failed to load layered config %s: %s", path, exc)
        return {}


# ── Public API ────────────────────────────────────────────────────────────────


def load_layered_config_dict(identity: "AgentIdentity") -> dict[str, Any]:
    """Return the merged raw config dict for the given identity.

    Loads each config.yaml in the identity hierarchy and deep-merges them in
    order (global → dept → user → agent).  The result is a plain dict; callers
    are responsible for constructing an ``AppConfig`` from it.
    """
    from deerflow.config.paths import get_paths

    paths = get_paths()
    config_files = paths.identity_config_files(identity)

    merged: dict[str, Any] = {}
    for path in config_files:
        layer = _load_yaml(path)
        if layer:
            logger.debug("Applying config layer: %s", path)
            merged = _deep_merge(merged, layer)

    return merged


def load_layered_app_config(identity: "AgentIdentity") -> "AppConfig":
    """Load a merged AppConfig for the given identity.

    When identity is global (no dept/user), returns the cached global AppConfig
    (same as ``get_app_config()``).  When identity specifies at least a dept or
    user, deep-merges all applicable config.yaml layers and validates the result
    as an AppConfig.

    Falls back to ``get_app_config()`` if any layer fails to load.
    """
    from deerflow.config.app_config import AppConfig, get_app_config

    if identity.is_global:
        return get_app_config()

    merged = load_layered_config_dict(identity)
    if not merged:
        return get_app_config()

    try:
        # Start from global config dict as base so unset fields keep their defaults
        global_dict = _load_yaml(_get_global_config_path())
        full_merged = _deep_merge(global_dict, merged) if global_dict else merged
        return AppConfig.model_validate(full_merged)
    except Exception as exc:
        logger.warning("Failed to build layered AppConfig for %s, falling back to global: %s", identity, exc)
        return get_app_config()


def _get_global_config_path() -> "Path":
    from deerflow.config.paths import get_paths
    return get_paths().base_dir.parent / "config.yaml"
