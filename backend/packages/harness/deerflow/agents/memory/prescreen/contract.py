"""Contract for the memory capture pre-screen: a cost gate, never a safety gate.

The pre-screen answers one question — "is this batch worth paying for an
extraction call?" — and nothing else. Its failure direction is therefore
**extraction**: an error, a deadline, an unusable response, an over-limit batch, or
no verdict at all means "extract as usual" (design L2). It gates no execution and
no write, and it never replaces the post-extraction confidence / scope /
durability / authority gates (L6).

Host contract, consumed by the DeerMem updater through the memory-layer judge:

* :class:`MemoryPrescreenRequest` — what the host knows about the batch;
* :class:`MemoryPrescreenDecision` — the verdict, or ``None`` for "no opinion";
* :class:`MemoryPrescreenProvider` — duck-typed, resolved by class path.

See ``docs/superpowers/specs/2026-09-25-jev-memory-prescreening-design.en.md``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from deerflow.reflection import resolve_variable

MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_ENFORCE = "enforce"
MODES: tuple[str, ...] = (MODE_OFF, MODE_SHADOW, MODE_ENFORCE)

VERDICT_EXTRACT: Literal["extract"] = "extract"
VERDICT_SKIP: Literal["skip"] = "skip"

CONFIGURATION_SOURCE = "memory.prescreen.config"


@dataclass(frozen=True)
class MemoryPrescreenRequest:
    """One batch, as the host sees it.

    ``batch_text`` is exactly what the extractor would be sent
    (``format_conversation_for_update`` output, including its existing head/tail
    retention for long single messages) — the judging side introduces no second
    truncation (L5). Existing memory, tool-call arguments and dropped messages are
    never part of the request (L10).
    """

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
class MemoryPrescreenDecision:
    """One verdict. ``model`` is the served version, already reduced to a recordable token."""

    verdict: Literal["extract", "skip"]
    probability: float
    model: str
    cached: bool = False
    reason: str = ""


@runtime_checkable
class MemoryPrescreenProvider(Protocol):
    """Contract for a pluggable memory pre-screen.

    ``decide`` is **synchronous**: the updater runs on the debounce Timer /
    executor thread and must not touch the event loop. It returns ``None`` for
    "no opinion", which the caller treats exactly like a failure — extract.
    """

    name: str

    def decide(self, request: MemoryPrescreenRequest) -> MemoryPrescreenDecision | None:
        """Return a verdict for this batch, or ``None`` to fall back to extraction."""
        ...

    def release_policy_parameters(self) -> dict[str, object]:
        """Behaviour-affecting parameters for assembly identity (never the credential)."""
        ...


def resolve_memory_prescreen(
    *,
    mode: str,
    use: str | None,
    config: Mapping[str, object] | None = None,
    configuration_source: str = CONFIGURATION_SOURCE,
) -> MemoryPrescreenProvider | None:
    """Resolve the configured pre-screen, or ``None`` when its mode is off.

    ``off`` resolves no class path, constructs nothing and validates no
    credentials (design §3), so a deployment without a pre-screen pays nothing and
    cannot fail at build time. Any other mode fails **loudly** when the class path
    is unusable or the provider rejects its configuration — never a silent
    fallback to "no pre-screen", which would hide a deployment mistake behind a
    behavior nothing records.
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


__all__ = [
    "CONFIGURATION_SOURCE",
    "MODE_ENFORCE",
    "MODE_OFF",
    "MODE_SHADOW",
    "MODES",
    "VERDICT_EXTRACT",
    "VERDICT_SKIP",
    "MemoryPrescreenDecision",
    "MemoryPrescreenProvider",
    "MemoryPrescreenRequest",
    "resolve_memory_prescreen",
]
