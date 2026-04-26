"""
Slack频道实现——通过Socket Mode连接（无需公网IP）

===================
设计思路说明
===================

**为什么选择Socket Mode**：
1. **无需公网IP**：使用WebSocket主动连接Slack服务器，无需暴露服务端
2. **防火墙友好**：从内网发起连接，不受防火墙限制
3. **简化部署**：无需配置反向代理或域名

**核心功能**：
1. 接收Slack消息（DM和@mention）
2. 发送回复消息和文件
3. 支持线程化对话
4. 用户权限控制（可选）

**消息流程**：
Slack → Socket Mode → _on_socket_event → _handle_message_event → MessageBus
MessageBus → _on_outbound → send/send_file → Slack API

**为什么使用两个客户端**：
- SocketModeClient：接收实时事件（WebSocket）
- WebClient：发送消息和文件（HTTP API）
- 分离关注点：不同操作使用最适合的客户端
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from markdown_to_mrkdwn import SlackMarkdownConverter

from app.channels.base import Channel
from app.channels.message_bus import InboundMessageType, MessageBus, OutboundMessage, ResolvedAttachment

logger = logging.getLogger(__name__)

# 全局Markdown转换器
# 为什么是全局变量：
# - 转换器是无状态的，可以安全共享
# - 避免重复创建，提高性能
# - SlackMarkdownConverter内部缓存了转换规则
_slack_md_converter = SlackMarkdownConverter()


class SlackChannel(Channel):
    """使用Socket Mode的Slack IM频道（WebSocket，无需公网IP）

    ===================
    设计思路说明
    ===================

    **核心职责**：
    1. 通过Socket Mode接收Slack事件
    2. 将用户消息发布到MessageBus
    3. 订阅出站消息并发送回Slack

    **为什么使用Socket Mode**：
    - 不需要公网IP或域名
    - 不需要配置webhook端点
    - 内网环境也能正常工作
    - 实时双向通信

    **配置说明**（在config.yaml的channels.slack下）：
        - ``bot_token``: Slack Bot User OAuth Token (xoxb-...)
        - ``app_token``: Slack App-Level Token (xapp-...)，用于Socket Mode
        - ``allowed_users``: （可选）允许的Slack用户ID列表。空列表=允许所有用户

    **权限要求**：
    - Bot Token Scope: chat:write, files:write, reactions:write
    - Event Subscriptions: message.im, app_mention

    **为什么需要allowed_users**：
    - 安全控制：限制只有特定用户可以使用
    - 测试阶段：只对测试用户开放
    - 成本控制：避免意外的高API调用
    """

    def __init__(self, bus: MessageBus, config: dict[str, Any]) -> None:
        super().__init__(name="slack", bus=bus, config=config)
        # Socket Mode客户端：用于接收实时事件
        self._socket_client = None
        # Web客户端：用于发送消息和文件
        self._web_client = None
        # 事件循环引用：用于从SDK线程调度到asyncio循环
        self._loop: asyncio.AbstractEventLoop | None = None
        # 允许的用户ID集合
        self._allowed_users: set[str] = set(config.get("allowed_users", []))

    async def start(self) -> None:
        """启动Slack频道，建立Socket Mode连接

        **启动流程**：
        1. 检查依赖是否安装
        2. 验证配置完整性
        3. 创建WebClient和SocketModeClient
        4. 注册事件监听器
        5. 订阅出站消息
        6. 在后台线程启动Socket Mode连接

        **为什么在后台线程运行**：
        - slack-sdk的Socket Mode客户端使用同步阻塞API
        - 需要在线程池中运行，避免阻塞事件循环
        - 使用run_in_executor实现异步包装

        **为什么保存SocketModeResponse**：
        - SDK的API设计需要在回调中创建响应对象
        - 保存类引用避免重复导入
        """
        if self._running:
            return

        # 步骤1：检查依赖
        try:
            from slack_sdk import WebClient
            from slack_sdk.socket_mode import SocketModeClient
            from slack_sdk.socket_mode.response import SocketModeResponse
        except ImportError:
            logger.error("slack-sdk is not installed. Install it with: uv add slack-sdk")
            return

        self._SocketModeResponse = SocketModeResponse

        # 步骤2：验证配置
        bot_token = self.config.get("bot_token", "")
        app_token = self.config.get("app_token", "")

        if not bot_token or not app_token:
            logger.error("Slack channel requires bot_token and app_token")
            return

        # 步骤3：创建客户端
        self._web_client = WebClient(token=bot_token)
        self._socket_client = SocketModeClient(
            app_token=app_token,
            web_client=self._web_client,
        )
        self._loop = asyncio.get_event_loop()

        # 步骤4：注册事件监听器
        self._socket_client.socket_mode_request_listeners.append(self._on_socket_event)

        self._running = True
        self.bus.subscribe_outbound(self._on_outbound)

        # 步骤5：在后台线程启动Socket Mode连接
        asyncio.get_event_loop().run_in_executor(None, self._socket_client.connect)
        logger.info("Slack channel started")

    async def stop(self) -> None:
        """停止Slack频道，关闭连接

        **停止流程**：
        1. 取消订阅出站消息
        2. 关闭Socket Mode连接
        3. 清理客户端引用

        **为什么先取消订阅**：
        - 避免停止期间收到新消息
        - 防止向已关闭的客户端发送消息
        """
        self._running = False
        self.bus.unsubscribe_outbound(self._on_outbound)
        if self._socket_client:
            self._socket_client.close()
            self._socket_client = None
        logger.info("Slack channel stopped")

    async def send(self, msg: OutboundMessage, *, _max_retries: int = 3) -> None:
        """发送消息到Slack

        **参数说明**：
        - msg: 出站消息对象
        - _max_retries: 最大重试次数（默认3次）

        **为什么转换Markdown**：
        - Slack使用特殊的mrkdwn格式
        - 使用转换器将标准Markdown转换为Slack格式
        - 确保链接、格式等正确显示

        **为什么添加表情反应**：
        - 提供视觉反馈：用户能看到消息已处理
        - 白色勾=成功，X=失败
        - 帮助用户理解AI响应状态

        **重试策略**：
        - 指数退避：1秒、2秒、4秒...
        - 最多重试3次
        - 所有重试失败后抛出异常

        **为什么使用to_thread**：
        - slack-sdk的API是同步的
        - 使用to_thread在线程池中运行
        - 避免阻塞事件循环
        """
        if not self._web_client:
            return

        # 准备发送参数
        kwargs: dict[str, Any] = {
            "channel": msg.chat_id,
            "text": _slack_md_converter.convert(msg.text),
        }
        if msg.thread_ts:
            kwargs["thread_ts"] = msg.thread_ts

        # 重试循环
        last_exc: Exception | None = None
        for attempt in range(_max_retries):
            try:
                await asyncio.to_thread(self._web_client.chat_postMessage, **kwargs)
                # 成功后添加完成反应到线程根消息
                if msg.thread_ts:
                    await asyncio.to_thread(
                        self._add_reaction,
                        msg.chat_id,
                        msg.thread_ts,
                        "white_check_mark",
                    )
                return
            except Exception as exc:
                last_exc = exc
                if attempt < _max_retries - 1:
                    # 指数退避：1秒、2秒
                    delay = 2**attempt  # 1s, 2s
                    logger.warning(
                        "[Slack] send failed (attempt %d/%d), retrying in %ds: %s",
                        attempt + 1,
                        _max_retries,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)

        # 所有重试都失败
        logger.error("[Slack] send failed after %d attempts: %s", _max_retries, last_exc)
        # 添加失败反应
        if msg.thread_ts:
            try:
                await asyncio.to_thread(
                    self._add_reaction,
                    msg.chat_id,
                    msg.thread_ts,
                    "x",
                )
            except Exception:
                pass
        raise last_exc  # type: ignore[misc]

    async def send_file(self, msg: OutboundMessage, attachment: ResolvedAttachment) -> bool:
        """上传文件附件到Slack

        **参数说明**：
        - msg: 出站消息对象，包含chat_id和thread_ts
        - attachment: 已解析的附件信息

        **返回值**：
        - True: 上传成功
        - False: 上传失败

        **为什么使用files_upload_v2**：
        - Slack推荐的新版文件上传API
        - 支持更大的文件
        - 更好的错误处理

        **为什么失败时返回False而非抛异常**：
        - 文件上传失败不应影响主消息
        - 允许部分交付（文本已发送，文件失败）
        - 调用者可以决定如何处理
        """
        if not self._web_client:
            return False

        try:
            kwargs: dict[str, Any] = {
                "channel": msg.chat_id,
                "file": str(attachment.actual_path),
                "filename": attachment.filename,
                "title": attachment.filename,
            }
            if msg.thread_ts:
                kwargs["thread_ts"] = msg.thread_ts

            await asyncio.to_thread(self._web_client.files_upload_v2, **kwargs)
            logger.info("[Slack] file uploaded: %s to channel=%s", attachment.filename, msg.chat_id)
            return True
        except Exception:
            logger.exception("[Slack] failed to upload file: %s", attachment.filename)
            return False

    # -- internal（内部方法）------------------------------------------

    def _add_reaction(self, channel_id: str, timestamp: str, emoji: str) -> None:
        """给消息添加表情反应（尽力而为，非阻塞）

        **参数说明**：
        - channel_id: 频道ID
        - timestamp: 消息时间戳
        - emoji: 表情名称（如"white_check_mark"、"eyes"）

        **为什么忽略"already_reacted"错误**：
        - 重复添加同一反应是正常情况
        - 不应产生错误日志
        - 避免日志污染

        **为什么捕获所有异常**：
        - 表情反应是辅助功能
        - 失败不应影响主流程
        - 静默失败即可
        """
        if not self._web_client:
            return
        try:
            self._web_client.reactions_add(
                channel=channel_id,
                timestamp=timestamp,
                name=emoji,
            )
        except Exception as exc:
            if "already_reacted" not in str(exc):
                logger.warning("[Slack] failed to add reaction %s: %s", emoji, exc)

    def _send_running_reply(self, channel_id: str, thread_ts: str) -> None:
        """在线程中发送"正在处理..."回复（从SDK线程调用）

        **参数说明**：
        - channel_id: 频道ID
        - thread_ts: 线程时间戳

        **为什么需要这个方法**：
        - 给用户即时反馈，表明AI正在处理
        - 在AI响应到达前提供确认
        - 改善用户体验

        **为什么是同步方法**：
        - 从SDK的线程调用
        - SDK的API是同步的
        - 避免异步复杂度
        """
        if not self._web_client:
            return
        try:
            self._web_client.chat_postMessage(
                channel=channel_id,
                text=":hourglass_flowing_sand: Working on it...",
                thread_ts=thread_ts,
            )
            logger.info("[Slack] 'Working on it...' reply sent in channel=%s, thread_ts=%s", channel_id, thread_ts)
        except Exception:
            logger.exception("[Slack] failed to send running reply in channel=%s", channel_id)

    def _on_socket_event(self, client, req) -> None:
        """slack-sdk对每个Socket Mode事件的回调

        **调用上下文**：
        - 从slack-sdk的后台线程调用
        - 需要快速返回，避免阻塞SDK
        - 使用asyncio.run_coroutine_threadsafe调度到主循环

        **处理流程**：
        1. 确认收到事件（ACK）
        2. 检查事件类型
        3. 处理消息和应用提及事件

        **为什么需要确认**：
        - Socket Mode要求确认每个事件
        - 不确认会导致超时重传
        - 确认后才能处理下一个事件
        """
        try:
            # 步骤1：确认收到事件
            response = self._SocketModeResponse(envelope_id=req.envelope_id)
            client.send_socket_mode_response(response)

            event_type = req.type
            if event_type != "events_api":
                return

            event = req.payload.get("event", {})
            etype = event.get("type", "")

            # 步骤2：处理消息事件（DM或@提及）
            if etype in ("message", "app_mention"):
                self._handle_message_event(event)

        except Exception:
            logger.exception("Error processing Slack event")

    def _handle_message_event(self, event: dict) -> None:
        """处理Slack消息事件

        **处理流程**：
        1. 过滤掉机器人消息
        2. 检查用户权限
        3. 提取消息内容和元数据
        4. 判断消息类型（聊天/命令）
        5. 创建入站消息并发布到总线

        **为什么忽略bot_id和subtype**：
        - bot_id: 避免处理其他机器人的消息
        - subtype: 避免处理系统消息（如加入频道）

        **为什么检查allowed_users**：
        - 安全控制：只允许特定用户使用
        - 防止滥用：限制API调用
        - 测试阶段：只对测试用户开放

        **topic_id的设计**：
        - 使用thread_ts作为topic_id
        - 线程消息：thread_ts是根消息时间戳（共享主题）
        - 非线程消息：thread_ts是消息自己的时间戳（新主题）
        - 这样设计确保同一对话共享DeerFlow线程
        """
        # 步骤1：忽略机器人消息
        if event.get("bot_id") or event.get("subtype"):
            return

        user_id = event.get("user", "")

        # 步骤2：检查用户权限
        if self._allowed_users and user_id not in self._allowed_users:
            logger.debug("Ignoring message from non-allowed user: %s", user_id)
            return

        text = event.get("text", "").strip()
        if not text:
            return

        channel_id = event.get("channel", "")
        thread_ts = event.get("thread_ts") or event.get("ts", "")

        # 步骤3：判断消息类型
        if text.startswith("/"):
            msg_type = InboundMessageType.COMMAND
        else:
            msg_type = InboundMessageType.CHAT

        # 步骤4：创建入站消息
        # topic_id: 使用thread_ts作为主题标识符
        # 对于线程消息，thread_ts是根消息ts（共享主题）
        # 对于非线程消息，thread_ts是消息自己的ts（新主题）
        inbound = self._make_inbound(
            chat_id=channel_id,
            user_id=user_id,
            text=text,
            msg_type=msg_type,
            thread_ts=thread_ts,
        )
        inbound.topic_id = thread_ts

        # 步骤5：发布到消息总线
        if self._loop and self._loop.is_running():
            # 添加eyes反应表示已接收
            self._add_reaction(channel_id, event.get("ts", thread_ts), "eyes")
            # 发送"正在处理"回复（从SDK线程发起，不等待结果）
            self._send_running_reply(channel_id, thread_ts)
            # 将消息发布到总线（调度到asyncio循环）
            asyncio.run_coroutine_threadsafe(self.bus.publish_inbound(inbound), self._loop)
