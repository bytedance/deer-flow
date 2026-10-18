"""Summarization middleware extensions for DeerFlow."""

from __future__ import annotations

import hashlib
import html
import logging
import threading
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from time import monotonic
from typing import Any, Protocol, override, runtime_checkable

from deerflow_extension_api import CompactionEvent, canonical_hash
from langchain.agents import AgentState
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.messages import AnyMessage, HumanMessage, RemoveMessage, SystemMessage, get_buffer_string
from langgraph.config import get_config
from langgraph.constants import TAG_NOSTREAM
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.runtime import Runtime

from deerflow.agents.middlewares.dynamic_context_middleware import is_dynamic_context_reminder
from deerflow.agents.middlewares.message_utils import is_genuine_user_message
from deerflow.agents.middlewares.pii_redaction_middleware import redact_text
from deerflow.agents.middlewares.todo_middleware import TODO_REMINDER_MESSAGE_NAME
from deerflow.config.app_config import get_app_config
from deerflow.config.summarization_config import DEFAULT_KEEP
from deerflow.config.task_continuity_config import TaskContinuityConfig
from deerflow.extensions.notify import notify_context_compacted
from deerflow.models import create_chat_model
from deerflow.models.reasoning import resolve_reasoning_contract
from deerflow.runtime.events.catalog import MIDDLEWARE_SUMMARIZE_TAG
from deerflow.utils.upload_context import project_upload_contexts

logger = logging.getLogger(__name__)
_SUMMARY_TRIGGER_MESSAGE_NAME = "summary"
_COMPACTION_TRANSFORM_KIND = "summarization"
_COMPACTION_TRANSFORM_VERSION = "2"
_UNSET = object()
_NOOP_CACHE_MAX_ENTRIES = 128
_MAX_SUMMARY_CHUNKS = 64
_SUMMARY_CHUNK_RETRY_SECONDS = 300
_SUMMARY_CHUNK_RETRY_MAX_ENTRIES = 128
_SUMMARY_CHUNK_RETRY_CACHE: OrderedDict[str, tuple[float, int]] = OrderedDict()
_SUMMARY_CHUNK_RETRY_LOCK = threading.Lock()
_SHORTENED_SUMMARY_MARKER = "\n[summary shortened]\n"


class _ReusedSummary(str):
    """Marks a summary reused from an identical, previously no-op prompt (no LLM call)."""


class SummaryGenerationError(RuntimeError):
    """Summary generation failed after exhausting the run-model fallback.

    Raised only when a caller opts in via ``raise_on_failure`` (the manual
    ``/compact`` path) so a real failure is reported distinctly from "nothing to
    compact". The automatic path leaves ``raise_on_failure`` False and swallows the
    failure, leaving compaction state unchanged for the turn.
    """


@dataclass(frozen=True)
class SummarizationEvent:
    """Context emitted before conversation history is summarized away."""

    messages_to_summarize: tuple[AnyMessage, ...]
    preserved_messages: tuple[AnyMessage, ...]
    thread_id: str | None
    agent_name: str | None
    runtime: Runtime


@dataclass(frozen=True)
class ContextCompactionResult:
    """Result of summarizing old context and retaining the active tail."""

    summary_text: str
    messages_to_summarize: tuple[AnyMessage, ...]
    preserved_messages: tuple[AnyMessage, ...]
    total_tokens: int
    task_history: dict | None = None


@runtime_checkable
class BeforeSummarizationHook(Protocol):
    """Hook invoked before summarization removes messages from state."""

    def __call__(self, event: SummarizationEvent) -> None: ...


def _resolve_thread_id(runtime: Runtime) -> str | None:
    """Resolve the current thread ID from runtime context or LangGraph config."""
    thread_id = runtime.context.get("thread_id") if runtime.context else None
    if thread_id is None:
        try:
            config_data = get_config()
        except RuntimeError:
            return None
        thread_id = config_data.get("configurable", {}).get("thread_id")
    return thread_id


def _resolve_agent_name(runtime: Runtime) -> str | None:
    """Resolve the current agent name from runtime context or LangGraph config."""
    agent_name = runtime.context.get("agent_name") if runtime.context else None
    if agent_name is None:
        try:
            config_data = get_config()
        except RuntimeError:
            return None
        agent_name = config_data.get("configurable", {}).get("agent_name")
    return agent_name


