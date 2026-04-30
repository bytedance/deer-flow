from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

from app.channels.base import Channel
from app.channels.message_bus import (
    InboundMessageType,
    MessageBus,
    OutboundMessage,
    ResolvedAttachment,
)

logger = logging.getLogger(__name__)


class WeComChannel(Channel):
    def __init__(self, bus: MessageBus, config: dict[str, Any]) -> None:
        super().__init__(name="wecom", bus=bus, config=config)
        self._bot_id: str | None = None
        self._bot_secret: str | None = None
        self._ws_client = None
        self._ws_task: asyncio.Task | None = None
        self._ws_frames: dict[str, dict[str, Any]] = {}
        self._ws_stream_ids: dict[str, str] = {}
        self._working_message = "Working on it..."

    @property
    def supports_streaming(self) -> bool:
        return True

    def _clear_ws_context(self, thread_ts: str | None) -> None:
        if not thread_ts:
            return
        self._ws_frames.pop(thread_ts, None)
        self._ws_stream_ids.pop(thread_ts, None)

    async def _send_ws_upload_command(self, req_id: str, body: dict[str, Any], cmd: str) -> dict[str, Any]:
        if not self._ws_client:
            raise RuntimeError("WeCom WebSocket client is not available")

        ws_manager = getattr(self._ws_client, "_ws_manager", None)
        send_reply = getattr(ws_manager, "send_reply", None)
        if not callable(send_reply):
            raise RuntimeError("Installed wecom-aibot-python-sdk does not expose the WebSocket media upload API expected by DeerFlow. Use wecom-aibot-python-sdk==0.1.6 or update the adapter.")

        send_reply_async = cast(Callable[[str, dict[str, Any], str], Awaitable[dict[str, Any]]], send_reply)
        return await send_reply_async(req_id, body, cmd)

    async def start(self) -> None:
        if self._running:
            return

        bot_id = self.config.get("bot_id")
        bot_secret = self.config.get("bot_secret")
        working_message = self.config.get("working_message")

        self._bot_id = bot_id if isinstance(bot_id, str) and bot_id else None
        self._bot_secret = bot_secret if isinstance(bot_secret, str) and bot_secret else None
        self._working_message = working_message if isinstance(working_message, str) and working_message else "Working on it..."

        if not self._bot_id or not self._bot_secret:
            logger.error("WeCom channel requires bot_id and bot_secret")
            return

        try:
            from aibot import WSClient, WSClientOptions
        except ImportError:
            logger.error("wecom-aibot-python-sdk is not installed. Install it with: uv add wecom-aibot-python-sdk")
            return
        else:
            self._ws_client = WSClient(WSClientOptions(bot_id=self._bot_id, secret=self._bot_secret, logger=logger))
            self._ws_client.on("message.text", self._on_ws_text)
            self._ws_client.on("message.mixed", self._on_ws_mixed)
            self._ws_client.on("message.image", self._on_ws_image)
            self._ws_client.on("message.file", self._on_ws_file)
            self._ws_task = asyncio.create_task(self._ws_client.connect())

            self._running = True
            self.bus.subscribe_outbound(self._on_outbound)
        logger.info("WeCom channel started")

    async def stop(self) -> None:
        self._running = False
        self.bus.unsubscribe_outbound(self._on_outbound)
        if self._ws_task:
            try:
                self._ws_task.cancel()
            except Exception:
                pass
            self._ws_task = None
        if self._ws_client:
            try:
                self._ws_client.disconnect()
            except Exception:
                pass
        self._ws_client = None
        self._ws_frames.clear()
        self._ws_stream_ids.clear()
        logger.info("WeCom channel stopped")

    async def send(self, msg: OutboundMessage, *, _max_retries: int = 3) -> None:
        if self._ws_client:
            await self._send_ws(msg, _max_retries=_max_retries)
            return
        logger.warning("[WeCom] send called but WebSocket client is not available")

    async def _on_outbound(self, msg: OutboundMessage) -> None:
        if msg.channel_name != self.name:
            return

        try:
            await self.send(msg)
        except Exception:
            logger.exception("Failed to send outbound message on channel %s", self.name)
            if msg.is_final:
                self._clear_ws_context(msg.thread_ts)
            return

        for attachment in msg.attachments:
            try:
                success = await self.send_file(msg, attachment)
                if not success:
                    logger.warning("[%s] file upload skipped for %s", self.name, attachment.filename)
            except Exception:
                logger.exception("[%s] failed to upload file %s", self.name, attachment.filename)

        if msg.is_final:
            self._clear_ws_context(msg.thread_ts)

    async def send_file(self, msg: OutboundMessage, attachment: ResolvedAttachment) -> bool:
        if not msg.is_final:
            return True
        if not self._ws_client:
            return False
        if not msg.thread_ts:
            return False
        frame = self._ws_frames.get(msg.thread_ts)
        if not frame:
            return False

        media_type = "image" if attachment.is_image else "file"
        size_limit = 2 * 1024 * 1024 if attachment.is_image else 20 * 1024 * 1024
        if attachment.size > size_limit:
            logger.warning(
                "[WeCom] %s too large (%d bytes), skipping: %s",
                media_type,
                attachment.size,
                attachment.filename,
            )
            return False

        try:
            media_id = await self._upload_media_ws(
                media_type=media_type,
                filename=attachment.filename,
                path=str(attachment.actual_path),
                size=attachment.size,
            )
            if not media_id:
                return False

            body = {media_type: {"media_id": media_id}, "msgtype": media_type}
            await self._ws_client.reply(frame, body)
            logger.debug("[WeCom] %s sent via ws: %s", media_type, attachment.filename)
            return True
        except Exception:
            logger.exception("[WeCom] failed to upload/send file via ws: %s", attachment.filename)
            return False

    async def _on_ws_text(self, frame: dict[str, Any]) -> None:
        body = frame.get("body", {}) or {}
        text = ((body.get("text") or {}).get("content") or "").strip()
        quote = body.get("quote", {}).get("text", {}).get("content", "").strip()
        if not text and not quote:
            return
        await self._publish_ws_inbound(frame, text + (f"\nQuote message: {quote}" if quote else ""))

    async def _on_ws_mixed(self, frame: dict[str, Any]) -> None:
        body = frame.get("body", {}) or {}
        mixed = body.get("mixed") or {}
        items = mixed.get("msg_item") or []
        parts: list[str] = []
        files: list[dict[str, Any]] = []
        for item in items:
            item_type = (item or {}).get("msgtype")
            if item_type == "text":
                content = (((item or {}).get("text") or {}).get("content") or "").strip()
                if content:
                    parts.append(content)
            elif item_type in ("image", "file"):
                payload = (item or {}).get(item_type) or {}
                url = payload.get("url")
                aeskey = payload.get("aeskey")
                if isinstance(url, str) and url:
                    files.append(
                        {
                            "type": item_type,
                            "url": url,
                            "aeskey": (aeskey if isinstance(aeskey, str) and aeskey else None),
                        }
                    )
        text = "\n\n".join(parts).strip()
        if not text and not files:
            return
        if not text:
            text = "（receive image/file）"
        await self._publish_ws_inbound(frame, text, files=files)

    async def _on_ws_image(self, frame: dict[str, Any]) -> None:
        body = frame.get("body", {}) or {}
        image = body.get("image") or {}
        url = image.get("url")
        aeskey = image.get("aeskey")
        if not isinstance(url, str) or not url:
            return
        await self._publish_ws_inbound(
            frame,
            "（receive image ）",
            files=[
                {
                    "type": "image",
                    "url": url,
                    "aeskey": aeskey if isinstance(aeskey, str) and aeskey else None,
                }
            ],
        )

    async def _on_ws_file(self, frame: dict[str, Any]) -> None:
        body = frame.get("body", {}) or {}
        file_obj = body.get("file") or {}
        url = file_obj.get("url")
        aeskey = file_obj.get("aeskey")
        if not isinstance(url, str) or not url:
            return
        await self._publish_ws_inbound(
            frame,
            "（receive file）",
            files=[
                {
                    "type": "file",
                    "url": url,
                    "aeskey": aeskey if isinstance(aeskey, str) and aeskey else None,
                }
            ],
        )

    async def _publish_ws_inbound(
        self,
        frame: dict[str, Any],
        text: str,
        *,
        files: list[dict[str, Any]] | None = None,
    ) -> None:
        if not self._ws_client:
            return
        try:
            from aibot import generate_req_id
        except Exception:
            return

        body = frame.get("body", {}) or {}
        msg_id = body.get("msgid")
        if not msg_id:
            return

        user_id = (body.get("from") or {}).get("userid")

        inbound_type = InboundMessageType.COMMAND if text.startswith("/") else InboundMessageType.CHAT
        inbound = self._make_inbound(
            chat_id=user_id,  # keep user's conversation in memory
            user_id=user_id,
            text=text,
            msg_type=inbound_type,
            thread_ts=msg_id,
            files=files or [],
            metadata={"aibotid": body.get("aibotid"), "chattype": body.get("chattype")},
        )
        inbound.topic_id = user_id  # keep the same thread

        stream_id = generate_req_id("stream")
        self._ws_frames[msg_id] = frame
        self._ws_stream_ids[msg_id] = stream_id

        try:
            await self._ws_client.reply_stream(frame, stream_id, self._working_message, False)
        except Exception:
            pass

        await self.bus.publish_inbound(inbound)

    async def _send_ws(self, msg: OutboundMessage, *, _max_retries: int = 3) -> None:
        if not self._ws_client:
            return
        try:
            from aibot import generate_req_id
        except Exception:
            generate_req_id = None

        if msg.thread_ts and msg.thread_ts in self._ws_frames:
            frame = self._ws_frames[msg.thread_ts]
            stream_id = self._ws_stream_ids.get(msg.thread_ts)
            if not stream_id and generate_req_id:
                stream_id = generate_req_id("stream")
                self._ws_stream_ids[msg.thread_ts] = stream_id
            if not stream_id:
                return

            last_exc: Exception | None = None
            for attempt in range(_max_retries):
                try:
                    await self._ws_client.reply_stream(frame, stream_id, msg.text, bool(msg.is_final))
                    return
                except Exception as exc:
                    last_exc = exc
                    if attempt < _max_retries - 1:
                        await asyncio.sleep(2**attempt)
            if last_exc:
                raise last_exc

        body = {"msgtype": "markdown", "markdown": {"content": msg.text}}
        last_exc = None
        for attempt in range(_max_retries):
            try:
                await self._ws_client.send_message(msg.chat_id, body)
                return
            except Exception as exc:
                last_exc = exc
                if attempt < _max_retries - 1:
                    await asyncio.sleep(2**attempt)
        if last_exc:
            raise last_exc

    async def _upload_media_ws(
        self,
        *,
        media_type: str,
        filename: str,
        path: str,
        size: int,
    ) -> str | None:
        if not self._ws_client:
            return None
        try:
            from aibot import generate_req_id
        except Exception:
            return None

        chunk_size = 512 * 1024
        total_chunks = (size + chunk_size - 1) // chunk_size
        if total_chunks < 1 or total_chunks > 100:
            logger.warning("[WeCom] invalid total_chunks=%d for %s", total_chunks, filename)
            return None

        md5_hasher = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                md5_hasher.update(chunk)
        md5 = md5_hasher.hexdigest()

        init_req_id = generate_req_id("aibot_upload_media_init")
        init_body = {
            "type": media_type,
            "filename": filename,
            "total_size": int(size),
            "total_chunks": int(total_chunks),
            "md5": md5,
        }
        init_ack = await self._send_ws_upload_command(init_req_id, init_body, "aibot_upload_media_init")
        upload_id = (init_ack.get("body") or {}).get("upload_id")
        if not upload_id:
            logger.warning("[WeCom] upload init returned no upload_id: %s", init_ack)
            return None

        with open(path, "rb") as f:
            for idx in range(total_chunks):
                data = f.read(chunk_size)
                if not data:
                    break
                chunk_req_id = generate_req_id("aibot_upload_media_chunk")
                chunk_body = {
                    "upload_id": upload_id,
                    "chunk_index": int(idx),
                    "base64_data": base64.b64encode(data).decode("utf-8"),
                }
                await self._send_ws_upload_command(chunk_req_id, chunk_body, "aibot_upload_media_chunk")

        finish_req_id = generate_req_id("aibot_upload_media_finish")
        finish_ack = await self._send_ws_upload_command(finish_req_id, {"upload_id": upload_id}, "aibot_upload_media_finish")
        media_id = (finish_ack.get("body") or {}).get("media_id")
        if not media_id:
            logger.warning("[WeCom] upload finish returned no media_id: %s", finish_ack)
            return None
        return media_id
