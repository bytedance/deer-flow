"""Telegram channel — connects via long-polling (no public IP needed)."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Coroutine
from typing import Any

from app.channels.base import Channel
from app.channels.connection_identity import attach_connection_identity
from app.channels.message_bus import (
    INBOUND_FILE_CONTENT_KEY,
    InboundMessage,
    InboundMessageType,
    InboundReservation,
    MessageBus,
    OutboundMessage,
    ResolvedAttachment,
)
from deerflow.uploads.manager import is_upload_staging_file, normalize_filename

logger = logging.getLogger(__name__)

TELEGRAM_MAX_MESSAGE_LENGTH = 4096
TELEGRAM_MAX_RICH_MESSAGE_LENGTH = 32768
# Telegram's hosted Bot API documents this as 20 MB (decimal bytes).
TELEGRAM_MAX_INBOUND_FILE_BYTES = 20_000_000
# Keep Telegram cleanup inside the Gateway's five-second shutdown-hook budget.
TELEGRAM_SHUTDOWN_TIMEOUT_SECONDS = 4.0
TELEGRAM_BRIDGE_DRAIN_TIMEOUT_SECONDS = 1.0
STREAM_EDIT_MIN_INTERVAL_SECONDS = 1.0
# Groups (negative chat_id) are capped at 20 messages/minute by Telegram,
# so stream edits there must pace well below the private-chat 1 msg/s guideline.
STREAM_EDIT_GROUP_MIN_INTERVAL_SECONDS = 3.0
# Bound on tracked in-flight streamed messages; entries normally clear on the
# final update, this only guards against leaks when a final never arrives.
MAX_TRACKED_STREAM_MESSAGES = 256

# Indirection so tests can patch the clock without touching the global time module.
_monotonic = time.monotonic


def _load_telegram_input_file(path, filename: str):
    from telegram import InputFile

    return InputFile(path.read_bytes(), filename=filename)


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
        # Tasks submitted from the main dispatcher loop back to PTB's loop.
        # Only the Telegram loop mutates this set.
        self._tg_bridge_tasks: set[asyncio.Task[Any]] = set()
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
        self._open_threadsafe_future_intake()
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
        app.add_handler(CommandHandler("goal", self._cmd_generic))
        app.add_handler(CommandHandler("help", self._cmd_generic))

        # Slash skill commands are dynamic and cannot all be pre-registered
        # with Telegram, so route unknown slash commands through chat handling.
        app.add_handler(MessageHandler(filters.TEXT & filters.COMMAND, self._on_text))

        # General message handler
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))

        # Telegram keeps attachment captions separate from message.text, and
        # photo/document updates do not match filters.TEXT.
        app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, self._on_text))

        self._application = app

        # Run polling in a dedicated thread with its own event loop
        self._thread = threading.Thread(target=self._run_polling, daemon=True)
        self._thread.start()
        logger.info("Telegram channel started")

    async def stop(self) -> None:
        self._running = False
        self.bus.unsubscribe_outbound(self._on_outbound)
        await self._close_and_drain_threadsafe_futures()
        shutdown_loop = asyncio.get_running_loop()
        deadline = shutdown_loop.time() + TELEGRAM_SHUTDOWN_TIMEOUT_SECONDS
        telegram_loop = self._tg_loop
        worker_thread = self._thread

        try:
            if telegram_loop and telegram_loop.is_running():
                drain_future = asyncio.run_coroutine_threadsafe(self._cancel_telegram_bridge_tasks(), telegram_loop)
                try:
                    remaining = max(0.0, deadline - shutdown_loop.time())
                    await asyncio.wait_for(asyncio.wrap_future(drain_future), timeout=remaining)
                except asyncio.CancelledError:
                    drain_future.cancel()
                    raise
                except TimeoutError:
                    drain_future.cancel()
                    logger.warning("[Telegram] timed out cancelling inbound file downloads during shutdown")
                except Exception as exc:
                    logger.warning("[Telegram] failed to cancel inbound file downloads during shutdown: %s", type(exc).__name__)
        finally:
            if telegram_loop and telegram_loop.is_running():
                try:
                    telegram_loop.call_soon_threadsafe(telegram_loop.stop)
                except RuntimeError:
                    pass
            try:
                if worker_thread is not None and worker_thread.is_alive():
                    remaining = max(0.0, deadline - shutdown_loop.time())
                    if remaining:
                        try:
                            await asyncio.wait_for(
                                asyncio.to_thread(worker_thread.join, remaining),
                                timeout=remaining,
                            )
                        except TimeoutError:
                            logger.warning("[Telegram] polling thread did not stop within the shutdown budget")
            finally:
                if worker_thread is not None and worker_thread.is_alive():
                    logger.warning("[Telegram] polling thread is still exiting after bounded shutdown")
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
            if self._can_send_rich(msg.text) and await self._edit_rich_message(chat_id, state["message_id"], msg.text):
                self._last_bot_message[msg.chat_id] = state["message_id"]
                return
            await self._finalize_stream_message(chat_id, msg.chat_id, state, msg.text)
            return

        if self._can_send_rich(msg.text):
            try:
                message_id = await self._send_new_rich_message(chat_id, msg.chat_id, msg.text, _max_retries=_max_retries)
            except Exception as exc:
                logger.warning("[Telegram] Rich Message send failed in chat=%s; falling back to plain text: %s", chat_id, exc)
                message_id = None
            if message_id is not None:
                return

        for chunk in self._split_message(msg.text):
            await self._send_new_message(chat_id, msg.chat_id, chunk, _max_retries=_max_retries)

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

    def _can_send_rich(self, text: str) -> bool:
        return bool(self.config.get("rich_messages")) and 0 < len(text) <= TELEGRAM_MAX_RICH_MESSAGE_LENGTH

    async def _edit_rich_message(self, chat_id: int, message_id: int, text: str) -> bool:
        """Replace a streamed preview with a persistent Telegram Rich Message."""
        from telegram.error import BadRequest, EndPointNotFound

        bot = self._application.bot
        data = {"chat_id": chat_id, "message_id": message_id, "rich_message": {"markdown": text}}
        for attempt in range(2):
            try:
                await bot.do_api_request("editMessageText", api_kwargs=data)
                return True
            except Exception as exc:
                if self._is_retry_after(exc) and attempt == 0:
                    await asyncio.sleep(self._retry_after_seconds(exc))
                    continue
                if isinstance(exc, (BadRequest, EndPointNotFound)):
                    logger.warning("[Telegram] Rich Message rejected in chat=%s; falling back to plain text: %s", chat_id, exc)
                    return False
                logger.warning("[Telegram] final rich edit failed in chat=%s: %s", chat_id, exc)
                return False
        return False

    async def _send_new_rich_message(self, chat_id: int, chat_key: str, text: str, *, _max_retries: int) -> int | None:
        """Send raw agent Markdown through Bot API 10.1 Rich Messages."""
        from telegram.error import BadRequest, EndPointNotFound

        bot = self._application.bot

        async def send_message() -> int | None:
            try:
                result = await bot.do_api_request(
                    "sendRichMessage",
                    api_kwargs={"chat_id": chat_id, "rich_message": {"markdown": text}},
                )
            except (BadRequest, EndPointNotFound) as exc:
                logger.warning("[Telegram] Rich Message rejected in chat=%s; falling back to plain text: %s", chat_id, exc)
                return None
            message_id = int(result["message_id"])
            self._last_bot_message[chat_key] = message_id
            return message_id

        return await self._send_with_retry(send_message, max_retries=_max_retries, log_prefix="[Telegram]")

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
            input_file = await asyncio.to_thread(_load_telegram_input_file, attachment.actual_path, attachment.filename)
            if attachment.is_image and attachment.size <= 10 * 1024 * 1024:
                kwargs: dict[str, Any] = {"chat_id": chat_id, "photo": input_file}
                if reply_to:
                    kwargs["reply_to_message_id"] = reply_to
                sent = await bot.send_photo(**kwargs)
            else:
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

    async def receive_file(self, msg: InboundMessage, thread_id: str, *, user_id: str | None = None) -> InboundMessage:
        """Download inbound Telegram attachments for the shared upload pipeline.

        The Bot API download URL contains the bot token, so this adapter never
        exposes that URL to ``InboundMessage`` or logs. Instead it hands the
        downloaded bytes to ``ChannelManager`` through a short-lived private
        field that the manager consumes before persisting safe upload metadata.
        """
        # Owner/thread scoping is intentionally applied by ChannelManager when
        # it persists these bytes through _ingest_inbound_files().
        del thread_id, user_id
        if not msg.files:
            return msg

        bot = self._application.bot if self._application is not None else None
        materialized: list[dict[str, Any]] = []
        unavailable: list[str] = []

        for file_info in msg.files:
            if not isinstance(file_info, dict):
                continue

            filename = self._safe_inbound_filename(file_info.get("filename"), "attachment")
            file_id = file_info.get("file_id") if isinstance(file_info.get("file_id"), str) else ""
            declared_size = self._file_size(file_info.get("size"))
            if declared_size is not None and declared_size > TELEGRAM_MAX_INBOUND_FILE_BYTES:
                logger.warning("[Telegram] inbound file exceeds 20 MB download limit, skipping: %s", filename)
                unavailable.append(f"{filename} (exceeds the 20 MB download limit)")
                continue

            if bot is None or not file_id:
                logger.error("[Telegram] cannot download inbound file: %s", filename)
                unavailable.append(f"{filename} (download unavailable)")
                continue

            try:
                resolved_size, content = await self._run_on_telegram_loop(self._download_inbound_file(bot, file_id))
            except Exception as exc:
                # Exception strings from HTTP clients can contain request URLs.
                # Log only the class name so a Bot API token can never leak.
                logger.error("[Telegram] failed to download inbound file %s: %s", filename, type(exc).__name__)
                unavailable.append(f"{filename} (download failed)")
                continue

            if content is None:
                logger.warning("[Telegram] resolved inbound file exceeds 20 MB download limit, skipping: %s", filename)
                unavailable.append(f"{filename} (exceeds the 20 MB download limit)")
                continue

            if len(content) > TELEGRAM_MAX_INBOUND_FILE_BYTES:
                logger.warning("[Telegram] downloaded inbound file exceeds 20 MB limit, skipping: %s", filename)
                unavailable.append(f"{filename} (exceeds the 20 MB download limit)")
                continue

            materialized.append(
                {
                    "type": "image" if file_info.get("type") == "image" else "file",
                    "filename": filename,
                    "mime_type": file_info.get("mime_type") if isinstance(file_info.get("mime_type"), str) else "application/octet-stream",
                    "size": len(content),
                    INBOUND_FILE_CONTENT_KEY: content,
                }
            )

        msg.files = materialized
        if unavailable:
            notice = f"[Telegram attachment unavailable: {', '.join(unavailable)}]"
            msg.text = f"{msg.text}\n\n{notice}" if msg.text else notice
        return msg

    # -- helpers -----------------------------------------------------------

    async def _download_inbound_file(self, bot: Any, file_id: str) -> tuple[int | None, bytearray | None]:
        """Fetch one file entirely on the event loop that owns PTB's HTTP client."""
        telegram_file = await bot.get_file(file_id)
        resolved_size = self._file_size(getattr(telegram_file, "file_size", None))
        if resolved_size is not None and resolved_size > TELEGRAM_MAX_INBOUND_FILE_BYTES:
            return resolved_size, None
        return resolved_size, await telegram_file.download_as_bytearray()

    async def _track_telegram_bridge_task(self, coroutine: Coroutine[Any, Any, Any]) -> Any:
        """Keep a main-loop submission visible to Telegram-loop shutdown."""
        task = asyncio.current_task()
        if task is None:
            coroutine.close()
            raise RuntimeError("Telegram bridge task is unavailable")
        self._tg_bridge_tasks.add(task)
        try:
            return await coroutine
        finally:
            self._tg_bridge_tasks.discard(task)

    async def _cancel_telegram_bridge_tasks(self) -> None:
        """Cancel and drain cross-loop PTB work before its event loop exits."""
        current = asyncio.current_task()
        pending = [task for task in self._tg_bridge_tasks if task is not current and not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            done, still_pending = await asyncio.wait(pending, timeout=TELEGRAM_BRIDGE_DRAIN_TIMEOUT_SECONDS)
            if done:
                await asyncio.gather(*done, return_exceptions=True)
            if still_pending:
                logger.warning("[Telegram] %d inbound file download task(s) did not cancel promptly", len(still_pending))

    async def _run_on_telegram_loop(self, coroutine: Coroutine[Any, Any, Any]) -> Any:
        """Await a PTB coroutine without using its HTTP client across event loops."""
        telegram_loop = self._tg_loop
        current_loop = asyncio.get_running_loop()
        if telegram_loop is None or telegram_loop is current_loop:
            return await coroutine

        if not telegram_loop.is_running():
            coroutine.close()
            raise RuntimeError("Telegram event loop is not running")

        tracked_coroutine = self._track_telegram_bridge_task(coroutine)
        try:
            future = asyncio.run_coroutine_threadsafe(tracked_coroutine, telegram_loop)
        except BaseException:
            # A concurrent shutdown can close the loop between the running
            # check and scheduling. Close the unscheduled coroutine explicitly.
            tracked_coroutine.close()
            coroutine.close()
            raise
        try:
            return await asyncio.wrap_future(future)
        except asyncio.CancelledError:
            future.cancel()
            raise

    @staticmethod
    def _stream_key(chat_id: str, thread_ts: str | None) -> str:
        return f"{chat_id}:{thread_ts or ''}"

    @staticmethod
    def _parse_message_id(value: str | None) -> int | None:
        try:
            return int(value) if value else None
        except (OverflowError, TypeError, ValueError):
            return None

    @staticmethod
    def _file_size(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            size = int(value)
        except (TypeError, ValueError):
            return None
        return size if size >= 0 else None

    @staticmethod
    def _safe_inbound_filename(value: Any, fallback: str) -> str:
        if not isinstance(value, str):
            return fallback
        try:
            candidate = normalize_filename(value.strip())
        except (UnicodeError, ValueError):
            return fallback
        if is_upload_staging_file(candidate) or any(ord(char) < 32 for char in candidate):
            return fallback
        return candidate

    @classmethod
    def _extract_inbound_files(cls, message: Any) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        message_id = str(getattr(message, "message_id", "message"))

        # Materialize the PTB sequence once. Test doubles and partially shaped
        # update objects can expose a truthy but empty iterable here.
        photo_sizes = tuple(getattr(message, "photo", None) or ())
        if photo_sizes:
            photo = max(
                photo_sizes,
                key=lambda item: (
                    (cls._file_size(getattr(item, "width", None)) or 0) * (cls._file_size(getattr(item, "height", None)) or 0),
                    cls._file_size(getattr(item, "file_size", None)) or 0,
                ),
            )
            file_id = getattr(photo, "file_id", None)
            if isinstance(file_id, str) and file_id:
                file_unique_id = getattr(photo, "file_unique_id", None)
                files.append(
                    {
                        "type": "image",
                        "file_id": file_id,
                        "file_unique_id": file_unique_id if isinstance(file_unique_id, str) else None,
                        "filename": f"telegram-photo-{message_id}.jpg",
                        "mime_type": "image/jpeg",
                        "size": cls._file_size(getattr(photo, "file_size", None)),
                    }
                )

        document = getattr(message, "document", None)
        document_id = getattr(document, "file_id", None) if document is not None else None
        if isinstance(document_id, str) and document_id:
            file_unique_id = getattr(document, "file_unique_id", None)
            mime_type = getattr(document, "mime_type", None)
            if not isinstance(mime_type, str) or not mime_type:
                mime_type = "application/octet-stream"
            # Avoid the lazy system MIME database lookup on the Telegram event
            # loop. The original name is preferred; an opaque extension is safe.
            fallback = f"telegram-document-{message_id}.bin"
            files.append(
                {
                    "type": "file",
                    "file_id": document_id,
                    "file_unique_id": file_unique_id if isinstance(file_unique_id, str) else None,
                    "filename": cls._safe_inbound_filename(getattr(document, "file_name", None), fallback),
                    "mime_type": mime_type,
                    "size": cls._file_size(getattr(document, "file_size", None)),
                }
            )

        return files

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
        application = self._application
        if application is None:
            return
        self._tg_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._tg_loop)
        try:
            # Cannot use run_polling() because it calls add_signal_handler(),
            # which only works in the main thread.  Instead, manually
            # initialize the application and start the updater.
            self._tg_loop.run_until_complete(application.initialize())
            self._tg_loop.run_until_complete(application.start())
            self._tg_loop.run_until_complete(application.updater.start_polling())
            self._tg_loop.run_forever()
        except Exception:
            if self._running:
                logger.exception("Telegram polling error")
        finally:
            # Graceful shutdown
            try:
                self._tg_loop.run_until_complete(self._cancel_telegram_bridge_tasks())
                if application.updater.running:
                    self._tg_loop.run_until_complete(application.updater.stop())
                self._tg_loop.run_until_complete(application.stop())
                self._tg_loop.run_until_complete(application.shutdown())
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
        args = getattr(context, "args", []) if context is not None else []
        if args:
            # Handle the deep-link bind token before applying allowed_users so a
            # browser-initiated bind can bootstrap a new external identity.
            handled = await self._bind_connection_from_start_token(update, str(args[0]))
            if handled:
                return
        if not self._check_user(update.effective_user.id):
            return
        await update.message.reply_text("Welcome to DeerFlow! Send me a message to start a conversation.\nType /help for available commands.")

    async def _process_incoming_with_reply(
        self,
        chat_id: str,
        msg_id: int,
        inbound: InboundMessage,
        *,
        reservation: InboundReservation | None = None,
    ) -> None:
        try:
            await self._send_running_reply(chat_id, msg_id)
            if reservation is None:
                await self.bus.publish_inbound(inbound)
            else:
                self._commit_reserved_inbound(reservation, inbound)
        finally:
            if reservation is not None:
                reservation.release()

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
            metadata={"message_id": msg_id},
        )
        inbound.topic_id = topic_id

        if self._main_loop and self._main_loop.is_running():
            reservation = self._reserve_inbound(inbound)
            if reservation is None:
                return
            try:
                inbound = await self._attach_connection_identity(inbound)
                scheduled = self._submit_threadsafe_coroutine(
                    self._process_incoming_with_reply(
                        chat_id,
                        update.message.message_id,
                        inbound,
                        reservation=reservation,
                    ),
                    self._main_loop,
                    name="process_incoming_with_reply",
                    msg_id=update.message.message_id,
                    reservation=reservation,
                )
                if not scheduled:
                    logger.info("[Telegram] main loop stopped before reserved command could be scheduled")
            except Exception:
                reservation.release()
                raise
        else:
            logger.warning("[Telegram] Main loop not running. Cannot publish inbound message.")

    async def _on_text(self, update, context) -> None:
        """Handle regular text, photo, and document messages."""
        if not self._check_user(update.effective_user.id):
            return

        message = update.message
        message_text = getattr(message, "text", None)
        caption = getattr(message, "caption", None)
        raw_text = message_text if isinstance(message_text, str) else caption if isinstance(caption, str) else ""
        text = raw_text.strip()
        if text:
            text = self._strip_bot_username_from_leading_command(text, self._get_bot_username(context))
        files = self._extract_inbound_files(message)
        if not text and not files:
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
            files=files,
            metadata={"message_id": msg_id},
        )
        inbound.topic_id = topic_id

        if self._main_loop and self._main_loop.is_running():
            reservation = self._reserve_inbound(inbound)
            if reservation is None:
                return
            try:
                inbound = await self._attach_connection_identity(inbound)
                scheduled = self._submit_threadsafe_coroutine(
                    self._process_incoming_with_reply(
                        chat_id,
                        update.message.message_id,
                        inbound,
                        reservation=reservation,
                    ),
                    self._main_loop,
                    name="process_incoming_with_reply",
                    msg_id=update.message.message_id,
                    reservation=reservation,
                )
                if not scheduled:
                    logger.info("[Telegram] main loop stopped before reserved inbound could be scheduled")
            except Exception:
                reservation.release()
                raise
        else:
            logger.warning("[Telegram] Main loop not running. Cannot publish inbound message.")
