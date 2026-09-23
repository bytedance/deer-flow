"""Supported stream modes for the LangGraph-compatible runtime boundary."""

from __future__ import annotations

from typing import Literal, get_args

type RunStreamMode = Literal[
    "values",
    "messages-tuple",
    "updates",
    "debug",
    "tasks",
    "checkpoints",
    "custom",
]

SUPPORTED_RUN_STREAM_MODES: frozenset[str] = frozenset(get_args(RunStreamMode.__value__))

#: Channels subscribed for every run regardless of what the caller asked for.
#: Middlewares and tools report progress through
#: ``langgraph.config.get_stream_writer()``; subscribing a channel nobody
#: writes to costs nothing. Because callers cannot opt out of them, they must
#: never be counted when deciding how the caller's *own* modes are streamed.
INTERNAL_LANGGRAPH_STREAM_MODES: tuple[str, ...] = ("custom",)


class UnsupportedStreamModeError(ValueError):
    """Raised when a caller requests a stream mode DeerFlow cannot honor."""

    def __init__(self, modes: list[str]) -> None:
        self.modes = tuple(dict.fromkeys(modes))
        super().__init__(f"Unsupported stream mode(s): {', '.join(self.modes)}")


def normalize_stream_modes(raw: list[str] | str | None) -> list[str]:
    """Normalize and validate public run stream modes."""
    if raw is None:
        modes = ["values"]
    elif isinstance(raw, str):
        modes = [raw]
    else:
        modes = raw or ["values"]

    unsupported = [mode if isinstance(mode, str) else type(mode).__name__ for mode in modes if not isinstance(mode, str) or mode not in SUPPORTED_RUN_STREAM_MODES]
    if unsupported:
        raise UnsupportedStreamModeError(unsupported)
    return modes


def _map_caller_modes(modes: list[str]) -> list[str]:
    """Map normalized public modes to their ``graph.astream`` names, deduplicated."""
    return list(dict.fromkeys("messages" if mode == "messages-tuple" else mode for mode in modes))


def to_langgraph_stream_modes(raw: list[str] | str | None) -> list[str]:
    """Map public run modes to ``graph.astream`` modes without silent fallback.

    Always includes ``custom`` so middlewares and tools can emit custom
    stream events: ToolStreamingMiddleware, LLMErrorHandlingMiddleware
    (retry hints), SafetyFinishReasonMiddleware, and the task tool all
    use get_stream_writer(). Including it adds zero overhead when no
    caller writes to the custom channel — LangGraph only allocates the
    writer when get_stream_writer() is called.
    """
    modes = normalize_stream_modes(raw)
    return list(dict.fromkeys((*_map_caller_modes(modes), *INTERNAL_LANGGRAPH_STREAM_MODES)))


def caller_langgraph_stream_modes(raw: list[str] | str | None) -> list[str]:
    """``graph.astream`` modes the caller itself asked for.

    :func:`to_langgraph_stream_modes` always appends the internal channels, so
    its result can no longer tell a single-mode request from a multi-mode one.
    Stream-*shape* decisions — the raw-chunk fast path and the file-tool chunk
    batcher — key off this list instead, which keeps a lone ``messages-tuple``
    caller on the per-chunk contract (#4354, backend/AGENTS.md) even though
    ``custom`` now rides along with it (#4150).
    """
    return _map_caller_modes(normalize_stream_modes(raw))
