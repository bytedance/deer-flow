"""Matrix channel implementation for DeerFlow."""

from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
from collections import deque
from typing import Any
from urllib.parse import quote

import aiohttp
import markdown

from app.channels.base import Channel
from app.channels.message_bus import InboundMessageType, OutboundMessage, ResolvedAttachment

logger = logging.getLogger(__name__)

# 支持的消息类型：纯文本 + 媒体文件
SUPPORTED_MSGTYPES = {"m.text", "m.file", "m.image", "m.video", "m.audio"}
MEDIA_DOWNLOAD_PATHS = (
    "/_matrix/media/v3/download/{server_name}/{media_id}",
    "/_matrix/media/r0/download/{server_name}/{media_id}",
    "/_matrix/client/v1/media/download/{server_name}/{media_id}",
)


class MatrixChannel(Channel):
    """Matrix channel implementation."""

    def __init__(self, bus, config):
        super().__init__("matrix", bus, config)
        self.homeserver = str(config.get("homeserver") or "").rstrip("/")
        self.access_token = config.get("access_token")
        self.user_id = config.get("user_id")
        self.device_id = config.get("device_id", "DeerFlowBot")
        self.next_batch = None
        self.session = None
        self.sync_task = None
        self.allowed_users = self._normalize_allowed_values(config.get("allowed_users"))
        self.allowed_rooms = self._normalize_allowed_values(config.get("allowed_rooms"))
        self.processed_events = deque(maxlen=1000)
        self._processed_event_ids: set[str] = set()

    @staticmethod
    def _normalize_allowed_values(value: Any) -> set[str]:
        if value in (None, "", []):
            return set()
        if isinstance(value, str):
            return {item.strip() for item in value.split(",") if item.strip()}
        if isinstance(value, (list, tuple, set)):
            return {str(item).strip() for item in value if str(item).strip()}
        return {str(value).strip()}

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _remember_event(self, event_id: str) -> bool:
        if event_id in self._processed_event_ids:
            return False
        if len(self.processed_events) == self.processed_events.maxlen:
            oldest = self.processed_events.popleft()
            self._processed_event_ids.discard(oldest)
        self.processed_events.append(event_id)
        self._processed_event_ids.add(event_id)
        return True

    def _ensure_configured(self) -> None:
        missing = []
        if not self.homeserver:
            missing.append("homeserver")
        if not self.access_token:
            missing.append("access_token")
        if not self.user_id:
            missing.append("user_id")
        if missing:
            raise RuntimeError(f"Matrix channel missing required config: {', '.join(missing)}")

    async def _validate_connection(self) -> None:
        whoami_url = f"{self.homeserver}/_matrix/client/v3/account/whoami"
        timeout = aiohttp.ClientTimeout(total=15)
        async with self.session.get(whoami_url, headers=self._auth_headers(), timeout=timeout) as resp:
            if not resp.ok:
                raise RuntimeError(f"Matrix whoami failed with status {resp.status}: {await resp.text()}")
            data = await resp.json()
        actual_user_id = data.get("user_id")
        if actual_user_id and self.user_id and actual_user_id != self.user_id:
            raise RuntimeError(f"Matrix user mismatch: configured {self.user_id}, got {actual_user_id}")

    async def _initial_sync(self) -> None:
        url = f"{self.homeserver}/_matrix/client/v3/sync"
        params = {"timeout": "0", "full_state": "false"}
        timeout = aiohttp.ClientTimeout(total=30)
        async with self.session.get(url, headers=self._auth_headers(), params=params, timeout=timeout) as resp:
            if not resp.ok:
                raise RuntimeError(f"Matrix initial sync failed with status {resp.status}: {await resp.text()}")
            data = await resp.json()
        self.next_batch = data.get("next_batch")
        if not self.next_batch:
            raise RuntimeError("Matrix initial sync did not return next_batch")
        logger.info("Matrix initial sync complete, next_batch=%s...", self.next_batch[:20])

    async def start(self) -> None:
        """Start listening for Matrix messages."""
        if self._running:
            return

        self._ensure_configured()
        logger.info("Starting Matrix channel...")
        self.session = aiohttp.ClientSession()
        try:
            await self._validate_connection()
            await self._initial_sync()
        except Exception:
            if self.session:
                await self.session.close()
                self.session = None
            raise

        self._running = True
        self.bus.subscribe_outbound(self._on_outbound)
        self.sync_task = asyncio.create_task(self._sync_loop())
        logger.info("Matrix channel started successfully")

    async def stop(self) -> None:
        """Stop the Matrix channel."""
        if not self._running and not self.session:
            return

        logger.info("Stopping Matrix channel...")
        self._running = False
        self.bus.unsubscribe_outbound(self._on_outbound)
        if self.sync_task:
            self.sync_task.cancel()
            try:
                await self.sync_task
            except asyncio.CancelledError:
                pass
            self.sync_task = None
        if self.session:
            await self.session.close()
            self.session = None
        logger.info("Matrix channel stopped successfully")

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message to Matrix."""
        url = f"{self.homeserver}/_matrix/client/v3/rooms/{msg.chat_id}/send/m.room.message/{int(asyncio.get_event_loop().time() * 1000)}"

        html_body = markdown.markdown(msg.text, extensions=["fenced_code", "tables"])

        content = {
            "msgtype": "m.text",
            "body": msg.text,
            "format": "org.matrix.custom.html",
            "formatted_body": html_body,
        }
        logger.debug(f"Matrix HTML body: {html_body}")

        if msg.thread_ts:
            content["m.relates_to"] = {
                "rel_type": "m.thread",
                "event_id": msg.thread_ts,
                "is_falling_back": True,
                "m.in_reply_to": {
                    "event_id": msg.thread_ts,
                },
            }

        logger.info(f"Sending Matrix message to room {msg.chat_id}: {msg.text[:50]}...")

        async with self.session.put(
            url,
            headers=self._auth_headers(),
            json=content,
        ) as resp:
            if not resp.ok:
                logger.error(f"Failed to send Matrix message: {await resp.text()}")
                raise Exception(f"Matrix API error: {resp.status}")
        logger.info(f"Matrix message sent successfully to room {msg.chat_id}")

    async def send_file(self, msg: OutboundMessage, attachment: ResolvedAttachment) -> bool:
        """Upload and send a file to Matrix."""
        try:
            file_content = attachment.actual_path.read_bytes()

            upload_url = f"{self.homeserver}/_matrix/media/v3/upload?filename={attachment.filename}"
            async with self.session.post(
                upload_url,
                headers={
                    **self._auth_headers(),
                    "Content-Type": attachment.mime_type,
                },
                data=file_content,
            ) as upload_resp:
                if not upload_resp.ok:
                    logger.error(f"Failed to upload file to Matrix: {await upload_resp.text()}")
                    return False
                upload_data = await upload_resp.json()
                mxc_uri = upload_data["content_uri"]

            msg_url = f"{self.homeserver}/_matrix/client/v3/rooms/{msg.chat_id}/send/m.room.message/{int(asyncio.get_event_loop().time() * 1000)}"

            content = {
                "msgtype": "m.file" if not attachment.mime_type.startswith("image/") else "m.image",
                "body": attachment.filename,
                "url": mxc_uri,
                "info": {
                    "mimetype": attachment.mime_type,
                    "size": len(file_content),
                },
            }

            if msg.thread_ts:
                content["m.relates_to"] = {
                    "rel_type": "m.thread",
                    "event_id": msg.thread_ts,
                    "is_falling_back": True,
                    "m.in_reply_to": {
                        "event_id": msg.thread_ts,
                    },
                }

            async with self.session.put(
                msg_url,
                headers=self._auth_headers(),
                json=content,
            ) as msg_resp:
                return msg_resp.ok

        except Exception as e:
            logger.exception(f"Failed to send file to Matrix: {e}")
            return False

    def _parse_mxc_uri(self, mxc_uri: str) -> tuple[str, str] | None:
        if not mxc_uri.startswith("mxc://"):
            return None
        parts = mxc_uri[6:].split("/", 1)
        if len(parts) != 2:
            return None
        server_name, media_id = parts
        if not server_name or not media_id:
            return None
        return server_name, media_id

    def _media_download_urls(self, mxc_uri: str) -> list[str]:
        parsed = self._parse_mxc_uri(mxc_uri)
        if not parsed:
            return []
        server_name, media_id = parsed
        encoded_server = quote(server_name, safe="")
        encoded_media = quote(media_id, safe="")
        return [f"{self.homeserver}{path.format(server_name=encoded_server, media_id=encoded_media)}" for path in MEDIA_DOWNLOAD_PATHS]

    async def _download_media(self, mxc_uri: str) -> tuple[bytes | None, str]:
        download_urls = self._media_download_urls(mxc_uri)
        if not download_urls:
            logger.warning("Invalid mxc URI: %s", mxc_uri)
            return None, ""

        timeout = aiohttp.ClientTimeout(total=60)
        for download_url in download_urls:
            try:
                async with self.session.get(
                    download_url,
                    headers=self._auth_headers(),
                    timeout=timeout,
                ) as resp:
                    if not resp.ok:
                        logger.info("Matrix media download miss: %s (status=%d)", download_url, resp.status)
                        continue
                    content = await resp.read()
                    content_type = resp.headers.get("Content-Type", "application/octet-stream")
                    mimetype = content_type.split(";")[0].strip()
                    return content, mimetype
            except Exception as e:
                logger.warning("Matrix media download request error for %s: %s", download_url, e)

        logger.warning("Matrix media download failed on all endpoints for %s", mxc_uri)
        return None, ""

    async def _handle_message_event(self, room_id: str, event: dict) -> None:
        """处理单条 Matrix 消息事件（文本或文件）。"""
        content = event["content"]
        msgtype = content.get("msgtype", "")

        if msgtype not in SUPPORTED_MSGTYPES:
            return

        event_id = event["event_id"]
        if not self._remember_event(event_id):
            return

        # 解析 thread_ts（线程回复）
        thread_ts = None
        relates_to = content.get("m.relates_to")
        if relates_to:
            if relates_to.get("rel_type") == "m.thread":
                thread_ts = relates_to.get("event_id")
            elif relates_to.get("m.in_reply_to"):
                thread_ts = relates_to["m.in_reply_to"].get("event_id")

        # 标记消息已读
        try:
            read_url = f"{self.homeserver}/_matrix/client/v3/rooms/{room_id}/receipt/m.read/{event_id}"
            async with self.session.post(
                read_url,
                headers=self._auth_headers(),
                json={},
            ):
                pass
        except Exception as e:
            logger.warning("Failed to mark message as read: %s", e)

        # 根据消息类型处理
        if msgtype == "m.text":
            await self._handle_text_message(room_id, event, thread_ts, event_id)
        elif msgtype in ("m.file", "m.image", "m.video", "m.audio"):
            await self._handle_media_message(room_id, event, thread_ts, event_id, msgtype)

    async def _handle_text_message(self, room_id: str, event: dict, thread_ts: str | None, event_id: str) -> None:
        """处理纯文本消息。"""
        inbound_text = event["content"]["body"].strip()
        msg_type = InboundMessageType.COMMAND if inbound_text.startswith("/") else InboundMessageType.CHAT
        inbound_msg = self._make_inbound(
            chat_id=room_id,
            user_id=event["sender"],
            text=inbound_text,
            msg_type=msg_type,
            thread_ts=thread_ts,
            metadata={"event_id": event_id},
        )
        await self.bus.publish_inbound(inbound_msg)

    async def _handle_media_message(self, room_id: str, event: dict, thread_ts: str | None, event_id: str, msgtype: str) -> None:
        """处理文件/图片/视频/音频消息。

        下载文件内容，构建设文件描述文本，将文件信息传入 InboundMessage.files。
        """
        content = event["content"]
        mxc_uri = content.get("url", "")
        if not mxc_uri:
            logger.warning("Media message without url: event_id=%s", event_id)
            return

        # 下载文件
        file_content, mimetype = await self._download_media(mxc_uri)
        if file_content is None:
            # 下载失败，仍然通知用户有文件但无法获取
            body = content.get("body", "unknown file")
            inbound_msg = self._make_inbound(
                chat_id=room_id,
                user_id=event["sender"],
                text=f"[文件: {body} - 下载失败]",
                msg_type=InboundMessageType.CHAT,
                thread_ts=thread_ts,
                metadata={"event_id": event_id},
            )
            await self.bus.publish_inbound(inbound_msg)
            return

        # 提取文件元数据
        info = content.get("info", {})
        filename = content.get("filename") or content.get("body", "unnamed_file")
        size = info.get("size", len(file_content))
        # 如果 info 中没有 mimetype，使用下载响应的 mimetype
        if not mimetype:
            mimetype = info.get("mimetype", "application/octet-stream")

        # 如果没有文件扩展名，根据 mimetype 推断
        if "." not in filename:
            ext = mimetypes.guess_extension(mimetype) or ""
            if ext:
                filename += ext

        # 构建人类可读的消息描述
        type_label = {"m.file": "文件", "m.image": "图片", "m.video": "视频", "m.audio": "音频"}
        label = type_label.get(msgtype, "文件")
        size_kb = size / 1024
        size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
        text = f"[{label}: {filename} ({size_str})]"

        # 将文件内容编码为 base64 以便传递
        file_b64 = base64.b64encode(file_content).decode("ascii")

        inbound_msg = self._make_inbound(
            chat_id=room_id,
            user_id=event["sender"],
            text=text,
            msg_type=InboundMessageType.CHAT,
            thread_ts=thread_ts,
            files=[
                {
                    "filename": filename,
                    "mimetype": mimetype,
                    "size": size,
                    "content_base64": file_b64,
                }
            ],
            metadata={"event_id": event_id, "msgtype": msgtype},
        )
        await self.bus.publish_inbound(inbound_msg)
        logger.info("Matrix media message processed: type=%s, file=%s, size=%d", msgtype, filename, size)

    async def _sync_loop(self) -> None:
        """Main sync loop for Matrix events."""
        logger.info("Matrix sync loop started")
        while self._running:
            try:
                url = f"{self.homeserver}/_matrix/client/v3/sync"
                params = {"timeout": "30000", "full_state": "false"}
                if self.next_batch:
                    params["since"] = self.next_batch

                logger.info(f"Matrix sync request: next_batch={self.next_batch[:20] if self.next_batch else 'None'}...")
                async with self.session.get(
                    url,
                    headers=self._auth_headers(),
                    params=params,
                ) as resp:
                    if not resp.ok:
                        logger.error(f"Matrix sync failed: {resp.status}")
                        await asyncio.sleep(1)
                        continue

                    data = await resp.json()
                    self.next_batch = data.get("next_batch")
                    logger.info(f"Matrix sync complete: next_batch={self.next_batch[:20] if self.next_batch else 'None'}...")

                    if data.get("rooms", {}).get("invite"):
                        for room_id in data["rooms"]["invite"]:
                            if self.allowed_rooms and room_id not in self.allowed_rooms:
                                logger.info("Ignoring Matrix invite for disallowed room %s", room_id)
                                continue
                            logger.info(f"Accepting Matrix invite to room {room_id}")
                            join_url = f"{self.homeserver}/_matrix/client/v3/rooms/{room_id}/join"
                            async with self.session.post(
                                join_url,
                                headers=self._auth_headers(),
                                json={},
                            ):
                                pass

                    if data.get("rooms", {}).get("join"):
                        for room_id, room_data in data["rooms"]["join"].items():
                            if self.allowed_rooms and room_id not in self.allowed_rooms:
                                continue
                            events = room_data.get("timeline", {}).get("events", [])
                            for event in events:
                                if event["type"] != "m.room.message":
                                    continue
                                if event["sender"] == self.user_id:
                                    continue
                                if self.allowed_users and event["sender"] not in self.allowed_users:
                                    continue

                                await self._handle_message_event(room_id, event)

            except Exception as e:
                logger.exception(f"Matrix sync error: {e}")
                await asyncio.sleep(1)
