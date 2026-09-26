"""The in-band progress-evaluation protocol payload and its redaction.

Split out of :mod:`progress_scoring_middleware` so the runtime layer (run
journal, run worker) can import the redaction helpers without dragging in the
middleware's agent-framework imports — those would create an import cycle
(``runtime.__init__`` → ``runs.worker`` → middleware → ``loop_detection`` →
``runtime``).

Everything here depends only on the standard library and
``langchain_core.messages``:

- ``PROGRESS_EVAL_TAG`` / ``_EVAL_BLOCK_RE`` — the fenced-block protocol the
  model is instructed to append to responses that follow tool results.
- :func:`strip_progress_eval_blocks` — remove complete blocks from message
  content (str or content-block list); used by the middleware's state rewrite
  and by the journal's ``llm.ai.response`` serialization.
- :class:`ProgressEvalStreamRedactor` — remove blocks from live ``messages``
  -mode chunks, where the block can be split across arbitrary chunk
  boundaries.
"""

from __future__ import annotations

import re
from typing import Any

from langchain_core.messages import AIMessage

# The fenced-block language tag the model is instructed to use for its
# self-evaluation. Distinctive so it cannot collide with ordinary markdown.
PROGRESS_EVAL_TAG = "deerflow-progress"

_EVAL_BLOCK_RE = re.compile(
    rf"```{PROGRESS_EVAL_TAG}[^\S\n]*\n(.*?)```",
    re.DOTALL,
)


def strip_progress_eval_blocks(content: str | list | None) -> str | list | None:
    """Remove the evaluation block(s) from AIMessage content.

    Shared by the middleware's ``after_model`` state rewrite and the
    presentation boundaries — the run journal's ``llm.ai.response``
    serialization and the live ``messages`` stream redactor — so the protocol
    payload stays out of checkpoints, durable events, and the UI alike.

    Never mutates the input: returns the original object when there is
    nothing to strip, a new value otherwise — including an *empty* value when
    the content consisted solely of the block, so a block-only response can
    never fall back to leaking the block. Text blocks that become empty after
    stripping are dropped.
    """
    if isinstance(content, str):
        stripped = _EVAL_BLOCK_RE.sub("", content)
        if stripped == content:
            return content
        return stripped.strip()

    if isinstance(content, list):
        new_blocks: list = []
        changed = False
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                stripped = _EVAL_BLOCK_RE.sub("", block["text"])
                if stripped != block["text"]:
                    changed = True
                    if stripped.strip():
                        new_blocks.append({**block, "text": stripped})
                    continue
                new_blocks.append(block)
            elif isinstance(block, str):
                stripped = _EVAL_BLOCK_RE.sub("", block)
                if stripped != block:
                    changed = True
                    if stripped.strip():
                        new_blocks.append(stripped)
                    continue
                new_blocks.append(block)
            else:
                new_blocks.append(block)
        return new_blocks if changed else content

    return content


def redacted_message_copy(message: AIMessage) -> AIMessage:
    """Return *message* with evaluation blocks stripped from its content.

    Returns the original object when there is nothing to strip; otherwise a
    ``model_copy`` whose content is :func:`strip_progress_eval_blocks`-cleaned
    (tool calls, usage, and metadata are preserved by the copy). Used by the
    run journal so every consumer of one response — the durable
    ``llm.ai.response`` event *and* the run-summary path
    (``_snapshot_message_summary`` → ``last_ai_message``) — sees the same
    sanitized message.
    """
    stripped = strip_progress_eval_blocks(message.content)
    if stripped is message.content:
        return message
    return message.model_copy(update={"content": stripped})


# Streaming redaction markers: the opening fence of the evaluation block, and
# the closing fence that terminates it. Both deliberately mirror what
# _EVAL_BLOCK_RE matches on complete content.
_OPEN_MARKER = f"```{PROGRESS_EVAL_TAG}"
_CLOSE_MARKER = "```"


def _longest_suffix_prefix(text: str, marker: str) -> str:
    """Longest suffix of *text* that is a proper prefix of *marker*."""
    max_len = min(len(text), len(marker) - 1)
    for size in range(max_len, 0, -1):
        if text[-size:] == marker[:size]:
            return text[-size:]
    return ""


