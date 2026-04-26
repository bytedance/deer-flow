"""
IM（即时通讯）频道的抽象基类

===================
设计思路说明
===================

**为什么需要抽象基类**：
1. 多个IM平台（飞书、Slack、Telegram等）需要统一的接口
2. 便于添加新的IM平台支持，只需实现基类定义的方法
3. 解耦具体平台实现与核心业务逻辑

**核心设计模式**：
- 模板方法模式：定义了消息处理的生命周期框架
- 发布-订阅模式：通过MessageBus进行消息传递
- 策略模式：不同平台实现不同的发送策略

**为什么这样设计**：
- 使用ABC强制子类实现关键方法，确保接口一致性
- 异步设计：所有I/O操作都是异步的，提高并发性能
- 消息总线集成：通过MessageBus解耦消息的生产和消费
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from app.channels.message_bus import InboundMessage, InboundMessageType, MessageBus, OutboundMessage, ResolvedAttachment

logger = logging.getLogger(__name__)


class Channel(ABC):
    """
    IM频道实现的抽象基类

    ===================
    设计思路说明
    ===================

    **核心职责**：
    每个频道连接到一个外部消息平台并负责：
    1. 接收消息，将其包装为InboundMessage，发布到消息总线
    2. 订阅出站消息，并将回复发送回平台

    **为什么这样设计**：
    - 统一接口：所有平台必须实现相同的方法签名
    - 生命周期管理：清晰的start/stop生命周期
    - 消息路由：通过channel_name进行消息过滤

    **子类必须实现的方法**：
    - start(): 启动频道，开始监听消息
    - stop(): 停止频道，清理资源
    - send(): 发送消息到外部平台

    **可选重写的方法**：
    - send_file(): 上传文件附件（默认返回False，表示不支持）
    """

    def __init__(self, name: str, bus: MessageBus, config: dict[str, Any]) -> None:
        """
        初始化频道

        **参数说明**：
        - name: 频道名称（如"feishu"、"slack"、"telegram"）
        - bus: 消息总线，用于接收和发送消息
        - config: 频道配置（API密钥、Webhook URL等）

        **为什么这样设计**：
        - name用于消息路由，确保消息发送到正确的频道
        - bus作为依赖注入，便于测试和解耦
        - config使用字典，支持不同平台的差异化配置
        """
        self.name = name
        self.bus = bus
        self.config = config
        self._running = False

    @property
    def is_running(self) -> bool:
        """
        检查频道是否正在运行

        **为什么使用property**：
        - 提供类似属性的访问方式，隐藏内部状态
        - 便于扩展（未来可以添加更复杂的运行状态判断）
        """
        return self._running

    # -- 生命周期管理 ---------------------------------------------------------

    @abstractmethod
    async def start(self) -> None:
        """
        启动频道，开始监听来自外部平台的消息

        **为什么这样设计**：
        - 异步方法：避免阻塞主事件循环
        - 抽象方法：强制子类实现自己的启动逻辑
        - 每个平台的启动方式不同（WebSocket、轮询、Webhook等）

        **子类实现要点**：
        - 建立与平台的连接
        - 订阅消息总线的出站消息
        - 设置消息接收回调
        - 更新self._running状态
        """

    @abstractmethod
    async def stop(self) -> None:
        """
        优雅地停止频道

        **为什么这样设计**：
        - 确保资源正确释放（连接、线程、定时器等）
        - 允许正在处理的消息完成
        - 抽象方法：不同平台的清理逻辑不同

        **子类实现要点**：
        - 取消消息订阅
        - 关闭网络连接
        - 清理后台任务
        - 更新self._running状态
        """

    # -- 出站消息处理 ----------------------------------------------------------

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        """
        发送消息回外部平台

        **为什么这样设计**：
        - 抽象方法：不同平台的API调用方式不同
        - 统一接口：上层代码无需关心具体平台

        **实现要点**：
        - 使用msg.chat_id定位目标对话
        - 使用msg.thread_ts回复到正确的线程（如果支持）
        - 处理发送失败的情况（重试、日志等）
        """

    async def send_file(self, msg: OutboundMessage, attachment: ResolvedAttachment) -> bool:
        """
        上传单个文件附件到平台

        **为什么这样设计**：
        - 可选重写：不是所有平台都支持文件上传
        - 默认返回False：表示不支持文件上传
        - 独立方法：文件上传可能需要不同的API调用

        **参数说明**：
        - msg: 出站消息对象，包含chat_id和thread_ts
        - attachment: 已解析的附件信息（路径、MIME类型、大小等）

        **返回值**：
        - True: 上传成功
        - False: 上传失败或不支持

        **实现要点**：
        - 检查文件大小限制
        - 根据MIME类型选择上传API
        - 处理上传失败的情况
        """
        return False

    # -- 辅助方法 -----------------------------------------------------------

    def _make_inbound(
        self,
        chat_id: str,
        user_id: str,
        text: str,
        *,
        msg_type: InboundMessageType = InboundMessageType.CHAT,
        thread_ts: str | None = None,
        files: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> InboundMessage:
        """
        便捷工厂方法：创建InboundMessage实例

        **为什么这样设计**：
        - 封装创建逻辑：避免重复代码
        - 设置默认值：减少参数传递的复杂性
        - 自动注入channel_name：确保消息来源正确

        **参数说明**：
        - chat_id: 平台对话ID
        - user_id: 发送者用户ID
        - text: 消息文本内容
        - msg_type: 消息类型（CHAT/COMMAND，默认CHAT）
        - thread_ts: 线程时间戳（用于回复线程）
        - files: 文件附件列表
        - metadata: 额外的元数据

        **返回值**：
        - InboundMessage对象，准备好发布到消息总线
        """
        return InboundMessage(
            channel_name=self.name,  # 自动注入频道名称
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            msg_type=msg_type,
            thread_ts=thread_ts,
            files=files or [],
            metadata=metadata or {},
        )

    async def _on_outbound(self, msg: OutboundMessage) -> None:
        """
        出站消息回调（注册到消息总线）

        ===================
        设计思路说明
        ===================

        **核心职责**：
        - 过滤消息：只处理发送给当前频道的消息
        - 发送文本：先发送文本消息
        - 上传附件：然后上传文件附件

        **为什么这样设计**：
        1. **消息过滤**：通过channel_name过滤，避免跨频道发送
        2. **发送顺序**：先文本后附件，确保用户看到完整的消息
        3. **失败处理**：文本发送失败时跳过附件上传，避免部分交付

        **为什么失败时要跳过附件上传**：
        - 避免用户收到文件但没有文本说明的困惑
        - 保持消息的完整性
        - 减少不必要的API调用和资源消耗

        **实现细节**：
        - 每个附件单独上传，互不影响
        - 记录失败的上传，便于调试
        - 异常隔离：单个附件失败不影响其他附件
        """
        # 消息过滤：只处理发送给当前频道的消息
        if msg.channel_name == self.name:
            try:
                # 步骤1：发送文本消息
                await self.send(msg)
            except Exception:
                logger.exception("Failed to send outbound message on channel %s", self.name)
                return  # 文本发送失败时，不尝试上传附件

            # 步骤2：上传文件附件
            for attachment in msg.attachments:
                try:
                    success = await self.send_file(msg, attachment)
                    if not success:
                        logger.warning("[%s] file upload skipped for %s", self.name, attachment.filename)
                except Exception:
                    logger.exception("[%s] failed to upload file %s", self.name, attachment.filename)