class DeerFlowSummarizationMiddleware(SummarizationMiddleware):
    """Summarization middleware with pre-compression hook dispatch."""

    def __init__(
        self,
        *args,
        before_summarization: list[BeforeSummarizationHook] | None = None,
        task_continuity_config: TaskContinuityConfig | None = None,
        app_config: Any | None = None,
        configured_model_name: str | None = None,
        run_model_name: str | None = None,
        anchor_model_name: str | None = _UNSET,  # type: ignore[assignment]
        prebuilt_models: Mapping[str | None, Any | None] | None = None,
        extensions=None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._task_continuity_config = task_continuity_config if task_continuity_config is not None and task_continuity_config.enabled is True else None
        self._before_summarization_hooks = before_summarization or []
        # Model-ownership state. The model that actually executes the run is selected
        # per run and is the authoritative source of truth, so the caller (lead /
        # subagent / manual builders) supplies it directly as ``run_model_name``
        # instead of the middleware re-deriving it from ``runtime.context`` /
        # ``get_config()`` — those fields do not carry a custom agent's or a subagent's
        # resolved model.
        #
        # ``configured_model_name`` is the explicitly configured summary model
        # (``None`` => summarize with the run's own model). ``run_model_name`` is the
        # model the run executes with; when they differ and the summary provider is
        # broken (expired key, quota, outage) the run's own working model can still
        # compact.
        self._app_config = app_config
        self._configured_summary_model_name = configured_model_name
        self._run_model_name = run_model_name
        # The summary LLM call runs inside a LangGraph middleware hook, so its token
        # stream would otherwise be captured by the messages-tuple stream callback and
        # broadcast to the frontend as a phantom AI message. Tag a dedicated model copy
        # with TAG_NOSTREAM so the streaming handler skips it.
        # Keep self.model untagged so the parent's profile / ls_params inspection
        # still works.
        self._summary_model = self._tag_nostream(self.model)
        # ``self.model`` is the pre-built *profile anchor*: it drives the parent's
        # token counter / profile inspection and is reused verbatim by generation
        # when a candidate matches its name. The factory anchors this to the active
        # run model even when a separate summary-generation model is configured.
        # Direct construction (tests) keeps the legacy inference from the supplied
        # names so the passed ``model`` remains primary unless the caller opts in to
        # an explicit anchor name.
        if anchor_model_name is _UNSET:
            self._anchor_model_name = configured_model_name or self._default_model_name()
        else:
            self._anchor_model_name = anchor_model_name
        if extensions is None:
            from deerflow.extensions import get_agent_build_extensions

            extensions = get_agent_build_extensions()
        self._extensions = extensions
        self.summary_call_count = 0
        self.summary_noop_count = 0
        self.summary_skip_count = 0
        self._summary_counters_lock = threading.Lock()
        # P1: exact prompt fingerprints whose summarizer output equalled the existing summary.
        self._noop_prompt_cache: OrderedDict[str, str] = OrderedDict()
        self._noop_prompt_cache_lock = threading.Lock()
        # Nostream generation models are either prebuilt by the factory or built
        # lazily by name. An eagerly seeded ``None`` pins the run-model fallback for
        # this middleware instance; unlike the legacy path, it does not allow one
        # lazy rebuild of the explicit summary model at the first compaction.
        self._model_cache: dict[str | None, Any | None] = {name: None if model is None else self._tag_nostream(model) for name, model in (prebuilt_models or {}).items()}

    def release_policy_parameters(self) -> dict[str, object]:
        """Return the effective compaction policy used for release identity."""

        def plain_size(value: object) -> object:
            if isinstance(value, tuple):
                return [plain_size(child) for child in value]
            if isinstance(value, list):
                return [plain_size(child) for child in value]
            return value

        return {
            "trigger": plain_size(self.trigger),
            "keep": plain_size(self.keep),
            "trim_tokens_to_summarize": self.trim_tokens_to_summarize,
            "source_coverage": "chronological_chunks",
            "max_summary_chunks": _MAX_SUMMARY_CHUNKS,
            "chunk_limit_retry_seconds": _SUMMARY_CHUNK_RETRY_SECONDS,
            "chunk_limit_retry_max_entries": _SUMMARY_CHUNK_RETRY_MAX_ENTRIES,
            "summary_carry_budget_fraction": 0.5,
            "summary_prompt_hash": canonical_hash(self.summary_prompt),
            # Model objects are not JSON-serialisable. Keep generation and context
            # budget ownership distinct in the identity: changing either can alter
            # when history is discarded or which model produces its replacement.
            "summary_model": self._configured_summary_model_name or self._run_model_name or self._anchor_model_name,
            "profile_model": self._anchor_model_name,
            "task_continuity": self._task_continuity_config.model_dump(mode="json") if self._task_continuity_config is not None else None,
        }

    def _tag_nostream(self, model: Any) -> Any:
        """Return a copy of ``model`` carrying TAG_NOSTREAM without clobbering tags.

        lead_agent/agent.py binds "middleware:summarize" for RunJournal attribution;
        RunnableBinding.with_config shallow-merges config, so existing tags must be
        preserved explicitly instead of being overwritten with just [TAG_NOSTREAM].
        """
        existing_tags = list((getattr(model, "config", None) or {}).get("tags") or [])
        merged_tags = [*existing_tags, TAG_NOSTREAM] if TAG_NOSTREAM not in existing_tags else existing_tags
        return model.with_config(tags=merged_tags)

    def _default_model_name(self) -> str | None:
        if self._app_config is None:
            return None
        models = getattr(self._app_config, "models", None)
        return models[0].name if models else None

    def _generation_candidate_names(self) -> list[str | None]:
        """Ordered summary-generation candidates by name (deduplicated).

        Explicit summary model: the configured model first, then the run's own model
        as a distinct fallback. ``model_name: null``: the run's own model only — its
        construction is the primary, so there is no eager dependency on
        ``config.models[0]`` (a bare default is used only when no run model was
        resolved). A ``None`` entry means "let ``create_chat_model`` pick the default",
        which only occurs when nothing resolves a name.
        """
        default = self._default_model_name()
        if self._configured_summary_model_name is not None:
            names = [self._configured_summary_model_name, self._run_model_name or default]
        else:
            names = [self._run_model_name or default]
        deduped: list[str | None] = []
        seen: set[str | None] = set()
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            deduped.append(name)
        return deduped

    def _model_for(self, name: str | None) -> Any | None:
        """The nostream summary model for ``name``, built lazily and guarded.

        Returns the pre-built anchor when ``name`` matches it (no rebuild), otherwise
        constructs and caches. A construction failure is caught and cached as ``None``
        so a broken candidate config never escapes the fail-open boundary, is never
        retried this turn, and still lets the next candidate run.
        """
        if name == self._anchor_model_name:
            return self._summary_model
        if name in self._model_cache:
            return self._model_cache[name]
        try:
            model = create_chat_model(
                name=name,
                thinking_enabled=_summary_model_thinking_enabled(name, self._app_config),
                app_config=self._app_config,
                attach_tracing=False,
            )
            built = self._tag_nostream(model.with_config(tags=["middleware:summarize"]))
        except Exception:
            logger.exception("Failed to build summary model %r; trying the next candidate", name)
            built = None
        self._model_cache[name] = built
        return built

    @override
    def _create_summary(self, messages_to_summarize: list[AnyMessage]) -> str | None:
        return self._summarize_with(messages_to_summarize)

    @override
    async def _acreate_summary(self, messages_to_summarize: list[AnyMessage]) -> str | None:
        return await self._asummarize_with(messages_to_summarize)

    @staticmethod
    def _nonempty_summary(text: Any) -> str | None:
        """A blank model response is a generation failure, never a replacement."""
        stripped = text.strip() if isinstance(text, str) else ""
        return stripped or None

    def _summary_source_text(self, messages: list[AnyMessage]) -> str:
        # Redact the complete source before splitting: an identifier spanning a
        # chunk boundary must not bypass PII screening. Input remains plain text,
        # so the chat-message human-anchor filter is neither needed nor safe.
        return redact_text(get_buffer_string(project_upload_contexts(messages)), getattr(self._app_config, "pii_redaction", None))

    def _summarize_with(self, messages_to_summarize: list[AnyMessage], previous_summary: str | None = None, *, runtime: Runtime | None = None) -> str | None:
        """Fold every selected source fragment before committing any removal.

        Chunk progress and summaries are local to this call; cached middleware
        instances can serve concurrent runs without sharing mutable cursors.
        The existing generation fallback and no-op cache apply to each prompt.
        """
        if not messages_to_summarize:
            return "No previous conversation history."
        source = self._summary_source_text(messages_to_summarize)
        retry_key = self._summary_retry_key(runtime, messages_to_summarize, previous_summary)
        if self._summary_retry_blocked(retry_key, len(source)):
            return None
        summary = self._bound_summary_carry(previous_summary) if previous_summary else None
        if previous_summary and summary is None:
            return None
        cursor, chunks, all_reused = 0, 0, True
        while cursor < len(source):
            if self._summary_chunk_limit_reached(chunks, cursor, len(source), summary):
                self._remember_summary_chunk_breach(retry_key, len(source))
                return None
            step = self._next_summary_step(source, cursor, summary)
            if step is None:
                return None
            prompt, end = step
            summary = self._summarize_prompt(prompt, summary)
            if summary is None:
                return None
            all_reused = all_reused and isinstance(summary, _ReusedSummary)
            cursor = end
            chunks += 1
        if summary is None:
            return None
        return _ReusedSummary(summary) if all_reused else str(summary)

    async def _asummarize_with(self, messages_to_summarize: list[AnyMessage], previous_summary: str | None = None, *, task_store=None, runtime: Runtime | None = None) -> str | None:
        """Async fold; hooks, state replacement and success telemetry stay atomic."""
        if not messages_to_summarize:
            return "No previous conversation history."
        source = self._summary_source_text(messages_to_summarize)
        retry_key = self._summary_retry_key(runtime, messages_to_summarize, previous_summary)
        if self._summary_retry_blocked(retry_key, len(source)):
            return None
        summary = self._bound_summary_carry(previous_summary) if previous_summary else None
        if previous_summary and summary is None:
            return None
        cursor, chunks, all_reused = 0, 0, True
        while cursor < len(source):
            if self._summary_chunk_limit_reached(chunks, cursor, len(source), summary):
                self._remember_summary_chunk_breach(retry_key, len(source))
                return None
            step = self._next_summary_step(source, cursor, summary)
            if step is None:
                return None
            prompt, end = step
            summary = await self._asummarize_prompt(prompt, summary, task_store=task_store)
            if summary is None:
                return None
            all_reused = all_reused and isinstance(summary, _ReusedSummary)
            cursor = end
            chunks += 1
        if summary is None:
            return None
        return _ReusedSummary(summary) if all_reused else str(summary)

    def _summarize_prompt(self, prompt: str, previous_summary: str | None) -> str | None:
        names = self._generation_candidate_names()
        noop_key = self._noop_cache_key(prompt, names)
        reused = self._reuse_noop_summary(noop_key, previous_summary)
        if reused is not None:
            return reused
        for index, name in enumerate(names):
            text = self._invoke_summary(self._model_for(name), prompt, last=index == len(names) - 1)
            if text is not None:
                # A fallback no-op must not suppress retrying a failed primary.
                if index == 0:
                    self._remember_noop_summary(noop_key, text, previous_summary)
                return text
        return None

    async def _asummarize_prompt(self, prompt: str, previous_summary: str | None = None, *, task_store=None) -> str | None:
        names = self._generation_candidate_names()
        noop_key = self._noop_cache_key(prompt, names)
        reused = self._reuse_noop_summary(noop_key, previous_summary)
        if reused is not None:
            return reused
        for index, name in enumerate(names):
            text = await self._ainvoke_summary(
                self._model_for(name),
                prompt,
                last=index == len(names) - 1,
                model_name=name,
                task_store=task_store,
            )
            if text is not None:
                if index == 0:
                    self._remember_noop_summary(noop_key, text, previous_summary)
                return text
        return None

    @staticmethod
    def _noop_cache_key(prompt: str, candidate_names: list[str | None]) -> str | None:
        """Fingerprint of the exact summarizer input: the rendered prompt plus the candidate models."""
        try:
            payload = "|".join([*(repr(name) for name in candidate_names), prompt])
            return hashlib.sha256(payload.encode("utf-8")).hexdigest()
        except Exception:
            logger.warning("Summarization no-op cache key failed", exc_info=True)
            return None

    def _reuse_noop_summary(self, key: str | None, previous_summary: str | None) -> str | None:
        """Return the existing summary instead of calling the LLM for a proven no-op input.

        Only an input whose first candidate produced output byte-identical to
        ``previous_summary`` is cached, and reuse additionally requires today's
        ``previous_summary`` to equal that cached output, so the reused value is exactly
        the existing ``summary_text``. Any failure falls through to the normal LLM call.
        """
        if key is None or not previous_summary:
            return None
        try:
            with self._noop_prompt_cache_lock:
                cached = self._noop_prompt_cache.get(key)
                if cached is None or cached != previous_summary:
                    return None
                self._noop_prompt_cache.move_to_end(key)
            logger.info("Summarization skipped: identical input previously produced an unchanged summary")
            return _ReusedSummary(cached)
        except Exception:
            logger.warning("Summarization no-op cache lookup failed", exc_info=True)
            return None

    def _remember_noop_summary(self, key: str | None, summary: str, previous_summary: str | None) -> None:
        if key is None or not previous_summary or summary != previous_summary:
            return
        try:
            with self._noop_prompt_cache_lock:
                self._noop_prompt_cache[key] = summary
                self._noop_prompt_cache.move_to_end(key)
                while len(self._noop_prompt_cache) > _NOOP_CACHE_MAX_ENTRIES:
                    self._noop_prompt_cache.popitem(last=False)
        except Exception:
            logger.warning("Summarization no-op cache store failed", exc_info=True)

    def _invoke_summary(self, model: Any | None, prompt: str, *, last: bool = False) -> str | None:
        """Invoke ``model`` for a summary; ``None`` on error or a blank response.

        Text extraction / non-empty validation runs *inside* the try: reading the
        response's ``.text`` is part of consuming the provider result, so a failing
        accessor must convert to a candidate failure (fall through) rather than escape
        the fail-open boundary.

        Deliberately unobserved by system-model-call extensions, unlike
        :meth:`_ainvoke_summary`. Both this method and its only host caller
        (``compact_state``) are the sync half of an async-only runtime: the agent runs
        through ``abefore_model``, and ``runtime/context_compaction.py`` calls
        ``acompact_state``. Notifying from here would have to block the calling thread
        on the extension loop for a call site the host never reaches.
        """
        if model is None:
            return None
        try:
            response = model.invoke(prompt, config={"metadata": {"lc_source": "summarization"}})
            return self._checked_summary(response, last)
        except Exception:
            self._log_summary_error(last)
            return None

    async def _ainvoke_summary(
        self,
        model: Any | None,
        prompt: str,
        *,
        last: bool = False,
        model_name: str | None = None,
        task_store=None,
    ) -> str | None:
        """Async counterpart of :meth:`_invoke_summary`."""
        if model is None:
            return None
        try:
            invoke_config = {"metadata": {"lc_source": "summarization"}}
            extensions = getattr(self, "_extensions", None)
            if extensions is None:
                response = await model.ainvoke(prompt, config=invoke_config)
            else:
                from deerflow_extension_api import SystemOperationKind

                from deerflow.extensions.notify import observe_system_model_call

                response = await observe_system_model_call(
                    extensions,
                    SystemOperationKind.SUMMARIZATION,
                    messages=prompt,
                    model_name=model_name,
                    invoke_config=invoke_config,
                    invoke=lambda: model.ainvoke(prompt, config=invoke_config),
                    task_store=task_store,
                )
            return self._checked_summary(response, last)
        except Exception:
            self._log_summary_error(last)
            return None

    def _checked_summary(self, response: Any, last: bool) -> str | None:
        summary = self._nonempty_summary(getattr(response, "text", None))
        if summary is None:
            self._log_summary_empty(last)
            return None
        # Bound every generated carry, including the final output, before it
        # enters either the no-op cache or persisted summary_text.
        return self._bound_summary_carry(summary)

    @staticmethod
    def _log_summary_error(last: bool) -> None:
        if last:
            logger.exception("Summary generation failed; skipping compaction this turn")
        else:
            logger.warning("Summary generation failed; falling back to the run model", exc_info=True)

    @staticmethod
    def _log_summary_empty(last: bool) -> None:
        if last:
            logger.warning("Summary model returned empty text; skipping compaction this turn")
        else:
            logger.warning("Summary model returned empty text; falling back to the run model")

    @staticmethod
    def _summary_count_message(summary_text: str) -> HumanMessage:
        return HumanMessage(content=summary_text, name=_SUMMARY_TRIGGER_MESSAGE_NAME)

    def _messages_for_trigger_count(self, messages: list[AnyMessage], summary_text: str | None) -> list[AnyMessage]:
        messages = project_upload_contexts(messages)
        if not summary_text:
            return messages
        return [*messages, self._summary_count_message(summary_text)]

    def _summary_text_tokens(self, text: str) -> int:
        if not text:
            return 0
        try:
            return max(0, int(self.token_counter([HumanMessage(content=text)])))
        except Exception:
            logger.debug("Failed to count summary input; using a character budget", exc_info=True)
            return len(text)

    def _bound_summary_carry(self, summary: str) -> str | None:
        """Reserve source capacity by bounding only already-generated summaries.

        Never apply this to selected raw history. Redact before shortening so
        slicing an identifier cannot bypass PII handling. Short summaries keep
        their exact text; oversized ones retain both ends and a visible marker.
        """
        text = redact_text(summary, getattr(self._app_config, "pii_redaction", None))
        if self.trim_tokens_to_summarize is None:
            return text
        budget = max(1, self.trim_tokens_to_summarize)
        carry_budget = budget // 2
        tokens = self._summary_text_tokens(text)
        if tokens <= carry_budget:
            return text

        def shortened(keep: int) -> str:
            head, tail = (keep + 1) // 2, keep // 2
            return text[:head] + _SHORTENED_SUMMARY_MARKER + text[-tail:]

        # The complete candidate (including its marker) is measured. An
        # impossibly small budget fails instead of producing an empty carry.
        low, high, bounded = 2, len(text) - 1, None
        while low <= high:
            middle = (low + high) // 2
            candidate = shortened(middle)
            if self._summary_text_tokens(candidate) <= carry_budget:
                bounded, low = candidate, middle + 1
            else:
                high = middle - 1
        if bounded is None:
            logger.warning("Summary carry cannot fit: carry_tokens=%d carry_budget=%d input_budget=%d", tokens, carry_budget, budget)
        else:
            logger.debug("Summary carry shortened: carry_tokens=%d bounded_tokens=%d carry_budget=%d input_budget=%d", tokens, self._summary_text_tokens(bounded), carry_budget, budget)
        return bounded

    def _summary_retry_key(self, runtime: Runtime | None, messages: list[AnyMessage], previous_summary: str | None) -> str | None:
        """Scope cap failures across builds without retaining history or identifiers.

        The opening source ID survives appended turns, unlike a full-source hash.
        A new history window, prior summary or effective policy gets a fresh key.
        Callers without a stable thread identity retain the per-pass limit only.
        """
        if runtime is None or not (thread_id := _resolve_thread_id(runtime)):
            return None
        from deerflow.runtime.user_context import resolve_runtime_user_id

        context = runtime.context if isinstance(runtime.context, Mapping) else {}
        is_subagent = context.get("is_subagent") is True
        agent = context.get("agent_id") if is_subagent else (_resolve_agent_name(runtime) or "lead_agent")
        # Subagents sharing a parent thread still own separate executions.
        execution = context.get("sandbox_lease_owner_id") if is_subagent else None
        return canonical_hash([resolve_runtime_user_id(runtime), str(thread_id), agent, execution, messages[0].id, previous_summary, self.release_policy_parameters()])

    def _summary_retry_blocked(self, key: str | None, source_chars: int) -> bool:
        if key is None:
            return False
        now = monotonic()
        with _SUMMARY_CHUNK_RETRY_LOCK:
            blocked = _SUMMARY_CHUNK_RETRY_CACHE.get(key)
            if blocked is None:
                return False
            deadline, failed_source_chars = blocked
            if now >= deadline or source_chars < failed_source_chars:
                del _SUMMARY_CHUNK_RETRY_CACHE[key]
                return False
            _SUMMARY_CHUNK_RETRY_CACHE.move_to_end(key)
        logger.warning(
            "Summary chunk-limit cooldown active; keeping history: retry_after_seconds=%.1f input_budget=%s. Increase summarization.trim_tokens_to_summarize within model capacity or reduce selected history.",
            deadline - now,
            self.trim_tokens_to_summarize,
        )
        return True

    @staticmethod
    def _remember_summary_chunk_breach(key: str | None, source_chars: int) -> None:
        if key is None:
            return
        with _SUMMARY_CHUNK_RETRY_LOCK:
            _SUMMARY_CHUNK_RETRY_CACHE[key] = (monotonic() + _SUMMARY_CHUNK_RETRY_SECONDS, source_chars)
            _SUMMARY_CHUNK_RETRY_CACHE.move_to_end(key)
            while len(_SUMMARY_CHUNK_RETRY_CACHE) > _SUMMARY_CHUNK_RETRY_MAX_ENTRIES:
                _SUMMARY_CHUNK_RETRY_CACHE.popitem(last=False)

    def _summary_chunk_limit_reached(self, chunks: int, cursor: int, source_chars: int, summary: str | None) -> bool:
        if chunks < _MAX_SUMMARY_CHUNKS:
            return False
        logger.warning(
            "Summary chunk limit reached; keeping history: chunks=%d limit=%d processed_chars=%d source_chars=%d carry_tokens=%d input_budget=%s. "
            "Increase summarization.trim_tokens_to_summarize within model capacity or reduce selected history.",
            chunks,
            _MAX_SUMMARY_CHUNKS,
            cursor,
            source_chars,
            self._summary_text_tokens(summary or ""),
            self.trim_tokens_to_summarize,
        )
        return True

    def _summary_prefix_length(self, source: str, cursor: int, available: int) -> int:
        """Find a verified fitting prefix without repeatedly scanning the suffix.

        Exponentially grow a local window, then bisect only its final interval.
        Character lengths guide probing, never stand in for the token counter.
        """
        remaining = len(source) - cursor
        low, high = 0, min(remaining, max(1, available))
        while self._summary_text_tokens(source[cursor : cursor + high]) <= available:
            low = high
            if high == remaining:
                return high
            high = min(remaining, high * 2)
        high -= 1
        best = low
        low += 1
        while low <= high:
            middle = (low + high) // 2
            if self._summary_text_tokens(source[cursor : cursor + middle]) <= available:
                best, low = middle, middle + 1
            else:
                high = middle - 1
        return best

    def _next_summary_step(self, source: str, cursor: int, previous_summary: str | None) -> tuple[str, int] | None:
        previous = redact_text(previous_summary, getattr(self._app_config, "pii_redaction", None)) if previous_summary else None
        end = len(source)
        if self.trim_tokens_to_summarize is not None:
            available = max(1, self.trim_tokens_to_summarize) - self._summary_text_tokens(previous or "")
            if available <= 0:
                logger.warning("Summary input cannot fit carry: carry_tokens=%d input_budget=%d", self._summary_text_tokens(previous or ""), self.trim_tokens_to_summarize)
                return None
            end = cursor + self._summary_prefix_length(source, cursor, available)
            if end < len(source):
                # Prefer complete serialized lines when possible. Oversized
                # individual messages still advance through contiguous slices.
                boundary = source.rfind("\n", cursor, end) + 1
                if boundary > cursor and self._summary_text_tokens(source[cursor:boundary]) <= available:
                    end = boundary
            if end <= cursor:
                logger.warning("Summary input cannot fit source: source_budget=%d carry_tokens=%d input_budget=%d", available, self._summary_text_tokens(previous or ""), self.trim_tokens_to_summarize)
                return None
        body = self._build_summary_input_text(source[cursor:end], previous)
        if body is None:
            return None
        return self.summary_prompt.format(messages=body).rstrip(), end

    def _build_summary_input_text(self, formatted_messages: str, previous_summary: str | None = None) -> str | None:
        """Wrap complete raw sections; never trim material selected for removal.

        The raw-text budget excludes escaping, wrapper tags and prompt overhead.
        A large carry or an impossibly small budget fails rather than replacing
        source history with a successful placeholder summary.
        """
        if self.trim_tokens_to_summarize is not None and self._summary_text_tokens(formatted_messages) + self._summary_text_tokens(previous_summary or "") > max(1, self.trim_tokens_to_summarize):
            return None
        parts: list[str] = []
        if previous_summary:
            parts.extend(["<existing_summary>", html.escape(previous_summary, quote=False), "</existing_summary>", ""])
        if formatted_messages:
            parts.extend(["<new_messages>", html.escape(formatted_messages, quote=False), "</new_messages>"])
        return "\n".join(parts) if parts else None

    def _build_summary_prompt(self, messages_to_summarize: list[AnyMessage], previous_summary: str | None = None) -> str | None:
        """Build one complete prompt, or reject a window that needs chunking."""
        source = self._summary_source_text(messages_to_summarize)
        previous = redact_text(previous_summary, getattr(self._app_config, "pii_redaction", None)) if previous_summary else None
        body = self._build_summary_input_text(source, previous)
        return self.summary_prompt.format(messages=body).rstrip() if body else None

    def before_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._maybe_summarize(state, runtime)

    async def abefore_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return await self._amaybe_summarize(state, runtime)

    def _prepare_compaction(
        self,
        state: AgentState,
        *,
        force: bool = False,
    ) -> tuple[list[AnyMessage], list[AnyMessage], str | None, int] | None:
        messages = state["messages"]
        self._ensure_message_ids(messages)

        previous_summary = state.get("summary_text") if isinstance(state.get("summary_text"), str) else None
        trigger_messages = self._messages_for_trigger_count(messages, previous_summary)
        total_tokens = self.token_counter(trigger_messages)
        if not force and not self._should_summarize(trigger_messages, total_tokens):
            return None

        # Todo reminders are snapshots of state["todos"], not conversation history.
        # Exclude them before partitioning so neither the summary nor the retained
        # tail contains stale task statuses. TodoMiddleware restores current context
        # when needed before the next model call. Keep state untouched if compaction
        # is skipped or summary generation fails.
        messages = [message for message in messages if not (isinstance(message, HumanMessage) and message.name == TODO_REMINDER_MESSAGE_NAME)]

        cutoff_index = self._determine_cutoff_index(project_upload_contexts(messages))
        if cutoff_index <= 0:
            return None

        # The latest real user message (the current request) must survive: peer
        # rescue no longer covers it (see _preserve_required_context), so
        # lock its id here and rescue by exact id. This keeps the current request
        # without "moving cutoff" — which would also retain early AI/Tool turns and
        # never compress a first-turn long analysis. A Human Input Card reply is
        # hidden from the UI but is still the user's current request.
        latest_user_id: str | None = None
        for msg in reversed(messages):
            if is_genuine_user_message(msg):
                latest_user_id = msg.id
                break

        messages_to_summarize, preserved_messages = self._partition_messages(messages, cutoff_index)
        messages_to_summarize, preserved_messages = self._preserve_required_context(messages_to_summarize, preserved_messages, latest_user_id=latest_user_id)
        if not messages_to_summarize:
            return None
        return messages_to_summarize, preserved_messages, previous_summary, total_tokens

    def _freeze_compaction_sources(self, messages_to_summarize: list[AnyMessage]) -> tuple[str, ...]:
        """Hash each about-to-be-removed message's content before the summary call.

        Returns empty when no ``ContextCompactionObserver`` is registered. The
        hashing is an O(context-size) canonical-JSON pass, and
        ``notify_context_compacted`` would discard the event anyway; an install
        with no observer must not pay for one, the same rule ``_complete_assembly``
        follows for descriptor construction. The check cannot live only in the
        notify call — by then the work is already done.

        Once the summary call returns, ``messages_to_summarize`` is gone from state —
        only the produced summary remains. The mapping from "these messages" to "this
        summary" exists only in this stack frame, so it must be captured now rather
        than reconstructed later.

        Hashes ``message.content`` directly, never ``str(message.content)``:
        DeerFlow messages are routinely multimodal (``list[dict]`` content, e.g.
        ``view_image_middleware``'s injected image payloads), and ``str()`` on a
        dict renders insertion order, so pre-stringifying would make two
        logically identical messages hash differently. ``canonical_hash`` exists
        precisely to normalize that away (sorted keys via ``canonical_json``);
        stringifying first throws the normalization away before it runs.
        """
        extensions = getattr(self, "_extensions", None)
        if extensions is None or not extensions.context_compaction_observers:
            return ()
        return tuple(canonical_hash(message.content) for message in messages_to_summarize)

    def _record_compaction(
        self,
        source_content_hashes: tuple[str, ...],
        *,
        summary: str,
        compacted_message_count: int,
        kept_message_count: int,
    ) -> None:
        event = CompactionEvent(
            transform_kind=_COMPACTION_TRANSFORM_KIND,
            transform_version=_COMPACTION_TRANSFORM_VERSION,
            source_content_hashes=source_content_hashes,
            output_content_hash=canonical_hash(summary),
            compacted_message_count=compacted_message_count,
            kept_message_count=kept_message_count,
        )
        notify_context_compacted(event, extensions=self._extensions)

    def _record_summary_telemetry(self, runtime: Runtime, previous_summary: str | None, summary: str, summarized_count: int, *, llm_call_skipped: bool = False) -> None:
        """Count successful summary results, unchanged results, and no-op cache reuse.

        ``call_count`` includes completed passes and reuse, not individual LLM requests.
        Counters and event snapshots update once per complete pass, regardless of
        its chunk count; telemetry failures stay soft.
        """
        try:
            noop = previous_summary is not None and summary.encode("utf-8") == previous_summary.encode("utf-8")
            with self._summary_counters_lock:
                self.summary_call_count += 1
                self.summary_noop_count += int(noop)
                self.summary_skip_count += int(llm_call_skipped)
                call_count = self.summary_call_count
                noop_count = self.summary_noop_count
                skip_count = self.summary_skip_count
            if noop:
                logger.info("Summarization no-op: result identical to existing summary_text (%d chars)", len(summary))
            context = getattr(runtime, "context", None)
            journal = context.get("__run_journal") if isinstance(context, dict) else None
            if journal is None:
                return
            journal.record_middleware(
                MIDDLEWARE_SUMMARIZE_TAG,
                name=type(self).__name__,
                hook="before_model",
                action="summary_result",
                changes={
                    "noop": noop,
                    "llm_call_skipped": llm_call_skipped,
                    "summary_chars": len(summary),
                    "previous_summary_chars": len(previous_summary) if previous_summary is not None else None,
                    "summarized_message_count": summarized_count,
                    "noop_count": noop_count,
                    "call_count": call_count,
                    "skip_count": skip_count,
                },
            )
        except Exception:
            logger.warning("Summarization telemetry failed", exc_info=True)

    def compact_state(
        self,
        state: AgentState,
        runtime: Runtime,
        *,
        force: bool = False,
        raise_on_failure: bool = False,
    ) -> ContextCompactionResult | None:
        """Summarize old context and retain the active tail.

        ``force`` bypasses the automatic trigger threshold (a manual caller always
        wants to compact). ``raise_on_failure`` is a *separate* concern: when set (the
        manual ``/compact`` path), a generation failure raises ``SummaryGenerationError``
        so it can be reported distinctly from "nothing to compact"; the automatic path
        leaves it False and swallows the failure, retrying on a later triggered turn.
        """
        prepared = self._prepare_compaction(state, force=force)
        if prepared is None:
            return None
        messages_to_summarize, preserved_messages, previous_summary, total_tokens = prepared
        source_content_hashes = self._freeze_compaction_sources(messages_to_summarize)
        summary = self._summarize_with(messages_to_summarize, previous_summary=previous_summary, runtime=runtime)
        if summary is None:
            if raise_on_failure:
                raise SummaryGenerationError("summary generation failed")
            return None
        llm_call_skipped = isinstance(summary, _ReusedSummary)
        summary = str(summary)
        self._record_summary_telemetry(runtime, previous_summary, summary, len(messages_to_summarize), llm_call_skipped=llm_call_skipped)
        # Fire hooks only once a replacement summary exists — flushing pre-compaction
        # messages into durable memory for a summary that never materializes would
        # duplicate that work on the next attempt. Messages are still removed after
        # this returns (in _maybe_summarize), so hooks run before they are gone.
        self._fire_hooks(messages_to_summarize, preserved_messages, runtime)
        self._record_compaction(
            source_content_hashes,
            summary=summary,
            compacted_message_count=len(messages_to_summarize),
            kept_message_count=len(preserved_messages),
        )
        task_history = None
        if self._task_continuity_config is not None:
            from deerflow.agents.task_continuity.archive import capture

            task_history = capture(state, runtime, messages_to_summarize, self._task_continuity_config)
        return ContextCompactionResult(
            summary_text=summary,
            messages_to_summarize=tuple(messages_to_summarize),
            preserved_messages=tuple(preserved_messages),
            total_tokens=total_tokens,
            task_history=task_history,
        )

    async def acompact_state(
        self,
        state: AgentState,
        runtime: Runtime,
        *,
        force: bool = False,
        raise_on_failure: bool = False,
    ) -> ContextCompactionResult | None:
        """Async counterpart of :meth:`compact_state` (see it for ``raise_on_failure``)."""
        prepared = self._prepare_compaction(state, force=force)
        if prepared is None:
            return None
        messages_to_summarize, preserved_messages, previous_summary, total_tokens = prepared
        from deerflow_extension_api import task_store_from_runtime

        source_content_hashes = self._freeze_compaction_sources(messages_to_summarize)
        summary = await self._asummarize_with(
            messages_to_summarize,
            previous_summary=previous_summary,
            task_store=task_store_from_runtime(runtime),
            runtime=runtime,
        )
        if summary is None:
            if raise_on_failure:
                raise SummaryGenerationError("summary generation failed")
            return None
        llm_call_skipped = isinstance(summary, _ReusedSummary)
        summary = str(summary)
        self._record_summary_telemetry(runtime, previous_summary, summary, len(messages_to_summarize), llm_call_skipped=llm_call_skipped)
        # Fire hooks only once a replacement summary exists (see compact_state).
        self._fire_hooks(messages_to_summarize, preserved_messages, runtime)
        self._record_compaction(
            source_content_hashes,
            summary=summary,
            compacted_message_count=len(messages_to_summarize),
            kept_message_count=len(preserved_messages),
        )
        task_history = None
        if self._task_continuity_config is not None:
            from deerflow.agents.task_continuity.archive import acapture

            task_history = await acapture(state, runtime, messages_to_summarize, self._task_continuity_config)
        return ContextCompactionResult(
            summary_text=summary,
            messages_to_summarize=tuple(messages_to_summarize),
            preserved_messages=tuple(preserved_messages),
            total_tokens=total_tokens,
            task_history=task_history,
        )

    def _maybe_summarize(self, state: AgentState, runtime: Runtime) -> dict | None:
        result = self.compact_state(state, runtime, force=False)
        if result is None:
            return None
        return {
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                *result.preserved_messages,
            ],
            "summary_text": result.summary_text,
            **({"task_history": result.task_history} if result.task_history is not None else {}),
        }

    async def _amaybe_summarize(self, state: AgentState, runtime: Runtime) -> dict | None:
        result = await self.acompact_state(state, runtime, force=False)
        if result is None:
            return None
        return {
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                *result.preserved_messages,
            ],
            "summary_text": result.summary_text,
            **({"task_history": result.task_history} if result.task_history is not None else {}),
        }

    def _preserve_required_context(
        self,
        messages_to_summarize: list[AnyMessage],
        preserved_messages: list[AnyMessage],
        *,
        latest_user_id: str | None = None,
    ) -> tuple[list[AnyMessage], list[AnyMessage]]:
        """Keep system messages, tagged dynamic-context reminders and the current user request out of compression.

        State-level SystemMessages are framework-owned instructions and must
        survive compaction, including legacy untagged reminders and extension
        instructions. Transient instructions should be injected into requests,
        not state. Tagged reminders (including their ``__memory`` peers) and the
        latest real user message are also rescued. A subagent keeps its whole system
        prompt as the leading ``SystemMessage`` in state (``create_agent`` is built
        with ``system_prompt=None``), so compressing it would leave every later
        call without its instructions. The untagged ``__user`` peer is deliberately NOT
        rescued by ID-swap prefix: it is a stale historical request that must be
        allowed to compress — the source of cross-turn prompt contamination. The
        *current* request is instead identified by ``latest_user_id``, so a
        first-turn long analysis keeps its ``__user`` request while its early
        AI/Tool turns still compress.

        Rescuing the whole partition is legitimate: ``_prepare_compaction``
        skips compaction when there is no history left to summarize.
        """
        rescued: list[AnyMessage] = []
        remaining: list[AnyMessage] = []
        for msg in messages_to_summarize:
            if isinstance(msg, SystemMessage) or is_dynamic_context_reminder(msg) or (latest_user_id is not None and msg.id == latest_user_id):
                rescued.append(msg)
            else:
                remaining.append(msg)
        return remaining, rescued + preserved_messages

    def _fire_hooks(
        self,
        messages_to_summarize: list[AnyMessage],
        preserved_messages: list[AnyMessage],
        runtime: Runtime,
    ) -> None:
        if not self._before_summarization_hooks:
            return

        event = SummarizationEvent(
            messages_to_summarize=tuple(messages_to_summarize),
            preserved_messages=tuple(preserved_messages),
            thread_id=_resolve_thread_id(runtime),
            agent_name=_resolve_agent_name(runtime),
            runtime=runtime,
        )

        for hook in self._before_summarization_hooks:
            try:
                hook(event)
            except Exception:
                hook_name = getattr(hook, "__name__", None) or type(hook).__name__
                logger.exception("before_summarization hook %s failed", hook_name)


