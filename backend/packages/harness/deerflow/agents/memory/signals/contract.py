"""Contract for Jev memory signal classification (reinforcement / weakening hints).

This side is **additive only**: a model verdict can add hint text and — under
pre-screen ``enforce`` × classifier ``hints`` — veto a skip. It never decides
extraction on its own, never drives deletion, and never participates in the
reinforcement evidence gate (locks S2-S5, §3 of the design).

Host contract, consumed through the memory-layer judge:

* :class:`MemorySignalRequest` — what the host knows about the batch;
* :class:`MemorySignalDecision` — hint labels, or ``None`` for "no model result";
* :class:`MemorySignalProvider` — duck-typed, resolved by class path.

See ``docs/superpowers/specs/2026-09-25-jev-memory-signal-classification-design.en.md``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from deerflow.reflection import resolve_variable

MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_HINTS = "hints"
MODES: tuple[str, ...] = (MODE_OFF, MODE_SHADOW, MODE_HINTS)

#: How this side's requests relate to the pre-screen's (§2.2.5).
COMBINE_AUTO = "auto"
COMBINE_ALWAYS = "always"
COMBINE_NEVER = "never"
COMBINES: tuple[str, ...] = (COMBINE_AUTO, COMBINE_ALWAYS, COMBINE_NEVER)

#: Label names aligned with the deterministic signal classes (`SIGNAL_NAMES`).
LABEL_REINFORCEMENT = "reinforcement"
LABEL_CORRECTION = "correction"
LABELS: tuple[str, ...] = (LABEL_REINFORCEMENT, LABEL_CORRECTION)

CONFIGURATION_SOURCE = "memory.signal_classification.config"


@dataclass(frozen=True)
class MemorySignalRequest:
    """One batch, as this side sees it (same data plane as the pre-screen)."""

    batch_text: str
    digest: str
    signals: frozenset[str] = frozenset()
    thread_id: str | None = None
    user_id: str | None = None
    agent_name: str | None = None
    trace_id: str | None = None
    bypass_watermark: bool = False
    message_count: int = 0


@dataclass(frozen=True)
class MemorySignalDecision:
    """Hint labels whose direction's probability reached ``hint_threshold``.

    ``probabilities`` carries only the directions that produced a validated
    answer, so a response with one usable direction still contributes that one
    (failure is counted per question, never per side).
    """

    labels: frozenset[str] = field(default_factory=frozenset)
    probabilities: Mapping[str, float] = field(default_factory=dict)
    model: str = ""
    cached: bool = False


@runtime_checkable
class MemorySignalProvider(Protocol):
    """Contract for a pluggable signal classifier (synchronous; same thread rules as the pre-screen)."""

    name: str

    def decide(self, request: MemorySignalRequest) -> MemorySignalDecision | None:
        """Return the batch's hint labels, or ``None`` when no model result is available."""
        ...

    def release_policy_parameters(self) -> dict[str, object]:
        """Behaviour-affecting parameters for assembly identity (never the credential)."""
        ...


def resolve_memory_signal_classifier(
    *,
    mode: str,
    use: str | None,
    config: Mapping[str, object] | None = None,
    configuration_source: str = CONFIGURATION_SOURCE,
) -> MemorySignalProvider | None:
    """Resolve the configured classifier, or ``None`` when its mode is off.

    Same rules as the pre-screen's resolver: ``off`` resolves nothing and
    validates nothing; any other mode fails loudly rather than silently
    degrading to "no model hints".
    """
    if mode == MODE_OFF:
        return None
    if mode not in MODES:
        raise ValueError(f"{configuration_source} mode must be one of {list(MODES)}, got {mode!r}")
    if not use:
        raise ValueError(f"{configuration_source} needs 'use' when mode={mode!r}")
    try:
        provider_class = resolve_variable(use)
    except (ImportError, ValueError) as exc:
        raise ValueError(f"{configuration_source} use={use!r} could not be resolved: {exc}") from exc
    if not callable(provider_class):
        raise ValueError(f"{configuration_source} use={use!r} is not instantiable")
    return provider_class(mode=mode, **dict(config or {}))


def direction_labels(affirmation: float | None, negation: float | None, *, hint_threshold: float) -> frozenset[str]:
    """Map the two directions' probabilities to labels (design §5's fixed mapping).

    ``affirmation >= hint_threshold`` ⇒ ``reinforcement``;
    ``negation >= hint_threshold`` ⇒ ``correction``. Both may hold at once
    ("keep using X, but stop using Y").
    """
    labels = set()
    if affirmation is not None and affirmation >= hint_threshold:
        labels.add(LABEL_REINFORCEMENT)
    if negation is not None and negation >= hint_threshold:
        labels.add(LABEL_CORRECTION)
    return frozenset(labels)


__all__ = [
    "COMBINE_ALWAYS",
    "COMBINE_AUTO",
    "COMBINE_NEVER",
    "COMBINES",
    "CONFIGURATION_SOURCE",
    "LABEL_CORRECTION",
    "LABEL_REINFORCEMENT",
    "LABELS",
    "MODE_HINTS",
    "MODE_OFF",
    "MODE_SHADOW",
    "MODES",
    "MemorySignalDecision",
    "MemorySignalProvider",
    "MemorySignalRequest",
    "direction_labels",
    "resolve_memory_signal_classifier",
]
