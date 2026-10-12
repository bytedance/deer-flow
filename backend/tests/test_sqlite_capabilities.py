"""The bundled SQLite must support what the scheduler's SQL relies on.

The fair drain (``ScheduledTaskRunRepository.list_queued_runs``) ranks queued
rows per owner with ``ROW_NUMBER() OVER (PARTITION BY ...)``, which SQLite
supports from 3.25. An older build should fail CI loudly here rather than at
runtime on the first poll.
"""

import sqlite3


def test_sqlite_supports_window_functions():
    assert sqlite3.sqlite_version_info >= (3, 25), f"SQLite {sqlite3.sqlite_version} lacks window functions (needs >= 3.25)"
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE TABLE t (owner TEXT, n INTEGER)")
        connection.executemany("INSERT INTO t VALUES (?, ?)", [("a", 1), ("a", 2), ("b", 1)])
        rows = connection.execute("SELECT owner, n, ROW_NUMBER() OVER (PARTITION BY owner ORDER BY n) FROM t ORDER BY owner, n").fetchall()
    finally:
        connection.close()
    assert rows == [("a", 1, 1), ("a", 2, 2), ("b", 1, 1)]
