"""Memory capture pre-screening: a pluggable, off-by-default cost gate.

The hook lives in the host (this package + the DeerMem updater that calls it),
not in an extension: the extension API's only memory touchpoint is a read-only
post-hoc observer and its contributions are fail-open, which is the wrong shape
for a switch that can affect writes (design §2.6).

See ``docs/superpowers/specs/2026-09-25-jev-memory-prescreening-design.en.md``.
"""

from deerflow.agents.memory.prescreen.contract import (
    CONFIGURATION_SOURCE,
    MODE_ENFORCE,
    MODE_OFF,
    MODE_SHADOW,
    MODES,
    VERDICT_EXTRACT,
    VERDICT_SKIP,
    MemoryPrescreenDecision,
    MemoryPrescreenProvider,
    MemoryPrescreenRequest,
    resolve_memory_prescreen,
)

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
