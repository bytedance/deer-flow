"""
消息总线（MessageBus）——异步发布/订阅中心，解耦IM频道与代理分发器

===================
设计思路说明
===================

**为什么需要消息总线**：
1. **解耦架构**：IM频道不需要知道代理分发器的存在，反之亦然
2. **统一接口**：多个IM平台（飞书、Slack、Telegram）通过统一的消息格式通信
3. **异步通信**：使用asyncio.Queue实现非阻塞的消息传递
4. **可扩展性**：易于添加新的消息生产者或消费者

**核心设计模式**：
- 发布-订阅模式：频道发布入站消息，订阅出站消息
- 异步队列：使用asyncio.Queue实现消息缓冲
- 回调机制：出站消息通过异步回调分发给订阅者

**为什么这样设计**：
1. **入站队列**：使用队列确保消息按顺序处理，支持背压控制
2. **出站回调**：使用列表支持多个订阅者，便于扩展（如日志、监控）
3. **类型安全**：使用dataclass定义消息结构，配合类型注解提高代码可维护性
4. **错误隔离**：每个回调的异常不会影响其他回调的执行
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Message types（消息类型定义）
# ---------------------------------------------------------------------------


class InboundMessageType(StrEnum):
    """来自IM频道的入站消息类型

    ===================
    设计思路说明
    ===================

    **为什么区分消息类型**：
    - 普通聊天消息（CHAT）：需要代理处理并生成响应
    - 命令消息（COMMAND）：由频道管理器直接处理的系统命令

    **使用场景**：
    - CHAT：用户与AI的对话、提问等
    - COMMAND：如/new、/status等系统控制命令
    """

    CHAT = "chat"
    COMMAND = "command"


@dataclass
class InboundMessage:
    """从IM频道发往代理分发器的入站消息

    ===================
    设计思路说明
    ===================

    **核心职责**：
    封装来自IM平台的消息，提供统一的格式供后续处理使用。

    **为什么这样设计**：
    1. **平台无关**：使用统一的字段名，屏蔽不同平台的差异
    2. **线程支持**：通过thread_ts和topic_id支持线程化对话
    3. **可扩展性**：使用metadata字段存储平台特定的额外信息

    **topic_id的作用**：
    - topic_id用于将IM平台的对话映射到DeerFlow线程
    - 相同topic_id的消息会复用同一个DeerFlow线程（保持上下文）
    - topic_id为None时，每条消息创建新线程（一次性问答）

    Attributes:
        channel_name: 源频道名称（如"feishu"、"slack"）
        chat_id: 平台特定的对话/会话标识符
        user_id: 平台特定的用户标识符
        text: 消息文本内容
        msg_type: 消息类型（普通聊天或命令）
        thread_ts: 可选的平台线程标识符（用于线程回复）
        topic_id: 会话主题标识符，用于映射到DeerFlow线程。
            同一chat_id内共享相同topic_id的消息会复用同一DeerFlow线程。
            当为None时，每条消息创建新线程（一次性问答）。
        files: 可选的文件附件列表（平台特定的字典格式）
        metadata: 来自频道的任意额外数据
        created_at: 消息创建时的Unix时间戳
    """

    channel_name: str
    chat_id: str
    user_id: str
    text: str
    msg_type: InboundMessageType = InboundMessageType.CHAT
    thread_ts: str | None = None
    topic_id: str | None = None
    files: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class ResolvedAttachment:
    """已解析到主机文件系统路径的文件附件，准备好上传

    ===================
    设计思路说明
    ===================

    **为什么需要这个类**：
    1. **路径转换**：将虚拟路径（/mnt/user-data/...）转换为实际主机路径
    2. **元数据收集**：预先收集文件大小、MIME类型等信息，便于上传时使用
    3. **安全检查**：确保文件在允许的目录内，防止路径遍历攻击

    **virtual_path与actual_path的区别**：
    - virtual_path：DeerFlow沙箱内的路径，用于显示给用户
    - actual_path：主机文件系统上的实际路径，用于文件上传

    **为什么标记is_image**：
    - 不同IM平台对图片的处理方式不同（可能预览、压缩等）
    - 便于平台根据文件类型选择合适的上传策略

    Attributes:
        virtual_path: 原始虚拟路径（如 /mnt/user-data/outputs/report.pdf）
        actual_path: 解析后的主机文件系统路径
        filename: 文件的基本名称
        mime_type: MIME类型（如 "application/pdf"）
        size: 文件大小（字节）
        is_image: 是否为图片类型（image/* MIME类型），
            平台可能对图片有特殊处理
    """

    virtual_path: str
    actual_path: Path
    filename: str
    mime_type: str
    size: int
    is_image: bool


@dataclass
class OutboundMessage:
    """从代理分发器发回频道的出站消息

    ===================
    设计思路说明
    ===================

    **核心职责**：
    封装AI代理的响应，准备发送到IM平台。

    **为什么这样设计**：
    1. **路由支持**：channel_name和chat_id用于消息路由
    2. **流式响应**：is_final字段支持流式响应的分段发送
    3. **文件附件**：artifacts（路径）和attachments（已解析）分离，
       支持文件上传和文本回退
    4. **线程关联**：thread_ts关联到原始消息线程

    **artifacts vs attachments**：
    - artifacts：代理生成的文件路径列表（虚拟路径）
    - attachments：已解析准备上传的附件（包含实际路径和元数据）

    **is_final的作用**：
    - 流式响应时，is_final=False表示中间更新
    - is_final=True表示最终响应，触发文件上传

    Attributes:
        channel_name: 目标频道名称（用于路由）
        chat_id: 目标对话/会话标识符
        thread_id: 生成此响应的DeerFlow线程ID
        text: 响应文本内容
        artifacts: 代理生成的文件路径列表（虚拟路径）
        is_final: 是否为响应流中的最终消息
        thread_ts: 可选的平台线程标识符，用于线程回复
        metadata: 任意额外数据
        created_at: Unix时间戳
    """

    channel_name: str
    chat_id: str
    thread_id: str
    text: str
    artifacts: list[str] = field(default_factory=list)
    attachments: list[ResolvedAttachment] = field(default_factory=list)
    is_final: bool = True
    thread_ts: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# MessageBus（消息总线实现）
# ---------------------------------------------------------------------------

# 出站消息回调的类型别名
# 定义为协程函数，支持异步处理
OutboundCallback = Callable[[OutboundMessage], Coroutine[Any, Any, None]]


class MessageBus:
    """连接频道与代理分发器的异步发布/订阅中心

    ===================
    设计思路说明
    ===================

    **核心职责**：
    1. 接收入站消息：IM频道发布消息到队列，分发器消费
    2. 分发出站消息：分发器发布消息，频道通过回调接收

    **为什么这样设计**：
    1. **解耦架构**：频道和分发器互不依赖，只依赖消息总线接口
    2. **异步处理**：使用asyncio.Queue实现非阻塞的消息传递
    3. **多订阅者支持**：出站消息支持多个监听器（便于日志、监控等）
    4. **错误隔离**：单个回调的异常不会影响其他回调

    **入站流程**：
    IM频道 → publish_inbound() → _inbound_queue → 分发器

    **出站流程**：
    分发器 → publish_outbound() → _outbound_listeners → IM频道

    **为什么使用Queue而非直接调用**：
    - 支持背压控制：队列满时自动阻塞
    - 顺序保证：消息按FIFO顺序处理
    - 异步安全：多个协程可安全地并发访问
    """

    def __init__(self) -> None:
        # 入站消息队列：使用asyncio.Queue支持异步生产者-消费者模式
        # 为什么用队列：支持背压控制、保证顺序、异步安全
        self._inbound_queue: asyncio.Queue[InboundMessage] = asyncio.Queue()
        # 出站消息监听器列表：支持多个订阅者
        # 为什么用列表：简单高效，遍历调用所有回调
        self._outbound_listeners: list[OutboundCallback] = []

    # -- inbound（入站消息处理）-------------------------------------------

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """将来自频道的入站消息加入队列

        **参数说明**：
        - msg: 入站消息对象，包含频道、用户、文本等信息

        **为什么这样设计**：
        - 异步方法：避免阻塞调用者（IM频道）
        - 队列缓冲：允许生产者和消费者以不同速度运行
        - 详细日志：记录队列大小，便于监控和调试

        **调用场景**：
        IM频道收到用户消息后，调用此方法将消息放入队列供分发器处理
        """
        await self._inbound_queue.put(msg)
        logger.info(
            "[Bus] inbound enqueued: channel=%s, chat_id=%s, type=%s, queue_size=%d",
            msg.channel_name,
            msg.chat_id,
            msg.msg_type.value,
            self._inbound_queue.qsize(),
        )

    async def get_inbound(self) -> InboundMessage:
        """阻塞等待直到有下一条入站消息可用

        **返回值**：
        - InboundMessage: 从队列中取出的入站消息

        **为什么这样设计**：
        - 异步等待：使用asyncio.Queue的get方法，自动处理等待
        - 阻塞语义：无消息时挂起协程，有消息时自动唤醒
        - FIFO保证：按消息到达顺序返回

        **调用场景**：
        分发器在主循环中调用此方法获取待处理的消息
        """
        return await self._inbound_queue.get()

    @property
    def inbound_queue(self) -> asyncio.Queue[InboundMessage]:
        """获取入站消息队列的只读访问

        **为什么提供此属性**：
        - 允许外部检查队列状态（如大小）
        - 保持封装性：返回内部队列引用，但不允许替换

        **使用场景**：
        监控、健康检查等需要查看队列状态的场景
        """
        return self._inbound_queue

    # -- outbound（出站消息处理）------------------------------------------

    def subscribe_outbound(self, callback: OutboundCallback) -> None:
        """注册出站消息的异步回调

        **参数说明**：
        - callback: 异步回调函数，接收OutboundMessage参数

        **为什么这样设计**：
        - 订阅模式：支持多个监听器同时接收出站消息
        - 简单注册：直接添加到列表，无需复杂的管理逻辑
        - 类型安全：使用类型别名确保回调签名正确

        **使用场景**：
        IM频道启动时注册回调，接收发往该频道的消息

        **注意**：
        同一回调多次注册会收到多次通知，应避免重复注册
        """
        self._outbound_listeners.append(callback)

    def unsubscribe_outbound(self, callback: OutboundCallback) -> None:
        """移除之前注册的出站消息回调

        **参数说明**：
        - callback: 要移除的回调函数

        **为什么这样设计**：
        - 身份比较：使用is而非==，确保移除正确的对象
        - 创建新列表：避免在遍历时修改列表的问题

        **使用场景**：
        IM频道停止时取消订阅，防止内存泄漏

        **注意**：
        如果回调未注册，此操作无效果（静默忽略）
        """
        self._outbound_listeners = [cb for cb in self._outbound_listeners if cb is not callback]

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """将出站消息分发给所有已注册的监听器

        **参数说明**：
        - msg: 出站消息对象，包含响应文本、附件等

        **为什么这样设计**：
        - 顺序调用：按注册顺序依次调用回调
        - 异常隔离：单个回调失败不影响其他回调
        - 异步等待：等待每个回调完成后再继续

        **错误处理**：
        捕获回调中的异常并记录日志，但不中断其他回调的执行

        **使用场景**：
        分发器处理完消息后，调用此方法将响应发送回IM频道
        """
        logger.info(
            "[Bus] outbound dispatching: channel=%s, chat_id=%s, listeners=%d, text_len=%d",
            msg.channel_name,
            msg.chat_id,
            len(self._outbound_listeners),
            len(msg.text),
        )
        for callback in self._outbound_listeners:
            try:
                await callback(msg)
            except Exception:
                logger.exception("Error in outbound callback for channel=%s", msg.channel_name)
