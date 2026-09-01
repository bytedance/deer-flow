"""Run event capture via LangChain callbacks.

RunJournal sits between LangChain's callback mechanism and the pluggable
RunEventStore. It standardizes callback data into RunEvent records and
handles token usage accumulation.

Key design decisions:
- on_llm_new_token is NOT implemented -- only complete messages via on_llm_end
- on_chat_model_start captures the first user-visible prompt as llm.human.input and
  extracts the first human message for run.input, because it is more reliable than
  on_chain_start (fires on every node) — messages here are fully structured.
- on_chain_start with parent_run_id=None emits a run.start trace marking root invocation.
- on_llm_end emits llm.ai.response in checkpoint-aligned AIMessage.model_dump() format
- Token usage accumulated in memory, written to RunRow on run completion
- Caller identification via tags injection (lead_agent / subagent:{name} / middleware:{name})
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, HumanMessage, ToolMessage, messages_from_dict
from langgraph.types import Command

from deerflow.agents.human_input import read_human_input_response
from deerflow.runtime.events.catalog import (
    LLM_AI_RESPONSE_EVENT,
    LLM_ERROR_EVENT,
    LLM_HUMAN_INPUT_EVENT,
    LLM_TOOL_RESULT_EVENT,
    MEMORY_CONTEXT_EVENT,
    MIDDLEWARE_EVENT_PATTERN,
    RUN_END_EVENT,
    RUN_ERROR_EVENT,
    RUN_START_EVENT,
)
from deerflow.utils.messages import message_to_text, restore_original_human_message

if TYPE_CHECKING:
    from deerflow.runtime.events.store.base import RunEventStore

logger = logging.getLogger(__name__)

_LEGACY_SUMMARY_MESSAGE_NAME = "summary"
_PERSISTED_HIDDEN_HUMAN_INPUT_RESPONSE_SOURCES = frozenset({"ask_clarification"})


def _should_persist_human_input_message(message: BaseMessage) -> bool:
    if not isinstance(message, HumanMessage):
        return False
    if message.name == _LEGACY_SUMMARY_MESSAGE_NAME:
        return False
    if message.additional_kwargs.get("hide_from_ui") is not True:
        return True
    response = read_human_input_response(message.additional_kwargs)
    return response is not None and response["source"] in _PERSISTED_HIDDEN_HUMAN_INPUT_RESPONSE_SOURCES


def _coerce_seed_message(message: Any) -> Any:
    """Return ``message`` as a ``BaseMessage``, deserializing dict form if needed.

    ``_checkpoint_messages`` (threads.py) returns whatever the snapshot holds,
    and its sibling branch-matching helpers all handle a message being either a
    ``BaseMessage`` or a ``model_dump()``-shaped dict (serde differences across
    checkpoint backends/modes). The seed path must handle both too — otherwise a
    dict-backed checkpoint seeds nothing and the branch silently reports
    ``skipped_empty`` while history exists. Unparseable dicts fall through
    unchanged and are dropped by the ``isinstance(BaseMessage)`` guard.
    """
    if isinstance(message, BaseMessage):
        return message
    if isinstance(message, Mapping):
        msg_type = message.get("type")
        if isinstance(msg_type, str) and msg_type:
            try:
                return messages_from_dict([{"type": msg_type, "data": dict(message)}])[0]
            except Exception:
                logger.warning("branch seed: could not deserialize checkpoint message dict (type=%s)", msg_type)
    return message


def _build_history_seed_events(
    messages: Sequence[Any],
    *,
    thread_id: str,
    run_id_prefix: str,
    seed_metadata: Mapping[str, Any],
) -> list[dict]:
    """Serialize checkpoint messages into run-event rows.

    Rows are grouped into one synthetic run per checkpoint turn
    (``{run_id_prefix}-{n}``), a new turn starting at every persisted human
    message — the same boundary a real run has, since a run begins with a
    human input (including the allowlisted hidden ``ask_clarification``
    reply, which resumes as its own run). ``run_id`` is a *turn* identity to
    the feed's consumers, not merely a provenance tag: regenerating the last
    inherited answer resolves that row's ``run_id`` as the superseded source
    (``_find_target_run_id``) and ``GET /messages/page`` then drops **every**
    row carrying it. One shared id for the whole seed therefore deleted the
    complete inherited history on the branch's first regenerate (#4458); one
    id per turn confines the drop to the turn actually regenerated.

    Mirrors RunJournal's message-event contract so seeded rows are
    indistinguishable from journaled ones except by the supplied seed metadata:
    same event types, ``category="message"``, ``content=message.model_dump()``,
    the human-input persistence rule
    (``_should_persist_human_input_message``), the original-user-text
    restoration, and the same treatment of ``hide_from_ui`` AI/tool rows —
    RunJournal persists them (``on_llm_end`` / ``_persist_tool_result_message``
    do not filter) and the frontend hides them client-side, so the seed writes
    them too rather than dropping them.

    The one deliberate divergence, because a checkpoint message carries no run
    scope: AI rows omit RunJournal's run-scoped enrichment (``usage`` /
    ``latency_ms`` / ``llm_call_index``), and ``caller`` is stamped
    ``lead_agent`` rather than the message's original caller (unrecoverable
    here). Neither is observable today — no consumer indexes those metadata
    keys, and per-message ``caller`` drives no attribution (the ``by_caller``
    usage panel is run-scoped, not fed from the message feed).
    """
    events: list[dict] = []
    created_at = datetime.now(UTC).isoformat()
    # Messages ahead of the first human turn (none in practice) stay in turn 0.
    turn_index = 0
    for raw_message in messages:
        message = _coerce_seed_message(raw_message)
        if not isinstance(message, BaseMessage):
            continue
        if isinstance(message, HumanMessage):
            if not _should_persist_human_input_message(message):
                continue
            turn_index += 1
            event_type = "llm.human.input"
            content = restore_original_human_message(message).model_dump()
            metadata: dict[str, Any] = {"caller": "lead_agent", **seed_metadata}
        elif isinstance(message, AIMessage):
            event_type = "llm.ai.response"
            content = message.model_dump()
            metadata = {"caller": "lead_agent", **seed_metadata}
        elif isinstance(message, ToolMessage):
            event_type = "llm.tool.result"
            content = message.model_dump()
            metadata = dict(seed_metadata)
        else:
            # System / remove / summary artifacts never enter the thread feed.
            continue
        events.append(
            {
                "thread_id": thread_id,
                "run_id": f"{run_id_prefix}-{turn_index}",
                "event_type": event_type,
                "category": "message",
                "content": content,
                "metadata": metadata,
                "created_at": created_at,
            }
        )
    return events


def build_branch_history_seed_events(
    messages: Sequence[Any],
    *,
    thread_id: str,
    run_id_prefix: str,
    parent_thread_id: str,
) -> list[dict]:
    """Serialize inherited branch history into the branch's empty event feed."""
    return _build_history_seed_events(
        messages,
        thread_id=thread_id,
        run_id_prefix=run_id_prefix,
        seed_metadata={
            "branch_seed": True,
            "branch_parent_thread_id": parent_thread_id,
        },
    )