class ProgressEvalStreamRedactor:
    """Stateful filter that removes evaluation blocks from streamed AI chunks.

    ``messages``-mode frames carry AIMessageChunk objects whose text arrives
    split across arbitrary chunk boundaries, so a per-chunk regex cannot see a
    whole fenced block — and the ``after_model`` state rewrite happens after
    those chunks were already published to the live stream. This filter
    scans the *concatenated* stream instead: ordinary text is held back only
    while it could still become the opening fence, everything between the
    opening and the closing fence is dropped, and an unterminated block is
    restored at message end so the stream never diverges from what the
    regex-based state rewrite keeps.

    Chunks whose text is fully dropped are still emitted with emptied
    content, so usage metadata / response metadata riding on the final chunk
    of a message is not lost. Non-AI messages pass through untouched. Text
    blocks inside list content are fed through the same stateful scanner as
    string content — a provider may emit the opening fence, the JSON payload,
    and the closing fence as separate text blocks across chunks, and a
    per-block regex would see no complete block in any of them. Non-text
    blocks (images, tool-use) pass through unchanged.

    Mirrors ``_LargeFileToolChunkBatcher``'s worker integration contract:
    ``push(chunk) -> list[chunk]`` plus ``finish()`` for the stream tail.
    """

    def __init__(self) -> None:
        self._inside = False
        self._carry = ""
        # Text consumed since the opening fence. Kept so an unterminated
        # block can be restored at message end — the state-side regex only
        # strips *closed* blocks, so the stream must keep unclosed ones too.
        self._held = ""
        self._last_message: AIMessage | None = None
        self._last_metadata: dict | None = None

    def push(self, chunk: Any) -> list[Any]:
        """Redact one ``messages``-mode ``(message, metadata)`` chunk.

        Returns the chunks to publish in order: possibly none of the text,
        several pieces when a block ended mid-chunk, or the original tuple
        unchanged when it carries nothing to redact.
        """
        if not (isinstance(chunk, tuple) and len(chunk) == 2):
            return [chunk]
        message, metadata = chunk
        if not isinstance(message, AIMessage):
            return [chunk]

        outputs: list = []
        message_id = getattr(message, "id", None)
        last_id = getattr(self._last_message, "id", None) if self._last_message is not None else None
        if self._last_message is not None and message_id is not None and last_id is not None and message_id != last_id:
            # A new AI message started: flush the previous message's
            # leftovers before tracking this one.
            outputs.extend(self._flush_message())
        self._last_message = message
        self._last_metadata = metadata if isinstance(metadata, dict) else {}

        content = message.content
        if isinstance(content, str):
            pieces = self._feed(content)
            if not pieces:
                return [*outputs, self._copy_chunk(message, metadata, "")]
            outputs.extend(self._copy_chunk(message, metadata, piece) for piece in pieces)
            return outputs

        if isinstance(content, list):
            new_blocks: list = []
            changed = False
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    # Same stateful scanner as string content: blocks feed
                    # the stream state machine in order, so a block split
                    # across text blocks / chunks is still redacted whole.
                    pieces = self._feed(block["text"])
                    if pieces == [block["text"]]:
                        new_blocks.append(block)
                        continue
                    changed = True
                    new_blocks.extend({**block, "text": piece} for piece in pieces)
                elif isinstance(block, str):
                    pieces = self._feed(block)
                    if pieces == [block]:
                        new_blocks.append(block)
                        continue
                    changed = True
                    new_blocks.extend(pieces)
                else:
                    new_blocks.append(block)
            if not changed:
                outputs.append((message, metadata))
            else:
                outputs.append(self._copy_chunk(message, metadata, new_blocks))
            return outputs

        return outputs + [(message, metadata)]

    def finish(self) -> list[Any]:
        """Flush leftovers held back at the end of the stream."""
        return self._flush_message()

    # ------------------------------------------------------------------
    # Internals

    def _feed(self, text: str) -> list[str]:
        """Return the pieces of *text* that are ordinary assistant text."""
        buf = self._carry + text
        self._carry = ""
        if not buf:
            return []

        if self._inside:
            close = buf.find(_CLOSE_MARKER)
            if close == -1:
                # The closing fence can split across chunks exactly like the
                # opening one; hold back a suffix that could still complete it.
                hold = _longest_suffix_prefix(buf, _CLOSE_MARKER)
                self._carry = hold
                self._held += buf[: len(buf) - len(hold)]
                return []
            self._inside = False
            self._held = ""
            return self._feed(buf[close + len(_CLOSE_MARKER) :])

        # Fast path: no backtick anywhere (including the carry) means the
        # opening fence cannot be present or forming.
        if "`" not in buf:
            return [buf]

        open_idx = buf.find(_OPEN_MARKER)
        if open_idx != -1:
            pieces = []
            before = buf[:open_idx]
            if before:
                pieces.append(before)
            self._inside = True
            self._held = _OPEN_MARKER
            pieces.extend(self._feed(buf[open_idx + len(_OPEN_MARKER) :]))
            return pieces

        hold = _longest_suffix_prefix(buf, _OPEN_MARKER)
        self._carry = hold
        emit = buf[: len(buf) - len(hold)]
        return [emit] if emit else []

    def _flush_message(self) -> list[Any]:
        """Emit the previous message's held-back text, if any, as one chunk."""
        outputs: list = []
        if self._last_message is not None:
            if self._inside:
                # Unterminated block: the state-side regex keeps unclosed
                # blocks, so restore everything, marker included.
                leftover = self._held + self._carry
            else:
                leftover = self._carry
            if leftover:
                outputs.append(self._copy_chunk(self._last_message, self._last_metadata, leftover))
        self._inside = False
        self._carry = ""
        self._held = ""
        self._last_message = None
        self._last_metadata = None
        return outputs

    @staticmethod
    def _copy_chunk(message: AIMessage, metadata: Any, content: Any) -> tuple:
        """Copy *message* with new *content*, keeping the original metadata."""
        model_copy = getattr(message, "model_copy", None)
        if callable(model_copy):
            return (model_copy(update={"content": content}), metadata)
        return (message, metadata)
