"""Publication topology admission and a short-transaction durable DB pool."""

from __future__ import annotations

import os
from pathlib import Path

from deerflow_extension_api.host_capabilities import HostCapabilityError
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


class PublicationTopology:
    """Operator attests local single host; SQLite additionally enforces one host.

    A file lock cannot prove that a mount is not NFS/CSI. That remains an explicit
    deployment prerequisite, not a capability inferred from PostgreSQL alone.
    """

    def __init__(self, backend: str, root: Path):
        self.backend = backend
        self.root = root
        self._fd: int | None = None

    def acquire(self):
        if os.name != "posix" or self.backend not in {"sqlite", "postgres"}:
            raise HostCapabilityError("UNSUPPORTED_TOPOLOGY")
        if self._fd is not None or self.backend == "postgres":
            return
        import fcntl

        self.root.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.root / ".skill-mutations-gateway.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            raise HostCapabilityError("UNSUPPORTED_TOPOLOGY", "SQLite publication requires one Gateway process") from exc
        self._fd = fd

    def close(self):
        if self._fd is not None:
            fd, self._fd = self._fd, None
            os.close(fd)


def mutation_session_factory(url: str, *, postgres_schema: str = ""):
    """Same application DB, dedicated bounded pool and fsync-strict journal writes.

    Do not change PRAGMAs on the shared agent-definition engine. FULL is needed
    for PREPARED to be durable before replacing the canonical filesystem file.
    """
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite":
        if not parsed.database or parsed.database == ":memory:":
            raise HostCapabilityError("UNSUPPORTED_TOPOLOGY")
        args = {"check_same_thread": False, "timeout": 5}
    elif parsed.get_backend_name() == "postgresql":
        from deerflow.config.postgres_schema import validate_postgres_schema
        from deerflow.persistence.postgres_schema import build_psycopg_options

        options = build_psycopg_options(validate_postgres_schema(postgres_schema)) or ""
        args = {"connect_timeout": 5, "options": f"{options} -c lock_timeout=5000 -c statement_timeout=30000 -c synchronous_commit=on".strip()}
    else:
        raise HostCapabilityError("UNSUPPORTED_TOPOLOGY")
    engine = create_engine(url, connect_args=args, pool_size=4, max_overflow=0, pool_timeout=5, pool_pre_ping=True)
    if parsed.get_backend_name() == "sqlite":

        @event.listens_for(engine, "connect")
        def setup(connection, _record):
            cursor = connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=FULL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=5000")
            finally:
                cursor.close()

    return engine, sessionmaker(engine, expire_on_commit=False)