def _summary_model_thinking_enabled(name: str | None, app_config: Any) -> bool:
    """Return a construction mode accepted by the model's reasoning contract.

    Summary generation prefers non-thinking mode, but a required-thinking model
    cannot honor that preference. In particular, a declared
    ``on_disable_request: reject`` contract would reject construction before its
    profile could anchor fraction-based compaction. Resolve ``None`` the same way
    as :func:`create_chat_model` and enable thinking only when the selected model
    requires it; optional and legacy models keep the existing disabled default.
    """
    resolved_app_config = app_config or get_app_config()
    resolved_name = name
    if resolved_name is None:
        models = getattr(resolved_app_config, "models", None)
        resolved_name = models[0].name if models else None
    model_config = resolved_app_config.get_model_config(resolved_name) if resolved_name is not None else None
    return model_config is not None and resolve_reasoning_contract(model_config).thinking_required


def _build_summary_model(candidate_names: list[str | None], app_config: Any) -> tuple[Any | None, str | None]:
    """Build the first constructible summarization model candidate (guarded).

    The returned model is tagged for RunJournal attribution but *not* TAG_NOSTREAM (the
    middleware wraps a nostream copy). The caller may use it as the parent's
    token-counter/profile anchor or seed it as an independent generation model. A
    per-name construction failure is swallowed and the next candidate tried; a trailing
    ``None`` name asks ``create_chat_model`` for its own default. Returns ``(None, None)``
    when nothing can be constructed.
    """
    tried: set[str | None] = set()
    for name in candidate_names:
        if name in tried:
            continue
        tried.add(name)
        try:
            model = create_chat_model(
                name=name,
                thinking_enabled=_summary_model_thinking_enabled(name, app_config),
                app_config=app_config,
                attach_tracing=False,
            )
        except Exception:
            logger.exception("Failed to build summarization model %r; trying the next candidate", name)
            continue
        return model.with_config(tags=["middleware:summarize"]), name
    return None, None


