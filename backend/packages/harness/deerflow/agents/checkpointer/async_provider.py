"""
异步检查点工厂

===================
设计思路说明
===================

**为什么需要异步检查点**：
1. **非阻塞操作**：在异步服务器中不阻塞事件循环
2. **资源管理**：提供上下文管理器，确保资源正确清理
3. **长运行服务**：适合FastAPI等长运行异步服务器

**核心设计模式**：
- 异步上下文管理器：使用@contextlib.asynccontextmanager
- 资源生命周期管理：进入时创建，退出时清理
- 多后端支持：memory、sqlite、postgres

**为什么需要这个模块**：
- FastAPI lifespan需要异步上下文管理器
- 与同步provider分离，避免混淆
- 提供类型安全的异步API

**支持的后端**：
- memory：内存存储，适合测试和开发
- sqlite：文件持久化，适合单机部署
- postgres：数据库持久化，适合生产环境

**使用示例**（如FastAPI lifespan）::

    from deerflow.agents.checkpointer.async_provider import make_checkpointer

    async with make_checkpointer() as checkpointer:
        app.state.checkpointer = checkpointer  # 未配置时为InMemorySaver

**同步使用场景**：
参见 :mod:`deerflow.agents.checkpointer.provider`
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator

from langgraph.types import Checkpointer

from deerflow.agents.checkpointer.provider import (
    POSTGRES_CONN_REQUIRED,
    POSTGRES_INSTALL,
    SQLITE_INSTALL,
)
from deerflow.config.app_config import get_app_config
from deerflow.runtime.store._sqlite_utils import ensure_sqlite_parent_dir, resolve_sqlite_conn_str

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Async factory（异步工厂）
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def _async_checkpointer(config) -> AsyncIterator[Checkpointer]:
    """创建和销毁异步检查点的上下文管理器

    **为什么使用上下文管理器**：
    - 确保资源正确清理
    - 自动处理连接生命周期
    - 支持异步with语句

    **为什么分后端处理**：
    - 每种后端有不同的初始化方式
    - 错误消息需要针对后端定制
    - 便于添加新的后端支持

    **参数说明**：
        config: 检查点配置对象

    **异常**：
        ImportError: 所需后端包未安装
        ValueError: 配置错误（如postgres缺少connection_string）
    """
    # Memory后端：最简单的实现
    if config.type == "memory":
        from langgraph.checkpoint.memory import InMemorySaver

        yield InMemorySaver()
        return

    # SQLite后端：单机持久化
    if config.type == "sqlite":
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        except ImportError as exc:
            raise ImportError(SQLITE_INSTALL) from exc

        conn_str = resolve_sqlite_conn_str(config.connection_string or "store.db")
        ensure_sqlite_parent_dir(conn_str)
        async with AsyncSqliteSaver.from_conn_string(conn_str) as saver:
            await saver.setup()
            yield saver
        return

    # PostgreSQL后端：生产级持久化
    if config.type == "postgres":
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        except ImportError as exc:
            raise ImportError(POSTGRES_INSTALL) from exc

        if not config.connection_string:
            raise ValueError(POSTGRES_CONN_REQUIRED)

        async with AsyncPostgresSaver.from_conn_string(config.connection_string) as saver:
            await saver.setup()
            yield saver
        return

    raise ValueError(f"Unknown checkpointer type: {config.type!r}")


# ---------------------------------------------------------------------------
# Public async context manager（公共异步上下文管理器）
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def make_checkpointer() -> AsyncIterator[Checkpointer]:
    """异步上下文管理器，在调用者生命周期内yield检查点

    **资源管理**：
    - 进入时打开资源
    - 退出时关闭资源
    - 无全局状态

    **为什么这样设计**：
    - 每个with块创建独立的连接
    - 明确的资源生命周期
    - 适合FastAPI lifespan模式

    **默认行为**：
    当config.yaml中未配置检查点时，yield InMemorySaver

    **使用示例**::

        async with make_checkpointer() as checkpointer:
            app.state.checkpointer = checkpointer

    **返回值**：
        Checkpointer实例（根据配置可能是InMemorySaver、AsyncSqliteSaver或AsyncPostgresSaver）
    """
    config = get_app_config()

    # 未配置时使用InMemorySaver
    if config.checkpointer is None:
        from langgraph.checkpoint.memory import InMemorySaver

        yield InMemorySaver()
        return

    # 使用配置的后端
    async with _async_checkpointer(config.checkpointer) as saver:
        yield saver
