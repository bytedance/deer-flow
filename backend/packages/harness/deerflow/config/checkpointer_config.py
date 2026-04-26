"""
LangGraph检查点（Checkpointer）配置模块

====================
设计思路说明
====================

**核心职责**：
1. 定义检查点配置模型
2. 管理全局检查点配置实例
3. 支持多种后端存储类型

**什么是检查点（Checkpointer）**：
- LangGraph的状态持久化机制
- 保存对话历史和执行状态
- 支持中断后恢复执行
- 实现长时间运行的任务

**为什么需要检查点**：
- 对话可能跨越多次请求
- 执行可能被中断（网络、超时）
- 需要保存中间状态用于调试
- 支持人工干预后继续

**后端类型选择**：
- memory: 仅用于测试，重启丢失
- sqlite: 轻量级持久化，适合单机部署
- postgres: 生产级持久化，支持分布式

**为什么使用全局变量**：
- 检查点配置是全局单例
- 多个模块需要访问同一配置
- 避免重复加载
"""

from typing import Literal

from pydantic import BaseModel, Field

CheckpointerType = Literal["memory", "sqlite", "postgres"]


class CheckpointerConfig(BaseModel):
    """LangGraph状态持久化检查点配置

    **配置字段说明**：
    - type: 后端存储类型（memory/sqlite/postgres）
    - connection_string: 连接字符串（sqlite文件路径或PostgreSQL DSN）

    **各类型特点**：

    **memory**：
    - 优点：最快，无需外部依赖
    - 缺点：重启丢失，不适合生产
    - 适用：单元测试、快速原型

    **sqlite**：
    - 优点：轻量级持久化，无需服务器
    - 缺点：不支持分布式写入
    - 适用：单机部署、开发环境

    **postgres**：
    - 优点：生产级、支持分布式、ACID保证
    - 缺点：需要额外部署PostgreSQL
    - 适用：生产环境、多实例部署
    """

    type: CheckpointerType = Field(
        description="Checkpointer backend type. "
        "'memory' is in-process only (lost on restart). "
        "'sqlite' persists to a local file (requires langgraph-checkpoint-sqlite). "
        "'postgres' persists to PostgreSQL (requires langgraph-checkpoint-postgres)."
    )
    connection_string: str | None = Field(
        default=None,
        description="Connection string for sqlite (file path) or postgres (DSN). "
        "Required for sqlite and postgres types. "
        "For sqlite, use a file path like '.deer-flow/checkpoints.db' or ':memory:' for in-memory. "
        "For postgres, use a DSN like 'postgresql://user:pass@localhost:5432/db'.",
    )


# Global configuration instance — None means no checkpointer is configured.
_checkpointer_config: CheckpointerConfig | None = None


def get_checkpointer_config() -> CheckpointerConfig | None:
    """获取当前检查点配置

    **返回值说明**：
    - CheckpointerConfig: 已配置的检查点
    - None: 未配置检查点（状态不持久化）

    **使用场景**：
    - 初始化检查点提供器
    - 验证是否启用持久化
    - 获取连接字符串

    Returns:
        检查点配置实例，未配置返回None
    """
    return _checkpointer_config


def set_checkpointer_config(config: CheckpointerConfig | None) -> None:
    """设置检查点配置

    **使用场景**：
    - 从配置文件加载后设置
    - 测试时注入mock配置
    - 运行时切换后端

    Args:
        config: 要设置的配置，None表示禁用检查点
    """
    global _checkpointer_config
    _checkpointer_config = config


def load_checkpointer_config_from_dict(config_dict: dict) -> None:
    """从字典加载检查点配置

    **使用场景**：
    - 从YAML配置文件解析后加载
    - 动态配置更新

    **为什么单独设置而不是返回实例**：
    - 全局配置需要统一管理
    - 与其他配置模块保持一致
    - 简化调用代码

    Args:
        config_dict: 包含检查点配置的字典
    """
    global _checkpointer_config
    _checkpointer_config = CheckpointerConfig(**config_dict)