def _anchor_profile_max_input_tokens(model: Any) -> int | None:
    """Pre-construction mirror of the parent's ``_get_profile_limits`` validation.

    Same rules the parent will apply moments later: ``model.profile`` must be a
    ``Mapping`` carrying an ``int`` ``max_input_tokens``. Anything else counts as
    "no usable profile".
    """
    profile = getattr(model, "profile", None)
    if not isinstance(profile, Mapping):
        return None
    max_input_tokens = profile.get("max_input_tokens")
    return max_input_tokens if isinstance(max_input_tokens, int) else None


def _drop_unusable_fraction_clauses(
    profile_model: Any,
    trigger: Any,
    keep: tuple[str, int | float],
) -> tuple[Any, tuple[str, int | float], bool]:
    """Drop fraction clauses the run-profile model cannot resolve.

    LangChain's parent constructor raises ``ValueError`` for a fraction clause when
    ``profile["max_input_tokens"]`` is unavailable, which on a third-party
    OpenAI-compatible model without a declared ``context_window`` would otherwise
    fail the whole agent build (#3103). Fraction trigger clauses are dropped
    (absolute clauses survive), and a fraction ``keep`` falls back to the messages
    default.

    Returns ``(trigger, keep, has_usable_trigger)``; ``has_usable_trigger`` is
    ``False`` only when trigger clauses were configured and every one of them was
    a dropped fraction clause. A ``trigger`` that was ``None`` to begin with passes
    through unchanged with ``has_usable_trigger=True``, preserving the long-standing
    "enabled but never auto-triggers" configuration.
    """
    clauses = list(trigger) if isinstance(trigger, list) else ([] if trigger is None else [trigger])
    has_fraction_trigger = any(isinstance(clause, tuple) and clause[0] == "fraction" for clause in clauses)
    keep_is_fraction = isinstance(keep, tuple) and keep[0] == "fraction"
    if not (has_fraction_trigger or keep_is_fraction):
        return trigger, keep, True
    if _anchor_profile_max_input_tokens(profile_model) is not None:
        return trigger, keep, True

    kept = [clause for clause in clauses if not (isinstance(clause, tuple) and clause[0] == "fraction")]
    dropped = [clause for clause in clauses if isinstance(clause, tuple) and clause[0] == "fraction"]
    if dropped:
        logger.warning(
            "Dropped summarization fraction trigger clause(s) %s: the run model exposes no context window to resolve them against. Declare `context_window` on the run model in config.yaml, or use absolute token/message thresholds.",
            dropped,
        )
    new_keep = keep
    if keep_is_fraction:
        # The shared constant keeps this fallback identical to SummarizationConfig's
        # documented default keep.
        new_keep = DEFAULT_KEEP
        logger.warning(
            "Summarization keep %s is unusable without the run model's context window; falling back to %s. Declare `context_window` on the run model in config.yaml to use fraction retention.",
            keep,
            new_keep,
        )
    if not kept:
        # No trigger clause survived, but only treat that as "nothing usable" when
        # clauses were configured at all: a trigger of None keeps constructing the
        # never-firing middleware, exactly as it does outside this degradation path.
        return None, new_keep, not clauses
    return (kept if isinstance(trigger, list) else kept[0]), new_keep, True


