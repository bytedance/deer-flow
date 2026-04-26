"""
流式桥接（Stream Bridge）配置模块

====================
设计思路说明
====================

**核心职责**：
1. 定义流式桥接后端配置
2. 连接Agent工作进程与SSE端点
3. 支持多种消息传递后端

**什么是流式桥接（Stream Bridge）**：
- 连接Agent执行和SSE流式响应的桥梁
- 异步传递执行事件
- 支持多进程部署
- 实现实时反馈

**为什么需要流式桥接**：
- Agent在后台工作进程中执行
- SSE端点在API进程中
- 需要跨进程通信机制
- 实时推送执行进度

**后端类型**：
- memory: 进程内asyncio.Queue（单进程）
- redis: Redis Streams（多进程，计划中）

**为什么queue_maxsize很重要**：
- 限制内存使用
- 防止慢消费者导致内存爆炸
- 背压机制
"""

"""Configuration for stream bridge."""

from typing import Literal

from pydantic import BaseModel, Field

StreamBridgeType = Literal["memory", "redis"]


class StreamBridgeConfig(BaseModel):
    """流式桥接配置（连接Agent工作进程与SSE端点）

    **type字段**：
    - memory: 使用进程内asyncio.Queue
      - 优点：快速、无需外部依赖
      - 缺点：仅支持单进程
    - redis: 使用Redis Streams
      - 优点：支持多进程、持久化
      - 缺点：需要Redis依赖（计划中）

    **redis_url字段**：
    - Redis连接字符串
    - 格式：redis://localhost:6379/0
    - 仅在type=redis时使用

    **queue_maxsize字段**：
    - 每个运行缓冲的最大事件数
    - 默认256个事件
    - 达到上限时阻塞生产者
    - 防止慢消费者导致内存问题

    **工作原理**：
    1. Agent工作进程产生事件
    2. 事件写入桥接队列
    3. SSE端点从队列读取
    4. 推送给客户端
    """

    type: StreamBridgeType = Field(
        default="memory",
        description="Stream bridge backend type. 'memory' uses in-process asyncio.Queue (single-process only). 'redis' uses Redis Streams (planned for Phase 2, not yet implemented).",
    )
    redis_url: str | None = Field(
        default=None,
        description="Redis URL for the redis stream bridge type. Example: 'redis://localhost:6379/0'.",
    )
    queue_maxsize: int = Field(
        default=256,
        description="Maximum number of events buffered per run in the memory bridge.",
    )


# Global configuration instance — None means no stream bridge is configured
# (falls back to memory with defaults).
_stream_bridge_config: StreamBridgeConfig | None = None


def get_stream_bridge_config() -> StreamBridgeConfig | None:
    """获取当前流式桥接配置

    **返回值说明**：
    - StreamBridgeConfig: 已配置的桥接
    - None: 未配置（使用memory默认值）

    Returns:
        流式桥接配置实例，未配置返回None
    """
    return _stream_bridge_config


def set_stream_bridge_config(config: StreamBridgeConfig | None) -> None:
    """设置流式桥接配置

    **使用场景**：
    - 从配置文件加载后设置
    - 测试时注入mock配置
    - 运行时切换后端

    Args:
        config: 要设置的配置，None表示使用默认值
    """
    global _stream_bridge_config
    _stream_bridge_config = config


def load_stream_bridge_config_from_dict(config_dict: dict) -> None:
    """从字典加载流式桥接配置

    **使用场景**：
    - 从YAML配置文件解析后加载
    - 动态配置更新

    Args:
        config_dict: 包含流式桥接配置的字典
    """
    global _stream_bridge_config
    _stream_bridge_config = StreamBridgeConfig(**config_dict)
