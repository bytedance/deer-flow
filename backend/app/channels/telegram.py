"""
Telegram频道 — 通过长轮询连接（无需公网IP）

===================
设计思路说明
===================

**为什么选择长轮询**：
1. 无需公网IP：适合内网或本地部署
2. 实现简单：python-telegram-bot库原生支持
3. 资源效率：相比WebSocket，长轮询更易管理

**核心设计模式**：
- 线程隔离：Telegram轮询运行在独立线程和事件循环中
- 消息桥接：跨线程将消息传递到主事件循环
- 状态跟踪：记录最后发送的消息ID以支持线程回复

**为什么需要独立线程**：
1. python-telegram-bot的run_polling()会阻塞
2. 需要避免与主事件循环冲突
3. 便于独立管理和监控轮询状态

**与Slack/飞书的区别**：
- Slack/飞书：使用Webhook（被动接收）
- Telegram：使用长轮询（主动拉取）
- 这种差异是因为Telegram推荐长轮询，更简单可靠
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from app.channels.base import Channel
from app.channels.message_bus import InboundMessage, InboundMessageType, MessageBus, OutboundMessage, ResolvedAttachment

logger = logging.getLogger(__name__)


class TelegramChannel(Channel):
    """
    使用长轮询的Telegram Bot频道

    ===================
    设计思路说明
    ===================

    **核心职责**：
    1. 通过长轮询接收Telegram消息
    2. 将消息转换为InboundMessage发布到总线
    3. 接收OutboundMessage并发送回Telegram
    4. 支持文件附件上传

    **为什么这样设计**：
    - **独立线程**：避免阻塞主事件循环
    - **用户白名单**：allowed_users配置提供访问控制
    - **线程回复**：通过reply_to_message_id实现类似thread的效果

    **配置项（在config.yaml的channels.telegram下）**：
        - bot_token: Telegram Bot API token（从@BotFather获取）
        - allowed_users: （可选）允许的Telegram用户ID列表，空=允许所有人

    **topic_id的设计**：
    - 私聊：topic_id为None，所有消息共享一个thread
    - 群聊：topic_id为message_id，每条消息启动新thread
    - 回复消息：topic_id为被回复消息的ID，复用已有thread

    **为什么群聊用message_id作为topic_id**：
    - Telegram没有原生thread概念
    - 通过message_id可以模拟thread行为
    - 回复消息时可以关联到之前的对话
    """

    def __init__(self, bus: MessageBus, config: dict[str, Any]) -> None:
        """
        初始化Telegram频道

        **为什么这样设计初始化**：
        - 提前解析allowed_users：避免运行时重复解析
        - 使用字典记录最后消息ID：支持线程化回复
        - 分离事件循环引用：便于跨线程调用

        **参数说明**：
        - bus: 消息总线实例
        - config: 配置字典，包含bot_token和allowed_users
        """
        super().__init__(name="telegram", bus=bus, config=config)
        self._application = None  # python-telegram-bot的Application实例
        self._thread: threading.Thread | None = None  # 轮询线程
        self._tg_loop: asyncio.AbstractEventLoop | None = None  # Telegram专用事件循环
        self._main_loop: asyncio.AbstractEventLoop | None = None  # 主事件循环引用
        self._allowed_users: set[int] = set()  # 允许的用户ID集合
        for uid in config.get("allowed_users", []):
            try:
                self._allowed_users.add(int(uid))
            except (ValueError, TypeError):
                pass
        # chat_id -> 最后发送的message_id，用于实现线程化回复
        # 为什么需要这个：Telegram没有原生thread，通过reply_to实现
        self._last_bot_message: dict[str, int] = {}

    async def start(self) -> None:
        """
        启动Telegram频道

        **启动流程**：
        1. 检查依赖和配置
        2. 注册消息处理器（命令和文本）
        3. 在独立线程中启动轮询

        **为什么使用独立线程**：
        - python-telegram-bot需要自己的事件循环
        - run_polling()是阻塞调用
        - 避免与主应用的异步代码冲突
        """
        if self._running:
            return

        try:
            from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
        except ImportError:
            logger.error("python-telegram-bot is not installed. Install it with: uv add python-telegram-bot")
            return

        bot_token = self.config.get("bot_token", "")
        if not bot_token:
            logger.error("Telegram channel requires bot_token")
            return

        # 保存主事件循环引用，用于跨线程调用
        self._main_loop = asyncio.get_event_loop()
        self._running = True
        self.bus.subscribe_outbound(self._on_outbound)

        # 构建Application并注册处理器
        app = ApplicationBuilder().token(bot_token).build()

        # 命令处理器：注册所有斜杠命令
        app.add_handler(CommandHandler("start", self._cmd_start))
        app.add_handler(CommandHandler("new", self._cmd_generic))
        app.add_handler(CommandHandler("status", self._cmd_generic))
        app.add_handler(CommandHandler("models", self._cmd_generic))
        app.add_handler(CommandHandler("memory", self._cmd_generic))
        app.add_handler(CommandHandler("help", self._cmd_generic))

        # 普通文本消息处理器
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))

        self._application = app

        # 在专用线程中运行轮询，每个线程有独立的事件循环
        self._thread = threading.Thread(target=self._run_polling, daemon=True)
        self._thread.start()
        logger.info("Telegram channel started")

    async def stop(self) -> None:
        """
        停止Telegram频道

        **停止流程**：
        1. 取消出站消息订阅
        2. 停止Telegram轮询
        3. 等待线程结束
        4. 清理资源

        **为什么需要call_soon_threadsafe**：
        - 轮询运行在另一个线程的事件循环中
        - 需要线程安全地调用stop()
        """
        self._running = False
        self.bus.unsubscribe_outbound(self._on_outbound)
        if self._tg_loop and self._tg_loop.is_running():
            self._tg_loop.call_soon_threadsafe(self._tg_loop.stop)
        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None
        self._application = None
        logger.info("Telegram channel stopped")

    async def send(self, msg: OutboundMessage, *, _max_retries: int = 3) -> None:
        """
        发送消息到Telegram

        **为什么实现重试机制**：
        - Telegram API可能有临时故障
        - 网络波动导致请求失败
        - 指数退避避免频繁重试

        **为什么记录最后消息ID**：
        - 实现类似thread的回复效果
        - 后续消息会reply_to这条消息
        - 形成视觉上的对话线程

        **参数说明**：
        - msg: 出站消息对象
        - _max_retries: 最大重试次数（内部参数）

        **实现细节**：
        - 使用reply_to_message_id实现线程化回复
        - 重试延迟为2^attempt秒（1s, 2s, 4s...）
        """
        if not self._application:
            return

        try:
            chat_id = int(msg.chat_id)
        except (ValueError, TypeError):
            logger.error("Invalid Telegram chat_id: %s", msg.chat_id)
            return

        kwargs: dict[str, Any] = {"chat_id": chat_id, "text": msg.text}

        # 回复该聊天中最后一条bot消息，实现线程化效果
        reply_to = self._last_bot_message.get(msg.chat_id)
        if reply_to:
            kwargs["reply_to_message_id"] = reply_to

        bot = self._application.bot
        last_exc: Exception | None = None
        for attempt in range(_max_retries):
            try:
                sent = await bot.send_message(**kwargs)
                self._last_bot_message[msg.chat_id] = sent.message_id
                return
            except Exception as exc:
                last_exc = exc
                if attempt < _max_retries - 1:
                    delay = 2**attempt  # 1s, 2s, 4s
                    logger.warning(
                        "[Telegram] send failed (attempt %d/%d), retrying in %ds: %s",
                        attempt + 1,
                        _max_retries,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)

        logger.error("[Telegram] send failed after %d attempts: %s", _max_retries, last_exc)
        raise last_exc  # type: ignore[misc]

    async def send_file(self, msg: OutboundMessage, attachment: ResolvedAttachment) -> bool:
        """
        上传文件附件到Telegram

        **为什么区分图片和文档**：
        - Telegram对图片和文档有不同的API
        - 图片：send_photo，限制10MB
        - 文档：send_document，限制50MB
        - 图片在Telegram中显示更友好

        **参数说明**：
        - msg: 出站消息对象
        - attachment: 已解析的附件信息

        **返回值**：
        - True: 上传成功
        - False: 上传失败

        **实现细节**：
        - 图片且<=10MB：使用send_photo
        - 其他情况：使用send_document
        - 超过50MB：跳过上传并记录警告
        """
        if not self._application:
            return False

        try:
            chat_id = int(msg.chat_id)
        except (ValueError, TypeError):
            logger.error("[Telegram] Invalid chat_id: %s", msg.chat_id)
            return False

        # Telegram限制：照片10MB，文档50MB
        if attachment.size > 50 * 1024 * 1024:
            logger.warning("[Telegram] file too large (%d bytes), skipping: %s", attachment.size, attachment.filename)
            return False

        bot = self._application.bot
        reply_to = self._last_bot_message.get(msg.chat_id)

        try:
            # 图片且小于10MB：使用send_photo（显示效果更好）
            if attachment.is_image and attachment.size <= 10 * 1024 * 1024:
                with open(attachment.actual_path, "rb") as f:
                    kwargs: dict[str, Any] = {"chat_id": chat_id, "photo": f}
                    if reply_to:
                        kwargs["reply_to_message_id"] = reply_to
                    sent = await bot.send_photo(**kwargs)
            else:
                # 其他文件：使用send_document
                from telegram import InputFile

                with open(attachment.actual_path, "rb") as f:
                    input_file = InputFile(f, filename=attachment.filename)
                    kwargs = {"chat_id": chat_id, "document": input_file}
                    if reply_to:
                        kwargs["reply_to_message_id"] = reply_to
                    sent = await bot.send_document(**kwargs)

            self._last_bot_message[msg.chat_id] = sent.message_id
            logger.info("[Telegram] file sent: %s to chat=%s", attachment.filename, msg.chat_id)
            return True
        except Exception:
            logger.exception("[Telegram] failed to send file: %s", attachment.filename)
            return False

    # -- 辅助方法 ------------------------------------------------------------

    async def _send_running_reply(self, chat_id: str, reply_to_message_id: int) -> None:
        """
        发送"正在处理..."回复

        **为什么需要这个方法**：
        - 给用户即时反馈，表明消息已接收
        - AI处理可能需要较长时间，避免用户重复发送
        - 提升用户体验

        **参数说明**：
        - chat_id: Telegram对话ID
        - reply_to_message_id: 要回复的消息ID
        """
        if not self._application:
            return
        try:
            bot = self._application.bot
            await bot.send_message(
                chat_id=int(chat_id),
                text="Working on it...",
                reply_to_message_id=reply_to_message_id,
            )
            logger.info("[Telegram] 'Working on it...' reply sent in chat=%s", chat_id)
        except Exception:
            logger.exception("[Telegram] failed to send running reply in chat=%s", chat_id)

    # -- 内部方法 ------------------------------------------------------------

    @staticmethod
    def _log_future_error(fut, name: str, msg_id: str):
        """
        记录跨线程任务的错误

        **为什么需要这个方法**：
        - 跨线程调用的异常不会自动传播
        - 需要手动检查future的异常
        - 便于调试和监控

        **参数说明**：
        - fut: asyncio.Future对象
        - name: 操作名称（用于日志）
        - msg_id: 消息ID（用于追踪）
        """
        try:
            exc = fut.exception()
            if exc:
                logger.error("[Telegram] %s failed for msg_id=%s: %s", name, msg_id, exc)
        except Exception:
            logger.exception("[Telegram] Failed to inspect future for %s (msg_id=%s)", name, msg_id)

    def _run_polling(self) -> None:
        """
        在专用线程中运行Telegram轮询

        **为什么不能直接用run_polling()**：
        - run_polling()内部调用add_signal_handler()
        - 该函数只能在主线程中工作
        - 因此手动初始化和启动各个组件

        **实现流程**：
        1. 创建新的事件循环
        2. 初始化Application
        3. 启动Updater（轮询组件）
        4. 运行事件循环直到停止

        **为什么需要手动管理生命周期**：
        - 精确控制启动和停止流程
        - 便于集成到自己的线程管理中
        - 更好的错误处理
        """
        self._tg_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._tg_loop)
        try:
            # 手动初始化并启动，因为run_polling()在非主线程中不工作
            self._tg_loop.run_until_complete(self._application.initialize())
            self._tg_loop.run_until_complete(self._application.start())
            self._tg_loop.run_until_complete(self._application.updater.start_polling())
            self._tg_loop.run_forever()
        except Exception:
            if self._running:
                logger.exception("Telegram polling error")
        finally:
            # 优雅关闭：按相反顺序停止各组件
            try:
                if self._application.updater.running:
                    self._tg_loop.run_until_complete(self._application.updater.stop())
                self._tg_loop.run_until_complete(self._application.stop())
                self._tg_loop.run_until_complete(self._application.shutdown())
            except Exception:
                logger.exception("Error during Telegram shutdown")

    def _check_user(self, user_id: int) -> bool:
        """
        检查用户是否在白名单中

        **为什么需要白名单**：
        - 生产环境中限制bot的使用范围
        - 防止未授权用户使用
        - 空白名单表示允许所有人

        **参数说明**：
        - user_id: Telegram用户ID

        **返回值**：
        - True: 用户有权限
        - False: 用户无权限
        """
        if not self._allowed_users:
            return True
        return user_id in self._allowed_users

    async def _cmd_start(self, update, context) -> None:
        """
        处理/start命令

        **为什么单独处理start**：
        - 这是用户与bot的第一次交互
        - 提供友好的欢迎消息
        - 引导用户了解可用的命令
        """
        if not self._check_user(update.effective_user.id):
            return
        await update.message.reply_text("Welcome to DeerFlow! Send me a message to start a conversation.\nType /help for available commands.")

    async def _process_incoming_with_reply(self, chat_id: str, msg_id: int, inbound: InboundMessage) -> None:
        """
        处理入站消息并发送"正在处理"回复

        **为什么这样设计**：
        - 先发送即时反馈，再处理消息
        - 避免用户等待时重复发送
        - 统一的处理流程

        **参数说明**：
        - chat_id: Telegram对话ID
        - msg_id: Telegram消息ID
        - inbound: 入站消息对象
        """
        await self._send_running_reply(chat_id, msg_id)
        await self.bus.publish_inbound(inbound)

    async def _cmd_generic(self, update, context) -> None:
        """
        处理通用斜杠命令

        **为什么使用相同的topic_id逻辑**：
        - 命令也应该能正确映射到线程
        - /new命令应该创建新线程
        - 回复命令应该复用已有线程

        **参数说明**：
        - update: Telegram Update对象
        - context: Telegram Context对象
        """
        if not self._check_user(update.effective_user.id):
            return

        text = update.message.text
        chat_id = str(update.effective_chat.id)
        user_id = str(update.effective_user.id)
        msg_id = str(update.message.message_id)

        # 使用与_on_text相同的topic_id逻辑
        # 这样命令如/new可以正确地定位到thread映射
        if update.effective_chat.type == "private":
            topic_id = None
        else:
            reply_to = update.message.reply_to_message
            if reply_to:
                topic_id = str(reply_to.message_id)
            else:
                topic_id = msg_id

        inbound = self._make_inbound(
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            msg_type=InboundMessageType.COMMAND,
            thread_ts=msg_id,
        )
        inbound.topic_id = topic_id

        # 跨线程调用：在主事件循环中处理消息
        if self._main_loop and self._main_loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(self._process_incoming_with_reply(chat_id, update.message.message_id, inbound), self._main_loop)
            fut.add_done_callback(lambda f: self._log_future_error(f, "process_incoming_with_reply", update.message.message_id))
        else:
            logger.warning("[Telegram] Main loop not running. Cannot publish inbound message.")

    async def _on_text(self, update, context) -> None:
        """
        处理普通文本消息

        **为什么这样设计topic_id**：
        - 私聊：topic_id为None，所有消息共享一个thread
        - 群聊新消息：topic_id为当前消息ID，创建新thread
        - 群聊回复：topic_id为被回复消息ID，复用已有thread

        **这样设计的好处**：
        - 私聊中保持连续对话
        - 群聊中每个回复链独立处理
        - 符合用户的使用习惯

        **参数说明**：
        - update: Telegram Update对象
        - context: Telegram Context对象
        """
        if not self._check_user(update.effective_user.id):
            return

        text = update.message.text.strip()
        if not text:
            return

        chat_id = str(update.effective_chat.id)
        user_id = str(update.effective_user.id)
        msg_id = str(update.message.message_id)

        # topic_id决定消息映射到哪个DeerFlow thread
        # 私聊：使用None，所有消息共享单个thread（store键为"channel:chat_id"）
        # 群聊：使用回复消息ID或当前消息ID，保持独立的对话线程
        if update.effective_chat.type == "private":
            topic_id = None
        else:
            reply_to = update.message.reply_to_message
            if reply_to:
                topic_id = str(reply_to.message_id)
            else:
                topic_id = msg_id

        inbound = self._make_inbound(
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            msg_type=InboundMessageType.CHAT,
            thread_ts=msg_id,
        )
        inbound.topic_id = topic_id

        # 跨线程调用：在主事件循环中处理消息
        if self._main_loop and self._main_loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(self._process_incoming_with_reply(chat_id, update.message.message_id, inbound), self._main_loop)
            fut.add_done_callback(lambda f: self._log_future_error(f, "process_incoming_with_reply", update.message.message_id))
        else:
            logger.warning("[Telegram] Main loop not running. Cannot publish inbound message.")
