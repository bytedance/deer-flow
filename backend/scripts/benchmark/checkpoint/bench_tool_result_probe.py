#!/usr/bin/env python
"""Probe: do oversized tool results reach checkpoint state as full text? (#4189 item 4)

`ToolOutputBudgetMiddleware` is registered by default and externalizes tool
results above `externalize_min_chars` (preview + file reference under
`.tool-results/`). This probe quantifies the storage effect of that
transformation: the same oversized tool result is driven through the
middleware's `awrap_tool_call` (or run raw), the resulting ToolMessage is
written into a checkpointed graph state, and the per-thread checkpoint
storage (rows + bytes, same normalized shape as bench_channels) is reported
for SQLite.

Scope limit (state this when citing the numbers): the middleware is invoked
manually and the resulting message is injected with ``aupdate_state`` — the
production agent-factory path (middleware stack wiring, ThreadDataMiddleware
runtime state, tool-node task writes) is NOT exercised. The probe therefore
bounds the middleware's own transformation and the checkpoint cost of its
output; by itself it cannot establish that "the default configuration
covers item 4". A residual gap claim must name the concrete factory path
and come with its own measurements.

Item 4 of #4189 can be closed as covered if the wrapped path's checkpoint
bytes stay flat as the result size grows and no factory-path measurement
shows full text landing in state.

Usage:
    cd backend
    python scripts/benchmark/checkpoint/bench_tool_result_probe.py \
        [--result-bytes 50000] [--outputs-dir .tool-results-probe]

Output: JSON on stdout.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage, ToolMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages

from deerflow.agents.middlewares.tool_output_budget_middleware import ToolOutputBudgetMiddleware

PROBE_TOOL = "probe_tool"


class ProbeState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


async def _stats_sqlite(saver: AsyncSqliteSaver, thread_id: str) -> dict[str, int]:
    async def one(sql: str) -> tuple[int, int]:
        async with saver.conn.execute(sql, (thread_id,)) as cursor:
            row = await cursor.fetchone()
        return int(row[0]), int(row[1] or 0)

    cp = await one("SELECT COUNT(*), COALESCE(SUM(LENGTH(checkpoint) + LENGTH(metadata)), 0) FROM checkpoints WHERE thread_id = ?")
    wr = await one("SELECT COUNT(*), COALESCE(SUM(LENGTH(value)), 0) FROM writes WHERE thread_id = ?")
    return {
        "checkpoint_rows": cp[0],
        "checkpoint_bytes": cp[1],
        "write_rows": wr[0],
        "write_bytes": wr[1],
    }


def _make_graph(saver: Any) -> Any:
    def call_probe_tool(state: dict[str, Any]) -> dict[str, Any]:
        # the oversized result never flows through this node: the probe
        # injects the (possibly externalized) ToolMessage via aupdate_state
        # below, so the graph only provides a checkpointed state container
        return {}

    builder = StateGraph(ProbeState)
    builder.add_node("tool", call_probe_tool)
    builder.set_entry_point("tool")
    builder.set_finish_point("tool")
    return builder.compile(checkpointer=saver)


async def _run_path(
    label: str,
    result_bytes: int,
    *,
    wrapped: bool,
    outputs_dir: Path | None,
) -> dict[str, Any]:
    tmp = Path(".probe-tmp")
    tmp.mkdir(exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(tmp / f"probe-{label}.sqlite")) as saver:
        await saver.setup()
        middleware = ToolOutputBudgetMiddleware() if wrapped else None
        graph = _make_graph(saver)

        thread_id = f"probe-{label}"
        config = {"configurable": {"thread_id": thread_id}}

        # invoke the tool through the middleware's wrap (or raw), then persist
        # the resulting ToolMessage into graph state and take a checkpoint
        oversized = "A" * result_bytes
        request = SimpleNamespace(
            tool_call={"name": PROBE_TOOL, "id": "probe-call-1"},
            runtime=SimpleNamespace(state={"thread_data": {"outputs_path": str(outputs_dir)}} if outputs_dir else {"thread_data": None}),
        )

        async def handler(_request: Any) -> ToolMessage:
            return ToolMessage(content=oversized, tool_call_id="probe-call-1")

        if wrapped and middleware is not None:
            message = await middleware.awrap_tool_call(request, handler)
        else:
            message = await handler(request)

        await graph.aupdate_state(config, {"messages": [message]})
        stats = await _stats_sqlite(saver, thread_id)
        content_chars = len(message.content) if isinstance(message.content, str) else -1

    return {
        "path": label,
        "result_bytes": result_bytes,
        "tool_message_content_chars": content_chars,
        "externalized_file_bytes": (sum(f.stat().st_size for f in outputs_dir.rglob("*") if f.is_file()) if outputs_dir and outputs_dir.exists() else 0),
        "checkpoint": stats,
    }


async def _main(result_bytes: int, outputs_dir: Path) -> dict[str, Any]:
    raw = await _run_path("raw-unwrapped", result_bytes, wrapped=False, outputs_dir=None)
    externalized = await _run_path("budget-externalized", result_bytes, wrapped=True, outputs_dir=outputs_dir)
    truncated = await _run_path("budget-truncated", result_bytes, wrapped=True, outputs_dir=None)
    return {
        "result_bytes": result_bytes,
        "paths": [raw, externalized, truncated],
        "verdict": {
            "wrapped_content_stays_small": externalized["tool_message_content_chars"] < result_bytes,
            "raw_content_is_full": raw["tool_message_content_chars"] == result_bytes,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-bytes", type=int, default=50_000)
    parser.add_argument("--outputs-dir", type=Path, default=Path(".tool-results-probe"))
    args = parser.parse_args()

    outputs_dir: Path = args.outputs_dir
    outputs_dir.mkdir(parents=True, exist_ok=True)
    try:
        report = asyncio.run(_main(args.result_bytes, outputs_dir))
    finally:
        import shutil

        shutil.rmtree(outputs_dir, ignore_errors=True)
        shutil.rmtree(".probe-tmp", ignore_errors=True)

    json.dump(report, __import__("sys").stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
