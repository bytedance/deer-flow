"""Detectors for provider-side model length termination signals.

Different providers report "the response hit the output-token limit" through
different fields and values. Keep those provider details here so
``ModelLengthFinishReasonMiddleware`` can stay focused on when to mark a run,
not on which provider emitted which spelling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from langchain_core.messages import AIMessage


@dataclass(frozen=True)
class ModelLengthTermination:
    """A detected model-output length cap."""

    detector: str
    reason_field: str
    reason_value: str
    extras: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ModelLengthTerminationDetector(Protocol):
    """Strategy interface for provider length-cap detection."""

    name: str

    def detect(self, message: AIMessage) -> ModelLengthTermination | None:
        """Return a hit when *message* indicates output length truncation."""
        ...


def _get_metadata_value(message: AIMessage, field_name: str) -> str | None:
    """Read a string metadata value from common LangChain provider fields."""
    for container_name in ("response_metadata", "additional_kwargs"):
        container = getattr(message, container_name, None) or {}
        if not isinstance(container, dict):
            continue
        value = container.get(field_name)
        if isinstance(value, str) and value:
            return value
    return None


class OpenAICompatibleLengthDetector:
    """OpenAI-compatible ``finish_reason == "length"`` signal."""

    name = "openai_compatible_length"

    def __init__(self, finish_reasons: list[str] | tuple[str, ...] | None = None) -> None:
        configured = finish_reasons if finish_reasons is not None else ("length",)
        self._finish_reasons: frozenset[str] = frozenset(r.lower() for r in configured)

    def detect(self, message: AIMessage) -> ModelLengthTermination | None:
        value = _get_metadata_value(message, "finish_reason")
        if value is None or value.lower() not in self._finish_reasons:
            return None
        return ModelLengthTermination(
            detector=self.name,
            reason_field="finish_reason",
            reason_value=value,
        )


class AnthropicMaxTokensDetector:
    """Anthropic ``stop_reason == "max_tokens"`` signal."""

    name = "anthropic_max_tokens"

    def __init__(self, stop_reasons: list[str] | tuple[str, ...] | None = None) -> None:
        configured = stop_reasons if stop_reasons is not None else ("max_tokens",)
        self._stop_reasons: frozenset[str] = frozenset(r.lower() for r in configured)

    def detect(self, message: AIMessage) -> ModelLengthTermination | None:
        value = _get_metadata_value(message, "stop_reason")
        if value is None or value.lower() not in self._stop_reasons:
            return None
        return ModelLengthTermination(
            detector=self.name,
            reason_field="stop_reason",
            reason_value=value,
        )


class GeminiMaxTokensDetector:
    """Gemini / Vertex AI ``finish_reason == "MAX_TOKENS"`` signal."""

    name = "gemini_max_tokens"

    def __init__(self, finish_reasons: list[str] | tuple[str, ...] | None = None) -> None:
        configured = finish_reasons if finish_reasons is not None else ("MAX_TOKENS",)
        self._finish_reasons: frozenset[str] = frozenset(r.upper() for r in configured)

    def detect(self, message: AIMessage) -> ModelLengthTermination | None:
        value = _get_metadata_value(message, "finish_reason")
        if value is None or value.upper() not in self._finish_reasons:
            return None
        return ModelLengthTermination(
            detector=self.name,
            reason_field="finish_reason",
            reason_value=value,
        )


def default_detectors() -> list[ModelLengthTerminationDetector]:
    """Built-in detector set used for provider length-cap signals."""
    return [
        OpenAICompatibleLengthDetector(),
        AnthropicMaxTokensDetector(),
        GeminiMaxTokensDetector(),
    ]


__all__ = [
    "AnthropicMaxTokensDetector",
    "GeminiMaxTokensDetector",
    "ModelLengthTermination",
    "ModelLengthTerminationDetector",
    "OpenAICompatibleLengthDetector",
    "default_detectors",
]