def build_checkpoint_history_seed_events(
    messages: Sequence[Any],
    *,
    thread_id: str,
    run_id_prefix: str,
) -> list[dict]:
    """Serialize legacy checkpoint history for a thread's empty event feed.

    Reuse the branch seed's message normalization and per-turn synthetic run
    grouping, but stamp migration-specific metadata so these rows are not
    misidentified as history inherited from another thread.
    """
    return _build_history_seed_events(
        messages,
        thread_id=thread_id,
        run_id_prefix=run_id_prefix,
        seed_metadata={"checkpoint_history_seed": True},
    )


class RunJournal(BaseCallbackHandler):
    """LangChain callback handler that captures events to RunEventStore."""

    # Subagents may execute on a persistent event loop in another thread. This
    # handler owns loop-local tasks and a store/pool created for the parent run,
    # so the isolated-loop context copier must not inherit it. LangGraph's own
    # stream callbacks remain inheritable and keep child token frames flowing.
    deerflow_loop_bound = True

    # Every callback only updates in-memory run state or schedules async IO.
    # Keeping callbacks on the run's event-loop thread serializes mutations
    # from parallel tool calls and prevents cancelled executor callbacks from
    # racing terminal delivery recording and flush.
    run_inline = True

    def __init__(
        self,
        run_id: str,
        thread_id: str,
        event_store: RunEventStore,
        *,
        track_token_usage: bool = True,
        flush_threshold: int = 20,
        progress_reporter: Callable[[dict], Awaitable[None]] | None = None,
        progress_flush_interval: float = 5.0,
    ):
        super().__init__()
        self.run_id = run_id
        self.thread_id = thread_id
        self._store: RunEventStore | None = event_store
        self._closed = False
        self._track_tokens = track_token_usage
        self._flush_threshold = flush_threshold
        self._progress_reporter = progress_reporter
        self._progress_flush_interval = progress_flush_interval

        # Write buffer
        self._buffer: list[dict] = []
        self._pending_flush_tasks: set[asyncio.Task[None]] = set()
        self._pending_progress_task: asyncio.Task[None] | None = None
        self._pending_progress_delayed = False
        self._progress_dirty = False
        self._last_progress_flush = 0.0

        # Token accumulators
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_tokens = 0
        self._llm_call_count = 0

        # Caller-bucketed token accumulators
        self._lead_agent_tokens = 0
        self._subagent_tokens = 0
        self._middleware_tokens = 0

        # Per-model token accumulator
        self._tokens_by_model: dict[str, dict[str, int]] = {}

        # Dedup: LangChain may fire on_llm_end multiple times for the same run_id
        self._counted_llm_run_ids: set[str] = set()
        self._counted_external_source_ids: set[str] = set()
        self._counted_message_llm_run_ids: set[str] = set()
        self._memory_context_recorded = False

        # Convenience fields
        self._last_ai_msg: str | None = None
        self._first_human_msg: str | None = None
        self._msg_count = 0
        self._had_llm_error_fallback = False
        self._llm_error_fallback_message: str | None = None

        # Latency tracking
        self._llm_start_times: dict[str, float] = {}  # langchain run_id -> start time

        # LLM request/response tracking
        self._llm_call_index = 0
        self._seen_llm_starts: set[str] = set()  # langchain run_ids that fired on_chat_model_start
        self._current_run_tool_call_names: dict[str, str] = {}
        self._active_tool_names: dict[str, str] = {}
        self._persisted_tool_message_identities: set[str] = set()

        # Bumped once per successful event-store write. A reader that cached a
        # "the feed does not hold this message" answer compares this between
        # reads to learn whether retrying could produce a different one,
        # without polling the store (#4696 review).
        self._feed_generation = 0

        # Artifact-production tracking for the terminal run.delivery event
        # (#4272 slice 1). Deduped by (path, tool_name); insertion order kept.
        self._produced_artifacts: list[tuple[str, str | None]] = []
        self._produced_artifact_keys: set[tuple[str, str | None]] = set()

    # -- Lifecycle callbacks --

    @staticmethod
    def _message_text(message: BaseMessage) -> str:
        """Extract displayable text from a message's mixed content shape."""
        return message_to_text(message, text_attribute_fallback=True)

    def _record_message_summary(self, message: BaseMessage, *, caller: str | None = None) -> None:
        """Update run-level convenience fields for persisted run rows."""
        self._msg_count += 1

        # ``last_ai_message`` should represent the lead agent's user-facing
        # answer. Middleware/subagent model calls and empty tool-call-only
        # AI messages must not overwrite the last useful assistant text.
        is_ai_message = isinstance(message, AIMessage) or getattr(message, "type", None) == "ai"
        if is_ai_message and (caller is None or caller == "lead_agent"):
            text = self._message_text(message).strip()
            if text:
                self._last_ai_msg = text[:2000]

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        caller = self._identify_caller(tags)
        if parent_run_id is None:
            # Root graph invocation — emit a single trace event for the run start.
            chain_name = (serialized or {}).get("name", "unknown")
            self._put(
                event_type=RUN_START_EVENT.event_type,
                category=RUN_START_EVENT.category,
                content={"chain": chain_name},
                metadata={"caller": caller, **(metadata or {})},
            )

    def on_chain_end(
        self,
        outputs: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        # Nested chain ends fire for internal graph nodes; only the root chain
        # represents the user-visible run lifecycle.
        if parent_run_id is not None:
            return
        self._reconcile_final_tool_messages(outputs)
        self._put(
            event_type=RUN_END_EVENT.event_type,
            category=RUN_END_EVENT.category,
            content=outputs,
            metadata={"status": "success"},
        )
        self._flush_sync()

    def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._put(
            event_type=RUN_ERROR_EVENT.event_type,
            category=RUN_ERROR_EVENT.category,
            content=str(error),
            metadata={"error_type": type(error).__name__},
        )
        self._flush_sync()

    # -- LLM callbacks --

    def on_chat_model_start(
        self,
        serialized: dict,
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Capture the first user-visible prompt as llm.human.input.

        This is also the canonical place to extract the first human message:
        messages are fully structured here, it fires only on real LLM calls,
        and the content is never compressed by checkpoint trimming.
        """
        rid = str(run_id)
        self._llm_start_times[rid] = time.monotonic()
        self._llm_call_index += 1
        self._seen_llm_starts.add(rid)

        logger.debug(
            "on_chat_model_start %s: tags=%s num_batches=%d message_counts=%s",
            run_id,
            tags,
            len(messages),
            [len(batch) for batch in messages],
        )

        # Capture the first user message sent to the lead agent in this run.
        caller = self._identify_caller(tags)
        if caller == "lead_agent" and not self._first_human_msg and messages:
            for batch in reversed(messages):
                for m in reversed(batch):
                    if _should_persist_human_input_message(m):
                        persisted_message = restore_original_human_message(m)
                        self.set_first_human_message(self._message_text(persisted_message))
                        self._put(
                            event_type=LLM_HUMAN_INPUT_EVENT.event_type,
                            category=LLM_HUMAN_INPUT_EVENT.category,
                            content=persisted_message.model_dump(),
                            metadata={"caller": caller},
                        )
                        self._record_message_summary(persisted_message, caller=caller)
                        break
                if self._first_human_msg:
                    break

    def on_llm_start(self, serialized: dict, prompts: list[str], *, run_id: UUID, parent_run_id: UUID | None = None, tags: list[str] | None = None, metadata: dict[str, Any] | None = None, **kwargs: Any) -> None:
        # Fallback: on_chat_model_start is preferred. This just tracks latency.
        self._llm_start_times[str(run_id)] = time.monotonic()

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        messages: list[AnyMessage] = []
        logger.debug("on_llm_end %s: tags=%s", run_id, tags)
        for generation in response.generations:
            for gen in generation:
                if hasattr(gen, "message"):
                    messages.append(gen.message)
                else:
                    logger.warning(f"on_llm_end {run_id}: generation has no message attribute: {gen}")

        for message in messages:
            caller = self._identify_caller(tags)
            self._remember_current_run_tool_calls(message, caller=caller)

            # Latency
            rid = str(run_id)
            start = self._llm_start_times.pop(rid, None)
            latency_ms = int((time.monotonic() - start) * 1000) if start else None

            # Token usage from message
            usage = getattr(message, "usage_metadata", None)
            usage_dict = dict(usage) if usage else {}
            additional_kwargs = getattr(message, "additional_kwargs", None) or {}
            if isinstance(additional_kwargs, dict) and additional_kwargs.get("deerflow_error_fallback"):
                self._had_llm_error_fallback = True
                detail = additional_kwargs.get("error_detail")
                reason = additional_kwargs.get("error_reason")
                fallback_text = self._message_text(message).strip()
                if isinstance(detail, str) and detail.strip():
                    self._llm_error_fallback_message = detail.strip()
                elif isinstance(reason, str) and reason.strip():
                    self._llm_error_fallback_message = reason.strip()
                elif fallback_text:
                    self._llm_error_fallback_message = fallback_text[:2000]

            # Resolve call index
            call_index = self._llm_call_index
            if rid not in self._seen_llm_starts:
                # Fallback: on_chat_model_start was not called
                self._llm_call_index += 1
                call_index = self._llm_call_index
                self._seen_llm_starts.add(rid)

            # Message event: checkpoint-aligned llm.ai.response payload.
            self._put(
                event_type=LLM_AI_RESPONSE_EVENT.event_type,
                category=LLM_AI_RESPONSE_EVENT.category,
                content=message.model_dump(),
                metadata={
                    "caller": caller,
                    "usage": usage_dict,
                    "latency_ms": latency_ms,
                    "llm_call_index": call_index,
                },
            )
            if rid not in self._counted_message_llm_run_ids:
                self._record_message_summary(message, caller=caller)

            # Token accumulation (dedup by langchain run_id to avoid double-counting
            # when the callback fires more than once for the same response)
            if self._track_tokens:
                input_tk = usage_dict.get("input_tokens", 0) or 0
                output_tk = usage_dict.get("output_tokens", 0) or 0
                total_tk = usage_dict.get("total_tokens", 0) or 0
                if total_tk == 0:
                    total_tk = input_tk + output_tk
                if total_tk > 0 and rid not in self._counted_llm_run_ids:
                    self._counted_llm_run_ids.add(rid)
                    self._total_input_tokens += input_tk
                    self._total_output_tokens += output_tk
                    self._total_tokens += total_tk
                    self._llm_call_count += 1

                    if caller.startswith("subagent:"):
                        self._subagent_tokens += total_tk
                    elif caller.startswith("middleware:"):
                        self._middleware_tokens += total_tk
                    else:
                        self._lead_agent_tokens += total_tk

                    # Per-model bucket
                    response_metadata = getattr(message, "response_metadata", None) or {}
                    per_call_model: str | None = None
                    if isinstance(response_metadata, Mapping):
                        per_call_model = response_metadata.get("model_name") or response_metadata.get("model")
                    self._record_model_usage(per_call_model, input_tk, output_tk, total_tk, self._extract_cache_read(usage_dict))

                    self._schedule_progress_flush()

        if messages:
            self._counted_message_llm_run_ids.add(str(run_id))

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._llm_start_times.pop(str(run_id), None)
        self._put(
            event_type=LLM_ERROR_EVENT.event_type,
            category=LLM_ERROR_EVENT.category,
            content=str(error),
        )

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, tags=None, metadata=None, inputs=None, **kwargs):
        """Cache the executing tool name for artifact attribution."""
        tool_run_id = str(run_id)
        tool_name = serialized.get("name") if isinstance(serialized, Mapping) else None
        if isinstance(tool_name, str) and tool_name:
            self._active_tool_names[tool_run_id] = tool_name
        logger.debug("Tool start for node %s, tool_run_id=%s, tags=%s", run_id, tool_run_id, tags)

    def on_tool_end(self, output, *, run_id, parent_run_id=None, **kwargs):
        """Handle tool end event, append message and clear node data"""
        active_tool_name = self._active_tool_names.pop(str(run_id), None)
        try:
            if isinstance(output, ToolMessage):
                msg = cast(ToolMessage, output)
                self._persist_tool_result_message(msg)
            elif isinstance(output, Command):
                cmd = cast(Command, output)
                messages = cmd.update.get("messages", [])
                # A non-empty ``artifacts`` update is only produced on the
                # success path (e.g. present_files returns an error ToolMessage
                # without touching state when validation fails), so its
                # presence is the artifact-production signal (#4272 slice 1).
                artifacts = cmd.update.get("artifacts")
                artifact_tool_names: set[str] = set()
                for message in messages:
                    if isinstance(message, BaseMessage):
                        self._persist_tool_result_message(message)
                        if artifacts and isinstance(message, ToolMessage):
                            tool_call_id = getattr(message, "tool_call_id", None)
                            if isinstance(tool_call_id, str):
                                tool_name = self._current_run_tool_call_names.get(tool_call_id)
                                if tool_name:
                                    artifact_tool_names.add(tool_name)
                    else:
                        logger.warning(f"on_tool_end {run_id}: command update message is not BaseMessage: {type(message)}")
                if artifacts:
                    artifact_tool_name = active_tool_name
                    if artifact_tool_name is None and len(artifact_tool_names) == 1:
                        artifact_tool_name = next(iter(artifact_tool_names))
                    self._record_produced_artifacts(artifacts, artifact_tool_name)
            else:
                logger.warning(f"on_tool_end {run_id}: output is not ToolMessage: {type(output)}")
        finally:
            logger.debug("Tool end for node %s", run_id)

    # -- Internal methods --

    @staticmethod
    def _message_identity(message: BaseMessage) -> str | None:
        tool_call_id = getattr(message, "tool_call_id", None)
        if isinstance(tool_call_id, str) and tool_call_id:
            return f"tool:{tool_call_id}"
        message_id = getattr(message, "id", None)
        if isinstance(message_id, str) and message_id:
            return f"message:{message_id}"
        return None

    @staticmethod
    def _tool_call_value(tool_call: Any, key: str) -> Any:
        if isinstance(tool_call, Mapping):
            return tool_call.get(key)
        return getattr(tool_call, key, None)

    def _remember_current_run_tool_calls(self, message: AnyMessage, *, caller: str) -> None:
        if caller != "lead_agent":
            return
        is_ai_message = isinstance(message, AIMessage) or getattr(message, "type", None) == "ai"
        if not is_ai_message:
            return
        tool_calls = getattr(message, "tool_calls", None) or []
        if not isinstance(tool_calls, list):
            return
        for tool_call in tool_calls:
            tool_call_id = self._tool_call_value(tool_call, "id")
            if not isinstance(tool_call_id, str) or not tool_call_id:
                continue
            name = self._tool_call_value(tool_call, "name")
            self._current_run_tool_call_names[tool_call_id] = str(name or "")

    def _persist_tool_result_message(self, message: BaseMessage) -> None:
        self._put(
            event_type=LLM_TOOL_RESULT_EVENT.event_type,
            category=LLM_TOOL_RESULT_EVENT.category,
            content=message.model_dump(),
        )
        identity = self._message_identity(message)
        if identity:
            self._persisted_tool_message_identities.add(identity)
        self._record_message_summary(message)

    def _final_output_messages(self, outputs: Any) -> list[Any]:
        if isinstance(outputs, Mapping):
            messages = outputs.get("messages", [])
            return messages if isinstance(messages, list) else []
        return []

    def _should_reconcile_tool_message(self, message: ToolMessage) -> bool:
        """Whether a final-output ToolMessage still needs persisting.

        A middleware can answer a tool call itself and short-circuit execution,
        so LangChain never emits ``on_tool_end`` and the result never reaches
        the event store. The user saw that result during the run, and it
        disappeared on reload (#4666). Any such result is reconciled here; the
        scope is bounded by three independent conditions rather than a tool-name
        allowlist: it must be user-visible, the call must belong to this run's
        lead agent (``_remember_current_run_tool_calls`` records lead-agent
        calls only, so subagent results stay in their own step feed), and it
        must not already be persisted.
        """
        if message.additional_kwargs.get("hide_from_ui") is True:
            return False
        tool_call_id = getattr(message, "tool_call_id", None)
        if not isinstance(tool_call_id, str) or not tool_call_id:
            return False
        # The call must belong to this run: a retained ToolMessage from an
        # earlier run is already persisted under its own run and must not be
        # re-attributed here.
        if self._current_run_tool_call_names.get(tool_call_id) is None:
            return False
        identity = self._message_identity(message)
        return identity is not None and identity not in self._persisted_tool_message_identities

    def _reconcile_final_tool_messages(self, outputs: Any) -> None:
        for message in self._final_output_messages(outputs):
            if not isinstance(message, ToolMessage):
                continue
            if self._should_reconcile_tool_message(message):
                self._persist_tool_result_message(message)

    def _put(self, *, event_type: str, category: str, content: str | dict = "", metadata: dict | None = None) -> None:
        if self._closed:
            return
        self._buffer.append(
            {
                "thread_id": self.thread_id,
                "run_id": self.run_id,
                "event_type": event_type,
                "category": category,
                "content": content,
                "metadata": metadata or {},
                "created_at": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._buffer) >= self._flush_threshold:
            self._flush_sync()

    def _flush_sync(self) -> None:
        """Best-effort flush of buffer to RunEventStore.

        BaseCallbackHandler methods are synchronous.  If an event loop is
        running we schedule an async ``put_batch``; otherwise the events
        stay in the buffer and are flushed later by the async ``flush()``
        call in the worker's ``finally`` block.
        """
        if not self._buffer:
            return
        # Skip if a flush is already in flight — avoids concurrent writes
        # to the same SQLite file from multiple fire-and-forget tasks.
        if self._pending_flush_tasks:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No event loop — keep events in buffer for later async flush.
            return
        batch = self._buffer.copy()
        self._buffer.clear()
        task = loop.create_task(self._flush_async(batch))
        self._pending_flush_tasks.add(task)
        task.add_done_callback(self._on_flush_done)

    async def _flush_async(self, batch: list[dict]) -> None:
        try:
            store = self._store
            if store is None:
                return
            await store.put_batch(batch)
            self._feed_generation += 1
        except Exception:
            logger.warning(
                "Failed to flush %d events for run %s — returning to buffer",
                len(batch),
                self.run_id,
                exc_info=True,
            )
            # Return failed events to buffer for retry on next flush
            self._buffer = batch + self._buffer

    def _on_flush_done(self, task: asyncio.Task) -> None:
        self._pending_flush_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.warning("Journal flush task failed: %s", exc)

    def _identify_caller(self, tags: list[str] | None) -> str:
        _tags = tags or []
        for tag in _tags:
            if isinstance(tag, str) and (tag.startswith("subagent:") or tag.startswith("middleware:") or tag == "lead_agent"):
                return tag
        # Default to lead_agent: the main agent graph does not inject
        # callback tags, while subagents and middleware explicitly tag
        # themselves.
        return "lead_agent"

    def _record_model_usage(
        self,
        model_name: str | None,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        cache_read_tokens: int = 0,
    ) -> None:
        """Add a single LLM call's token usage to the per-model accumulator.

        Missing / empty ``model_name`` collapses into a shared ``"unknown"``
        bucket so the breakdown stays usable when a provider doesn't surface
        ``response_metadata.model_name``.

        ``cache_read_tokens`` (prompt-cache hits, from
        ``usage_metadata.input_token_details.cache_read``) is stored as a
        sparse bucket key — only written when non-zero — so buckets from
        providers without cache reporting keep their historical shape.
        """
        if total_tokens <= 0:
            return
        bucket = self._tokens_by_model.setdefault(
            model_name or "unknown",
            {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
        bucket["input_tokens"] += int(input_tokens or 0)
        bucket["output_tokens"] += int(output_tokens or 0)
        bucket["total_tokens"] += int(total_tokens)
        if cache_read_tokens > 0:
            bucket["cache_read_tokens"] = bucket.get("cache_read_tokens", 0) + int(cache_read_tokens)

    @staticmethod
    def _extract_cache_read(usage_dict: dict) -> int:
        """Prompt-cache-hit input tokens from LangChain's normalized usage."""
        details = usage_dict.get("input_token_details") or {}
        if not isinstance(details, Mapping):
            return 0
        try:
            return max(int(details.get("cache_read") or 0), 0)
        except (TypeError, ValueError):
            return 0

    # -- Public methods (called by worker) --

    def record_external_llm_usage_records(
        self,
        records: list[dict[str, int | str | None]],
    ) -> None:
        """Record token usage from external sources (e.g., subagents).

        Each record should contain:
            source_run_id: Unique identifier to prevent double-counting
            caller: Caller tag (e.g. "subagent:general-purpose")
            model_name: Real per-call model name (str or None; falls back to
                ``"unknown"`` bucket when missing)
            input_tokens: Input token count
            output_tokens: Output token count
            total_tokens: Total token count (computed from input+output if 0/missing)
            cache_read_tokens: Optional prompt-cache-hit input tokens
        """
        if not self._track_tokens:
            return
        for record in records:
            source_id = str(record.get("source_run_id", ""))
            if not source_id:
                continue
            if source_id in self._counted_external_source_ids:
                continue

            total_tk = record.get("total_tokens", 0) or 0
            if total_tk <= 0:
                input_tk = record.get("input_tokens", 0) or 0
                output_tk = record.get("output_tokens", 0) or 0
                total_tk = input_tk + output_tk
            if total_tk <= 0:
                continue

            input_tk = record.get("input_tokens", 0) or 0
            output_tk = record.get("output_tokens", 0) or 0

            self._counted_external_source_ids.add(source_id)
            self._total_input_tokens += input_tk
            self._total_output_tokens += output_tk
            self._total_tokens += total_tk

            caller = str(record.get("caller", ""))
            if caller.startswith("subagent:"):
                self._subagent_tokens += total_tk
            elif caller.startswith("middleware:"):
                self._middleware_tokens += total_tk
            else:
                self._lead_agent_tokens += total_tk

            cache_read_tk = record.get("cache_read_tokens", 0) or 0
            self._record_model_usage(record.get("model_name"), input_tk, output_tk, total_tk, int(cache_read_tk))

            self._schedule_progress_flush()

    def set_first_human_message(self, content: str) -> None:
        """Record the first human message for convenience fields."""
        self._first_human_msg = content[:2000] if content else None

    def record_middleware(self, tag: str, *, name: str, hook: str, action: str, changes: dict) -> None:
        """Record a middleware state-change event.

        Called by middleware implementations when they perform a meaningful
        state change (e.g., title generation, summarization, HITL approval).
        Pure-observation middleware should not call this.

        Args:
            tag: Short identifier for the middleware (e.g., "title", "summarize",
                 "guardrail"). Used to form event_type="middleware:{tag}" and
                 limited by the persisted event-type column width.
            name: Full middleware class name.
            hook: Lifecycle hook that triggered the action (e.g., "after_model").
            action: Specific action performed (e.g., "generate_title").
            changes: Dict describing the state changes made.
        """
        self._put(
            event_type=MIDDLEWARE_EVENT_PATTERN.event_type(tag),
            category=MIDDLEWARE_EVENT_PATTERN.category,
            content={"name": name, "hook": hook, "action": action, "changes": changes},
        )

    def record_memory_context(self, *, content_sha256: str) -> None:
        """Record the effective hidden memory block for this run.

        The full block already lives in checkpoint state and may contain user
        data, so the event stores only its exact SHA-256 identity. Operators
        consume it through the existing run-events debug API to compare the
        effective memory used by different runs without copying that content.
        """
        if self._memory_context_recorded:
            return
        self._put(
            event_type=MEMORY_CONTEXT_EVENT.event_type,
            category=MEMORY_CONTEXT_EVENT.category,
            content={"content_sha256": content_sha256},
        )
        self._memory_context_recorded = True

    def _record_produced_artifacts(self, artifacts: Any, tool_name: str | None) -> None:
        """Accumulate produced artifact paths, deduped by (path, tool_name)."""
        if not isinstance(artifacts, list):
            return
        for path in artifacts:
            if not isinstance(path, str) or not path:
                continue
            key = (path, tool_name)
            if key not in self._produced_artifact_keys:
                self._produced_artifact_keys.add(key)
                self._produced_artifacts.append(key)

    def get_delivery_content(self) -> dict[str, Any]:
        """Return the terminal delivery fact accumulated for this run.

        This is a fact record, not a verdict: runs that produced no artifacts
        emit ``presented: 0``.
        """
        by_tool: dict[str, list[str]] = {}
        paths: list[str] = []
        for path, tool_name in self._produced_artifacts:
            paths.append(path)
            if tool_name:
                by_tool.setdefault(tool_name, []).append(path)
        return {"presented": len(paths), "paths": paths, "by_tool": by_tool}

    def record_delivery(self) -> None:
        """Buffer the terminal ``run.delivery`` event for this run (#4272 slice 1).

        Kept for direct journal users. The worker uses the event store's
        idempotent singleton write so crash recovery can safely backfill it.
        """
        self._put(
            event_type="run.delivery",
            category="outputs",
            content=self.get_delivery_content(),
        )

    async def flush(self) -> None:
        """Force flush remaining buffer. Called in worker's finally block."""
        if self._closed:
            return
        if self._pending_flush_tasks:
            await asyncio.gather(*tuple(self._pending_flush_tasks), return_exceptions=True)
        while self._pending_progress_task is not None:
            pending_progress_task = self._pending_progress_task
            if pending_progress_task.done():
                if self._pending_progress_task is pending_progress_task:
                    self._pending_progress_task = None
                break
            if self._pending_progress_delayed:
                pending_progress_task.cancel()
                await asyncio.gather(pending_progress_task, return_exceptions=True)
                if self._pending_progress_task is pending_progress_task:
                    self._pending_progress_task = None
                self._progress_dirty = False
                self._pending_progress_delayed = False
                break
            await asyncio.gather(pending_progress_task, return_exceptions=True)
            if self._pending_progress_task is pending_progress_task:
                self._pending_progress_task = None

        while self._buffer:
            batch = self._buffer[: self._flush_threshold]
            del self._buffer[: self._flush_threshold]
            try:
                store = self._store
                if store is None:
                    return
                await store.put_batch(batch)
                self._feed_generation += 1
            except Exception:
                self._buffer = batch + self._buffer
                raise

    def _detach_runtime_dependencies(self) -> None:
        """Drop every external or potentially cyclic run-scoped reference."""
        self._closed = True
        self._store = None
        self._progress_reporter = None
        self._buffer.clear()
        self._pending_flush_tasks.clear()
        self._pending_progress_task = None
        self._pending_progress_delayed = False
        self._progress_dirty = False
        self._tokens_by_model.clear()
        self._counted_llm_run_ids.clear()
        self._counted_external_source_ids.clear()
        self._counted_message_llm_run_ids.clear()
        self._llm_start_times.clear()
        self._seen_llm_starts.clear()
        self._current_run_tool_call_names.clear()
        self._persisted_tool_message_identities.clear()
        self._produced_artifacts.clear()
        self._produced_artifact_keys.clear()
        self._last_ai_msg = None
        self._first_human_msg = None
        self._llm_error_fallback_message = None

    async def close(self, *, flush: bool = True) -> None:
        """Release run-scoped references, optionally flushing buffered events."""
        if self._closed:
            return
        if flush:
            # A failed terminal write returns its batch to ``_buffer``. Keep the
            # store and all buffered state attached so a later close/flush can retry
            # instead of silently discarding the tail of the run event stream.
            await self.flush()
            self._detach_runtime_dependencies()
            return

        # A worker that lost its lease must detach without starting another
        # durable write. Drop dependencies before cancelling already-scheduled
        # work so tasks that have not begun observe the detached state. The
        # final detach must survive a second cancellation while those tasks stop.
        self._closed = True
        self._store = None
        self._progress_reporter = None
        try:
            pending_flush_tasks = tuple(self._pending_flush_tasks)
            for task in pending_flush_tasks:
                task.cancel()
            if pending_flush_tasks:
                await asyncio.gather(*pending_flush_tasks, return_exceptions=True)
            pending_progress_task = self._pending_progress_task
            if pending_progress_task is not None:
                pending_progress_task.cancel()
                await asyncio.gather(pending_progress_task, return_exceptions=True)
        finally:
            self._detach_runtime_dependencies()

    def _schedule_progress_flush(self) -> None:
        """Best-effort throttled progress snapshot for active run visibility."""
        if self._progress_reporter is None:
            return
        now = time.monotonic()
        elapsed = now - self._last_progress_flush
        if elapsed < self._progress_flush_interval:
            self._progress_dirty = True
            self._schedule_delayed_progress_flush(self._progress_flush_interval - elapsed)
            return
        if self._pending_progress_task is not None and not self._pending_progress_task.done():
            self._progress_dirty = True
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._progress_dirty = False
        self._pending_progress_task = loop.create_task(self._flush_progress_async(snapshot=self.get_completion_data()))

    def _schedule_delayed_progress_flush(self, delay: float) -> None:
        if self._pending_progress_task is not None and not self._pending_progress_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        delay = max(0.0, delay)
        self._pending_progress_delayed = delay > 0
        self._pending_progress_task = loop.create_task(self._flush_progress_async(delay=delay))

    async def _flush_progress_async(self, *, snapshot: dict | None = None, delay: float = 0.0) -> None:
        if self._progress_reporter is None:
            return
        if delay > 0:
            self._pending_progress_delayed = True
            await asyncio.sleep(delay)
            self._pending_progress_delayed = False
        dirty_before_write = self._progress_dirty
        self._progress_dirty = False
        snapshot_to_write = snapshot or self.get_completion_data()
        try:
            await self._progress_reporter(snapshot_to_write)
            self._last_progress_flush = time.monotonic()
        except Exception:
            logger.warning("Failed to persist progress snapshot for run %s", self.run_id, exc_info=True)
        if dirty_before_write or self._progress_dirty:
            self._progress_dirty = False
            self._pending_progress_task = None
            self._schedule_delayed_progress_flush(self._progress_flush_interval)

    def get_completion_data(self) -> dict:
        """Return accumulated token and message data for run completion."""
        return {
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "total_tokens": self._total_tokens,
            "llm_call_count": self._llm_call_count,
            "lead_agent_tokens": self._lead_agent_tokens,
            "subagent_tokens": self._subagent_tokens,
            "middleware_tokens": self._middleware_tokens,
            "token_usage_by_model": {model: dict(usage) for model, usage in self._tokens_by_model.items()},
            "message_count": self._msg_count,
            "last_ai_message": self._last_ai_msg,
            "first_human_message": self._first_human_msg,
        }

    @property
    def feed_generation(self) -> int:
        """Monotonic count of successful writes to the thread feed.

        Buffered events are not in the feed yet, so a lookup for a message this
        run just produced legitimately misses. This counter is what tells such
        a reader that its cached miss is worth re-asking — it changes exactly
        when the feed gained rows, and never while the buffer is merely
        filling. A failed write leaves it alone: nothing became readable.
        """
        return self._feed_generation

    @property
    def had_llm_error_fallback(self) -> bool:
        return self._had_llm_error_fallback

    @property
    def llm_error_fallback_message(self) -> str | None:
        return self._llm_error_fallback_message
