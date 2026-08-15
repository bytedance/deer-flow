"""DeerMem -- the default :class:`MemoryManager` backend (self-contained).

DeerMem wraps the DeerFlow memory machinery (the five ``core/`` modules:
storage / queue / updater / prompt / message_processing) behind the
backend-neutral :class:`~deerflow.agents.memory.manager.MemoryManager`
contract. DeerMem owns its storage / queue / updater as ``PrivateAttr`` dependencies
(no module-level singletons): the factory passes ``backend_config`` to the
BaseModel field, and ``model_post_init`` parses it into a :class:`DeerMemConfig`
and constructs the dependencies. Behaviour matches the pre-abstraction code: the same filter +
human/ai validation + correction/reinforcement detection feeds the same
debounced queue; the same ``format_memory_for_injection`` produces injection
text; the same CRUD backs the management endpoints.

DeerMem-private concerns (filter/detect, the ``<memory>`` wrap, ``enabled``
gating, the facts model) deliberately stay OUT of the ABC -- they live here.
``warm`` / ``reload_memory`` / fact CRUD are tier-3 optional hooks ON the ABC
(with defaults: ``warm``=True, the rest raise ``NotImplementedError``); DeerMem
overrides the ones it supports. Callers (gateway / client / tools) invoke them
directly and catch ``NotImplementedError`` for unsupported backends -- no more
``hasattr`` probing.
"""

from __future__ import annotations

import copy
import logging
import threading
from typing import Any, ClassVar, Literal

from pydantic import PrivateAttr

from deerflow.agents.memory.manager import MemoryConflictError, MemoryCorruptionError, MemoryManager

from .deermem.config import DeerMemConfig
from .deermem.core.eviction import EVICTION_POLICY_HYBRID_V1
from .deermem.core.llm import build_llm
from .deermem.core.message_processing import (
    SIGNAL_NAMES,
    detect_signals,
    filter_messages_for_memory,
    filter_trivial,
    load_patterns,
)
from .deermem.core.paths import DEFAULT_AGENT_BUCKET
from .deermem.core.prompt import format_memory_for_injection, load_prompt, load_prompt_messages, warm_tiktoken_cache
from .deermem.core.queue import MemoryUpdateQueue, QueueFull
from .deermem.core.storage import MemoryRevisionConflict, MemoryStorageCorruption, create_storage
from .deermem.core.updater import MemoryUpdater, _coerce_source_confidence

logger = logging.getLogger(__name__)


def _resolve_agent_name(agent_name: str | None) -> str:
    """Return DeerFlow's case-insensitive canonical agent identifier."""
    return agent_name.lower() if agent_name is not None else DEFAULT_AGENT_BUCKET


def _call_backend(operation):
    """Translate DeerMem-private storage errors into the public manager contract."""
    try:
        return operation()
    except MemoryRevisionConflict as exc:
        raise MemoryConflictError(str(exc)) from exc
    except MemoryStorageCorruption as exc:
        raise MemoryCorruptionError(str(exc)) from exc


def _legacy_source_value(source: Any) -> str:
    """Project structured source metadata back to the legacy public string."""
    if isinstance(source, str):
        return source
    if not isinstance(source, dict):
        return "unknown"
    source_type = source.get("type")
    thread_id = source.get("threadId")
    if source_type == "conversation" and isinstance(thread_id, str) and thread_id:
        return thread_id
    if isinstance(source_type, str) and source_type:
        return source_type
    if isinstance(thread_id, str) and thread_id:
        return thread_id
    return "unknown"


def _compat_document(memory_data: dict[str, Any]) -> dict[str, Any]:
    """Return the historical Manager/API shape without changing persistence."""
    result = copy.deepcopy(memory_data)
    for fact in result.get("facts", []):
        if isinstance(fact, dict):
            fact["source"] = _legacy_source_value(fact.get("source"))
    return result


