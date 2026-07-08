"""
DatabaseRepository with connection pooling for DuckDB.

This module provides a thread-safe DuckDB repository with connection pooling
to support concurrent read/write access in multi-agent scenarios.

Features:
- List-based connection pool with threading lock for write serialization
- DuckDB's single-writer model protected by threading.Lock
- Context manager for safe connection handling
- High-level methods for common operations
"""

import atexit
import os
import queue
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

import duckdb


def _infer_table_name(query: str) -> str:
    """Best-effort table label for audit and column classification."""
    import re

    match = re.search(r"\bfrom\s+([\"`]?[a-zA-Z_][\w]*[\"`]?)", query, re.IGNORECASE)
    if match:
        return match.group(1).strip('"`')
    return "query_result"


class DatabaseRepository:
    """Thread-safe DuckDB repository with connection pooling.

    This class manages a pool of DuckDB connections with thread-safe
    write serialization, allowing concurrent read and write operations
    from multiple threads.

    Attributes:
        _db_path: Path to the DuckDB database file.
        _pool: List-based connection pool.
        _lock: Thread lock for write serialization.

    Example:
        >>> repo = DatabaseRepository("workspace.duckdb", pool_size=5)
        >>> with repo.connection() as conn:
        ...     conn.execute("SELECT * FROM users")
        ...     print(conn.fetchall())
        >>> repo.close_all()
    """

    def __init__(self, db_path: str, pool_size: int = 5):
        """Initialize the database repository with connection pool.

        Args:
            db_path: Path to the DuckDB database file.
            pool_size: Number of connections in the pool (default: 5).
        """
        self._db_path = db_path
        self._pool: queue.Queue[duckdb.DuckDBPyConnection] = queue.Queue()
        self._lock = threading.Lock()
        self._initialize_pool(pool_size)

    def _initialize_pool(self, size: int) -> None:
        """Create connection pool with DuckDB configuration.

        Each connection is configured with:
        - threads=4: Parallel query execution
        - memory_limit=2GB: Memory usage cap

        Args:
            size: Number of connections to create.
        """
        for _ in range(size):
            conn = self._create_connection()
            self._pool.put(conn)

    def _create_connection(self) -> duckdb.DuckDBPyConnection:
        """Create a single DuckDB connection with optimal settings.

        Returns:
            duckdb.DuckDBPyConnection: A configured DuckDB connection.
        """
        self._prepare_database_path()
        conn = duckdb.connect(self._db_path)
        conn.execute("SET threads=4")
        conn.execute("SET memory_limit='2GB'")
        return conn

    def _prepare_database_path(self) -> None:
        """Ensure DuckDB can create or open the configured database file."""
        if self._db_path == ":memory:":
            return

        db_path = Path(self._db_path)
        if db_path.parent and str(db_path.parent) != ".":
            db_path.parent.mkdir(parents=True, exist_ok=True)

        if db_path.exists() and db_path.is_file() and db_path.stat().st_size == 0:
            db_path.unlink()

    @contextmanager
    def connection(self) -> Iterator[duckdb.DuckDBPyConnection]:
        """Get a connection from the pool as a context manager.

        The connection is automatically returned to the pool when the
        context exits, even if an exception occurs.

        Yields:
            duckdb.DuckDBPyConnection: A database connection from the pool.

        Example:
            >>> with repo.connection() as conn:
            ...     conn.execute("SELECT 1")
        """
        try:
            conn = self._pool.get_nowait()
        except queue.Empty:
            conn = self._create_connection()
        try:
            yield conn
        finally:
            self._pool.put(conn)

    def execute_query_raw(self, query: str, params: tuple = ()) -> list[dict]:
        """Execute a parameterized query and return unmasked raw results.

        Args:
            query: SQL query string.
            params: Query parameters (default: empty tuple).

        Returns:
            List of dictionaries, one per row.

        Example:
            >>> results = repo.execute_query(
            ...     "SELECT * FROM users WHERE age > ?",
            ...     (18,)
            ... )
        """
        with self.connection() as conn:
            if params:
                conn.execute(query, params)
            else:
                conn.execute(query)
            if conn.description is None:
                return []
            columns = [desc[0] for desc in conn.description]
            rows = conn.fetchall()
            return [dict(zip(columns, row)) for row in rows]

    def execute_query(self, query: str, params: tuple = ()) -> list[dict]:
        """Execute a query through the default privacy and audit pipeline.

        PII masking is controlled by ``echart_config.txt`` and is off by
        default. Audit logging is on by default so query access remains
        traceable even when masking is disabled.
        """
        from scripts.config_manager import get_config
        from scripts.privacy_guard import PrivacyGuard

        cfg = get_config()
        guard = PrivacyGuard(
            enabled=cfg.privacy.enabled,
            read_only=cfg.privacy.read_only,
            audit_enabled=cfg.privacy.audit_enabled,
            mask_pii=cfg.privacy.mask_pii,
            audit_log_path=cfg.privacy.audit_log_path,
        )

        guard.enforce_read_only(query)
        rows = self.execute_query_raw(query, params)
        columns = list(rows[0].keys()) if rows else []
        return guard.guard_query(query, _infer_table_name(query), columns, rows)

    def execute_many(self, query: str, params_list: list[tuple]) -> int:
        """Execute many INSERT/UPDATE operations efficiently.

        This method uses executemany for batch operations, which is
        more efficient than individual execute calls.

        Args:
            query: SQL query string (INSERT/UPDATE statements).
            params_list: List of parameter tuples.

        Returns:
            Number of rows affected.

        Example:
            >>> count = repo.execute_many(
            ...     "INSERT INTO users (name, age) VALUES (?, ?)",
            ...     [("Alice", 25), ("Bob", 30)]
            ... )
        """
        with self.connection() as conn:
            conn.executemany(query, params_list)
            return conn.rowcount if conn.rowcount != -1 else len(params_list)

    def close_all(self) -> None:
        """Close all connections in the pool.

        This method should be called when the repository is no longer
        needed to release database resources.
        """
        with self._lock:
            while not self._pool.empty():
                conn = self._pool.get_nowait()
                conn.close()


# Module-level repositories keyed by DuckDB path.
_repo: Optional[DatabaseRepository] = None
_repositories: dict[str, DatabaseRepository] = {}
_get_repo_lock = threading.Lock()


def get_repository(db_path: str = "workspace.duckdb") -> DatabaseRepository:
    """Get or create the database repository singleton.

    This function provides a convenient way to access a shared
    DatabaseRepository instance across the application.

    Args:
        db_path: Path to the DuckDB database file (default: "workspace.duckdb").

    Returns:
        DatabaseRepository: The singleton repository instance.

    Example:
        >>> repo = get_repository("workspace.duckdb")
        >>> with repo.connection() as conn:
        ...     conn.execute("SELECT 1")
    """
    global _repo
    key = os.path.abspath(db_path) if db_path != ":memory:" else db_path

    if key not in _repositories:
        with _get_repo_lock:
            if key not in _repositories:
                _repositories[key] = DatabaseRepository(db_path)
                _repo = _repositories[key]
                atexit.register(_cleanup_repo)
    return _repositories[key]


def _cleanup_repo() -> None:
    """Cleanup function registered with atexit."""
    global _repo
    for repo in list(_repositories.values()):
        repo.close_all()
    _repositories.clear()
    _repo = None
