"""Telegram channel — connects via long-polling (no public IP needed)."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

from app.channels.base import Channel
from app.channels.connection_identity import attach_connection_identity
from app.channels.message_bus import InboundMessage, InboundMessageType, MessageBus, OutboundMessage, ResolvedAttachment

logger = logging.getLogger(__name__)

TELEGRAM_MAX_MESSAGE_LENGTH = 4096
STREAM_EDIT_MIN_INTERVAL_SECONDS = 1.0
# Groups (negative chat_id) are capped at 20 messages/minute by Telegram,
# so stream edits there must pace well below the private-chat 1 msg/s guideline.
STREAM_EDIT_GROUP_MIN_INTERVAL_SECONDS = 3.0
# Bound on tracked in-flight streamed messages; entries normally clear on the
# final update, this only guards against leaks when a final never arrives.
MAX_TRACKED_STREAM_MESSAGES = 256

# Indirection so tests can patch the clock without touching the global time module.
_monotonic = time.monotonic


class TelegramChannel(Channel):
    """Telegram bot channel using long-polling.

    Configuration keys (in ``config.yaml`` under ``channels.telegram``):
        - ``bot_token``: Telegram Bot API token (from @BotFather).
        - ``allowed_users``: (optional) List of allowed Telegram user IDs. Empty = allow all.
    """

    def __init__(self, bus: MessageBus, config: dict[str, Any]) -> None:
        super().__init__(name="telegram", bus=bus, config=config)
        self._application = None
        self._thread: threading.Thread | None = None
        self._tg_loop: asyncio.AbstractEventLoop | None = None
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._allowed_users: set[int] = set()
        for uid in config.get("allowed_users", []):
            try:
                self._allowed_users.add(int(uid))
            except (ValueError, TypeError):
                pass
        # chat_id -> last sent message_id for threaded replies
        self._last_bot_message: dict[str, int] = {}
        # stream_key ("chat_id:thread_ts") -> state of the in-flight streamed
        # bot message being edited in place: {"message_id", "last_edit_at", "last_text"}
        self._stream_messages: dict[str, dict[str, Any]] = {}
        self._connection_repo = config.get("connection_repo")

    @property
    def supports_streaming(self) -> bool:
        return True

    async def start(self) -> None:
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

        self._main_loop = asyncio.get_event_loop()
        self._running = True
        self.bus.subscribe_outbound(self._on_outbound)

        # Build the application
        app = ApplicationBuilder().token(bot_token).build()

        # Command handlers
        app.add_handler(CommandHandler("start", self._cmd_start))
        app.add_handler(CommandHandler("bootstrap", self._cmd_generic))
        app.add_handler(CommandHandler("new", self._cmd_generic))
        app.add_handler(CommandHandler("status", self._cmd_generic))
        app.add_handler(CommandHandler("models", self._cmd_generic))
        app.add_handler(CommandHandler("memory", self._cmd_generic))
        app.add_handler(CommandHandler("help", self._cmd_generic))

        # Slash skill commands are dynamic and cannot all be pre-registered
        # with Telegram, so route unknown slash commands through chat handling.
        app.add_handler(MessageHandler(filters.TEXT & filters.COMMAND, self._on_text))

        # General message handler
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))

        self._application = app

        # Run polling in a dedicated thread with its own event loop
        self._thread = threading.Thread(target=self._run_polling, daemon=True)
        self._thread.start()
        logger.info("Telegram channel started")

    async def stop(self) -> None:
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
        if not self._application:
            return

        try:
            chat_id = int(msg.chat_id)
        except (ValueError, TypeError):
            logger.error("Invalid Telegram chat_id: %s", msg.chat_id)
            return

        key = self._stream_key(msg.chat_id, msg.thread_ts)

        if not msg.is_final:
            await self._send_stream_update(chat_id, key, msg.text, reply_to=self._parse_message_id(msg.thread_ts))
            return

        state = self._stream_messages.pop(key, None)
        if state is not None:
            await self._finalize_stream_message(chat_id, msg.chat_id, state, msg.text)
            return

        await self._send_new_message(chat_id, msg.chat_id, msg.text, _max_retries=_max_retries)

    async def _send_stream_update(self, chat_id: int, key: str, text: str, reply_to: int | None = None) -> None:
        """Edit the in-flight streamed message with accumulated text.

        Updates are best-effort: throttled, rate-limit drops are silent.  The
        manager always publishes a final message afterwards, which guarantees
        delivery of the complete text.
        """
        if not text:
            return

        display = text
        if len(display) > TELEGRAM_MAX_MESSAGE_LENGTH:
            display = display[: TELEGRAM_MAX_MESSAGE_LENGTH - 1] + "…"

        bot = self._application.bot
        state = self._stream_messages.get(key)

        send_kwargs: dict[str, Any] = {"chat_id": chat_id, "text": display}
        if reply_to:
            send_kwargs["reply_to_message_id"] = reply_to

        if state is None:
            try:
                sent = await bot.send_message(**send_kwargs)
            except Exception:
                logger.exception("[Telegram] failed to start stream message in chat=%s", chat_id)
                return
            self._register_stream_message(key, message_id=sent.message_id, last_text=display, last_edit_at=_monotonic())
            return

        now = _monotonic()
        min_interval = STREAM_EDIT_GROUP_MIN_INTERVAL_SECONDS if chat_id < 0 else STREAM_EDIT_MIN_INTERVAL_SECONDS
        if now - state["last_edit_at"] < min_interval:
            return
        if display == state["last_text"]:
            return

        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=state["message_id"], text=display)
        except Exception as exc:
            if self._is_not_modified(exc):
                state["last_text"] = display
                return
            if self._is_retry_after(exc):
                logger.debug("[Telegram] stream edit rate-limited in chat=%s, dropping update", chat_id)
                return
            logger.warning("[Telegram] stream edit failed in chat=%s, sending new message: %s", chat_id, exc)
            try:
                sent = await bot.send_message(**send_kwargs)
            except Exception:
                logger.exception("[Telegram] failed to send fallback stream message in chat=%s", chat_id)
                return
            state["message_id"] = sent.message_id

        state["last_edit_at"] = _monotonic()
        state["last_text"] = display

    async def _finalize_stream_message(self, chat_id: int, chat_key: str, state: dict[str, Any], text: str) -> None:
        """Apply the final text: edit the streamed message, splitting overflow into follow-ups."""
        bot = self._application.bot
        chunks = self._split_message(text or "")

        edited = True
        if chunks[0] != state["last_text"]:
            edited = await self._edit_final_chunk(bot, chat_id, state["message_id"], chunks[0])

        if edited:
            self._last_bot_message[chat_key] = state["message_id"]
        else:
            # Edit could not be applied (e.g. message deleted) — deliver the
            # first chunk as a fresh message with the standard retry policy.
            await self._send_new_message(chat_id, chat_key, chunks[0])

        for chunk in chunks[1:]:
            await self._send_new_message(chat_id, chat_key, chunk)

    async def _edit_final_chunk(self, bot, chat_id: int, message_id: int, text: str) -> bool:
        """Edit with one rate-limit retry. Returns False if the edit could not be applied."""
        for attempt in range(2):
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
                return True
            except Exception as exc:
                if self._is_not_modified(exc):
                    return True
                if self._is_retry_after(exc) and attempt == 0:
                    await asyncio.sleep(self._retry_after_seconds(exc))
                    continue
                logger.warning("[Telegram] final edit failed in chat=%s: %s", chat_id, exc)
                return False
        return False

    async def _send_new_message(self, chat_id: int, chat_key: str, text: str, *, _max_retries: int = 3) -> int | None:
        """Send a fresh message with retry/backoff. Returns the sent message_id."""
        kwargs: dict[str, Any] = {"chat_id": chat_id, "text": text}

        # Reply to the last bot message in this chat for threading
        reply_to = self._last_bot_message.get(chat_key)
        if reply_to:
            kwargs["reply_to_message_id"] = reply_to

        bot = self._application.bot

        async def send_message() -> int:
            sent = await bot.send_message(**kwargs)
            self._last_bot_message[chat_key] = sent.message_id
            return sent.message_id

        return await self._send_with_retry(
            send_message,
            max_retries=_max_retries,
            log_prefix="[Telegram]",
        )

    async def send_file(self, msg: OutboundMessage, attachment: ResolvedAttachment) -> bool:
        if not self._application:
            return False

        try:
            chat_id = int(msg.chat_id)
        except (ValueError, TypeError):
            logger.error("[Telegram] Invalid chat_id: %s", msg.chat_id)
            return False

        # Telegram limits: 10MB for photos, 50MB for documents
        if attachment.size > 50 * 1024 * 1024:
            logger.warning("[Telegram] file too large (%d bytes), skipping: %s", attachment.size, attachment.filename)
            return False

        bot = self._application.bot
        reply_to = self._last_bot_message.get(msg.chat_id)

        try:
            if attachment.is_image and attachment.size <= 10 * 1024 * 1024:
                with open(attachment.actual_path, "rb") as f:
                    kwargs: dict[str, Any] = {"chat_id": chat_id, "photo": f}
                    if reply_to:
                        kwargs["reply_to_message_id"] = reply_to
                    sent = await bot.send_photo(**kwargs)
            else:
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

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _stream_key(chat_id: str, thread_ts: str | None) -> str:
        return f"{chat_id}:{thread_ts or ''}"

    @staticmethod
    def _parse_message_id(value: str | None) -> int | None:
        try:
            return int(value) if value else None
        except (TypeError, ValueError):
            return None

    def _register_stream_message(self, key: str, *, message_id: int, last_text: str, last_edit_at: float) -> None:
        self._stream_messages.pop(key, None)
        while len(self._stream_messages) >= MAX_TRACKED_STREAM_MESSAGES:
            self._stream_messages.pop(next(iter(self._stream_messages)))
        self._stream_messages[key] = {
            "message_id": message_id,
            "last_edit_at": last_edit_at,
            "last_text": last_text,
        }

    @staticmethod
    def _is_retry_after(exc: Exception) -> bool:
        return getattr(exc, "retry_after", None) is not None

    @staticmethod
    def _retry_after_seconds(exc: Exception) -> float:
        value = getattr(exc, "retry_after", 0)
        if hasattr(value, "total_seconds"):
            return float(value.total_seconds())
        return float(value)

    @staticmethod
    def _is_not_modified(exc: Exception) -> bool:
        return "message is not modified" in str(exc).lower()

    @staticmethod
    def _split_message(text: str) -> list[str]:
        return [text[i : i + TELEGRAM_MAX_MESSAGE_LENGTH] for i in range(0, len(text), TELEGRAM_MAX_MESSAGE_LENGTH)] or [text]

    async def _send_running_reply(self, chat_id: str, reply_to_message_id: int) -> None:
        """Send a 'Working on it...' reply and register it as the stream target."""
        if not self._application:
            return
        try:
            bot = self._application.bot
            sent = await bot.send_message(
                chat_id=int(chat_id),
                text="Working on it...",
                reply_to_message_id=reply_to_message_id,
            )
            self._register_stream_message(
                self._stream_key(chat_id, str(reply_to_message_id)),
                message_id=sent.message_id,
                last_text="Working on it...",
                last_edit_at=0.0,
            )
            logger.info("[Telegram] 'Working on it...' reply sent in chat=%s", chat_id)
        except Exception:
            logger.exception("[Telegram] failed to send running reply in chat=%s", chat_id)

    def _run_polling(self) -> None:
        """Run telegram polling in a dedicated thread."""
        self._tg_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._tg_loop)
        try:
            # Cannot use run_polling() because it calls add_signal_handler(),
            # which only works in the main thread.  Instead, manually
            # initialize the application and start the updater.
            self._tg_loop.run_until_complete(self._application.initialize())
            self._tg_loop.run_until_complete(self._application.start())
            self._tg_loop.run_until_complete(self._application.updater.start_polling())
            self._tg_loop.run_forever()
        except Exception:
            if self._running:
                logger.exception("Telegram polling error")
        finally:
            # Graceful shutdown
            try:
                if self._application.updater.running:
                    self._tg_loop.run_until_complete(self._application.updater.stop())
                self._tg_loop.run_until_complete(self._application.stop())
                self._tg_loop.run_until_complete(self._application.shutdown())
            except Exception:
                logger.exception("Error during Telegram shutdown")

    def _check_user(self, user_id: int) -> bool:
        if not self._allowed_users:
            return True
        return user_id in self._allowed_users

    @staticmethod
    def _telegram_display_name(user) -> str:
        full_name = getattr(user, "full_name", None)
        if isinstance(full_name, str) and full_name:
            return full_name
        username = getattr(user, "username", None)
        if isinstance(username, str) and username:
            return username
        return str(getattr(user, "id", ""))

    async def _bind_connection_from_start_token(self, update, state_token: str) -> bool:
        if self._connection_repo is None or not state_token:
            return False

        state = await self._connection_repo.consume_oauth_state(provider="telegram", state=state_token)
        if state is None:
            await update.message.reply_text("Telegram connection link is invalid or expired.")
            return True

        owner_user_id = state["owner_user_id"]
        user_id = str(update.effective_user.id)
        chat_id = str(update.effective_chat.id)
        connection = await self._connection_repo.upsert_connection(
            owner_user_id=owner_user_id,
            provider="telegram",
            external_account_id=user_id,
            external_account_name=self._telegram_display_name(update.effective_user),
            workspace_id=chat_id,
            workspace_name=None,
            metadata={
                "chat_id": chat_id,
                "chat_type": update.effective_chat.type,
                "telegram_username": getattr(update.effective_user, "username", None),
            },
            status="connected",
        )
        logger.info("[Telegram] bound chat=%s user=%s to DeerFlow user=%s connection=%s", chat_id, user_id, owner_user_id, connection["id"])
        await update.message.reply_text("Telegram connected to DeerFlow.")
        return True

    async def _attach_connection_identity(self, inbound: InboundMessage) -> InboundMessage:
        return await attach_connection_identity(
            inbound,
            repo=self._connection_repo,
            provider="telegram",
            workspace_id=inbound.chat_id,
        )

    def _get_bot_username(self, context) -> str | None:
        bot = getattr(context, "bot", None)
        username = getattr(bot, "username", None)
        if not username and self._application is not None:
            username = getattr(getattr(self._application, "bot", None), "username", None)
        return str(username) if username else None

    @staticmethod
    def _strip_bot_username_from_leading_command(text: str, bot_username: str | None) -> str:
        username = (bot_username or "").lstrip("@").lower()
        if not username or not text.startswith("/"):
            return text

        parts = text.split(maxsplit=1)
        command_token = parts[0]
        if "@" not in command_token:
            return text

        command_name, addressed_username = command_token[1:].rsplit("@", 1)
        if not command_name or addressed_username.lower() != username:
            return text

        normalized = f"/{command_name}"
        if len(parts) > 1:
            normalized = f"{normalized} {parts[1]}"
        return normalized

    async def _cmd_start(self, update, context) -> None:
        """Handle /start command."""
        if not self._check_user(update.effective_user.id):
            return
        args = getattr(context, "args", []) if context is not None else []
        if args:
            handled = await self._bind_connection_from_start_token(update, str(args[0]))
            if handled:
                return
        await update.message.reply_text("Welcome to DeerFlow! Send me a message to start a conversation.\nType /help for available commands.")

    async def _process_incoming_with_reply(self, chat_id: str, msg_id: int, inbound: InboundMessage) -> None:
        await self._send_running_reply(chat_id, msg_id)
        await self.bus.publish_inbound(inbound)

    async def _cmd_generic(self, update, context) -> None:
        """Forward slash commands to the channel manager."""
        if not self._check_user(update.effective_user.id):
            return

        text = self._strip_bot_username_from_leading_command(update.message.text.strip(), self._get_bot_username(context))
        chat_id = str(update.effective_chat.id)
        user_id = str(update.effective_user.id)
        msg_id = str(update.message.message_id)

        # Use the same topic_id logic as _on_text so that commands
        # like /new target the correct thread mapping.
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
        inbound = await self._attach_connection_identity(inbound)

        if self._main_loop and self._main_loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(self._process_incoming_with_reply(chat_id, update.message.message_id, inbound), self._main_loop)
            fut.add_done_callback(lambda f: self._log_future_error(f, "process_incoming_with_reply", update.message.message_id))
        else:
            logger.warning("[Telegram] Main loop not running. Cannot publish inbound message.")

    async def _on_text(self, update, context) -> None:
        """Handle regular text messages."""
        if not self._check_user(update.effective_user.id):
            return

        text = self._strip_bot_username_from_leading_command(update.message.text.strip(), self._get_bot_username(context))
        if not text:
            return

        chat_id = str(update.effective_chat.id)
        user_id = str(update.effective_user.id)
        msg_id = str(update.message.message_id)

        # topic_id determines which DeerFlow thread the message maps to.
        # In private chats, use None so that all messages share a single
        # thread (the store key becomes "channel:chat_id").
        # In group chats, use the reply-to message id or the current
        # message id to keep separate conversation threads.
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
        inbound = await self._attach_connection_identity(inbound)

        if self._main_loop and self._main_loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(self._process_incoming_with_reply(chat_id, update.message.message_id, inbound), self._main_loop)
            fut.add_done_callback(lambda f: self._log_future_error(f, "process_incoming_with_reply", update.message.message_id))
        else:
            logger.warning("[Telegram] Main loop not running. Cannot publish inbound message.")
