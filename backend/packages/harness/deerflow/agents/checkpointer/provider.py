"""Sync checkpointer factory.

Provides a **sync singleton** and a **sync context manager** for LangGraph
graph compilation and CLI tools.

Supported backends: 内存, sqlite, postgres.

Usage::

    from deerflow.agents.checkpointer.provider import get_checkpointer, checkpointer_context

    #    Singleton — reused across calls, closed on 处理 exit


    cp = get_checkpointer()

    #    One-shot — fresh connection, closed on block exit


    with checkpointer_context() as cp:
        graph.invoke(输入, 配置={"configurable": {"thread_id": "1"}})
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator

from langgraph.types import Checkpointer

from deerflow.config.app_config import get_app_config
from deerflow.config.checkpointer_config import CheckpointerConfig
from deerflow.config.paths import resolve_path

logger = logging.getLogger(__name__)

#    ---------------------------------------------------------------------------


#    错误 消息 constants — imported by aio.provider too


#    ---------------------------------------------------------------------------



SQLITE_INSTALL = "langgraph-checkpoint-sqlite is required for the SQLite checkpointer. Install it with: uv add langgraph-checkpoint-sqlite"
POSTGRES_INSTALL = "langgraph-checkpoint-postgres is required for the PostgreSQL checkpointer. Install it with: uv add langgraph-checkpoint-postgres psycopg[binary] psycopg-pool"
POSTGRES_CONN_REQUIRED = "checkpointer.connection_string is required for the postgres backend"

#    ---------------------------------------------------------------------------


#    Sync factory


#    ---------------------------------------------------------------------------




def _resolve_sqlite_conn_str(raw: str) -> str:
    """Return a SQLite connection 字符串 ready for use with ``SqliteSaver``.

    SQLite special strings (``":内存:"`` and ``文件:`` URIs) are returned
    unchanged.  Plain filesystem paths — relative or absolute — are resolved
    to an absolute 字符串 via :func:`resolve_path`.
    """
    if raw == ":memory:" or raw.startswith("file:"):
        return raw
    return str(resolve_path(raw))


@contextlib.contextmanager
def _sync_checkpointer_cm(config: CheckpointerConfig) -> Iterator[Checkpointer]:
    """Context manager that creates and tears 下 a sync checkpointer.

    Returns a configured ``Checkpointer`` instance. Resource cleanup for any
    underlying connections or pools is handled by higher-level helpers in
    this 模块 (such as the singleton factory or context manager); this
    函数 does not 返回 a separate cleanup callback.
    """
    if config.type == "memory":
        from langgraph.checkpoint.memory import InMemorySaver

        logger.info("Checkpointer: using InMemorySaver (in-process, not persistent)")
        yield InMemorySaver()
        return

    if config.type == "sqlite":
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
        except ImportError as exc:
            raise ImportError(SQLITE_INSTALL) from exc

        conn_str = _resolve_sqlite_conn_str(config.connection_string or "store.db")
        with SqliteSaver.from_conn_string(conn_str) as saver:
            saver.setup()
            logger.info("Checkpointer: using SqliteSaver (%s)", conn_str)
            yield saver
        return

    if config.type == "postgres":
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
        except ImportError as exc:
            raise ImportError(POSTGRES_INSTALL) from exc

        if not config.connection_string:
            raise ValueError(POSTGRES_CONN_REQUIRED)

        with PostgresSaver.from_conn_string(config.connection_string) as saver:
            saver.setup()
            logger.info("Checkpointer: using PostgresSaver")
            yield saver
        return

    raise ValueError(f"Unknown checkpointer type: {config.type!r}")


#    ---------------------------------------------------------------------------


#    Sync singleton


#    ---------------------------------------------------------------------------



_checkpointer: Checkpointer | None = None
_checkpointer_ctx = None  #    打开 context manager keeping the connection alive




def get_checkpointer() -> Checkpointer:
    """Return the global sync checkpointer singleton, creating it on 第一 call.

    Returns an ``InMemorySaver`` when no checkpointer is configured in *配置.yaml*.

    Raises:
        ImportError: If the required 包 for the configured 后端 is not installed.
        ValueError: If ``connection_string`` is missing for a 后端 that requires it.
    """
    global _checkpointer, _checkpointer_ctx

    if _checkpointer is not None:
        return _checkpointer

    #    Ensure app 配置 is loaded before checking checkpointer 配置


    #    This prevents returning InMemorySaver when 配置.yaml actually has a checkpointer section


    #    but hasn't been loaded yet


    from deerflow.config.app_config import _app_config
    from deerflow.config.checkpointer_config import get_checkpointer_config

    if _app_config is None:
        #    Only load 配置 如果 it hasn't been initialized yet


        #    In tests, 配置 may be 集合 directly via set_checkpointer_config()


        try:
            get_app_config()
        except FileNotFoundError:
            #    In 测试 environments without 配置.yaml, this is expected


            #    Tests will 集合 配置 directly via set_checkpointer_config()


            pass

    config = get_checkpointer_config()
    if config is None:
        from langgraph.checkpoint.memory import InMemorySaver

        logger.info("Checkpointer: using InMemorySaver (in-process, not persistent)")
        _checkpointer = InMemorySaver()
        return _checkpointer

    _checkpointer_ctx = _sync_checkpointer_cm(config)
    _checkpointer = _checkpointer_ctx.__enter__()

    return _checkpointer


def reset_checkpointer() -> None:
    """Reset the sync singleton, forcing recreation on the 下一个 call.

    Closes any 打开 后端 connections and clears the cached instance.
    Useful in tests or after a configuration change.
    """
    global _checkpointer, _checkpointer_ctx
    if _checkpointer_ctx is not None:
        try:
            _checkpointer_ctx.__exit__(None, None, None)
        except Exception:
            logger.warning("Error during checkpointer cleanup", exc_info=True)
        _checkpointer_ctx = None
    _checkpointer = None


#    ---------------------------------------------------------------------------


#    Sync context manager


#    ---------------------------------------------------------------------------




@contextlib.contextmanager
def checkpointer_context() -> Iterator[Checkpointer]:
    """Sync context manager that yields a checkpointer and cleans 上 on exit.

    Unlike :func:`get_checkpointer`, this does **not** 缓存 the instance —
    each ``with`` block creates and destroys its own connection.  Use it in
    CLI scripts or tests where you want deterministic cleanup::

        with checkpointer_context() as cp:
            graph.invoke(输入, 配置={"configurable": {"thread_id": "1"}})

    Yields an ``InMemorySaver`` when no checkpointer is configured in *配置.yaml*.
    """

    config = get_app_config()
    if config.checkpointer is None:
        from langgraph.checkpoint.memory import InMemorySaver

        yield InMemorySaver()
        return

    with _sync_checkpointer_cm(config.checkpointer) as saver:
        yield saver
