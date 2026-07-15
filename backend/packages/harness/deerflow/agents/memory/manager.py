"""Memory manager contract + pluggable backend factory.

This module is the shared, backend-agnostic core of the memory package. It
defines the :class:`MemoryManager` interface (9 methods) that every backend
implements, plus a singleton :func:`get_memory_manager` factory that resolves
the active backend from ``MemoryConfig.manager_class``.

Swap backend = drop a ``backends/<name>/`` folder exposing ``MANAGER_CLASS``
and set ``manager_class: <name>``. Nothing else in deer-flow changes.

Scope note: this phase is *pluggable only*, not black-box. Agent-side
conventions (``enabled`` gating at call sites, ``<memory>`` wrapping in
``_get_memory_context``) stay where they are; they are backend-agnostic and
do not impede pluggability.
"""

from __future__ import annotations

import importlib
import logging
import os
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from types import ModuleType
from typing import Any

from deerflow.config.memory_config import get_memory_config

logger = logging.getLogger(__name__)

# Backend packages live in <this dir>/backends/<name>/.
_BACKENDS_DIR = Path(__file__).parent / "backends"
# Sentinel attribute each backend's __init__ exposes (a MemoryManager subclass).
_MANAGER_CLASS_ATTR = "MANAGER_CLASS"

# Singleton instance + backend-registry cache (reset together by reset_memory_manager).
# _manager_lock guards get_memory_manager()'s double-checked init (multi-threaded).
_memory_manager: MemoryManager | None = None
_backends_cache: dict[str, type[MemoryManager]] | None = None
_manager_lock = threading.Lock()


