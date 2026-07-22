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
from abc import abstractmethod
from pathlib import Path
from types import ModuleType
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class MemoryCallbacks:
    """Observability hooks for memory backends. Default implementations are
    no-ops; override the ones you need. The pre-LLM-call hook
    ``on_memory_llm_call`` mutates ``invoke_config`` before the LLM call so a
    tracer (e.g. langfuse) emits a span at the LLM boundary. (More hooks --
    post-extract / search / inject / error -- can be added when callers need
    them.)"""

    def on_memory_llm_call(
        self,
        invoke_config: dict[str, Any],
        *,
        thread_id: str | None,
        user_id: str | None,
        trace_id: str | None,
        model_name: str | None,
    ) -> None:
        """Pre-LLM-call: mutate ``invoke_config`` (e.g. merge trace metadata)
        before the backend invokes the model. Default: no-op."""


class MemoryManagerError(RuntimeError):
    """Backend-neutral base error exposed at the MemoryManager boundary."""


class MemoryConflictError(MemoryManagerError):
    """The requested write lost an optimistic-concurrency race."""


class MemoryCorruptionError(MemoryManagerError):
    """Persisted memory cannot be read safely."""


class MemoryManager(BaseModel):
    """Backend-neutral memory manager contract.

    A pydantic ``BaseModel`` (not a bare ``ABC``) so the contract gains field
    validation + serialization for free and shares the pydantic v2 type system
    with backend configs (e.g. ``DeerMemConfig``). Subclasses still MUST
    implement the ``@abstractmethod``s -- pydantic's ``ModelMetaclass`` derives
    from ``ABCMeta``, so unimplemented abstractmethods raise ``TypeError`` at
    instantiation (memory is persistent state; a backend missing ``add`` /
    ``get_context`` is a severe bug, caught at construction). Backend-private
    dependencies (storage / llm / queue / ...) are NOT fields -- they are
    ``PrivateAttr`` set in ``model_post_init`` (or ``from_config``), kept out of
    validation / serialization.

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

    Methods are tiered: tier-1 (``add`` / ``get_context``) are ``@abstractmethod``;
    tier-2 management ops and tier-3 optional hooks carry defaults (``raise
    NotImplementedError`` or a no-op) so a backend implements only what it
    supports. ``delete_memory`` / ``export_memory`` are dead contract (zero
    callers; ``/memory/export`` routes via ``get_memory``) kept available via the
    default raise.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Backend-private config (factory passes it through). Backends that need to
    # parse it (DeerMem -> DeerMemConfig) do so in model_post_init / from_config.
    # None is coerced to {} so zero-config ``Backend(backend_config=None)`` stays
    # valid (BaseModel would otherwise reject None for a dict field).
    backend_config: dict[str, Any] = Field(default_factory=dict)
    # Operation mode mirrors host ``MemoryConfig.mode`` ("middleware" | "tool");
    # the factory passes ``cfg.mode``. The invariant validator requires
    # tool-mode backends to support search.
    mode: Literal["middleware", "tool"] = "middleware"
    # Observability callbacks (optional; a ``MemoryCallbacks`` instance). The
    # factory injects ``LangfuseMemoryCallbacks`` so memory-LLM calls surface in
    # langfuse; None = no callbacks (direct construction / standalone). Backends
    # pass this to their LLM path and call ``on_memory_llm_call`` before invoke.
    callbacks: MemoryCallbacks | None = None

    @field_validator("backend_config", mode="before")
    @classmethod
    def _coerce_backend_config(cls, value: Any) -> dict[str, Any]:
        """Accept None (zero-config) as an empty dict; leave dicts untouched."""
        return value or {}

    # Search capability flag (ClassVar, not a field): set True iff the backend
    # overrides search(). The invariant validator checks the flag MATCHES whether
    # search() is actually overridden (type(self).search is not MemoryManager.search),
    # so the two can't drift -- required for mode="tool" (the agent calls
    # memory_search in tool mode, so a non-search backend is a misconfiguration
    # that fails fast at instantiation rather than silently returning empty
    # results). Default False: a new backend must explicitly opt in to tool mode.
    supports_search: ClassVar[bool] = False

    @model_validator(mode="after")
    def _check_invariants(self) -> MemoryManager:
        """Cross-field invariants every backend must satisfy at instantiation.

        Fires on the factory path AND when a backend is constructed directly
        (bypassing the factory), since it lives on the base model. DeerMem-private
        invariants (e.g. storage_path is a directory) stay on ``DeerMemConfig``.

        ``supports_search`` (ClassVar flag) must match whether ``search()`` is
        actually overridden, so the declarative flag can't drift from the
        implementation -- a backend that overrides ``search()`` but forgets
        ``supports_search = True`` (or sets the flag without overriding) is a bug
        caught at instantiation, not a misleading tool-mode rejection or a runtime
        ``NotImplementedError`` on the first ``memory_search`` call.
        """
        search_overridden = type(self).search is not MemoryManager.search
        if type(self).supports_search != search_overridden:
            raise ValueError(
                f"{type(self).__name__}.supports_search={type(self).supports_search} "
                f"is inconsistent with search(): search() is "
                f"{'overridden' if search_overridden else 'inherited (not implemented)'}. "
                f"Set supports_search={search_overridden} on the backend to match."
            )
        if self.mode == "tool" and not search_overridden:
            raise ValueError(
                f"memory mode='tool' requires a backend that implements search(), but {type(self).__name__} does not override search(). Use mode='middleware' or a backend that overrides search() (and sets supports_search=True)."
            )
        return self

    # ── Tier 1: @abstractmethod ─────────────────────────────────────────
    # Every backend MUST implement these (write + read-inject are the backend's
    # fundamental duties). Missing one is a severe bug (memory is persistent
    # state) -- @abstractmethod catches it at instantiation. noop implements
    # them as no-op / "".
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

    # ── Tier 2: management ops with defaults ────────────────────────────
    # A backend that does not support an operation inherits the default (raise
    # ``NotImplementedError``) instead of having to write the raise. ``add_nowait``
    # defaults to delegating to ``add`` (a backend without a debounce queue has no
    # "immediate" vs "queued" distinction); ``shutdown_flush`` defaults to True (a
    # backend without a buffer has nothing to drain) so the host can call it
    # unconditionally. ``delete_memory`` / ``export_memory`` are dead contract
    # (zero callers; /memory/export routes via get_memory) -- the default raise
    # keeps them available without forcing backends to implement.
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
        content is captured instead of lost. Default: delegate to :meth:`add`
        (backends without a debounce queue override to enqueue with nowait
        priority).
        """
        self.add(thread_id, messages, agent_name=agent_name, user_id=user_id)

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
        categories' higher-ranked facts. Default: unsupported (raise); backends
        with retrieval override AND set ``supports_search = True`` (required for
        ``mode='tool'``)."""
        raise NotImplementedError(f"search not supported by {type(self).__name__}")

    def get_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        """Return the full memory document for the bucket. Default: unsupported."""
        raise NotImplementedError(f"get_memory not supported by {type(self).__name__}")

    def delete_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> None:
        """Delete the entire memory document for the bucket. Default: unsupported
        (dead contract -- zero callers)."""
        raise NotImplementedError(f"delete_memory not supported by {type(self).__name__}")

    def clear_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        """Clear the bucket's memory; return the cleared (now-empty) document.

        ``agent_name=None`` means all memory owned by the user. An explicit
        agent name clears only that agent's memory and must preserve shared
        user-level summaries. Default: unsupported (raise
        ``NotImplementedError``); backends that support clearing override.
        """
        raise NotImplementedError(f"clear_memory not supported by {type(self).__name__}")

    def import_memory(
        self,
        memory_data: dict[str, Any],
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        """Import a memory document into the bucket; return the merged result.
        Default: unsupported."""
        raise NotImplementedError(f"import_memory not supported by {type(self).__name__}")

    def export_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        """Export the memory document for the bucket. Default: unsupported (dead
        contract -- zero callers; /memory/export routes via get_memory)."""
        raise NotImplementedError(f"export_memory not supported by {type(self).__name__}")

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
        any unfinished tail is dropped, strictly better than no flush). Default:
        ``True`` (a backend with no buffer has nothing to drain), so the host may
        call this unconditionally when memory is enabled; backends with a debounce
        queue override to flush within ``timeout``.
        """
        return True

    # ── Tier 3: optional hooks ──────────────────────────────────────────
    # A-class: agent-side has real callers (startup warm-up, manual reload, fact
    # CRUD). Previously reached via ``hasattr`` probing; now contracted with
    # defaults so callers invoke directly and catch ``NotImplementedError``.
    # ``warm`` defaults to None (nothing to warm); the rest default to raise.
    def warm(self) -> bool | None:
        """Pre-warm backend resources at startup (e.g. the tiktoken encoding
        cache). Probed off the event loop by the Gateway lifespan.

        Return contract (tri-state so the host logs accurately):
          * ``True``  -- warmed successfully (or already cached / unnecessary).
          * ``False`` -- warming was attempted and failed (host falls back).
          * ``None``  -- this backend has nothing to warm (the default). The
            host logs a "skipping" message instead of the misleading "warmed
            successfully", so a non-DeerMem backend doesn't claim a tiktoken
            cache it never touched.

        Backends with heavy one-time init override and return ``True``/``False``.
        """
        return None

    def reload_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        """Drop the cached memory document and reload from storage. Default:
        unsupported (callers fall back to :meth:`get_memory`). Backends with a
        cache override."""
        raise NotImplementedError(f"reload_memory not supported by {type(self).__name__}")

    def create_fact(
        self,
        content: str,
        category: str = "context",
        confidence: float = 0.5,
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        """Manually add one fact. Returns ``(memory_data, fact_id)`` -- ``fact_id``
        is None when a storage cap evicted the just-added fact. Default: unsupported."""
        raise NotImplementedError(f"create_fact not supported by {type(self).__name__}")

    def delete_fact(
        self,
        fact_id: str,
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Delete one fact by id. Default: unsupported."""
        raise NotImplementedError(f"delete_fact not supported by {type(self).__name__}")

    def update_fact(
        self,
        fact_id: str,
        content: str | None = None,
        category: str | None = None,
        confidence: float | None = None,
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Update one fact by id (preserving omitted fields). Default: unsupported."""
        raise NotImplementedError(f"update_fact not supported by {type(self).__name__}")

    # B-class: no agent-side caller yet -- signatures only, for future scenarios.
    # Default no-op so callers can invoke unconditionally without gating. (The
    # self-serving hooks on_delegation / on_session_end / on_memory_write are
    # deliberately NOT contracted: no caller, no event source, or subsumed by
    # the callbacks field.)
    def on_pre_compress(self, messages: list[Any]) -> str:
        """Memory -> compressor feedback (future memory-driven summary
        enrichment). Returns text to inject into the compression prompt
        (default: none)."""
        return ""

    def on_turn_start(self, turn_number: int, message: Any, **kwargs: Any) -> None:
        """Turn-start nudge (future background review). Default: no-op."""
        return None

    # ── Async (speculative) ──────────────────────────────────────────────
    # Interface placeholders so a future async LLM client can override without
    # changing the contract. Defaults delegate to the sync methods (no
    # concurrency benefit -- the real LLM call stays sync); callers today use
    # the sync path.
    async def aadd(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        return self.add(thread_id, messages, agent_name=agent_name, user_id=user_id, trace_id=trace_id)

    async def aget_context(
        self,
        user_id: str | None,
        *,
        agent_name: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        return self.get_context(user_id, agent_name=agent_name, thread_id=thread_id)

    async def asearch(
        self,
        query: str,
        top_k: int = 5,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.search(query, top_k, user_id=user_id, agent_name=agent_name, category=category)

    # ── Construction ─────────────────────────────────────────────────────
    @classmethod
    @abstractmethod
    def from_config(
        cls,
        backend_config: dict[str, Any],
        *,
        mode: Literal["middleware", "tool"] = "middleware",
        **host_hooks: Any,
    ) -> MemoryManager:
        """Build a fully-wired instance from backend config + host-provided hooks.

        The factory calls this instead of constructing the class directly, so
        each backend owns its own assembly (parse config, wire dependencies,
        consume the host hooks it needs). Adding a backend = implement
        ``from_config``; the factory stays unchanged. ``host_hooks`` carries
        host-provided callables/values (tracing, hidden-message filter,
        trace-context manager, a host-llm factory); a backend that needs none
        of them (e.g. noop) ignores them and returns
        ``cls(backend_config=backend_config, mode=mode)``.
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


# ── Host-default hook providers (passed to from_config by the factory) ────
#
# These callables are the host's defaults for the slots a backend may consume
# (tracing, hidden-message filtering, trace-context binding, a host default
# LLM). The portable backend package never names a deer-flow concept; the host
# supplies them HERE (host code outside ``backends/deermem/``). The factory
# passes them to ``cls.from_config(..., **host_hooks)``; each backend's
# ``from_config`` consumes the ones it needs (DeerMem does; noop ignores them).
# An explicit value in ``backend_config`` (set programmatically) takes
# precedence and is left untouched (from_config's merge skips present keys).
#
# Imports are lazy (matching the ``runtime_home`` precedent) so this module
# stays cheap to import and so another agent vendoring the contract only has
# to edit these helpers, not the top-level imports.
class LangfuseMemoryCallbacks(MemoryCallbacks):
    """Host default callbacks: emit langfuse spans at the memory-LLM boundary.

    Implements ``on_memory_llm_call`` (pre-LLM-call) by merging langfuse trace
    metadata into ``invoke_config`` -- identical to the former
    ``_host_default_tracing_callback`` (same signature, same timing, same
    mutation), repackaged as a callbacks method so the langfuse binding lives in
    host code and the portable backend package never names langfuse. No-op when
    langfuse is not an enabled tracing provider.
    """

    def on_memory_llm_call(
        self,
        invoke_config: dict[str, Any],
        *,
        thread_id: str | None,
        user_id: str | None,
        trace_id: str | None,
        model_name: str | None,
    ) -> None:
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
    via the callbacks' ``on_memory_llm_call`` metadata merge), mirroring pre-abstraction
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


def _collect_host_hooks() -> dict[str, Any]:
    """Provide host hook callables for backends to consume in ``from_config``.

    The factory is a hook *provider*; each backend's ``from_config`` is the
    *consumer* that decides which hooks to use (so adding a backend does not
    change this factory). ``host_llm`` is provided as a factory callable
    (``host_llm_factory``) rather than a built instance so a backend only
    builds the host default model when it actually needs one (i.e. has no model
    of its own) -- building an unused default on every startup would waste
    time. The others are direct values (cheap function refs).
    """
    from deerflow.trace_context import request_trace_context

    return {
        "callbacks": LangfuseMemoryCallbacks(),
        "should_keep_hidden_message": _host_default_should_keep_hidden_message,
        "trace_context_manager": request_trace_context,
        "host_llm_factory": _host_default_llm,
    }


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
        # storage_path-is-a-file guard lives on DeerMemConfig.model_validator
        # now (DeerMem-private semantics; fires even when the factory bypassed).
        # Host hook providers: the factory supplies these as kwargs; each
        # backend's from_config decides which to consume (the factory stays
        # backend-agnostic -- it no longer knows which hooks a backend needs).
        # An explicit value in backend_config still wins (from_config's merge
        # skips keys already present).
        host_hooks = _collect_host_hooks()
        # ``mode`` mirrors host MemoryConfig.mode so the invariant validator
        # (mode=="tool" requires search) can fire on the factory path too.
        _memory_manager = cls.from_config(backend_config, mode=cfg.mode, **host_hooks)
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
