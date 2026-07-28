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
  3. ``<yourname>_manager.py``: rename the class; declare your deps as
     ``PrivateAttr``; ``model_post_init`` parses ``self.backend_config`` into
     your config; implement the ABC methods against your memory system.
  4. (Optional) override the tier-3 hooks at the bottom (``create_fact`` /
     ``delete_fact`` / ``update_fact`` / ``reload_memory`` / ``warm``) -- they
     have base defaults (``warm``=True, the rest raise ``NotImplementedError``)
     so your backend only overrides the ones it supports; callers catch
     ``NotImplementedError`` for the rest.
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

from typing import Any, ClassVar, Literal

from pydantic import PrivateAttr

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

    ``model_post_init`` parses ``backend_config`` into a :class:`NoopConfig`
    purely to demonstrate the pattern -- noop ignores every field. A real
    backend reads its knobs (storage root, model, ...) from ``self._config``.
    """

    # Parsed config (PrivateAttr: not a validated/serialized field). Noop ignores
    # every field; a real backend uses self._config.* for storage root, model,
    # etc. storage_path comes from here (host-injected) -- never import a
    # deer-flow path helper.
    _config: Any = PrivateAttr(default=None)

    # noop overrides search() to return [] (its "store/recall nothing" design --
    # every read returns empty, never raises), so it is search-capable; the flag
    # is True to match the override (the invariant requires flag == override).
    supports_search: ClassVar[bool] = True

    def model_post_init(self, __context: Any) -> None:
        self._config = NoopConfig.from_backend_config(self.backend_config)

    @classmethod
    def from_config(
        cls,
        backend_config: dict[str, Any] | None = None,
        *,
        mode: Literal["middleware", "tool"] = "middleware",
        **host_hooks: Any,
    ) -> NoopMemoryManager:
        """Noop has no dependencies to wire; ignore host_hooks."""
        return cls(backend_config=backend_config, mode=mode)

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

    # delete_memory / export_memory inherit the base tier-2 default (raise
    # NotImplementedError) -- dead contract (zero callers); noop does not
    # override them.

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

    # ── Lifecycle ───────────────────────────────────────────────────────
    def shutdown_flush(self, timeout: float) -> bool:
        """Nothing is ever queued, so shutdown drain is a clean no-op success."""
        return True

    # ── Tier 3 hooks (inherit base defaults; override if your backend supports) ──
    # warm / reload_memory / fact CRUD are tier-3 optional hooks ON the base
    # MemoryManager with defaults: warm=True (nothing to warm), the rest raise
    # NotImplementedError. Noop does not support fact CRUD / reload, so it
    # inherits the defaults (callers catch NotImplementedError -> 501 / fallback).
    # Override the ones your backend supports; signatures must match the base
    # (see DeerMem for full implementations):
    #
    # def create_fact(self, content, category="context", confidence=0.5, *,
    #                 agent_name=None, user_id=None) -> tuple[dict, str | None]:
    #     ...  # return (memory_data, fact_id); fact_id=None if a cap evicted it
    # def delete_fact(self, fact_id, *, agent_name=None, user_id=None) -> dict: ...
    # def update_fact(self, fact_id, content=None, category=None, confidence=None,
    #                 *, agent_name=None, user_id=None) -> dict: ...
    # def reload_memory(self, *, user_id=None, agent_name=None) -> dict: ...
    # def warm(self) -> bool | None: ...   # default None (nothing to warm); override for heavy one-time init