class MemoryManager(ABC):
    """Backend-neutral memory manager contract (9 methods).

    Memories are bucketed per ``(agent_name, user_id)``; ``thread_id`` aligns
    with the deer-flow conversation thread. The contract is deliberately
    neutral so a third-party memory system can be adapted without deer-flow
    code changes:

    - :meth:`get_context` returns plain injection text; the *format* is the
      implementation's own choice and is NOT part of the contract (DeerMem
      does load + ``format_memory_for_injection``; another backend may do
      its own search + formatting).
    - :meth:`add` / :meth:`add_nowait` take raw conversation messages; any
      filtering / correction-/reinforcement-detection is the implementation's
      private concern (not on the contract).
    - No facts-model assumption: a backend need not store "facts" at all.

    Methods marked *stub* are part of the contract but have no caller yet in
    this phase; DeerMem raises ``NotImplementedError`` for them, a future
    backend (or a later DeerMem ``core/`` module) may implement them for real.
    """

    def __init__(self, backend_config: dict[str, Any] | None = None) -> None:
        """Receive backend-private config (the factory passes ``backend_config``).

        Default stores the raw dict; backends that need to parse it (e.g. DeerMem
        into a ``DeerMemConfig``) override ``__init__``. Backends that ignore
        private config (e.g. noop) inherit this unchanged.
        """
        self._backend_config = backend_config

    # ── Write ────────────────────────────────────────────────────────────
    @abstractmethod
    def add(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        """Queue a conversation for memory update (debounced, asynchronous).

        Args:
            thread_id: Conversation thread id.
            messages: Raw conversation messages; the implementation filters
                to user inputs + final assistant responses itself.
            agent_name: Per-agent bucket; ``None`` = global memory.
            user_id: Per-user bucket.
            trace_id: Request trace id captured for memory-LLM tracing.
        """

    @abstractmethod
    def add_nowait(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
    ) -> None:
        """Queue a conversation for *immediate* memory update (emergency flush).

        Used right before summarization removes messages from state, so the
        content is captured instead of lost.
        """

    # ── Read ─────────────────────────────────────────────────────────────
    @abstractmethod
    def get_context(
        self,
        user_id: str | None,
        *,
        agent_name: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        """Return injection-ready memory text for the given bucket.

        Implementations load their memory and format it however they choose;
        the returned string is injected verbatim by call sites. Format
        parameters are the backend's own private config (received via
        ``backend_config`` at construction), NOT a host config on this method.
        """

    @abstractmethod
    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search the bucket's memory for facts matching ``query``; return up to
        ``top_k`` ranked by relevance. ``category`` (optional) filters BEFORE the
        ``top_k`` slice so a category-scoped search is not starved by other
        categories' higher-ranked facts."""

    # ── Manage ───────────────────────────────────────────────────────────
    @abstractmethod
    def get_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        """Return the full memory document for the bucket."""

    @abstractmethod
    def delete_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> None:
        """Delete the entire memory document for the bucket. *stub* this phase."""

    @abstractmethod
    def clear_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        """Clear the bucket's memory; return the cleared (now-empty) document."""

    @abstractmethod
    def import_memory(
        self,
        memory_data: dict[str, Any],
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        """Import a memory document into the bucket; return the merged result."""

    @abstractmethod
    def export_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        """Export the memory document for the bucket. *stub* this phase (no caller yet)."""

    # ── Lifecycle ───────────────────────────────────────────────────────
    @abstractmethod
    def shutdown_flush(self, timeout: float) -> bool:
        """Best-effort bounded drain of pending updates on graceful shutdown.

        Runs on the Gateway shutdown path (after IM channels and the scheduler
        stop, so no new IM/scheduler updates arrive during the drain) to flush
        updates still sitting in the backend's debounce buffer. Without it, any
        update enqueued since the last timer fire is lost on restart / rolling
        deploy / SIGTERM, because the buffer is pure in-memory and the debounce
        worker is a daemon thread killed on process exit.

        Implementations must honour a *hard* ``timeout``: the drain makes a
        synchronous LLM call that cannot be interrupted, so the caller (the
        Gateway lifespan) needs a real upper bound that lines up with the K8s
        ``terminationGracePeriodSeconds`` (the drain must finish inside the pod
        grace window, or K8s SIGKILLs it mid-drain and the loss the drain is
        fixing is silently re-introduced).

        Returns ``True`` if the drain genuinely finished within ``timeout``
        (buffer empty, no worker still running, no exception); ``False`` on
        timeout or failure (the caller logs a warning and proceeds to exit --
        any unfinished tail is dropped, strictly better than no flush). A
        backend with no pending work (or no buffer at all) returns ``True``
        immediately, so the host may call this unconditionally when memory is
        enabled without gating on backend-private queue state.
        """


# ── Backend discovery (drop-in) ───────────────────────────────────────────
def _scan_backends() -> dict[str, type[MemoryManager]]:
    """Discover pluggable backends under ``backends/<name>/``.

    Each subpackage that exposes a ``MANAGER_CLASS`` attribute (a
    :class:`MemoryManager` subclass) is registered under its folder name.
    Results are cached for the process. Folder name == backend name ==
    ``manager_class`` config value (drop-in contract). A backend that fails
    to import is logged and skipped so a broken optional backend never breaks
    the factory.
    """
    global _backends_cache
    if _backends_cache is not None:
        return _backends_cache

    registry: dict[str, type[MemoryManager]] = {}
    if not _BACKENDS_DIR.is_dir():
        _backends_cache = registry
        return registry

    for entry in sorted(_BACKENDS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue
        if not (entry / "__init__.py").is_file():
            continue
        dotted = f"deerflow.agents.memory.backends.{entry.name}"
        try:
            module: ModuleType = importlib.import_module(dotted)
        except Exception:  # noqa: BLE001 - a broken backend must not break the factory
            logger.exception("Failed to import memory backend %r; skipping", entry.name)
            continue
        cls = getattr(module, _MANAGER_CLASS_ATTR, None)
        if cls is None:
            continue
        if not (isinstance(cls, type) and issubclass(cls, MemoryManager)):
            logger.warning(
                "Memory backend %r exposes MANAGER_CLASS=%r which is not a MemoryManager subclass; skipping",
                entry.name,
                cls,
            )
            continue
        registry[entry.name] = cls

    _backends_cache = registry
    return registry


def _resolve_manager_class(manager_class: str) -> type[MemoryManager]:
    """Resolve a ``manager_class`` config value to a concrete class.

    Resolution order:
      1. Registered short name (from :func:`_scan_backends`).
      2. Dotted import path (``pkg.mod:Cls`` or ``pkg.mod.Cls``).

    A value that resolves to neither is a config error: raise rather than
    silently fall back to a different storage backend. Memory is persistent
    state, so silently substituting DeerMem when an explicit ``manager_class``
    fails to resolve (typo / import error / missing attr) would route writes to
    the wrong store -- a silent data-integrity footgun. Fail loud (the manager
    is resolved eagerly at startup so it can be warmed) so the operator fixes
    ``memory.manager_class`` instead of discovering the mismatch later.
    """
    registry = _scan_backends()
    if manager_class in registry:
        return registry[manager_class]

    # Treat as a dotted path: support both "pkg.mod:Cls" and "pkg.mod.Cls".
    dotted_error: str | None = None
    if ":" in manager_class:
        module_path, _, attr = manager_class.partition(":")
    else:
        module_path, _, attr = manager_class.rpartition(".")
    if module_path and attr:
        try:
            module = importlib.import_module(module_path)
        except ImportError as e:
            dotted_error = f"cannot import module {module_path!r}: {e}"
        else:
            cls = getattr(module, attr, None)
            if cls is None:
                dotted_error = f"attribute {attr!r} not found in {module_path!r}"
            elif not (isinstance(cls, type) and issubclass(cls, MemoryManager)):
                dotted_error = f"{manager_class!r} resolved to non-MemoryManager {cls!r}"
            else:
                return cls

    raise ValueError(
        f"memory.manager_class={manager_class!r} is not a registered backend name "
        f"(known: {sorted(registry)}) nor a resolvable 'pkg.mod:Cls' path" + (f": {dotted_error}" if dotted_error else "") + ". Fix memory.manager_class in config; refusing to silently fall back to a "
        "different storage backend (memory is persistent state -- a wrong store is a "
        "silent data-integrity footgun)."
    )


# ── Host-default hooks (injected into backend_config by the factory) ──────
#
# DeerMemConfig declares ``tracing_callback`` and ``should_keep_hidden_message``
# as optional, host-agnostic slots (default ``None``). The portable package
# never names a deer-flow concept, so the host fills these slots HERE -- in the
# factory, which is host code outside ``backends/deermem/``. Backends whose
# config schema declares these slots (DeerMem) consume them via
# ``from_backend_config``'s known-field filter; others (e.g. noop) ignore
# them. An explicit value in ``backend_config`` (set programmatically) takes
# precedence and is left untouched.
#
# Imports are lazy (matching the ``runtime_home`` precedent) so this module
# stays cheap to import and so another agent vendoring the contract only has
# to edit these two helpers, not the top-level imports.
def _host_default_tracing_callback(
    invoke_config: dict[str, Any],
    *,
    thread_id: str | None,
    user_id: str | None,
    trace_id: str | None,
    model_name: str | None,
) -> None:
    """deer-flow default for DeerMem's ``tracing_callback`` slot.

    Merges Langfuse trace metadata into ``invoke_config`` (no-op when
    Langfuse is not an enabled tracing provider). Maps DeerMem's ``trace_id``
    onto ``inject_langfuse_metadata``'s ``deerflow_trace_id`` kwarg -- the
    name mismatch that previously made memory LLM tracing silently TypeError
    is bridged here, at the host seam, so the portable package is untouched.
    """
    from deerflow.tracing import inject_langfuse_metadata

    inject_langfuse_metadata(
        invoke_config,
        thread_id=thread_id,
        user_id=user_id,
        assistant_id="memory_agent",
        model_name=model_name,
        environment=os.environ.get("DEER_FLOW_ENV") or os.environ.get("ENVIRONMENT"),
        deerflow_trace_id=trace_id,
    )


def _host_default_should_keep_hidden_message(additional_kwargs: Any) -> bool:
    """deer-flow default for DeerMem's ``should_keep_hidden_message`` slot.

    Keep a ``hide_from_ui`` message only when it carries a human-input
    clarification response, so the user's clarification is captured into
    memory; drop all other hidden messages (framework-internal reminders,
    view-image payloads, etc.). Restores the pre-abstraction behaviour where
    ``message_processing`` imported ``read_human_input_response`` directly.
    """
    from deerflow.agents.human_input import read_human_input_response

    return read_human_input_response(additional_kwargs) is not None


def _host_default_llm() -> Any:
    """deer-flow default for DeerMem's ``host_llm`` slot (zero-config extraction).

    Builds the host's default chat model (``create_chat_model(name=None)`` ->
    app default, ``attach_tracing=True`` so memory LLM calls surface in langfuse
    via the metadata ``tracing_callback`` merges), mirroring pre-abstraction
    ``model_name: null``. Returns ``None`` if no model is available (no models
    configured) so DeerMem no-ops extraction with a clear error rather than
    crashing startup.
    """
    try:
        from deerflow.models import create_chat_model

        return create_chat_model(name=None)
    except Exception:  # noqa: BLE001 - no default model is a config state, not a crash
        logger.warning("Could not build host default model for DeerMem memory extraction; memory extraction will be disabled", exc_info=True)
        return None


# ── Singleton factory ─────────────────────────────────────────────────────
def get_memory_manager() -> MemoryManager:
    """Return the singleton :class:`MemoryManager` for the active config.

    Reads ``MemoryConfig.manager_class`` and resolves it via
    :func:`_resolve_manager_class`. The instance is cached; call
    :func:`reset_memory_manager` to force re-resolution (tests / runtime
    backend switching).
    """
    global _memory_manager
    if _memory_manager is not None:
        return _memory_manager

    # deer-flow is multi-threaded: memory injection runs via asyncio.to_thread,
    # the update queue fires on a Timer thread, and gateway/agent threads all
    # reach here. Double-checked locking ensures only one instance is built even
    # on first-call contention -- essential since backends now own stateful
    # dependencies (DeerMem owns its storage/queue/updater; others may open
    # connections) constructed here in __init__.
    with _manager_lock:
        if _memory_manager is not None:
            return _memory_manager

        cfg = get_memory_config()
        manager_class = cfg.manager_class
        cls = _resolve_manager_class(manager_class)
        backend_config = dict(cfg.backend_config or {})
        # Zero-config UX: default DeerMem storage to deer-flow's state dir
        # (absolute, CWD-independent) so memory lands at
        # {runtime_home}/users/{user_id}/memory.json (deer-flow's base_dir,
        # same as pre-abstraction) unless the host explicitly sets storage_path.
        if not backend_config.get("storage_path"):
            from deerflow.config.runtime_paths import runtime_home

            backend_config["storage_path"] = str(runtime_home())
        elif not Path(backend_config.get("storage_path", "")).is_absolute():
            # A relative storage_path is resolved against runtime_home() (base_dir-
            # relative, CWD-independent) to preserve pre-abstraction semantics; left
            # as-is it would be CWD-relative and fragile. (Resolved here in host code
            # so the portable paths.py stays free of any runtime_home dependency.)
            from deerflow.config.runtime_paths import runtime_home

            backend_config["storage_path"] = str((Path(runtime_home()) / backend_config["storage_path"]).resolve())
        # Guard: DeerMem treats storage_path as a root DIRECTORY (per-user memory
        # under {storage_path}/users/{uid}/memory.json). A file-style value (e.g. a
        # leftover .json file from the pre-abstraction file-path semantics) would
        # make FileMemoryStorage.save's mkdir(parents=True) raise NotADirectoryError,
        # caught as OSError -> silent write failure. Fail loud at startup instead
        # (memory is persistent state -- a wrong root is a data-integrity footgun).
        _resolved_storage_path = Path(backend_config["storage_path"])
        if _resolved_storage_path.is_file():
            raise ValueError(
                f"memory.backend_config.storage_path={backend_config['storage_path']!r} "
                f"resolves to an existing file {_resolved_storage_path}; DeerMem treats "
                f"storage_path as a root DIRECTORY (per-user memory under "
                f"{{storage_path}}/users/{{uid}}/memory.json). Point it at a directory."
            )
        # Host-default hooks: callables cannot come from YAML, so the host
        # injects them here. DeerMem consumes them (known config fields);
        # noop ignores them (unknown-field filter in from_backend_config).
        # An explicit value (incl. ``null`` in YAML) takes precedence -> the
        # host default is only filled when the key is absent.
        if "tracing_callback" not in backend_config:
            backend_config["tracing_callback"] = _host_default_tracing_callback
        if "should_keep_hidden_message" not in backend_config:
            backend_config["should_keep_hidden_message"] = _host_default_should_keep_hidden_message
        # Zero-config LLM: when no memory model is configured, inject the host's
        # default chat model so memory extraction works out of the box (mirrors
        # pre-abstraction `model_name: null` -> app default). DeerMem prefers
        # host_llm over build_llm(model); other backends ignore the slot.
        model_cfg = backend_config.get("model")
        if not (isinstance(model_cfg, dict) and model_cfg.get("model")) and "host_llm" not in backend_config:
            backend_config["host_llm"] = _host_default_llm()
        # Restore structured-log trace correlation on the memory-update worker
        # thread (Timer / executor): bind trace_id into the request-trace
        # ContextVar. A None trace_id is left unbound by the updater's guard.
        if "trace_context_manager" not in backend_config:
            from deerflow.trace_context import request_trace_context

            backend_config["trace_context_manager"] = request_trace_context
        _memory_manager = cls(backend_config=backend_config)
        logger.info("Memory manager resolved: %s (manager_class=%r)", cls.__name__, manager_class)
        return _memory_manager


def reset_memory_manager() -> None:
    """Clear the cached singleton manager and the backend registry.

    The next :func:`get_memory_manager` call re-reads the config and re-scans
    backends. Use this in tests or when switching backends at runtime.
    """
    global _memory_manager, _backends_cache
    with _manager_lock:
        _memory_manager = None
        _backends_cache = None
