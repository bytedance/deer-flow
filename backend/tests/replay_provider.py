"""Replay a recorded LLM trace deterministically — the "replay" half of
record/replay e2e (mirrors open-design's ``mocks/`` golden traces).

A fixture is a JSON file capturing the *real* model calls of one scenario,
keyed by a normalized hash of the **input** each call received::

    {
      "scenario": "write_read_file",
      "mode": "ultra",
      "model": "gpt-5.5",
      "turns": [
        {"input_hash": "<sha256>", "input_preview": "...", "output": <message dict>},
        ...
      ]
    }

Why hash-by-input (not turn index)
----------------------------------
A real run makes model calls from several callers — the lead agent's own turns,
``TitleMiddleware`` (auto-title), memory, and possibly subagents. They interleave
and their count/order is not something we want a replay to depend on. Matching by
a normalized hash of the *input messages* means each call gets back exactly the
output that was recorded for that input, regardless of order or which middleware
issued it. That keeps the in-graph, deterministic title call part of the
recording; memory/summarization, by contrast, are disabled in the replay config
(``_replay_fixture.py``) because their background, debounced timing is not
reproducible across runs.

Volatile fields (UUID thread/run/user ids, timestamps, dates, tmp/home paths)
are normalized out before hashing so a recording replays across processes with
different temp dirs. The same ``hash_messages`` is used by the recorder
(``scripts/record_gateway.py``) and here, so record and replay agree by
construction.

This lives in ``tests/`` (not in the publishable ``deerflow-harness`` package),
matching the repo convention for test-only fakes (cf. ``FakeToolCallingModel`` in
``_agent_e2e_helpers.py``). In-process tests get ``tests/`` on ``sys.path`` for
free via pytest; a standalone replay gateway just needs ``PYTHONPATH`` to include
``backend/tests`` so the config ``use:`` below resolves.

Point a config model's ``use`` at this class and set the fixture via env::

    models:
      - name: replay-model
        use: replay_provider:ReplayChatModel
        model: gpt-5.5            # placeholder; ignored

    DEERFLOW_REPLAY_FIXTURE=/path/to/write_read_file.ultra.json

A cache miss raises loudly with a diagnostic — that is the signal that the
replayed run diverged from the recording (graph changed, a new volatile field
slipped through normalization, or a non-deterministic tool result changed a
downstream input). Re-record or extend normalization; never pass silently.

Recording lives outside production code too (``scripts/record_gateway.py`` +
``scripts/build_fixture_from_jsonl.py``); CI consumes the fixtures through this
replay side with no API key.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import deque
from collections.abc import Iterator
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, messages_from_dict
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable
from pydantic import PrivateAttr

_FIXTURE_ENV = "DEERFLOW_REPLAY_FIXTURE"

# Process-wide record of replay misses. A miss raises inside the model, but the
# gateway's LLMErrorHandlingMiddleware swallows it into a normal assistant error
# message — so the SSE *event shapes* are unchanged and a shape-only golden stays
# green on a stale fixture. The in-process Layer-1 test inspects this list to fail
# loud on a miss instead. (Layer-2 already fails on a miss: the recorded turns
# never render.)
_replay_misses: list[str] = []


def replay_misses() -> list[str]:
    """Hashes that missed the fixture since the last reset (see ``_replay_misses``)."""
    return list(_replay_misses)


def reset_replay_misses() -> None:
    _replay_misses.clear()


# Volatile substrings that differ between a recording run and a replay run but
# carry no semantic weight for matching. Normalized to stable placeholders
# before hashing so the same logical input hashes identically across processes.
# The frontend injects a per-request ``<system-reminder>`` (current date, weekday,
# dynamic context) that the backend-direct path does not — and its date/weekday
# change every day. Strip the whole block before hashing so a fixture replays
# (a) across days and (b) from both the browser and direct-POST paths.
_SYSTEM_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_ISO_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# Absolute temp/home roots used for per-run isolation (macOS + Linux + DEER_FLOW_HOME tmp).
_PATH_RE = re.compile(r"(?:/private)?/(?:var/folders|tmp)/[^\s\"']*")


def _normalize_text(text: str) -> str:
    text = _SYSTEM_REMINDER_RE.sub("", text)
    text = _UUID_RE.sub("<UUID>", text)
    text = _ISO_TS_RE.sub("<TS>", text)
    text = _DATE_RE.sub("<DATE>", text)
    text = _PATH_RE.sub("<PATH>", text)
    return text


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", "") or json.dumps(block, sort_keys=True, ensure_ascii=False))
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content)


def _canonical_messages(messages: list[BaseMessage]) -> str:
    """Project messages to a stable shape that excludes volatile metadata/ids.

    Keeps only what determines which recorded turn to replay: the conversation
    (human / ai / tool messages — role, text content, tool-call name+args). Drops
    ``id``, ``response_metadata``, ``usage_metadata``, ``tool_call_id`` (all
    volatile), then normalizes embedded volatile substrings.

    **The system message is excluded entirely.** The lead-agent system prompt is
    a living, frequently-edited implementation detail (its wording changes across
    PRs), not part of the front-back contract this harness verifies. Hashing it
    would make every fixture go stale — and red-fail on unrelated PRs — the moment
    anyone edits the prompt. The conversation flow (user input -> tool calls ->
    results -> answer) is the stable key that identifies a recorded turn.
    """
    projected: list[dict[str, Any]] = []
    for message in messages:
        # Exclude the system prompt from the match key — see docstring. It is the
        # most-edited part of the prompt and not part of the contract under test.
        if message.type == "system":
            continue
        content = _normalize_text(_content_to_text(message.content))
        tool_calls = getattr(message, "tool_calls", None)
        # Drop messages that are empty after normalization — e.g. a turn that was
        # nothing but a frontend-injected <system-reminder>. They carry no
        # decision-relevant content and differ between client paths.
        if not content.strip() and not tool_calls:
            continue
        entry: dict[str, Any] = {"type": message.type, "content": content}
        if tool_calls:
            entry["tool_calls"] = [{"name": tc.get("name"), "args": tc.get("args")} for tc in tool_calls]
        name = getattr(message, "name", None)
        if name:
            entry["name"] = name
        projected.append(entry)
    raw = json.dumps(projected, sort_keys=True, ensure_ascii=False)
    return _normalize_text(raw)


def hash_messages(messages: list[BaseMessage]) -> str:
    """Stable hash of a model call's input. Shared by recorder and replayer."""
    return hashlib.sha256(_canonical_messages(messages).encode("utf-8")).hexdigest()


