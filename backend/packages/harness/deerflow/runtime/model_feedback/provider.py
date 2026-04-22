"""Gateway lifespan: construct the configured model feedback store."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator

from deerflow.config.app_config import get_app_config
from deerflow.runtime.model_feedback.factory import native_model_feedback_store
from deerflow.runtime.model_feedback.registry import set_model_feedback_store
from deerflow.runtime.model_feedback.types import ModelFeedbackStore

logger = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def make_model_feedback_store() -> AsyncIterator[ModelFeedbackStore | None]:
    """Yield the feedback store from ``model_feedback`` config, or ``None`` when disabled / unset."""
    cfg = get_app_config().model_feedback
    if cfg is None or not cfg.enabled:
        set_model_feedback_store(None)
        logger.info("Model feedback: disabled (no section or enabled=false)")
        yield None
        return

    async with native_model_feedback_store(cfg) as store:
        set_model_feedback_store(store)
        yield store
    set_model_feedback_store(None)
