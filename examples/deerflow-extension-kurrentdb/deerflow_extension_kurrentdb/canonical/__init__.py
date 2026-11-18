"""Canonical kurrent-agents events: mapping (pure) and best-effort emitters (``emitter``)."""

from __future__ import annotations

from . import emitter, mapping
from .emitter import MAX_LIFETIME_SECONDS, AsyncCanonicalEmitter, AsyncChains, BackgroundQueue, CanonicalEmitter
from .mapping import CanonicalEvent, matches, matches_intent, memory_events, session_events

__all__ = [
    "MAX_LIFETIME_SECONDS",
    "AsyncCanonicalEmitter",
    "AsyncChains",
    "BackgroundQueue",
    "CanonicalEmitter",
    "CanonicalEvent",
    "emitter",
    "mapping",
    "matches",
    "matches_intent",
    "memory_events",
    "session_events",
]
