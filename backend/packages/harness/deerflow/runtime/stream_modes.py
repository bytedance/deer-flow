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


def to_langgraph_stream_modes(raw: list[str] | str | None) -> list[str]:
    """Map public run modes to ``graph.astream`` modes without silent fallback."""
    modes = normalize_stream_modes(raw)
    mapped = ["messages" if mode == "messages-tuple" else mode for mode in modes]
    return list(dict.fromkeys(mapped))
