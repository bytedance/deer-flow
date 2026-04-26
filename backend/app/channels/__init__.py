"""
IM（即时通讯）频道集成模块 - DeerFlow

===================
设计思路说明
===================

**核心功能**：
提供可插拔的频道系统，将外部消息平台（飞书/Lark、Slack、Telegram）
连接到DeerFlow代理。

**架构设计**：
1. **ChannelManager**：核心调度器
   - 使用langgraph-sdk与底层LangGraph Server通信
   - 管理消息的生命周期（接收、处理、回复）
   - 维护IM对话到DeerFlow线程的映射

2. **Channel基类**：抽象接口
   - 定义统一的频道接口
   - 支持多种IM平台实现

3. **MessageBus**：消息总线
   - 解耦消息的生产者和消费者
   - 支持异步消息传递

**为什么这样设计**：
- **可扩展性**：添加新平台只需实现Channel接口
- **解耦**：平台特定逻辑与核心业务分离
- **统一管理**：通过ChannelManager统一处理所有平台

**使用流程**：
1. 配置IM平台凭据（app_id、app_secret等）
2. 创建对应的Channel实例
3. ChannelManager接收并分发消息
4. DeerFlow Agent处理消息
5. 结果通过原Channel返回给用户
"""

from app.channels.base import Channel
from app.channels.message_bus import InboundMessage, MessageBus, OutboundMessage

__all__ = [
    "Channel",           # 抽象基类：所有频道实现的基础
    "InboundMessage",    # 入站消息：从IM平台到DeerFlow
    "MessageBus",        # 消息总线：异步消息传递
    "OutboundMessage",   # 出站消息：从DeerFlow到IM平台
]
