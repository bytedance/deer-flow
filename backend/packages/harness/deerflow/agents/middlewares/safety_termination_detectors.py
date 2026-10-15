"""Detectors for provider-side safety termination signals.

Different LLM providers signal "I stopped this response for safety reasons"
through different fields with different values. This module defines a small
strategy interface and three built-in detectors that cover the major
providers DeerFlow supports today. New providers (Wenxin, Hunyuan, Bedrock
adapters, in-house gateways, ...) can be added by implementing
``SafetyTerminationDetector`` and wiring it through
``config.yaml: safety_finish_reason.detectors``.

The middleware that consumes these detectors lives in
``safety_finish_reason_middleware.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from langchain_core.messages import AIMessage


@dataclass(frozen=True)
class SafetyTermination:
    """A detected safety-related termination signal.

    Attributes:
        detector: Name of the detector that produced this result. Used for
            observability so operators can see which provider rule fired.
        reason_field: The message metadata field that carried the signal
            (e.g. ``finish_reason``, ``stop_reason``).
        reason_value: The actual value of that field
            (e.g. ``content_filter``, ``refusal``, ``SAFETY``).
        extras: Provider-specific metadata that may help downstream
            consumers (e.g. Azure OpenAI content_filter_results, Gemini
            safety_ratings). Detectors are free to populate or skip this.
    """

    detector: str
    reason_field: str
    reason_value: str
    extras: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SafetyTerminationDetector(Protocol):
    """Strategy interface for provider safety termination detection."""

    name: str

    def detect(self, message: AIMessage) -> SafetyTermination | None:
        """Return a SafetyTermination if *message* indicates provider safety
        termination, otherwise return ``None``.

        Implementations must be side-effect free and tolerant of missing or
        oddly-typed metadata — detectors run on every model response.
        """
        ...


def _get_metadata_value(message: AIMessage, field_name: str) -> str | None:
    """Read a string-typed value from either ``response_metadata`` or
    ``additional_kwargs``.

    LangChain provider adapters are inconsistent about where they stash
    provider stop signals. Most modern adapters use ``response_metadata``,
    but some legacy / passthrough paths still surface them via
    ``additional_kwargs``. We check both, in that order, and only accept
    string values — Pydantic enums or dicts are ignored so we never raise
    on malformed inputs.
    """
    for container_name in ("response_metadata", "additional_kwargs"):
        container = getattr(message, container_name, None) or {}
        if not isinstance(container, dict):
            continue
        value = container.get(field_name)
        if isinstance(value, str) and value:
            return value
    return None


class OpenAICompatibleContentFilterDetector:
    """OpenAI-compatible content_filter signal.

    Covers OpenAI, Azure OpenAI, Moonshot/Kimi, DeepSeek, Mistral, vLLM,
    Qwen (OpenAI-compatible mode), and any other adapter that follows the
    OpenAI ``finish_reason`` convention.

    Some Chinese providers ship custom OpenAI-compatible gateways that use
    alternative tokens like ``sensitive`` or ``violation``. Extend the set
    via the ``finish_reasons`` kwarg in config.
    """

    name = "openai_compatible_content_filter"

    def __init__(self, finish_reasons: list[str] | tuple[str, ...] | None = None) -> None:
        configured = finish_reasons if finish_reasons is not None else ("content_filter",)
        self._finish_reasons: frozenset[str] = frozenset(r.lower() for r in configured)

    def detect(self, message: AIMessage) -> SafetyTermination | None:
        value = _get_metadata_value(message, "finish_reason")
        if value is None or value.lower() not in self._finish_reasons:
            return None

        extras: dict[str, Any] = {}
        # Azure OpenAI ships a structured content_filter_results block; carry it
        # through so operators can see *what* was filtered without re-tracing.
        response_metadata = getattr(message, "response_metadata", None) or {}
        if isinstance(response_metadata, dict):
            filter_results = response_metadata.get("content_filter_results")
            if filter_results:
                extras["content_filter_results"] = filter_results

        return SafetyTermination(
            detector=self.name,
            reason_field="finish_reason",
            reason_value=value,
            extras=extras,
        )


class AnthropicRefusalDetector:
    """Anthropic ``stop_reason == "refusal"`` signal.

    Anthropic models surface safety refusals via a dedicated ``stop_reason``
    rather than ``finish_reason``. See:
    https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/handle-streaming-refusals
    """

    name = "anthropic_refusal"

    def __init__(self, stop_reasons: list[str] | tuple[str, ...] | None = None) -> None:
        configured = stop_reasons if stop_reasons is not None else ("refusal",)
        self._stop_reasons: frozenset[str] = frozenset(r.lower() for r in configured)

    def detect(self, message: AIMessage) -> SafetyTermination | None:
        value = _get_metadata_value(message, "stop_reason")
        if value is None or value.lower() not in self._stop_reasons:
            return None
        return SafetyTermination(
            detector=self.name,
            reason_field="stop_reason",
            reason_value=value,
        )


class GeminiSafetyDetector:
    """Gemini / Vertex AI safety-related finish reasons.

    Gemini uses the same ``finish_reason`` field as OpenAI but with an
    enumerated upper-case taxonomy. The default set covers every Gemini
    finish_reason that means "the model stopped because the content/image
    tripped a safety, blocklist, recitation, or PII filter" — i.e. cases
    where any tool_calls returned alongside are likely truncated/
    unreliable. Full enum:
    https://docs.cloud.google.com/python/docs/reference/aiplatform/latest/google.cloud.aiplatform_v1.types.Candidate.FinishReason

    Intentionally **excluded** from the default set:
    - ``STOP``                       — normal termination.
    - ``MAX_TOKENS``                 — output length truncation, not safety
                                       (same root failure mode as
                                       content_filter, but issue #3028
                                       scopes it out; expose separately if
                                       desired).
    - ``LANGUAGE`` / ``NO_IMAGE``    — capability mismatches, unrelated to
                                       safety; tool_calls would be absent
                                       anyway.
    - ``MALFORMED_FUNCTION_CALL`` /
      ``UNEXPECTED_TOOL_CALL``       — tool-call protocol errors. The
                                       tool_calls are *also* unreliable
                                       here, but the failure category is
                                       distinct from safety filtering;
                                       handle in a dedicated detector to
                                       keep observability records honest.
    - ``OTHER`` / ``IMAGE_OTHER`` /
      ``FINISH_REASON_UNSPECIFIED``  — too broad to enable by default;
                                       opt in via ``finish_reasons=`` if
                                       your provider abuses these.
    """

    name = "gemini_safety"

    _DEFAULT_FINISH_REASONS = (
        # Text safety
        "SAFETY",
        "BLOCKLIST",
        "PROHIBITED_CONTENT",
        "SPII",
        "RECITATION",
        # Image safety (multimodal generation)
        "IMAGE_SAFETY",
        "IMAGE_PROHIBITED_CONTENT",
        "IMAGE_RECITATION",
    )

    def __init__(self, finish_reasons: list[str] | tuple[str, ...] | None = None) -> None:
        configured = finish_reasons if finish_reasons is not None else self._DEFAULT_FINISH_REASONS
        self._finish_reasons: frozenset[str] = frozenset(r.upper() for r in configured)

    def detect(self, message: AIMessage) -> SafetyTermination | None:
        value = _get_metadata_value(message, "finish_reason")
        if value is None or value.upper() not in self._finish_reasons:
            return None

        extras: dict[str, Any] = {}
        response_metadata = getattr(message, "response_metadata", None) or {}
        if isinstance(response_metadata, dict):
            # Gemini surfaces per-category scoring under safety_ratings.
            ratings = response_metadata.get("safety_ratings")
            if ratings:
                extras["safety_ratings"] = ratings

        return SafetyTermination(
            detector=self.name,
            reason_field="finish_reason",
            reason_value=value,
            extras=extras,
        )


def default_detectors() -> list[SafetyTerminationDetector]:
    """Built-in detector set used when no custom detectors are configured."""
    return [
        OpenAICompatibleContentFilterDetector(),
        AnthropicRefusalDetector(),
        GeminiSafetyDetector(),
    ]


__all__ = [
    "AnthropicRefusalDetector",
    "GeminiSafetyDetector",
    "OpenAICompatibleContentFilterDetector",
    "SafetyTermination",
    "SafetyTerminationDetector",
    "default_detectors",
]
