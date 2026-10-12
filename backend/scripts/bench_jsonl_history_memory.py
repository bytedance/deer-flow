#!/usr/bin/env python3
"""Offline allocation benchmark for bounded JSONL history queries.

Run from backend with its environment (no network or existing user data needed):
    uv run python scripts/bench_jsonl_history_memory.py

The generated logs live in a temporary directory removed on exit. Peaks are
Python allocations traced during each query, not process RSS or disk-cache use.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
import time
import tracemalloc
from pathlib import Path

from deerflow.runtime.events.store.jsonl import JsonlRunEventStore


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def seed(root: Path, *, events: int, payload_bytes: int, runs: int, page_size: int) -> int:
    directory = root / "threads" / "benchmark" / "runs"
    directory.mkdir(parents=True)
    payload = "x" * payload_bytes
    for run in range(runs):
        run_id = f"run-{run:04d}"
        with (directory / f"{run_id}.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
            for seq in range(run + 1, events + 1, runs):
                stream.write(json.dumps({"run_id": run_id, "seq": seq, "category": "trace", "event_type": "tool.end", "content": payload}) + "\n")
            for index in range(page_size):
                stream.write(
                    json.dumps(
                        {
                            "run_id": run_id,
                            "seq": events + run * page_size + index + 1,
                            "category": "message",
                            "event_type": "llm.ai.response",
                            "content": {"type": "ai", "id": f"answer-{run}-{index}", "content": "answer"},
                        }
                    )
                    + "\n"
                )
    return sum(path.stat().st_size for path in directory.glob("*.jsonl"))


async def measure(args: argparse.Namespace) -> dict:
    with tempfile.TemporaryDirectory(prefix="deerflow-jsonl-bench-") as temporary:
        root = Path(temporary)
        file_bytes = seed(root, events=args.events, payload_bytes=args.payload_bytes, runs=args.runs, page_size=args.page_size)
        store = JsonlRunEventStore(root)
        target = f"answer-{args.runs - 1}-{args.page_size - 1}"
        queries = [
            ("list_messages", lambda: store.list_messages("benchmark", limit=args.page_size)),
            ("list_messages_forward", lambda: store.list_messages("benchmark", after_seq=args.events, limit=args.page_size)),
            ("list_messages_by_run", lambda: store.list_messages_by_run("benchmark", "run-0000", limit=args.page_size)),
            ("list_events", lambda: store.list_events("benchmark", "run-0000", limit=args.page_size)),
            ("list_events_filtered", lambda: store.list_events("benchmark", "run-0000", event_types=["llm.ai.response"], limit=args.page_size)),
            ("count_messages", lambda: store.count_messages("benchmark")),
            ("get_message_seqs", lambda: store.get_message_seqs("benchmark", {f"message:{target}", "message:missing"})),
            ("find_latest_ai_message_run_ids", lambda: store.find_latest_ai_message_run_ids("benchmark", {target, "missing"})),
            ("get_last_visible_ai_seq_by_run", lambda: store.get_last_visible_ai_seq_by_run("benchmark", {f"run-{run:04d}" for run in range(args.runs)})),
        ]
        measurements = []
        for name, query in queries:
            tracemalloc.start()
            started = time.perf_counter()
            try:
                result = await query()
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            measurements.append({"method": name, "peak_python_bytes": peak, "elapsed_seconds": time.perf_counter() - started, "result_count": result if isinstance(result, int) else len(result)})
        return {"parameters": vars(args), "file_bytes": file_bytes, "measurements": measurements}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=positive_int, default=2000, help="total unrelated trace records")
    parser.add_argument("--payload-bytes", type=positive_int, default=32768, help="ASCII content bytes per trace")
    parser.add_argument("--runs", type=positive_int, default=4)
    parser.add_argument("--page-size", type=positive_int, default=5, help="requested page size and generated messages per run")
    print(json.dumps(asyncio.run(measure(parser.parse_args())), indent=2))


if __name__ == "__main__":
    main()
