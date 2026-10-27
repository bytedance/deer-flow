"""Normalized model reasoning capability contract (issue #5073).

Every model creation path — the lead agent, subagents, summarization, title
generation, one-shot utilities — used to interpret ``supports_thinking`` /
``supports_reasoning_effort`` on its own and then hand generic
``thinking_enabled`` / ``reasoning_effort`` values to the factory. That could
not describe models whose provider contract differs from the generic
assumptions (required thinking, restricted effort vocabularies, provider
specific payload dialects).

This module owns the single normalized view:

* :func:`resolve_reasoning_contract` turns a :class:`ModelConfig` (or any
  duck-typed profile) into an immutable :class:`ReasoningContract`. Profiles
  that declare ``reasoning:`` map 1:1; legacy profiles derive the contract from
  the booleans and keep their historical, non-strict behavior.
* :func:`resolve_reasoning_request` applies a caller's generic request to the
  contract and returns the effective ``thinking_enabled`` and provider effort
  value. It is the one policy the factory and the callers share.
* :func:`reasoning_capabilities_payload` projects the contract for the
  Gateway ``/api/models`` response and ``DeerFlowClient``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

from deerflow.config.model_config import ReasoningCapabilities

ThinkingMode = Literal["unsupported", "optional", "required"]
DisableRequestPolicy = Literal["keep_enabled", "reject"]
ReasoningDialect = Literal["auto", "openai_extra_body", "anthropic", "vllm_chat_template", "ollama", "none"]
ReasoningHistory = Literal["preserve", "clear"]
ContractSource = Literal["legacy", "contract"]

#: The vocabulary DeerFlow's generic UI and per-agent defaults emit. Legacy
#: profiles advertise exactly this set so the frontend keeps its old choices.
GENERIC_EFFORT_VALUES: tuple[str, ...] = ("minimal", "low", "medium", "high")

#: Constructor keyword the OpenAI-compatible clients accept for effort.
DEFAULT_EFFORT_PATH = "reasoning_effort"


class ReasoningPolicyError(ValueError):
    """A request contradicts the model's reasoning contract and must not reach the provider."""


@dataclass(frozen=True)
class EffortContract:
    """Allowed effort values for one model.

    ``strict`` distinguishes a declared contract (unknown values never reach the
    provider) from the legacy projection (values are forwarded verbatim, as
    they always were).
    """

    values: tuple[str, ...]
    default: str | None = None
    aliases: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    path: str = DEFAULT_EFFORT_PATH
    strict: bool = True


@dataclass(frozen=True)
class ReasoningContract:
    """Normalized reasoning capabilities of one model profile."""

    thinking: ThinkingMode
    effort: EffortContract | None
    on_disable_request: DisableRequestPolicy = "keep_enabled"
    dialect: ReasoningDialect = "auto"
    history: ReasoningHistory | None = None
    source: ContractSource = "legacy"

    @property
    def supports_thinking(self) -> bool:
        return self.thinking != "unsupported"

    @property
    def thinking_required(self) -> bool:
        return self.thinking == "required"

    @property
    def supports_reasoning_effort(self) -> bool:
        return self.effort is not None


@dataclass(frozen=True)
class ResolvedReasoning:
    """The effective policy for one model call.

    ``adjustments`` lists what the contract changed about the request so
    callers can log it: ``thinking_unsupported``, ``thinking_forced_on``,
    ``effort_unsupported``, ``effort_aliased``, ``effort_unsupported_value``.
    """

    thinking_enabled: bool
    reasoning_effort: str | None
    adjustments: tuple[str, ...] = ()


def resolve_reasoning_contract(model_config: Any) -> ReasoningContract:
    """Normalize a model profile into a :class:`ReasoningContract`.

    Accepts a real :class:`ModelConfig` as well as duck-typed stand-ins (the
    subagent descriptor builder and several tests pass ``SimpleNamespace`` or
    mocks). Only a genuine :class:`ReasoningCapabilities` instance counts as a
    declared contract; anything else falls back to the legacy booleans.
    """
    declared = getattr(model_config, "reasoning", None)
    if isinstance(declared, ReasoningCapabilities):
        effort = None
        if declared.effort is not None:
            effort = EffortContract(
                values=tuple(declared.effort.values),
                default=declared.effort.default,
                aliases=MappingProxyType(dict(declared.effort.aliases)),
                path=declared.effort.path,
                strict=True,
            )
        return ReasoningContract(
            thinking=declared.thinking,
            effort=effort,
            on_disable_request=declared.on_disable_request,
            dialect=declared.dialect,
            history=declared.history,
            source="contract",
        )

    supports_thinking = bool(getattr(model_config, "supports_thinking", False))
    supports_effort = bool(getattr(model_config, "supports_reasoning_effort", False))
    return ReasoningContract(
        thinking="optional" if supports_thinking else "unsupported",
        effort=EffortContract(values=GENERIC_EFFORT_VALUES, strict=False) if supports_effort else None,
        source="legacy",
    )


def resolve_reasoning_request(contract: ReasoningContract, *, thinking_enabled: bool, reasoning_effort: str | None) -> ResolvedReasoning:
    """Apply a generic request to the contract.

    Raises:
        ReasoningPolicyError: the model requires thinking, the caller asked for
            it to be off, and the profile chose ``on_disable_request: reject``.
    """
    adjustments: list[str] = []

    if contract.thinking == "unsupported":
        if thinking_enabled:
            adjustments.append("thinking_unsupported")
        effective_thinking = False
    elif contract.thinking == "required":
        if not thinking_enabled:
            if contract.on_disable_request == "reject":
                raise ReasoningPolicyError("model requires thinking, but the request asked for it to be disabled")
            adjustments.append("thinking_forced_on")
        effective_thinking = True
    else:
        effective_thinking = bool(thinking_enabled)

    effort = contract.effort
    if effort is None:
        if reasoning_effort is not None:
            adjustments.append("effort_unsupported")
        effective_effort: str | None = None
    elif not effort.strict:
        effective_effort = reasoning_effort
    elif reasoning_effort is None:
        effective_effort = effort.default
    elif not isinstance(reasoning_effort, str):
        # Only string tokens can be matched against a vocabulary; anything else
        # is an invalid request and falls back like an unknown value.
        adjustments.append("effort_unsupported_value")
        effective_effort = effort.default
    elif reasoning_effort in effort.values:
        effective_effort = reasoning_effort
    elif reasoning_effort in effort.aliases:
        adjustments.append("effort_aliased")
        effective_effort = effort.aliases[reasoning_effort]
    else:
        adjustments.append("effort_unsupported_value")
        effective_effort = effort.default

    return ResolvedReasoning(thinking_enabled=effective_thinking, reasoning_effort=effective_effort, adjustments=tuple(adjustments))


def reasoning_capabilities_payload(contract: ReasoningContract) -> dict[str, Any]:
    """JSON-shaped projection of the contract for the Gateway API and the client."""
    effort: dict[str, Any] | None = None
    if contract.effort is not None:
        effort = {
            "values": list(contract.effort.values),
            "default": contract.effort.default,
            "aliases": dict(contract.effort.aliases),
        }
    return {
        "thinking": contract.thinking,
        "effort": effort,
        "history": contract.history,
        "source": contract.source,
    }


__all__ = [
    "DEFAULT_EFFORT_PATH",
    "GENERIC_EFFORT_VALUES",
    "EffortContract",
    "ReasoningContract",
    "ReasoningPolicyError",
    "ResolvedReasoning",
    "reasoning_capabilities_payload",
    "resolve_reasoning_contract",
    "resolve_reasoning_request",
]
