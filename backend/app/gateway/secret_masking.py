"""Shared masking for credential values that Gateway routes echo back from config."""

import re
from collections.abc import Callable
from typing import Any

MASKED_VALUE = "***"


def normalize_config_key(key: str) -> str:
    """Snake-case a config key so ``apiKey``, ``API-Key`` and ``api_key`` compare equal."""
    with_boundaries = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", key)
    with_boundaries = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", with_boundaries)
    return re.sub(r"[^a-z0-9]+", "_", with_boundaries.lower()).strip("_")


def mask_secret_values(value: Any, is_secret_key: Callable[[str], bool], *, keep_unset: bool = False) -> Any:
    """Return a copy of ``value`` with every value under a secret-named key masked, at any depth.

    A secret-named key masks its whole value, containers included: a
    ``credentials`` mapping can hold keys under arbitrary names, so masking only
    its secret-named leaves could pass one through. With ``keep_unset``, a
    ``None`` or ``""`` value stays as it is, so a response still shows that no
    secret is configured.
    """
    if isinstance(value, dict):
        return {key: MASKED_VALUE if is_secret_key(str(key)) and not (keep_unset and nested in (None, "")) else mask_secret_values(nested, is_secret_key, keep_unset=keep_unset) for key, nested in value.items()}
    if isinstance(value, list):
        return [mask_secret_values(item, is_secret_key, keep_unset=keep_unset) for item in value]
    return value
