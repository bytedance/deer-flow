"""Configuration for SafetyFinishReasonMiddleware.

Mirrors the shape of GuardrailsConfig: detectors are loaded by class path
through ``deerflow.reflection.resolve_variable`` (same loader the
``guardrails.provider`` config uses) so users can drop in custom provider
detectors without modifying core code.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SafetyDetectorConfig(BaseModel):
    """One detector entry under ``safety_finish_reason.detectors``."""

    use: str = Field(
        description=("Class path of a SafetyTerminationDetector implementation (e.g. 'deerflow.agents.middlewares.safety_termination_detectors:OpenAICompatibleContentFilterDetector')."),
    )
    config: dict = Field(
        default_factory=dict,
        description="Constructor kwargs passed to the detector class.",
    )


class SafetyFinishReasonConfig(BaseModel):
    """Configuration for the SafetyFinishReasonMiddleware.

    The middleware intercepts AIMessages where the provider signaled a
    safety-related termination (e.g. OpenAI ``finish_reason='content_filter'``)
    while still returning tool calls, and suppresses those tool calls so the
    half-truncated arguments never execute.
    """

    enabled: bool = Field(
        default=True,
        description="Master switch for the SafetyFinishReasonMiddleware.",
    )
    detectors: list[SafetyDetectorConfig] | None = Field(
        default=None,
        description=(
            "Custom detector list. Leave unset (None) to use the built-in "
            "set covering OpenAI-compatible content_filter, Anthropic "
            "refusal, and Gemini SAFETY/BLOCKLIST/PROHIBITED_CONTENT/SPII/"
            "RECITATION. Provide a non-null list to fully override."
        ),
    )
