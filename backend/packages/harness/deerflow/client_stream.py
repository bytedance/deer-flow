"""Shared incremental event encoding for native sync and async client streams."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

if TYPE_CHECKING:
    from deerflow.client import DeerFlowClient, StreamEvent


class _StreamEventEncoder:
    """One turn's deduplication and token accounting, independent of graph IO."""

    def __init__(self, client: DeerFlowClient, run_id: str) -> None:
        self.client = client
        self.run_id = run_id
        self.seen_messages: dict[str, Any] = {}
        # AI text already emitted per id. A replacement that appends to it (a
        # guard's stop notice) only needs the part that was added.
        self.sent_text_by_id: dict[str, str] = {}
        # Cross-mode handoff: ids already streamed via LangGraph ``messages``
        # mode so the ``values`` path skips re-synthesis of the same message.
        self.streamed_ids: set[str] = set()
        # A resumed thread's values snapshots include prior turns. They remain
        # in the full-state event, but must not become new deltas or usage.
        self.historical_message_ids: set[str] = set()
        # AI messages whose tool calls arrived as streamed fragments. The
        # arguments only parse once the message is complete, so their
        # tool_calls event is emitted from the values snapshot instead.
        self.pending_tool_call_ids: set[str] = set()
        # Chunks carry additive usage; complete messages carry the total.
        # Reconcile that total once, without counting the streamed part again.
        self.streamed_usage_by_id: dict[str, dict[str, int]] = {}
        self.counted_usage_ids: set[str] = set()
        self.sent_additional_kwargs_by_id: dict[str, dict[str, Any]] = {}
        self.cumulative_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    def _account_usage(self, msg_id: str | None, usage: Any, *, is_chunk: bool = False) -> dict | None:
        """Accumulate chunk deltas or reconcile a complete message once.

        ``usage`` is a ``langchain_core.messages.UsageMetadata`` TypedDict
        or ``None``; typed as ``Any`` because TypedDicts are not
        structurally assignable to plain ``dict`` under strict type
        checking.  Returns the newly accounted usage (for attaching
        to an event) when we accepted it, otherwise ``None``.
        """
        if not usage:
            return None
        if msg_id and msg_id in self.counted_usage_ids:
            return None
        delta = {key: usage.get(key, 0) or 0 for key in self.cumulative_usage}
        if msg_id:
            if is_chunk:
                streamed = self.streamed_usage_by_id.setdefault(msg_id, {})
                for key, value in delta.items():
                    streamed[key] = streamed.get(key, 0) + value
            else:
                self.counted_usage_ids.add(msg_id)
                streamed = self.streamed_usage_by_id.pop(msg_id, {})
                # State rewrites may lower totals; do not retract streamed usage.
                # Signed provider corrections remain valid in the chunk path.
                delta = {key: max(value - streamed.get(key, 0), 0) for key, value in delta.items()}
        for key, value in delta.items():
            self.cumulative_usage[key] += value
        return delta

    def _unsent_additional_kwargs(self, msg_id: str | None, additional_kwargs: dict[str, Any] | None) -> dict[str, Any] | None:
        if not additional_kwargs:
            return None
        if not msg_id:
            return additional_kwargs

        sent = self.sent_additional_kwargs_by_id.setdefault(msg_id, {})
        delta = {key: value for key, value in additional_kwargs.items() if sent.get(key) != value}
        if not delta:
            return None

        sent.update(delta)
        return delta

    def feed(self, item: Any) -> Iterator[StreamEvent]:
        from deerflow.client import StreamEvent

        if isinstance(item, tuple) and len(item) == 2:
            mode, chunk = item
            mode = str(mode)
        else:
            mode, chunk = "values", item

        if mode == "custom":
            yield StreamEvent(type="custom", data=chunk)
            return

        if mode == "messages":
            # LangGraph ``messages`` mode emits ``(message_chunk, metadata)``.
            if isinstance(chunk, tuple) and len(chunk) == 2:
                msg_chunk, _metadata = chunk
            else:
                msg_chunk = chunk

            msg_id = getattr(msg_chunk, "id", None)
            if msg_id and msg_id in self.historical_message_ids:
                return

            if isinstance(msg_chunk, AIMessage):
                text = self.client._extract_text(msg_chunk.content)
                additional_kwargs = self.client._serialize_additional_kwargs(msg_chunk)
                counted_usage = self._account_usage(msg_id, msg_chunk.usage_metadata, is_chunk=isinstance(msg_chunk, AIMessageChunk))
                sent_additional_kwargs = False

                if text:
                    if msg_id:
                        self.streamed_ids.add(msg_id)
                        self.sent_text_by_id[msg_id] = self.sent_text_by_id.get(msg_id, "") + text
                    additional_kwargs_delta = self._unsent_additional_kwargs(msg_id, additional_kwargs)
                    yield self.client._ai_text_event(
                        msg_id,
                        text,
                        counted_usage,
                        additional_kwargs_delta,
                    )
                    sent_additional_kwargs = bool(additional_kwargs_delta)

                # A chunk without an id can't be matched to its values
                # snapshot, so it keeps the per-chunk event below.
                if isinstance(msg_chunk, AIMessageChunk) and msg_chunk.tool_call_chunks and msg_id:
                    self.streamed_ids.add(msg_id)
                    self.pending_tool_call_ids.add(msg_id)
                elif msg_chunk.tool_calls:
                    if msg_id:
                        self.streamed_ids.add(msg_id)
                    additional_kwargs_delta = None if sent_additional_kwargs else self._unsent_additional_kwargs(msg_id, additional_kwargs)
                    yield self.client._ai_tool_calls_event(
                        msg_id,
                        msg_chunk.tool_calls,
                        additional_kwargs_delta,
                    )

            elif isinstance(msg_chunk, ToolMessage):
                if msg_id:
                    self.streamed_ids.add(msg_id)
                yield self.client._tool_message_event(msg_chunk)
            return

        # mode == "values"
        messages = chunk.get("messages", [])

        current_user_index = next(
            (index for index, msg in enumerate(messages) if isinstance(msg, HumanMessage) and (getattr(msg, "additional_kwargs", None) or {}).get("run_id") == self.run_id),
            None,
        )
        if current_user_index is not None:
            self.historical_message_ids.update(msg_id for msg in messages[:current_user_index] if (msg_id := getattr(msg, "id", None)))

        for index, msg in enumerate(messages):
            msg_id = getattr(msg, "id", None)
            if (current_user_index is not None and index < current_user_index) or (msg_id and msg_id in self.historical_message_ids):
                continue
            if msg_id and msg_id in self.seen_messages:
                if self.seen_messages[msg_id] is msg:
                    continue
                self.seen_messages[msg_id] = msg
                if isinstance(msg, AIMessage):
                    # Replaced after it was sent. Emit text appended to what
                    # was already sent, plus any new metadata.
                    text = self.client._extract_text(msg.content)
                    sent_text = self.sent_text_by_id.get(msg_id, "")
                    additional_kwargs_delta = self._unsent_additional_kwargs(msg_id, self.client._serialize_additional_kwargs(msg))
                    if len(text) > len(sent_text) and text.startswith(sent_text):
                        self.sent_text_by_id[msg_id] = text
                        yield self.client._ai_text_event(msg_id, text[len(sent_text) :], None, additional_kwargs_delta)
                    elif additional_kwargs_delta:
                        yield self.client._ai_text_event(msg_id, "", None, additional_kwargs_delta)
                continue
            if msg_id:
                self.seen_messages[msg_id] = msg

            # Already streamed via ``messages`` mode; emit only text added
            # before this first snapshot, plus unsent tool calls/metadata.
            if msg_id and msg_id in self.streamed_ids:
                if isinstance(msg, AIMessage):
                    self._account_usage(msg_id, getattr(msg, "usage_metadata", None))
                    additional_kwargs = self.client._serialize_additional_kwargs(msg)
                    additional_kwargs_delta = self._unsent_additional_kwargs(msg_id, additional_kwargs)
                    text = self.client._extract_text(msg.content)
                    sent_text = self.sent_text_by_id.get(msg_id, "")
                    if len(text) > len(sent_text) and text.startswith(sent_text):
                        self.sent_text_by_id[msg_id] = text
                        yield self.client._ai_text_event(msg_id, text[len(sent_text) :], None, additional_kwargs_delta)
                        additional_kwargs_delta = None
                    if msg_id in self.pending_tool_call_ids and msg.tool_calls:
                        self.pending_tool_call_ids.discard(msg_id)
                        yield self.client._ai_tool_calls_event(msg_id, msg.tool_calls, additional_kwargs_delta)
                    elif additional_kwargs_delta:
                        # Metadata-only follow-up: ``messages-tuple`` has no
                        # dedicated attribution event, so clients should
                        # merge this empty-content AI event by message id
                        # and ignore it for text rendering.
                        yield self.client._ai_text_event(msg_id, "", None, additional_kwargs_delta)
                continue

            if isinstance(msg, AIMessage):
                counted_usage = self._account_usage(msg_id, msg.usage_metadata)
                additional_kwargs = self.client._serialize_additional_kwargs(msg)
                sent_additional_kwargs = False

                if msg.tool_calls:
                    additional_kwargs_delta = self._unsent_additional_kwargs(msg_id, additional_kwargs)
                    yield self.client._ai_tool_calls_event(
                        msg_id,
                        msg.tool_calls,
                        additional_kwargs_delta,
                    )
                    sent_additional_kwargs = bool(additional_kwargs_delta)

                text = self.client._extract_text(msg.content)
                if text:
                    if msg_id:
                        self.sent_text_by_id[msg_id] = text
                    additional_kwargs_delta = None if sent_additional_kwargs else self._unsent_additional_kwargs(msg_id, additional_kwargs)
                    yield self.client._ai_text_event(
                        msg_id,
                        text,
                        counted_usage,
                        additional_kwargs_delta,
                    )
                elif msg_id:
                    additional_kwargs_delta = None if sent_additional_kwargs else self._unsent_additional_kwargs(msg_id, additional_kwargs)
                    if not additional_kwargs_delta:
                        continue
                    # See the metadata-only follow-up convention above.
                    yield self.client._ai_text_event(msg_id, "", None, additional_kwargs_delta)

            elif isinstance(msg, ToolMessage):
                yield self.client._tool_message_event(msg)

        # Emit a values event for each state snapshot
        yield StreamEvent(
            type="values",
            data={
                "title": chunk.get("title"),
                "summary_text": chunk.get("summary_text"),
                "messages": [self.client._serialize_message(m) for m in messages],
                "artifacts": chunk.get("artifacts", []),
            },
        )

    def finish(self) -> StreamEvent:
        from deerflow.client import StreamEvent

        return StreamEvent(type="end", data={"usage": self.cumulative_usage})
