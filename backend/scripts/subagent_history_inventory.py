"""Inspect ordinary task() checkpoint histories in one file-backed SQLite thread."""

import argparse
import json
import sqlite3
from contextlib import closing
from itertools import groupby
from operator import itemgetter
from pathlib import Path

# Both aggregates belong to the same SELECT, so a WAL commit cannot split the
# snapshot. Group each table independently: joining individual writes to
# checkpoints would multiply counts and omit namespaces with writes alone.
_INVENTORY = """
    WITH scoped AS (
        SELECT checkpoint_ns,
               CASE WHEN json_valid(CAST(metadata AS TEXT)) THEN CAST(metadata AS TEXT) END AS meta
        FROM checkpoints
        WHERE thread_id = :thread AND checkpoint_ns GLOB :pattern
    )
    SELECT checkpoint_ns,
           CASE WHEN json_type(meta, '$.deerflow_subagent_execution_id') = 'text'
                THEN CAST(json_extract(meta, '$.deerflow_subagent_execution_id') AS BLOB) END AS execution_id,
           CASE WHEN json_type(meta, '$.deerflow_parent_run_id') = 'text'
                THEN CAST(json_extract(meta, '$.deerflow_parent_run_id') AS BLOB) END AS parent_run_id,
           count(*) AS checkpoint_rows, 0 AS write_rows
    FROM scoped
    GROUP BY checkpoint_ns, execution_id, parent_run_id
    UNION ALL
    SELECT checkpoint_ns, NULL, NULL, 0, count(*)
    FROM writes
    WHERE thread_id = :thread AND checkpoint_ns GLOB :pattern
    GROUP BY checkpoint_ns
    ORDER BY checkpoint_ns
"""

_CHILD_PREFIX = "deerflow_subagent:"


def _decode_id(value: bytes | None) -> str | None:
    # SQLite JSON strings can contain invalid UTF-8, including lone surrogates.
    try:
        return value.decode("utf-8") if value is not None else None
    except UnicodeDecodeError:
        return None


def inspect_thread(db_path: Path, thread_id: str) -> list[dict]:
    """Return logical row counts for exact child namespaces, without loading payloads."""
    uri = db_path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(_INVENTORY, {"thread": thread_id, "pattern": f"?*|{_CHILD_PREFIX}?*"}).fetchall()

    histories = []
    for namespace, group in groupby(rows, key=itemgetter("checkpoint_ns")):
        # LangGraph appends a numeric subgraph counter for repeated graph
        # calls in a parent node. Keep it in the reported namespace.
        _, _, tail = namespace.rpartition(f"|{_CHILD_PREFIX}")
        namespace_id, separator, counter = tail.partition("|")
        if not namespace_id or (separator and not (counter.isascii() and counter.isdecimal())):
            continue
        counts = list(group)
        checkpoints = [row for row in counts if row["checkpoint_rows"]]
        execution_ids = {_decode_id(row["execution_id"]) for row in checkpoints}
        parent_ids = {_decode_id(row["parent_run_id"]) for row in checkpoints if row["parent_run_id"]}
        matches = execution_ids == {namespace_id}
        reason = "No durable record confirms the checkpoint writer has finished."
        if not matches:
            reason = "Checkpoint metadata is missing or disagrees with the execution namespace."
        elif len(parent_ids) > 1:
            reason = "Checkpoint metadata records conflicting parent run IDs."
        histories.append(
            {
                "checkpoint_ns": namespace,
                "execution_id": namespace_id if matches else None,
                "parent_run_id": next(iter(parent_ids)) if matches and len(parent_ids) == 1 else None,
                "checkpoint_rows": sum(row["checkpoint_rows"] for row in checkpoints),
                "write_rows": sum(row["write_rows"] for row in counts),
                "status": "unknown / retained",
                "reason": reason,
            }
        )
    return histories


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="path to the SQLite checkpoint database")
    parser.add_argument("--thread-id", required=True, help="parent thread to inspect")
    args = parser.parse_args()
    try:
        histories = inspect_thread(args.db, args.thread_id)
    except (OSError, sqlite3.Error) as exc:
        parser.exit(1, f"Could not inspect {args.db}: {exc}\n")
    print(json.dumps({"thread_id": args.thread_id, "histories": histories}, indent=2))


if __name__ == "__main__":
    main()
