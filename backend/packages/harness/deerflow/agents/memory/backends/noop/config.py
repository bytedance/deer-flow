"""Noop backend config -- TEMPLATE for parsing ``backend_config``.

Reference for how a new memory backend configures itself. **Portability golden
rule** (read before writing a backend):

    A backend receives ALL host-provided info through exactly TWO channels:
      1. The :class:`MemoryManager` ABC method arguments (``manager.py``) --
         ``user_id`` / ``agent_name`` / ``thread_id`` / ``messages`` / etc.
      2. The ``backend_config`` dict (passed to ``__init__``).
    It MUST NOT import deer-flow modules or hardcode deer-flow paths. The ONLY
    ``from deerflow`` line allowed in the whole backend folder is the ABC
    contract import in ``<name>_manager.py``::

        from deerflow.agents.memory.manager import MemoryManager

    That single line ties the backend to the host; change it (and only it) to
    port the backend to another agent. Everything else -- storage root, model,
    hooks -- arrives via ``backend_config``.

What the factory (``manager.py::get_memory_manager``) injects into
``backend_config`` for every backend:
  - ``storage_path`` (str): a writable state dir (the host's default, or
    whatever the user sets in config.yaml). **Use this as your storage root** --
    do NOT call a deer-flow path helper yourself.
  - ``tracing_callback`` (Callable | None): host default for tracing the
    backend's LLM calls (langfuse). Declare a slot + consume it if your backend
    traces; otherwise ignore (unknown-key filtering drops it).
  - ``should_keep_hidden_message`` (Callable | None): host default for keeping
    ``hide_from_ui`` messages (human-clarification). Consume if your backend
    filters hidden messages; otherwise ignore.
  - Plus the user's ``config.yaml::memory.backend_config`` keys (your backend's
    own knobs: ``model``, ``vector_store``, ``embedder``, thresholds, etc.).

``NoopConfig`` below mirrors that surface. Noop stores nothing, so it ignores
every field -- but copy this structure, rename, and fill in your own knobs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class NoopConfig:
    """Parsed config for the noop backend (template -- noop ignores all fields).

    A real backend declares its own knobs here (e.g. ``model``, ``vector_store``,
    ``max_facts``) and parses them in :meth:`from_backend_config`.
    """

    #: Writable state dir, host-injected. A real backend lands its storage
    #: (DB / vector store / JSON) under here. Noop ignores it.
    storage_path: str = ""

    #: Example backend-private knob (would come from config.yaml
    #: ``memory.backend_config.example_option``). Replace with your own.
    example_option: str = "default"

    #: Host-injected hook (optional). A backend that traces its LLM calls calls
    #: ``self._config.tracing_callback(invoke_config, *, thread_id, user_id,
    #: trace_id, model_name)`` before invoking. ``None`` = no tracing.
    tracing_callback: Callable[..., Any] | None = None

    #: Host-injected hook (optional). A backend that filters ``hide_from_ui``
    #: messages calls ``self._config.should_keep_hidden_message(additional_kwargs)``
    #: -> bool (True = keep despite hide_from_ui). ``None`` = skip all hidden.
    should_keep_hidden_message: Callable[[Any], bool] | None = None

    @classmethod
    def from_backend_config(cls, backend_config: dict[str, Any] | None) -> NoopConfig:
        """Build a config from the ``backend_config`` dict.

        Usage in your manager's ``__init__``::

            super().__init__(backend_config)
            self._config = YourConfig.from_backend_config(backend_config)

        Reads ONLY known keys; unknown keys (including host-injected slots this
        backend doesn't consume) are ignored -- so the host can safely inject
        shared slots like ``tracing_callback`` for every backend without
        breaking ones that don't use them.
        """
        cfg = dict(backend_config or {})
        return cls(
            storage_path=str(cfg.get("storage_path") or ""),
            example_option=str(cfg.get("example_option", "default")),
            tracing_callback=cfg.get("tracing_callback"),
            should_keep_hidden_message=cfg.get("should_keep_hidden_message"),
        )