class DeerMem(MemoryManager):
    """Default memory backend: file-backed facts + debounced LLM extraction."""

    # Backend-private dependencies are PrivateAttr (not pydantic fields): they
    # are non-pydantic objects (storage / llm / queue) that must NOT participate
    # in validation / serialization. Built once in model_post_init from
    # self.backend_config -> DeerMemConfig.
    _config: Any = PrivateAttr(default=None)
    _storage: Any = PrivateAttr(default=None)
    _llm: Any = PrivateAttr(default=None)
    _updater: Any = PrivateAttr(default=None)
    _queue: Any = PrivateAttr(default=None)
    _trivial_patterns: Any = PrivateAttr(default=None)

    # DeerMem implements search() (case-insensitive substring over stored facts),
    # so it is valid for mode="tool" (the base invariant validator requires this
    # for tool mode). Backends without real search inherit the False default and
    # cannot be used with mode="tool".
    supports_search: ClassVar[bool] = True

    def model_post_init(self, __context: Any) -> None:
        """Construct DeerMem's dependencies from ``self.backend_config``.

        Runs after pydantic's ``__init__`` validates the fields. Parses
        ``backend_config`` into a :class:`DeerMemConfig` (defaults apply when
        empty/None) and wires storage / patterns / llm / updater / queue (DI).
        """
        self._config = DeerMemConfig.from_backend_config(self.backend_config)
        self._storage = create_storage(self._config)
        # Signal-detection patterns (externalized YAML; ``patterns_dir`` override
        # or bundled defaults = pre-externalization behavior). Loaded once at
        # construction and reused by ``_prepare_update``'s detect_* calls.
        # Pre-load trivial + signal patterns at construction so a misconfigured
        # patterns_dir (missing / invalid yaml) surfaces at startup, not on the
        # first update. Compiled patterns are cached by load_patterns.
        self._trivial_patterns = load_patterns("trivial", patterns_dir=self._config.patterns_dir)
        for _signal_name in SIGNAL_NAMES:
            load_patterns(_signal_name, patterns_dir=self._config.patterns_dir)
        # host_llm (host-injected default model) takes precedence over build_llm(model)
        # so zero-config DeerMem (empty `model`) still extracts via the app default,
        # mirroring pre-abstraction `model_name: null`. Standalone (no factory) -> None.
        self._llm = self._config.host_llm if self._config.host_llm is not None else build_llm(self._config.model)
        self._updater = MemoryUpdater(self._config, self._storage, self._llm, prompts_dir=self._config.prompts_dir, callbacks=self.callbacks)
        # Retrieval is derived data. The first search for a scope lazily
        # rebuilds it; Gateway warm-up performs the full rebuild off-loop.
        self._retrieval_lock = threading.RLock()
        self._retrieval_warmed_scopes: set[tuple[str | None, str | None]] = set()
        self._retrieval_fully_warmed = False
        # Validate the *global* explicit prompt templates at construction so a
        # misconfigured prompts_dir surfaces at startup rather than as a silent
        # dropped update. Per-agent overrides ({prompts_dir}/{agent}/*.yaml)
        # cannot be known here -- they are validated lazily at first use and
        # logged at ERROR by the updater's exception handler.
        # fact_extraction is dormant (not wired to any runtime caller); excluded.
        if self._config.prompts_dir is not None:
            _dummy_vars = {
                "current_memory": "{}",
                "conversation": "(validation)",
                "correction_hint": "",
                "staleness_review_section": "",
                "consolidation_section": "",
            }
            load_prompt("staleness_review", prompts_dir=self._config.prompts_dir).format(stale_facts="")
            load_prompt("consolidation", prompts_dir=self._config.prompts_dir).format(consolidation_groups="", max_groups=1)
            load_prompt_messages("memory_update", _dummy_vars, prompts_dir=self._config.prompts_dir)
        self._queue = MemoryUpdateQueue(self._config, self._updater)

    @classmethod
    def from_config(
        cls,
        backend_config: dict[str, Any] | None = None,
        *,
        mode: Literal["middleware", "tool"] = "middleware",
        **host_hooks: Any,
    ) -> DeerMem:
        """Build a DeerMem with dependencies wired, consuming host hooks.

        The factory passes host hooks (tracing, hidden-message filter,
        trace-context manager, a host-llm factory) as kwargs rather than
        injecting them into ``backend_config``; DeerMem merges the ones it
        consumes (DeerMemConfig fields) here, respecting explicit
        ``backend_config`` values. ``host_llm`` is built from the host factory
        only when no model is configured (host_llm takes precedence over
        ``build_llm(model)``; building an unused host default when a model
        exists would waste startup time). The actual dependency wiring runs in
        ``model_post_init`` (shared with direct construction).
        """
        config_dict = dict(backend_config or {})
        for key in ("should_keep_hidden_message", "trace_context_manager", "extraction_callback"):
            if key not in config_dict and key in host_hooks:
                config_dict[key] = host_hooks[key]
        if "host_llm" not in config_dict:
            model_cfg = config_dict.get("model")
            if not (isinstance(model_cfg, dict) and model_cfg.get("model")):
                host_llm_factory = host_hooks.get("host_llm_factory")
                if host_llm_factory is not None:
                    config_dict["host_llm"] = host_llm_factory()
        # callbacks is a base MemoryManager field (not DeerMemConfig); pass through.
        # config_dict carries the host hooks merged above so model_post_init can
        # parse them into DeerMemConfig (self._config, PrivateAttr). After wiring,
        # restore backend_config to the pure data the host passed (no injected
        # hooks) so the field stays serializable and matches the README contract
        # ("host hooks arrive as from_config kwargs, NOT in backend_config") --
        # the hooks live in self._config, not the backend_config field.
        instance = cls(backend_config=config_dict, mode=mode, callbacks=host_hooks.get("callbacks"))
        instance.backend_config = dict(backend_config or {})
        return instance

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
        """Filter, validate, detect signals, then enqueue (debounced).

        Mirrors the preprocessing that lived in ``MemoryMiddleware.after_agent``
        before the abstraction. The ``enabled`` gate and
        ``thread_id``/``user_id``/``trace_id`` resolution stay at the call site.
        """
        prepared = self._prepare_update(messages)
        if prepared is None:
            return
        filtered, signals = prepared
        # DeerMem owns the queue, so it owns the backpressure degradation: a
        # QueueFull here is logged + dropped so memory backpressure degrades to
        # "update skipped" rather than propagating into
        # MemoryMiddleware.after_agent and breaking the agent run (peer
        # middlewares self-guard the same way). The dropped update is re-fed
        # next turn (the middleware passes the full conversation each cycle, and
        # the watermark does not advance on a non-enqueued turn).
        try:
            self._queue.add(
                thread_id=thread_id,
                messages=filtered,
                agent_name=_resolve_agent_name(agent_name),
                user_id=user_id,
                trace_id=trace_id,
                signals=signals,
            )
        except QueueFull as e:
            logger.warning("Memory update rejected under backpressure (thread=%s): %s", thread_id, e)

    def add_nowait(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
    ) -> None:
        """Filter, validate, detect signals, then enqueue for immediate flush.

        Mirrors the preprocessing that lived in ``memory_flush_hook`` before
        the abstraction. Used right before summarization removes messages.
        """
        prepared = self._prepare_update(messages)
        if prepared is None:
            return
        filtered, signals = prepared
        # Defense-in-depth: the emergency path always admits under backpressure
        # (see _enqueue_locked), so QueueFull is not expected here -- but the
        # emergency flush is invoked from summarization_hook, so a propagated
        # exception would break summarization. Catch + log to be safe.
        try:
            self._queue.add_nowait(
                thread_id=thread_id,
                messages=filtered,
                agent_name=_resolve_agent_name(agent_name),
                user_id=user_id,
                signals=signals,
            )
        except QueueFull as e:
            logger.warning("Memory emergency flush rejected under backpressure (thread=%s): %s", thread_id, e)

    def _prepare_update(
        self,
        messages: list[Any],
    ) -> tuple[list[Any], frozenset[str]] | None:
        """Filter to user+final-AI messages, require both, detect signals.

        Returns ``(filtered, signals)`` where ``signals`` is the set of signal
        classes detected in the recent turns, or ``None`` when there is no
        meaningful conversation (missing a user or an assistant turn, or every
        turn dropped as a trivial pure-acknowledgment).
        """
        filtered = filter_messages_for_memory(
            messages,
            should_keep_hidden_message=self._config.should_keep_hidden_message,
        )
        filtered = filter_trivial(filtered, patterns=self._trivial_patterns)
        user_messages = [m for m in filtered if getattr(m, "type", None) == "human"]
        assistant_messages = [m for m in filtered if getattr(m, "type", None) == "ai"]
        if not user_messages or not assistant_messages:
            return None
        signals = detect_signals(filtered, patterns_dir=self._config.patterns_dir)
        return filtered, frozenset(signals)

    # ── Read ─────────────────────────────────────────────────────────────
    def get_context(
        self,
        user_id: str | None,
        *,
        agent_name: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        """Load memory and format it for injection (plain text, no wrap).

        Middleware mode injects the selected agent's facts together with the
        user-global summaries. Tool mode injects only those global summaries;
        facts stay behind ``memory_search`` so they are not duplicated in the
        prompt and a later retrieval result.

        Format parameters come from DeerMem's own ``DeerMemConfig`` (set at
        construction from ``backend_config``). The ``enabled``/
        ``injection_enabled`` gate and the ``<memory>`` wrapping stay at the
        call site (``_get_memory_context``); this returns only the body.
        """
        injection_agent = None if self.mode == "tool" else _resolve_agent_name(agent_name)
        memory_data = _call_backend(lambda: self._updater.get_memory_data(agent_name=injection_agent, user_id=user_id))
        return format_memory_for_injection(
            memory_data,
            max_tokens=self._config.max_injection_tokens,
            use_tiktoken=(self._config.token_counting == "tiktoken"),
            guaranteed_categories=self._config.guaranteed_categories,
            guaranteed_token_budget=self._config.guaranteed_token_budget,
        )

    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search through the configured retrieval adapter.

        Retrieval errors never make canonical memory unavailable: the existing
        case-insensitive substring path remains the last-resort fallback.
        """
        if not query or not query.strip() or top_k <= 0:
            return []
        resolved_agent_name = _resolve_agent_name(agent_name)
        indexed = self._fts5_search(query, top_k=top_k, user_id=user_id, agent_name=resolved_agent_name, category=category)
        results = indexed or self._substring_search(
            query,
            top_k=top_k,
            user_id=user_id,
            agent_name=resolved_agent_name,
            category=category,
        )
        if results and (self._config.fact_eviction_policy == EVICTION_POLICY_HYBRID_V1 or self._config.fact_eviction_shadow_enabled):
            try:
                self._storage.record_fact_accesses(
                    [str(fact["id"]) for fact in results if fact.get("id")],
                    agent_name=resolved_agent_name,
                    user_id=user_id,
                )
            except Exception:
                # Usage is an eviction hint, never canonical memory. A sidecar
                # write failure must not make memory_search lose its results.
                logger.warning("Failed to record memory-search access heat", exc_info=True)
        return results

    def _fts5_search(
        self,
        query: str,
        *,
        top_k: int,
        user_id: str | None,
        agent_name: str | None,
        category: str | None,
    ) -> list[dict[str, Any]]:
        """Return adapter results in the public fact shape (compatibility helper)."""
        agent_name = _resolve_agent_name(agent_name)
        search_facts = getattr(self._storage, "search_facts", None)
        scopes = [{"userId": user_id, "agentName": agent_name}]
        try:
            self._ensure_retrieval_scopes(scopes)
            indexed = (
                search_facts(
                    query,
                    scopes=scopes,
                    top_k=top_k,
                    mode="hybrid",
                    filters={"category": category} if category else None,
                )
                if callable(search_facts)
                else []
            )
        except Exception:
            logger.exception("Memory retrieval adapter failed; using substring fallback")
            indexed = []
        if indexed:
            return [_compat_document({"facts": [result.get("fact", result)]})["facts"][0] for result in indexed]

        return []

    def _substring_search(
        self,
        query: str,
        *,
        top_k: int,
        user_id: str | None,
        agent_name: str | None,
        category: str | None,
    ) -> list[dict[str, Any]]:
        query_lower = query.strip().lower()
        memory_data = _call_backend(lambda: self._updater.get_memory_data(agent_name=agent_name, user_id=user_id))
        matched = [fact for fact in memory_data.get("facts", []) if isinstance(fact.get("content"), str) and query_lower in fact["content"].lower() and (category is None or fact.get("category") == category)]
        matched.sort(key=_coerce_source_confidence, reverse=True)
        return _compat_document({"facts": matched[:top_k]})["facts"]

    def _ensure_retrieval_scopes(self, scopes: list[dict[str, str | None]]) -> None:
        """Lazily rebuild every requested scope when warm-up was skipped."""
        if not hasattr(self, "_retrieval_lock"):
            self._retrieval_lock = threading.RLock()
        if not hasattr(self, "_retrieval_warmed_scopes"):
            self._retrieval_warmed_scopes = set()
        if not hasattr(self, "_retrieval_fully_warmed"):
            self._retrieval_fully_warmed = False
        rebuild = getattr(self._storage, "rebuild_index", None)
        if not callable(rebuild):
            return
        with self._retrieval_lock:
            if self._retrieval_fully_warmed:
                return
            status = getattr(self._storage, "retrieval_status", lambda: {"configured": True})()
            if not status.get("configured", True):
                self._retrieval_warmed_scopes.update((scope.get("userId"), scope.get("agentName")) for scope in scopes)
                return
            for scope in scopes:
                key = (scope.get("userId"), scope.get("agentName"))
                if key in self._retrieval_warmed_scopes:
                    continue
                try:
                    result = rebuild([scope])
                except Exception:
                    logger.exception("Failed to lazily rebuild memory retrieval index for scope %r", key)
                    continue
                if result.get("supported") and not result.get("fatal"):
                    self._retrieval_warmed_scopes.add(key)

    # ── Manage ───────────────────────────────────────────────────────────
    def get_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        memory_data = _call_backend(lambda: self._updater.get_memory_data(agent_name=_resolve_agent_name(agent_name), user_id=user_id))
        return _compat_document(memory_data)

    # delete_memory / export_memory inherit the base tier-2 default (raise
    # NotImplementedError) -- they are dead contract (zero callers; /memory/export
    # routes via get_memory), so DeerMem no longer repeats the raise.

    def clear_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        if agent_name is None:
            memory_data = _call_backend(lambda: self._updater.clear_all_memory_data(user_id=user_id))
        else:
            memory_data = _call_backend(lambda: self._updater.clear_memory_data(agent_name=_resolve_agent_name(agent_name), user_id=user_id))
        return _compat_document(memory_data)

    def import_memory(
        self,
        memory_data: dict[str, Any],
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        imported = _call_backend(
            lambda: self._updater.import_memory_data(
                memory_data,
                agent_name=_resolve_agent_name(agent_name),
                user_id=user_id,
            )
        )
        return _compat_document(imported)

    # ── Lifecycle ───────────────────────────────────────────────────────
    def shutdown_flush(self, timeout: float) -> bool:
        """Drain the debounce queue within ``timeout`` on graceful shutdown.

        Delegates to the queue's bounded synchronous flush, which joins an
        in-flight worker first (so contexts a debounce Timer already pulled out
        of the queue are not lost on exit) and otherwise drains the queue on a
        daemon thread with a real hard timeout (the memory-update LLM call is
        synchronous and cannot be interrupted). Returns ``True`` only when the
        drain genuinely finished within ``timeout``.
        """
        return self._queue.flush_sync(timeout)

    def close(self) -> None:
        """Close derived retrieval resources after pending updates drain."""
        self._storage.close()

    # ── Tier 3 hooks (override the base defaults; warm/reload/fact CRUD) ──
    def warm(self) -> bool:
        """Pre-warm DeerMem's token-counting resources.

        Overrides the base tier-3 hook (default None = nothing to warm). The
        Gateway lifespan calls ``manager.warm()`` directly off the event loop;
        backends without heavy init inherit the None default (the host logs
        "skipping"). Returns True if the encoding loaded (or was already cached,
        or warming was unnecessary); False if tiktoken is unavailable or the
        download failed.
        """
        if self._config.token_counting == "char":
            logger.info("token_counting='char'; tiktoken not used, skipping warm-up")
            return True
        return warm_tiktoken_cache()

    def warm_retrieval(self) -> bool:
        """Rebuild the complete derived retrieval index before serving traffic."""
        rebuild = getattr(self._storage, "rebuild_index", None)
        if not callable(rebuild):
            return True
        try:
            result = rebuild()
            index_ok = not bool(result.get("fatal"))
            failed = int(result.get("failed") or 0)
            if failed and index_ok:
                logger.warning(
                    "Memory retrieval index rebuilt with %d fact(s) skipped",
                    failed,
                )
            if index_ok:
                with self._retrieval_lock:
                    self._retrieval_fully_warmed = True
                    self._retrieval_warmed_scopes.clear()
            return index_ok
        except Exception:
            logger.exception("Failed to rebuild memory retrieval index during warm-up")
            return False

    def reload_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        """Drop the cached memory document and reload from disk."""
        memory_data = _call_backend(
            lambda: self._updater.reload_memory_data(
                agent_name=_resolve_agent_name(agent_name),
                user_id=user_id,
            )
        )
        return _compat_document(memory_data)

    def create_fact(
        self,
        content: str,
        category: str = "context",
        confidence: float = 0.5,
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        memory_data, fact_id = _call_backend(
            lambda: self._updater.create_memory_fact(
                content,
                category=category,
                confidence=confidence,
                agent_name=_resolve_agent_name(agent_name),
                user_id=user_id,
            )
        )
        return _compat_document(memory_data), fact_id

    def delete_fact(
        self,
        fact_id: str,
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        memory_data = _call_backend(
            lambda: self._updater.delete_memory_fact(
                fact_id,
                agent_name=_resolve_agent_name(agent_name),
                user_id=user_id,
            )
        )
        return _compat_document(memory_data)

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
        memory_data = _call_backend(
            lambda: self._updater.update_memory_fact(
                fact_id,
                content=content,
                category=category,
                confidence=confidence,
                agent_name=_resolve_agent_name(agent_name),
                user_id=user_id,
            )
        )
        return _compat_document(memory_data)
