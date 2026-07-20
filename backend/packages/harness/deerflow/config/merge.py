"""Non-mutating configuration merge helpers for embedded DeerFlow users."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any


def deep_merge(file_config: Mapping[str, Any], code_config: Mapping[str, Any] | None) -> dict[str, Any]:
    """Recursively overlay user-supplied config on file-derived config.

    Mapping values are merged recursively; every other value (including lists)
    is replaced by the code value. Neither input is mutated.
    """
    merged = deepcopy(dict(file_config))
    if not code_config:
        return merged
    for key, code_value in code_config.items():
        file_value = merged.get(key)
        if isinstance(file_value, Mapping) and isinstance(code_value, Mapping):
            merged[key] = deep_merge(file_value, code_value)
        else:
            merged[key] = deepcopy(code_value)
    return merged
