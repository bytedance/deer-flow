"""Noop memory backend -- a functional empty :class:`MemoryManager`.

Proves the pluggable mechanism end-to-end (factory + drop-in discovery + config
switch) and doubles as the **template** for a new backend.

Portability golden rule (see ``config.py`` for the full version): a backend
receives ALL host info through (1) the ABC method args and (2) the
``backend_config`` dict. The ONLY ``from deerflow`` import allowed in this
folder is the ABC contract line below -- change that one line to port the
backend to another agent. Do NOT import deer-flow path helpers, config
singletons, or models; get everything from ``backend_config``.

Writing a new backend:
  1. Copy this folder to ``backends/<yourname>/``.
  2. ``config.py``: declare your config knobs + ``from_backend_config`` (parse
     ``backend_config``; read ``storage_path`` from it, NOT from deer-flow).
  3. ``<yourname>_manager.py``: rename the class; ``__init__`` parses
     ``backend_config`` into your config; implement the 9 ABC methods against
     your memory system.
  4. (Optional) implement the DeerMem-internal capability methods at the bottom
     (``create_fact`` / ``delete_fact`` / ``update_fact`` / ``reload_memory`` /
     ``warm``) so the host gateway's ``hasattr`` probes find them and the
     fact-CRUD / reload / warm-up UI works.
  5. ``__init__.py``: set ``MANAGER_CLASS = YourManager`` (relative import).
  6. ``config.yaml``: ``manager_class: <yourname>``.

Return-shape note: the host gateway casts ``get_memory`` / ``export_memory`` /
``clear_memory`` / ``import_memory`` returns to a DeerMem-shape response
(``version`` / ``lastUpdated`` / ``user`` / ``history`` / ``facts[]``). A real
backend returns a dict castable to that shape (a non-DeerMem backend maps
its native records into this shape). Noop returns the minimal ``{"facts": []}`` -- the
gateway fills the rest with defaults.

With ``manager_class: noop`` the system runs with an empty memory: nothing is
stored, nothing is injected, every read returns empty. Useful for tests, for
disabling memory without touching ``enabled``, and as a baseline.
"""

from __future__ import annotations

from typing import Any

# ABC contract -- the ONE allowed `from deerflow` in this backend folder.
# Change this single line (to the other agent's MemoryManager) to port.
from deerflow.agents.memory.manager import MemoryManager

from .config import NoopConfig


def _empty_memory() -> dict[str, Any]:
    """A fresh empty memory document (callers may mutate).

    Minimal shape; the host gateway fills ``version`` / ``lastUpdated`` /
    ``user`` / ``history`` with defaults. A real backend returns the full
    DeerMem-shape doc (see the return-shape note in the module docstring).
    """
    return {"facts": []}


class NoopMemoryManager(MemoryManager):
    """Backend that stores and recalls nothing.

    ``__init__`` parses ``backend_config`` into a :class:`NoopConfig` purely to
    demonstrate the pattern -- noop ignores every field. A real backend reads
    its knobs (storage root, model, ...) from ``self._config``.
    """

    def __init__(self, backend_config: dict[str, Any] | None = None) -> None:
        super().__init__(backend_config)
        # Parse backend_config into a typed config. Noop ignores it; a real
        # backend uses self._config.* for storage root, model, etc. storage_path
        # comes from here (host-injected) -- never import a deer-flow path helper.
        self._config: NoopConfig = NoopConfig.from_backend_config(backend_config)

    # ── Write ────────────────────────────────────────────────────────────
    def add(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        return None

    def add_nowait(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
    ) -> None:
        return None

    # ── Read ─────────────────────────────────────────────────────────────
    def get_context(
        self,
        user_id: str | None,
        *,
        agent_name: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        return ""

    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        return []

    # ── Manage ───────────────────────────────────────────────────────────
    def get_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        return _empty_memory()

    def delete_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> None:
        return None

    def clear_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        return _empty_memory()

    def import_memory(
        self,
        memory_data: dict[str, Any],
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        return _empty_memory()

    def export_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        return _empty_memory()

    # ── Lifecycle ───────────────────────────────────────────────────────
    def shutdown_flush(self, timeout: float) -> bool:
        """Nothing is ever queued, so shutdown drain is a clean no-op success."""
        return True

    # ── Optional DeerMem-internal capabilities (NOT on the ABC) ──────────
    # The host gateway discovers these via ``hasattr(manager, "<name>")`` and
    # returns 501 when absent. Implement the ones your backend supports so the
    # frontend's fact-CRUD / reload / warm-up works. Signatures must match what
    # the gateway calls. Uncomment & adapt for your backend:
    #
    # def delete_fact(self, fact_id, *, user_id=None, agent_name=None) -> dict:
    #     """Delete one memory by id (DELETE /memory/facts/{id})."""
    #     ...  # your_store.delete(fact_id)
    #     return self.get_memory(user_id=user_id, agent_name=agent_name)
    #
    # def create_fact(self, content: str, category: str = "context",
    #                 confidence: float = 0.5, *,
    #                 user_id: str | None = None,
    #                 agent_name: str | None = None,
    # ) -> tuple[dict, str | None]:
    #     """Manually add one memory (POST /memory/facts).
    #
    #     Returns ``(memory_data, fact_id)`` -- NOT a bare dict. ``content`` is
    #     positional (the memory_add tool passes it positionally); ``fact_id``
    #     is None when a storage cap (e.g. max_facts) evicted the just-added
    #     fact, so the caller reports "not stored" instead of a dangling id.
    #     Signatures must match what the gateway/client/tools call (see DeerMem).
    #     """
    #     ...  # your_store.add(content); fact_id = your_store.last_id()
    #     return self.get_memory(user_id=user_id, agent_name=agent_name), fact_id
    #
    # def update_fact(self, *, fact_id, content=None, category=None,
    #                 confidence=None, user_id=None, agent_name=None) -> dict:
    #     """Update one memory's text by id (PATCH /memory/facts/{id})."""
    #     ...  # your_store.update(fact_id, content)
    #     return self.get_memory(user_id=user_id, agent_name=agent_name)
    #
    # def reload_memory(self, *, user_id=None, agent_name=None) -> dict:
    #     """Drop caches & re-read storage (POST /memory/reload).
    #     If your backend has no cache, just delegate to get_memory(...)."""
    #     return self.get_memory(user_id=user_id, agent_name=agent_name)
    #
    # def warm(self) -> None:
    #     """Heavy one-time init at gateway startup (e.g. load a tokenizer).
    #     Probed via hasattr; absent = skipped. Keep it fast (host guards it
    #     with a timeout)."""
    #     ...
