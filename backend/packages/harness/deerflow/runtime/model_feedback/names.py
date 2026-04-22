"""Resolve and validate model names for feedback / counter keys."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def normalize_feedback_model_name(name: str) -> str:
    """Validate a counter key: non-empty, bounded length (matches configured model ``name``)."""
    s = str(name).strip()
    if not s or len(s) > 256:
        raise ValueError("model_name must be 1–256 non-empty characters")
    return s


def extract_model_name_from_run_config(config: dict[str, Any]) -> str | None:
    """Read ``model_name`` from RunnableConfig-like dict (``configurable`` or ``context``), else first configured model."""
    for block in (config.get("configurable"), config.get("context")):
        if not isinstance(block, dict):
            continue
        raw = block.get("model_name")
        if raw is None or raw == "":
            continue
        try:
            return normalize_feedback_model_name(str(raw))
        except ValueError:
            logger.debug("Ignoring invalid model_name in run config for model_feedback: %r", raw)
    try:
        from deerflow.config.app_config import get_app_config

        ac = get_app_config()
        if ac.models:
            return normalize_feedback_model_name(ac.models[0].name)
    except Exception:
        logger.debug("Could not resolve default model for model_feedback", exc_info=True)
    return None
