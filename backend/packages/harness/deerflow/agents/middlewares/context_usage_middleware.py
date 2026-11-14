"""Snapshot the context-window composition of the final model request.

The thread view's percentage counts checkpoint messages only, so the static
system prompt, bound tool schemas and middleware-injected context are invisible.
This middleware records an approximate per-source breakdown at the model-call
boundary, where all of them are finally visible together.

It is read-only: it never rewrites the request. The only state it writes is one
JSON-safe dict on the response's last AIMessage (``deerflow_context_usage``),
which the Gateway reads back for ``GET /api/threads/{id}/token-usage``.

Ordering matters. The snapshot must run *outside* (earlier than)
``SystemMessageCoalescingMiddleware``: coalescing merges every SystemMessage
into one block and overwrites its provenance, after which the date reminder,
recalled memory and durable-context contract can no longer be attributed. It
must also run inside the middlewares that inject that context, so their
provenance is visible. Middlewares appended later (request sanitizers, run-input
admission and extension contributions) can still shrink the request, so the
counts describe the request at the coalescing boundary rather than the exact
provider payload.

Counts are LangChain's network-free approximation, consistent with the existing
percentage. Exact provider tokenization is deliberately out of scope.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, override

from deerflow_extension_api import ContentKind, read_provenance
from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.runtime import Runtime

from deerflow.agents.middlewares._bounded_dict import BoundedDict
from deerflow.tools.mcp_metadata import is_mcp_tool

logger = logging.getLogger(__name__)

#: Server-owned ``AIMessage.additional_kwargs`` key carrying the last snapshot.
#: A caller-supplied copy is stripped at the Gateway input boundary.
CONTEXT_USAGE_KEY = "deerflow_context_usage"

_COUNT_FIELDS = (
    "system_prompt_tokens",
    "builtin_tools_tokens",
    "mcp_tools_tokens",
    "skill_body_tokens",
    "memory_tokens",
    "task_state_tokens",
    "other_injection_tokens",
    "conversation_tokens",
    "tool_result_tokens",
)

#: Provenance kinds that map to a dedicated bucket. Anything else (including an
#: ``IMAGE_PAYLOAD`` or a kind from a newer host) falls through to the
#: message-type bucket, so an unknown stamp can never hide tokens.
_PROVENANCE_BUCKETS = {
    ContentKind.SKILL_BODY: "skill_body_tokens",
    ContentKind.MEMORY: "memory_tokens",
    ContentKind.DURABLE_CONTEXT: "task_state_tokens",
    ContentKind.MIDDLEWARE_INJECTION: "other_injection_tokens",
}


def _callable_identity(counter: Callable[..., int]) -> str:
    """Name the counter for release identity, including injected callables."""
    module = getattr(counter, "__module__", "")
    qualname = getattr(counter, "__qualname__", None) or getattr(counter, "__name__", None) or type(counter).__name__
    return f"{module}.{qualname}" if module else str(qualname)


def strip_context_usage_stamps(messages: Iterable[Any]) -> list[Any]:
    """Return messages with the server-owned snapshot key removed.

    Compaction keeps the newest AIMessage, whose stamp describes the
    pre-compaction request. Leaving it in place would make the read path report
    a composition that includes messages compaction just removed. Clearing it
    on write makes the endpoint fall back to the placeholder until the next
    model call records a snapshot for the compacted context.
    """
    return [_strip_context_usage_stamp(message) for message in messages]


def _strip_context_usage_stamp(message: Any) -> Any:
    additional_kwargs = getattr(message, "additional_kwargs", None)
    if not isinstance(additional_kwargs, dict) or CONTEXT_USAGE_KEY not in additional_kwargs:
        return message
    cleaned = dict(additional_kwargs)
    cleaned.pop(CONTEXT_USAGE_KEY, None)
    model_copy = getattr(message, "model_copy", None)
    if model_copy is None:
        return message
    return model_copy(update={"additional_kwargs": cleaned})


@dataclass(frozen=True)
class ContextUsageSnapshot:
    """Approximate token counts per context source for one model request.

    Only counts are stored — never message text, tool schemas or memory bodies.
    """

    system_prompt_tokens: int = 0
    builtin_tools_tokens: int = 0
    mcp_tools_tokens: int = 0
    skill_body_tokens: int = 0
    memory_tokens: int = 0
    task_state_tokens: int = 0
    other_injection_tokens: int = 0
    conversation_tokens: int = 0
    tool_result_tokens: int = 0
    model_name: str | None = None
    context_window: int | None = None
    captured_at: str = ""

    @property
    def total_tokens(self) -> int:
        # Derived rather than stored so a malformed persisted total can never
        # disagree with the parts the UI shows.
        return sum(getattr(self, field) for field in _COUNT_FIELDS)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["total_tokens"] = self.total_tokens
        return payload

    def to_payload(self) -> dict[str, Any]:
        """Build the API shape, including the window-relative figures."""
        window = self.context_window
        total = self.total_tokens
        # Keep more than display precision: the formatter turns a non-zero
        # share below 0.1% into "<0.1", and rounding here to one decimal would
        # collapse it to 0 first.
        percentage = round(total / window * 100, 4) if window and window > 0 else None
        remaining = max(window - total, 0) if window and window > 0 else None
        return {
            **{field: getattr(self, field) for field in _COUNT_FIELDS},
            "total_tokens": total,
            "percentage": percentage,
            "remaining_tokens": remaining,
            "model_name": self.model_name,
            "context_window": window,
            "captured_at": self.captured_at,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> ContextUsageSnapshot | None:
        """Validate a persisted snapshot; ``None`` when it is not usable.

        Checkpoints written by other versions or direct integrations are
        untrusted, so every field is type-checked and negative counts are
        rejected instead of being rendered.
        """
        if not isinstance(raw, Mapping):
            return None
        counts: dict[str, int] = {}
        for field in _COUNT_FIELDS:
            value = raw.get(field, 0)
            # ``bool`` is an ``int`` subclass; a boolean count is malformed.
            if type(value) is not int or value < 0:
                return None
            counts[field] = value
        model_name = raw.get("model_name")
        if model_name is not None and not isinstance(model_name, str):
            return None
        context_window = raw.get("context_window")
        if context_window is not None and (type(context_window) is not int or context_window <= 0):
            return None
        captured_at = raw.get("captured_at")
        if captured_at is not None and not isinstance(captured_at, str):
            return None
        return cls(**counts, model_name=model_name, context_window=context_window, captured_at=captured_at or "")


def _classify_message(message: Any) -> str:
    """Return the single bucket a request message belongs to."""
    provenance = read_provenance(message)
    if provenance is not None:
        bucket = _PROVENANCE_BUCKETS.get(provenance.content_kind)
        if bucket is not None:
            return bucket
    if isinstance(message, ToolMessage):
        return "tool_result_tokens"
    if isinstance(message, SystemMessage):
        # External callers cannot persist system messages; an unstamped one was
        # injected by a middleware that predates provenance stamping. Counting
        # it as conversation would overstate what the user wrote.
        return "other_injection_tokens"
    return "conversation_tokens"


class ContextUsageMiddleware(AgentMiddleware[AgentState]):
    """Record a per-source token snapshot before the provider request is sent."""

    def __init__(
        self,
        *,
        model_name: str | None = None,
        context_window: int | None = None,
        token_counter: Callable[..., int] = count_tokens_approximately,
    ) -> None:
        super().__init__()
        self._model_name = model_name
        self._context_window = int(context_window) if context_window else None
        self._token_counter = token_counter
        self._static_fingerprint: tuple[Any, ...] | None = None
        self._static_counts: tuple[int, int, int] = (0, 0, 0)
        self._pending: BoundedDict = BoundedDict(maxsize=256)

    def release_policy_parameters(self) -> dict[str, object]:
        return {
            "token_counter": _callable_identity(self._token_counter),
            "snapshot_version": 1,
            "categories": list(_COUNT_FIELDS),
            "model_name": self._model_name,
            "context_window": self._context_window,
        }

    @staticmethod
    def _thread_id(runtime: Runtime | None) -> str | None:
        context = getattr(runtime, "context", None)
        if isinstance(context, Mapping):
            thread_id = context.get("thread_id")
            if isinstance(thread_id, str) and thread_id:
                return thread_id
        return None

    def _count_tools(self, tools: list[Any]) -> int:
        if not tools:
            return 0
        return int(self._token_counter([], tools=tools))

    def _static_counts_for(self, request: ModelRequest) -> tuple[int, int, int]:
        """Count the system prompt and tool schemas once per stable assembly.

        The fingerprint is cheap (text length plus tool names); the tool count
        itself is the expensive part because it serializes every schema.
        """
        system_message = request.system_message
        system_text = system_message.text if system_message is not None else ""
        tools = list(request.tools or [])
        fingerprint = (len(system_text), tuple(getattr(tool, "name", None) for tool in tools))
        if self._static_fingerprint == fingerprint:
            return self._static_counts

        system_tokens = int(self._token_counter([system_message])) if system_message is not None else 0
        builtin = [tool for tool in tools if not is_mcp_tool(tool)]
        mcp = [tool for tool in tools if is_mcp_tool(tool)]
        self._static_counts = (system_tokens, self._count_tools(builtin), self._count_tools(mcp))
        self._static_fingerprint = fingerprint
        return self._static_counts

    def _build_snapshot(self, request: ModelRequest) -> ContextUsageSnapshot:
        system_tokens, builtin_tokens, mcp_tokens = self._static_counts_for(request)

        grouped: dict[str, list[Any]] = {}
        for message in request.messages:
            grouped.setdefault(_classify_message(message), []).append(message)
        counts = {bucket: int(self._token_counter(messages)) for bucket, messages in grouped.items()}

        return ContextUsageSnapshot(
            system_prompt_tokens=system_tokens,
            builtin_tools_tokens=builtin_tokens,
            mcp_tools_tokens=mcp_tokens,
            **{field: counts.get(field, 0) for field in _COUNT_FIELDS[3:]},
            model_name=self._model_name,
            context_window=self._context_window,
            captured_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )

    def _capture(self, request: ModelRequest) -> None:
        # Observability must never break the run: a tool schema the counter
        # cannot serialize or an unexpected message shape skips the snapshot.
        try:
            snapshot = self._build_snapshot(request)
        except Exception:
            logger.warning("Context usage snapshot failed; skipping this model call", exc_info=True)
            return
        self._pending[self._thread_id(getattr(request, "runtime", None))] = snapshot

    def _stamp(self, state: AgentState, runtime: Runtime | None) -> dict[str, Any] | None:
        snapshot = self._pending.pop(self._thread_id(runtime), None)
        if snapshot is None:
            return None
        messages = state.get("messages") or []
        if not messages:
            return None
        last = messages[-1]
        if not isinstance(last, AIMessage):
            return None
        payload = snapshot.to_dict()
        additional_kwargs = dict(getattr(last, "additional_kwargs", {}) or {})
        if additional_kwargs.get(CONTEXT_USAGE_KEY) == payload:
            return None
        additional_kwargs[CONTEXT_USAGE_KEY] = payload
        return {"messages": [last.model_copy(update={"additional_kwargs": additional_kwargs})]}

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        self._capture(request)
        return handler(request)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        self._capture(request)
        return await handler(request)

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self._stamp(state, runtime)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self._stamp(state, runtime)
