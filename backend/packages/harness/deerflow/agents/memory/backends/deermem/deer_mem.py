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
from typing import Any, ClassVar, Literal

from pydantic import PrivateAttr

from deerflow.agents.memory.manager import MemoryConflictError, MemoryCorruptionError, MemoryManager

from .deermem.config import DeerMemConfig
from .deermem.core.llm import build_llm
from .deermem.core.message_processing import (
    detect_correction,
    detect_reinforcement,
    filter_messages_for_memory,
    load_patterns,
)
from .deermem.core.paths import DEFAULT_AGENT_BUCKET
from .deermem.core.prompt import format_memory_for_injection, load_prompt, load_prompt_messages, warm_tiktoken_cache
from .deermem.core.queue import MemoryUpdateQueue
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
    _correction_patterns: Any = PrivateAttr(default=None)
    _reinforcement_patterns: Any = PrivateAttr(default=None)

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
        self._correction_patterns = load_patterns("correction", patterns_dir=self._config.patterns_dir)
        self._reinforcement_patterns = load_patterns("reinforcement", patterns_dir=self._config.patterns_dir)
        # host_llm (host-injected default model) takes precedence over build_llm(model)
        # so zero-config DeerMem (empty `model`) still extracts via the app default,
        # mirroring pre-abstraction `model_name: null`. Standalone (no factory) -> None.
        self._llm = self._config.host_llm if self._config.host_llm is not None else build_llm(self._config.model)
        self._updater = MemoryUpdater(self._config, self._storage, self._llm, prompts_dir=self._config.prompts_dir, callbacks=self.callbacks)
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
        for key in ("should_keep_hidden_message", "trace_context_manager"):
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
        filtered, correction_detected, reinforcement_detected = prepared
        self._queue.add(
            thread_id=thread_id,
            messages=filtered,
            agent_name=_resolve_agent_name(agent_name),
            user_id=user_id,
            trace_id=trace_id,
            correction_detected=correction_detected,
            reinforcement_detected=reinforcement_detected,
        )

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
        filtered, correction_detected, reinforcement_detected = prepared
        self._queue.add_nowait(
            thread_id=thread_id,
            messages=filtered,
            agent_name=_resolve_agent_name(agent_name),
            user_id=user_id,
            correction_detected=correction_detected,
            reinforcement_detected=reinforcement_detected,
        )

    def _prepare_update(
        self,
        messages: list[Any],
    ) -> tuple[list[Any], bool, bool] | None:
        """Filter to user+final-AI messages, require both, detect signals.

        Returns ``(filtered, correction_detected, reinforcement_detected)``
        or ``None`` when there is no meaningful conversation (missing a user
        or an assistant turn).
        """
        filtered = filter_messages_for_memory(
            messages,
            should_keep_hidden_message=self._config.should_keep_hidden_message,
        )
        user_messages = [m for m in filtered if getattr(m, "type", None) == "human"]
        assistant_messages = [m for m in filtered if getattr(m, "type", None) == "ai"]
        if not user_messages or not assistant_messages:
            return None
        correction_detected = detect_correction(filtered, patterns=self._correction_patterns)
        reinforcement_detected = not correction_detected and detect_reinforcement(filtered, patterns=self._reinforcement_patterns)
        return filtered, correction_detected, reinforcement_detected

    # ── Read ─────────────────────────────────────────────────────────────
    def get_context(
        self,
        user_id: str | None,
        *,
        agent_name: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        """Load memory and format it for injection (plain text, no wrap).

        Format parameters come from DeerMem's own ``DeerMemConfig`` (set at
        construction from ``backend_config``). The ``enabled``/
        ``injection_enabled`` gate and the ``<memory>`` wrapping stay at the
        call site (``_get_memory_context``); this returns only the body.
        """
        memory_data = _call_backend(lambda: self._updater.get_memory_data(agent_name=_resolve_agent_name(agent_name), user_id=user_id))
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
        """Case-insensitive substring search over stored facts.

        Stand-in for the planned BM25+vector+MMR retrieval
        (``core/retrieval.py``): returns facts whose ``content`` contains the
        query, ranked by confidence desc, capped at ``top_k``. ``category``
        filters BEFORE the ``top_k`` slice so a category-scoped search is not
        starved by higher-confidence facts in other categories. Sufficient for
        the tool-driven memory mode; upgrade to semantic retrieval later
        without changing call sites.
        """
        if not query or not query.strip() or top_k <= 0:
            return []
        query_lower = query.strip().lower()
        search_facts = getattr(self._storage, "search_facts", None)
        resolved_agent_name = _resolve_agent_name(agent_name)
        scopes = [{"userId": user_id, "agentName": resolved_agent_name}]
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
        if indexed:
            return [_compat_document({"facts": [result.get("fact", result)]})["facts"][0] for result in indexed]
        memory_data = _call_backend(lambda: self._updater.get_memory_data(agent_name=resolved_agent_name, user_id=user_id))
        matched = [fact for fact in memory_data.get("facts", []) if isinstance(fact.get("content"), str) and query_lower in fact["content"].lower() and (category is None or fact.get("category") == category)]
        matched.sort(key=_coerce_source_confidence, reverse=True)
        return _compat_document({"facts": matched[:top_k]})["facts"]

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

    # ── Tier 3 hooks (override the base defaults; warm/reload/fact CRUD) ─
    def warm(self) -> bool:
        """Pre-warm DeerMem-specific resources (the tiktoken encoding cache).

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
