"""Capture of the host's guarded evolution capabilities (PR #5645).

Extension API 0.2.7 added two optional, source-bound service dependencies:

* ``ExtensionRuntimeDeps.skill_mutations`` — the ``SkillMutationService``
  backbone (``read_skill`` → ``stage`` → ``check`` → ``commit``/``discard`` /
  ``revert``) for *existing* custom skills, delivered when the operator grants
  ``plugins[].host_access.skill_mutations``.
* ``ExtensionRuntimeDeps.completed_run_evidence`` — the sealed completed-run
  evidence reader, delivered via ``host_access.evidence``. The mutation
  backbone requires a sealed snapshot reference as the acting source on every
  call, so the evidence grant (whose owners must be a superset of the mutation
  owners, enforced host-side) is what makes source resolution possible.

Both grants are restart-bound, owner- and target-allowlisted, and scoped to
this plugin's durable identity. A registered Gateway service binds the
handles at start; ``mutations.py`` then drives the real pipeline through
them, and the ``status`` action reports whether they are wired. Handles are
process-local by host design and revoked before host shutdown; ``start`` and
``stop`` are the only writers, matching that lifetime.

The attributes are read with ``getattr`` so the package keeps loading against
older 0.2.x hosts whose ``ExtensionRuntimeDeps`` predates the fields.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


class CapabilityHandle:
    """Process-local slot for one host-granted capability handle (or ``None``)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._service: Any | None = None

    def bind(self, service: Any | None) -> None:
        with self._lock:
            self._service = service

    def clear(self) -> None:
        with self._lock:
            self._service = None

    def get(self) -> Any | None:
        with self._lock:
            return self._service


class SkillEvolutionBridgeService:
    """Gateway-lifetime service capturing the granted host capability handles."""

    def __init__(self, *, mutations: CapabilityHandle, evidence: CapabilityHandle, model: CapabilityHandle | None = None) -> None:
        self._mutations = mutations
        self._evidence = evidence
        self._model = model

    async def start(self, deps: Any) -> None:
        self._mutations.bind(getattr(deps, "skill_mutations", None))
        self._evidence.bind(getattr(deps, "completed_run_evidence", None))
        if self._model is not None:
            self._model.bind(getattr(deps, "model_invoker", None))
        # Log here, not at install(): handles only exist after the host grants
        # and starts services, so an install-time check would always report
        # "not granted" even on a fully granted host.
        if self._mutations.get() is None or self._evidence.get() is None:
            logger.info("skill-evolution: the guarded managed-mutation backbone is not granted on this host (host_access.skill_mutations / host_access.evidence); managed_* actions will report UNAVAILABLE")
        if self._model is not None and self._model.get() is None:
            logger.info("skill-evolution: no legacy operator-granted model service; browser evolution uses authenticated chat-model access when available")

    async def stop(self) -> None:
        self._mutations.clear()
        self._evidence.clear()
        if self._model is not None:
            self._model.clear()