def create_summarization_middleware(
    *,
    app_config: Any | None = None,
    keep: tuple[str, int | float] | None = None,
    skip_memory_flush: bool = False,
    archive_task_history: bool = True,
    run_model_name: str | None = None,
    extensions=None,
) -> DeerFlowSummarizationMiddleware | None:
    """Create the configured summarization middleware.

    Both the lead-agent automatic path and the manual context-compaction path
    use this factory so model resolution, hooks, prompt config, and retention
    defaults cannot drift.

    ``run_model_name`` is the model the run actually executes with, resolved by the
    caller (the lead / subagent / manual builders each already resolve it) and passed
    in as the authoritative source of truth for ``model_name: null`` summarization and
    the explicit-summary-model fallback. The middleware does not re-derive it from
    ``runtime.context`` / ``get_config()``, which do not carry a custom agent's or a
    subagent's resolved model.

    ``archive_task_history=False`` keeps subagent-internal messages out of the
    parent thread archive, independently of the long-term memory opt-out.

    ``skip_memory_flush`` omits the ``memory_flush_hook`` that otherwise
    flushes pre-compaction messages into the durable memory queue. The lead
    chain keeps it unless its Custom Agent opted out of memory; manual
    compaction follows that same policy. The subagent chain always sets it so a
    subagent's INTERNAL turns (the "Task" human message + intermediate AI/tool
    turns) are not written into the PARENT thread's durable memory — the hook
    is keyed by ``thread_id`` and subagents share the parent's ``thread_id``
    (#3875 Phase 3 review).
    """
    resolved_app_config = app_config or get_app_config()
    config = resolved_app_config.summarization

    if not config.enabled:
        return None

    trigger = None
    if config.trigger is not None:
        if isinstance(config.trigger, list):
            trigger = [item.to_tuple() for item in config.trigger]
        else:
            trigger = config.trigger.to_tuple()

    default_name = resolved_app_config.models[0].name if getattr(resolved_app_config, "models", None) else None
    # The parent middleware uses one model for token counting and profile lookup.
    # That owner must be the model receiving the next lead/subagent request, not an
    # independently configured summary generator: a fraction of the latter's window
    # can be dangerously late or unnecessarily early for the active run model.
    profile_name = run_model_name or default_name
    anchor_model, anchor_name = _build_summary_model(
        [profile_name, default_name, None],
        resolved_app_config,
    )
    if anchor_model is None:
        logger.warning("Summarization is enabled but no run-profile model could be constructed; compaction is unavailable for this build")
        return None

    # A distinct explicit summary model owns generation only. Build it eagerly so
    # invalid provider/configuration errors remain visible at agent construction as
    # before, but seed the guarded cache rather than exposing its profile to LangChain.
    # Cache ``None`` on failure so generation falls back to the run model for this
    # middleware instance. This deliberately removes the legacy one-time lazy rebuild
    # at first compaction, so a transient constructor failure during agent build does
    # not recover until a new middleware instance is built.
    prebuilt_models: dict[str | None, Any | None] = {}
    if config.model_name is not None and config.model_name != anchor_name:
        summary_model, _ = _build_summary_model([config.model_name], resolved_app_config)
        prebuilt_models[config.model_name] = summary_model

    # LangChain's SummarizationMiddleware raises ValueError at construction when a
    # fraction clause is configured but the active run model exposes no usable profile
    # (``profile["max_input_tokens"]``) — the default for any third-party
    # OpenAI-compatible model whose ``context_window`` was not declared in
    # config.yaml (#3103: `trigger: fraction` used to fail the whole agent build).
    # Degrade instead: drop the unusable fraction clauses (absolute ones survive)
    # and fall the keep policy back to its messages default. When every configured
    # trigger clause is dropped, construction continues with ``trigger=None`` —
    # the never-firing shape — so manual compaction (``/compact``, which runs with
    # ``force=True`` and never consults trigger clauses) keeps working for a
    # profile-less model instead of reporting "compaction is disabled". The factory
    # attaches a profile from a declared ``context_window``, so this path is
    # reached only when the model's capacity is genuinely unknown.
    trigger, keep_tuple, has_usable_trigger = _drop_unusable_fraction_clauses(anchor_model, trigger, keep or config.keep.to_tuple())
    if not has_usable_trigger:
        logger.warning(
            "Every configured summarization trigger is fraction-based but run model %r "
            "exposes no context window (no `context_window` on the model in config.yaml, no provider profile); "
            "auto-compaction will not fire for this build. Declare `context_window` on the run model to enable "
            "fraction triggers. Manual compaction (/compact) remains available.",
            anchor_name,
        )
    kwargs: dict[str, Any] = {
        "model": anchor_model,
        "trigger": trigger,
        "keep": keep_tuple,
        "trim_tokens_to_summarize": config.trim_tokens_to_summarize,
    }
    if config.summary_prompt is not None:
        kwargs["summary_prompt"] = config.summary_prompt

    hooks: list[BeforeSummarizationHook] = []
    if resolved_app_config.memory.enabled and not skip_memory_flush:
        from functools import partial

        from deerflow.agents.memory.summarization_hook import memory_flush_hook

        hooks.append(partial(memory_flush_hook, pii_redaction_config=getattr(resolved_app_config, "pii_redaction", None)))

    return DeerFlowSummarizationMiddleware(
        **kwargs,
        before_summarization=hooks,
        task_continuity_config=(resolved_app_config.task_continuity if archive_task_history and getattr(getattr(resolved_app_config, "task_continuity", None), "enabled", False) is True else None),
        app_config=resolved_app_config,
        configured_model_name=config.model_name,
        run_model_name=run_model_name,
        anchor_model_name=anchor_name,
        prebuilt_models=prebuilt_models,
        extensions=extensions,
    )