def _load_fixture(fixture_path: str) -> dict[str, deque[AIMessage]]:
    with open(fixture_path, encoding="utf-8") as handle:
        payload = json.load(handle)
    table: dict[str, deque[AIMessage]] = {}
    for index, turn in enumerate(payload.get("turns", [])):
        input_hash = turn["input_hash"]
        (message,) = messages_from_dict([turn["output"]])
        if not isinstance(message, AIMessage):
            raise ValueError(f"replay fixture {fixture_path!r} turn {index} output is {type(message).__name__}, expected AIMessage")
        table.setdefault(input_hash, deque()).append(message)
    return table


class ReplayChatModel(BaseChatModel):
    """Returns the recorded assistant output whose input matches this call.

    ``bind_tools`` is a no-op returning ``self`` — recorded turns already carry
    the real ``tool_calls``, so the agent dispatches them as if a live model had
    produced them.
    """

    _table: dict[str, deque] = PrivateAttr(default_factory=dict)
    _fixture_path: str = PrivateAttr(default="")

    def __init__(self, **kwargs: Any) -> None:
        # Ignore provider noise the factory forwards from config (model, api_key,
        # base_url, ...). Fixture path comes from the ``fixture`` kwarg or env.
        fixture_path = kwargs.pop("fixture", None) or os.environ.get(_FIXTURE_ENV)
        super().__init__()
        if not fixture_path:
            raise ValueError(f"ReplayChatModel needs a fixture path via the ``fixture`` kwarg or ${_FIXTURE_ENV}")
        self._fixture_path = fixture_path
        self._table = _load_fixture(fixture_path)

    @property
    def _llm_type(self) -> str:
        return "deerflow-replay"

    def _match(self, messages: list[BaseMessage]) -> AIMessage:
        key = hash_messages(messages)
        bucket = self._table.get(key)
        if not bucket:
            _replay_misses.append(key)
            preview = _canonical_messages(messages)
            raise KeyError(
                f"replay miss: no recorded output for input hash {key} in {self._fixture_path!r}. "
                "The replayed run diverged from the recording (graph changed, a non-deterministic tool result "
                "altered a downstream input, or a volatile field slipped past normalization). "
                f"Known hashes: {sorted(self._table)}. "
                f"Normalized input (first 800 chars): {preview[:800]!r}"
            )
        return bucket.popleft()

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._match(messages))])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        turn = self._match(messages)
        text = turn.content if isinstance(turn.content, str) else ""
        chunk = ChatGenerationChunk(message=AIMessageChunk(content=turn.content, tool_calls=turn.tool_calls, additional_kwargs=turn.additional_kwargs, id=turn.id))
        if run_manager is not None and text:
            run_manager.on_llm_new_token(text, chunk=chunk)
        yield chunk

    def bind_tools(self, tools: Any, **kwargs: Any) -> Runnable:  # type: ignore[override]
        return self


# Re-export so the recorder shares the exact hashing logic.
__all__ = ["ReplayChatModel", "hash_messages", "replay_misses", "reset_replay_misses"]
