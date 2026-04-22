"""Process-wide handle to the active :class:`ModelFeedbackStore` (set by gateway lifespan)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deerflow.runtime.model_feedback.types import ModelFeedbackStore

_feedback_store: ModelFeedbackStore | None = None


def set_model_feedback_store(store: ModelFeedbackStore | None) -> None:
    global _feedback_store
    _feedback_store = store


def get_model_feedback_store() -> ModelFeedbackStore | None:
    return _feedback_store
