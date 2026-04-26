"""同步检查点工厂

===================
设计思路说明
===================

**为什么需要同步检查点**：
1. **CLI工具**：命令行工具通常使用同步API
2. **简单脚本**：简单的自动化脚本不需要异步复杂性
3. **测试便利**：单元测试中同步代码更容易编写
4. **向后兼容**：一些旧代码可能依赖同步API

**核心设计模式**：
- 单例模式：get_checkpointer()返回全局单例
- 上下文管理器：checkpointer_context()提供独立连接
- 工厂模式：根据配置创建不同的后端实例

**为什么需要两种API**：
- **单例模式**：适合长运行进程，连接复用，性能更好
- **上下文管理器**：适合短期任务，资源明确释放

**支持的后端**：
- memory：内存存储，适合测试
- sqlite：文件持久化，适合单机部署
- postgres：数据库持久化，适合生产环境

**使用方式**::

    from deerflow.agents.checkpointer.provider import get_checkpointer, checkpointer_context

    # 单例模式 — 跨调用复用，进程退出时关闭
    cp = get_checkpointer()

    # 一次性使用 — 独立连接，块退出时关闭
    with checkpointer_context() as cp:
        graph.invoke(input, config={"configurable": {"thread_id": "1"}})
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator

from langgraph.types import Checkpointer

from deerflow.config.app_config import get_app_config
from deerflow.config.checkpointer_config import CheckpointerConfig
from deerflow.runtime.store._sqlite_utils import resolve_sqlite_conn_str

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 错误消息常量 — 同时被async_provider导入
# ---------------------------------------------------------------------------

# 为什么定义这些常量：
# - 避免重复的错误消息
# - 便于统一维护和更新
# - 确保同步和异步API的错误消息一致

SQLITE_INSTALL = "langgraph-checkpoint-sqlite is required for the SQLite checkpointer. Install it with: uv add langgraph-checkpoint-sqlite"
POSTGRES_INSTALL = "langgraph-checkpoint-postgres is required for the PostgreSQL checkpointer. Install it with: uv add langgraph-checkpoint-postgres psycopg[binary] psycopg-pool"
POSTGRES_CONN_REQUIRED = "checkpointer.connection_string is required for the postgres backend"

# ---------------------------------------------------------------------------
# 同步工厂函数
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _sync_checkpointer_cm(config: CheckpointerConfig) -> Iterator[Checkpointer]:
    """创建和销毁同步检查点的上下文管理器

    **为什么使用上下文管理器**：
    - 确保资源正确清理
    - 自动处理连接生命周期
    - 支持with语句

    **为什么分后端处理**：
    - 每种后端有不同的初始化方式
    - 错误消息需要针对后端定制
    - 便于添加新的后端支持

    **参数说明**：
        config: 检查点配置对象

    **异常**：
        ImportError: 所需后端包未安装
        ValueError: 配置错误（如postgres缺少connection_string）

    **资源管理**：
    任何底层连接或池的资源清理由此模块的更高级辅助函数处理
    （如单例工厂或上下文管理器）；此函数不返回单独的清理回调。
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

        conn_str = resolve_sqlite_conn_str(config.connection_string or "store.db")
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


# ---------------------------------------------------------------------------
# 同步单例模式
# ---------------------------------------------------------------------------

_checkpointer: Checkpointer | None = None
_checkpointer_ctx = None  # 保持连接活跃的开放上下文管理器

# 为什么使用单例模式：
# - 连接复用：避免重复创建连接的开销
# - 状态共享：整个进程共享同一个检查点实例
# - 延迟初始化：只在首次使用时创建


def get_checkpointer() -> Checkpointer:
    """返回全局同步检查点单例，首次调用时创建

    **为什么使用单例模式**：
    - **性能优化**：连接复用，避免重复创建
    - **资源节约**：减少数据库连接数量
    - **状态一致**：整个进程使用同一个检查点实例

    **配置未设置时的行为**：
    当config.yaml中未配置检查点时，返回InMemorySaver

    **异常**：
        ImportError: 配置的后端所需包未安装
        ValueError: 需要connection_string的后端缺少该配置

    **懒加载机制**：
    应用配置在检查检查点配置之前加载，防止当config.yaml实际有检查点
    部分但尚未加载时返回InMemorySaver
    """
    global _checkpointer, _checkpointer_ctx

    if _checkpointer is not None:
        return _checkpointer

    # Ensure app config is loaded before checking checkpointer config
    # This prevents returning InMemorySaver when config.yaml actually has a checkpointer section
    # but hasn't been loaded yet
    from deerflow.config.app_config import _app_config
    from deerflow.config.checkpointer_config import get_checkpointer_config

    config = get_checkpointer_config()

    if config is None and _app_config is None:
        # Only load app config lazily when neither the app config nor an explicit
        # checkpointer config has been initialized yet. This keeps tests that
        # intentionally set the global checkpointer config isolated from any
        # ambient config.yaml on disk.
        try:
            get_app_config()
        except FileNotFoundError:
            # In test environments without config.yaml, this is expected.
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
    """重置同步单例，强制下次调用时重新创建

    **为什么需要重置功能**：
    - **测试隔离**：每个测试开始前重置状态
    - **配置变更**：配置更改后需要重新初始化
    - **错误恢复**：检查点出错后可以重新创建

    **清理机制**：
    关闭任何打开的后端连接并清除缓存的实例

    **使用场景**：
    - 单元测试中的setup/teardown
    - 配置文件更改后
    - 需要重新连接数据库的场景
    """
    global _checkpointer, _checkpointer_ctx
    if _checkpointer_ctx is not None:
        try:
            _checkpointer_ctx.__exit__(None, None, None)
        except Exception:
            logger.warning("Error during checkpointer cleanup", exc_info=True)
        _checkpointer_ctx = None
    _checkpointer = None


# ---------------------------------------------------------------------------
# 同步上下文管理器
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def checkpointer_context() -> Iterator[Checkpointer]:
    """同步上下文管理器，yield检查点并在退出时清理

    **为什么需要上下文管理器**：
    - **确定性清理**：with块结束时自动清理资源
    - **独立连接**：每次调用创建新连接，避免状态污染
    - **测试友好**：测试中可以精确控制资源生命周期

    **与单例模式的区别**：
    与:func:`get_checkpointer`不同，这**不**缓存实例 —
    每个``with``块创建并销毁自己的连接

    **使用场景**：
    在CLI脚本或测试中使用，当你需要确定性的清理时::

        with checkpointer_context() as cp:
            graph.invoke(input, config={"configurable": {"thread_id": "1"}})

    **配置未设置时的行为**：
    当config.yaml中未配置检查点时，yield InMemorySaver
    """

    config = get_app_config()
    if config.checkpointer is None:
        from langgraph.checkpoint.memory import InMemorySaver

        yield InMemorySaver()
        return

    with _sync_checkpointer_cm(config.checkpointer) as saver:
        yield saver
