"""WeChat channel — connects to iLink via long-polling."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import logging
import mimetypes
import secrets
import time
from collections.abc import Mapping
from enum import IntEnum
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.channels.base import Channel
from app.channels.message_bus import InboundMessageType, MessageBus, OutboundMessage, ResolvedAttachment

logger = logging.getLogger(__name__)


class MessageItemType(IntEnum):
    NONE = 0
    TEXT = 1
    IMAGE = 2
    VOICE = 3
    FILE = 4
    VIDEO = 5


class UploadMediaType(IntEnum):
    IMAGE = 1
    VIDEO = 2
    FILE = 3
    VOICE = 4


def _build_ilink_client_version(version: str) -> str:
    parts = [part.strip() for part in version.split(".")]

    def _part(index: int) -> int:
        if index >= len(parts):
            return 0
        try:
            return max(0, min(int(parts[index] or 0), 0xFF))
        except ValueError:
            return 0

    major = _part(0)
    minor = _part(1)
    patch = _part(2)
    return str((major << 16) | (minor << 8) | patch)


def _build_wechat_uin() -> str:
    return base64.b64encode(str(secrets.randbits(32)).encode("utf-8")).decode("utf-8")


def _md5_hex(content: bytes) -> str:
    return hashlib.md5(content).hexdigest()


def _encrypted_size_for_aes_128_ecb(plaintext_size: int) -> int:
    if plaintext_size < 0:
        raise ValueError("plaintext_size must be non-negative")
    return ((plaintext_size // 16) + 1) * 16


def _validate_aes_128_key(key: bytes) -> None:
    if len(key) != 16:
        raise ValueError("AES-128-ECB requires a 16-byte key")


def _encrypt_aes_128_ecb(content: bytes, key: bytes) -> bytes:
    _validate_aes_128_key(key)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(content) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    encryptor = cipher.encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def _decrypt_aes_128_ecb(content: bytes, key: bytes) -> bytes:
    _validate_aes_128_key(key)
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    decryptor = cipher.decryptor()
    padded = decryptor.update(content) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def _safe_media_filename(prefix: str, extension: str, message_id: str | None = None, index: int | None = None) -> str:
    safe_ext = extension if extension.startswith(".") else f".{extension}" if extension else ""
    safe_msg = (message_id or "msg").replace("/", "_").replace("\\", "_")
    suffix = f"-{index}" if index is not None else ""
    return f"{prefix}-{safe_msg}{suffix}{safe_ext}"


def _build_cdn_upload_url(cdn_base_url: str, upload_param: str, filekey: str) -> str:
    return f"{cdn_base_url.rstrip('/')}/upload?encrypted_query_param={quote(upload_param, safe='')}&filekey={quote(filekey, safe='')}"


def _encode_outbound_media_aes_key(aes_key: bytes) -> str:
    return base64.b64encode(aes_key.hex().encode("utf-8")).decode("utf-8")


def _detect_image_extension_and_mime(content: bytes) -> tuple[str, str] | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return ".gif", "image/gif"
    if len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return ".webp", "image/webp"
    if content.startswith(b"BM"):
        return ".bmp", "image/bmp"
    return None


class WechatChannel(Channel):
    """WeChat iLink bot channel using long-polling.

    Configuration keys (in ``config.yaml`` under ``channels.wechat``):
        - ``bot_token``: iLink bot token used for authenticated API calls.
        - ``qrcode_login_enabled``: (optional) Allow first-time QR bootstrap when ``bot_token`` is missing.
        - ``base_url``: (optional) iLink API base URL.
        - ``allowed_users``: (optional) List of allowed iLink user IDs. Empty = allow all.
        - ``polling_timeout``: (optional) Long-poll timeout in seconds. Default: 35.
        - ``state_dir``: (optional) Directory used to persist the long-poll cursor.
    """

    DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
    DEFAULT_CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
    DEFAULT_CHANNEL_VERSION = "1.0"
    DEFAULT_POLLING_TIMEOUT = 35.0
    DEFAULT_RETRY_DELAY = 5.0
    DEFAULT_QRCODE_POLL_INTERVAL = 2.0
    DEFAULT_QRCODE_POLL_TIMEOUT = 180.0
    DEFAULT_QRCODE_BOT_TYPE = 3
    DEFAULT_API_TIMEOUT = 15.0
    DEFAULT_CONFIG_TIMEOUT = 10.0
    DEFAULT_CDN_TIMEOUT = 30.0
    DEFAULT_IMAGE_DOWNLOAD_DIRNAME = "downloads"
    DEFAULT_MAX_IMAGE_BYTES = 20 * 1024 * 1024
    DEFAULT_MAX_OUTBOUND_IMAGE_BYTES = 20 * 1024 * 1024
    DEFAULT_MAX_INBOUND_FILE_BYTES = 50 * 1024 * 1024
    DEFAULT_MAX_OUTBOUND_FILE_BYTES = 50 * 1024 * 1024
    DEFAULT_ALLOWED_FILE_EXTENSIONS = frozenset(
        {
            ".txt",
            ".md",
            ".pdf",
            ".csv",
            ".json",
            ".yaml",
            ".yml",
            ".xml",
            ".html",
            ".log",
            ".zip",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".ppt",
            ".pptx",
            ".rtf",
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".jsx",
            ".java",
            ".go",
            ".rs",
            ".c",
            ".cpp",
            ".h",
            ".hpp",
            ".sql",
            ".sh",
            ".bat",
            ".ps1",
            ".toml",
            ".ini",
            ".conf",
        }
    )
    DEFAULT_ALLOWED_FILE_MIME_TYPES = frozenset(
        {
            "application/pdf",
            "application/json",
            "application/xml",
            "application/zip",
            "application/x-zip-compressed",
            "application/x-yaml",
            "application/yaml",
            "text/csv",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-powerpoint",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/rtf",
        }
    )

    def __init__(self, bus: MessageBus, config: dict[str, Any]) -> None:
        super().__init__(name="wechat", bus=bus, config=config)
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._poll_task: asyncio.Task | None = None
        self._client: httpx.AsyncClient | None = None
        self._auth_lock = asyncio.Lock()

        self._base_url = str(config.get("base_url") or self.DEFAULT_BASE_URL).rstrip("/")
        self._cdn_base_url = str(config.get("cdn_base_url") or self.DEFAULT_CDN_BASE_URL).rstrip("/")
        self._channel_version = str(config.get("channel_version") or self.DEFAULT_CHANNEL_VERSION)
        self._polling_timeout = self._coerce_float(config.get("polling_timeout"), self.DEFAULT_POLLING_TIMEOUT)
        self._retry_delay = self._coerce_float(config.get("polling_retry_delay"), self.DEFAULT_RETRY_DELAY)
        self._qrcode_poll_interval = self._coerce_float(config.get("qrcode_poll_interval"), self.DEFAULT_QRCODE_POLL_INTERVAL)
        self._qrcode_poll_timeout = self._coerce_float(config.get("qrcode_poll_timeout"), self.DEFAULT_QRCODE_POLL_TIMEOUT)
        self._qrcode_login_enabled = bool(config.get("qrcode_login_enabled", False))
        self._qrcode_bot_type = self._coerce_int(config.get("qrcode_bot_type"), self.DEFAULT_QRCODE_BOT_TYPE)
        self._ilink_app_id = str(config.get("ilink_app_id") or "").strip()
        self._route_tag = str(config.get("route_tag") or "").strip()
        self._respect_server_longpoll_timeout = bool(config.get("respect_server_longpoll_timeout", True))
        self._max_inbound_image_bytes = self._coerce_int(config.get("max_inbound_image_bytes"), self.DEFAULT_MAX_IMAGE_BYTES)
        self._max_outbound_image_bytes = self._coerce_int(config.get("max_outbound_image_bytes"), self.DEFAULT_MAX_OUTBOUND_IMAGE_BYTES)
        self._max_inbound_file_bytes = self._coerce_int(config.get("max_inbound_file_bytes"), self.DEFAULT_MAX_INBOUND_FILE_BYTES)
        self._max_outbound_file_bytes = self._coerce_int(config.get("max_outbound_file_bytes"), self.DEFAULT_MAX_OUTBOUND_FILE_BYTES)
        self._allowed_file_extensions = self._coerce_str_set(config.get("allowed_file_extensions"), self.DEFAULT_ALLOWED_FILE_EXTENSIONS)
        self._allowed_users: set[str] = {str(uid).strip() for uid in config.get("allowed_users", []) if str(uid).strip()}
        self._bot_token = str(config.get("bot_token") or "").strip()
        self._ilink_bot_id = str(config.get("ilink_bot_id") or "").strip() or None
        self._auth_state: dict[str, Any] = {}
        self._server_longpoll_timeout_seconds: float | None = None

        self._get_updates_buf = ""
        self._context_tokens_by_chat: dict[str, str] = {}
        self._context_tokens_by_thread: dict[str, str] = {}

        self._state_dir = self._resolve_state_dir(config.get("state_dir"))
        self._cursor_path = self._state_dir / "wechat-getupdates.json" if self._state_dir else None
        self._auth_path = self._state_dir / "wechat-auth.json" if self._state_dir else None
        self._load_state()

    async def start(self) -> None:
        if self._running:
            return

        if not self._bot_token and not self._qrcode_login_enabled:
            logger.error("WeChat channel requires bot_token or qrcode_login_enabled")
            return

        self._main_loop = asyncio.get_running_loop()
        if self._state_dir:
            self._state_dir.mkdir(parents=True, exist_ok=True)

        await self._ensure_client()
        self._running = True
        self.bus.subscribe_outbound(self._on_outbound)
        self._poll_task = self._main_loop.create_task(self._poll_loop())
        logger.info("WeChat channel started")

    async def stop(self) -> None:
        self._running = False
        self.bus.unsubscribe_outbound(self._on_outbound)

        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

        if self._client is not None:
            await self._client.aclose()
            self._client = None

        logger.info("WeChat channel stopped")

    async def send(self, msg: OutboundMessage, *, _max_retries: int = 3) -> None:
        text = msg.text.strip()
        if not text:
            return

        if not self._bot_token and not await self._ensure_authenticated():
            logger.warning("[WeChat] unable to authenticate before sending chat=%s", msg.chat_id)
            return

        context_token = self._resolve_context_token(msg)
        if not context_token:
            logger.warning("[WeChat] missing context_token for chat=%s, dropping outbound message", msg.chat_id)
            return

        await self._send_text_message(
            chat_id=msg.chat_id,
            context_token=context_token,
            text=text,
            client_id_prefix="deerflow",
            max_retries=_max_retries,
        )

    async def _send_text_message(
        self,
        *,
        chat_id: str,
        context_token: str,
        text: str,
        client_id_prefix: str,
        max_retries: int,
    ) -> None:
        payload = {
            "msg": {
                "from_user_id": "",
                "to_user_id": chat_id,
                "client_id": f"{client_id_prefix}_{int(time.time() * 1000)}_{secrets.token_hex(2)}",
                "message_type": 2,
                "message_state": 2,
                "context_token": context_token,
                "item_list": [
                    {
                        "type": int(MessageItemType.TEXT),
                        "text_item": {"text": text},
                    }
                ],
            },
            "base_info": self._base_info(),
        }

        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                data = await self._request_json("/ilink/bot/sendmessage", payload)
                self._ensure_success(data, "sendmessage")
                return
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries - 1:
                    delay = 2**attempt
                    logger.warning(
                        "[WeChat] send failed (attempt %d/%d), retrying in %ds: %s",
                        attempt + 1,
                        max_retries,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)

        logger.error("[WeChat] send failed after %d attempts: %s", max_retries, last_exc)
        raise last_exc  # type: ignore[misc]

    async def send_file(self, msg: OutboundMessage, attachment: ResolvedAttachment) -> bool:
        if attachment.is_image:
            return await self._send_image_attachment(msg, attachment)
        return await self._send_file_attachment(msg, attachment)

    async def _send_image_attachment(self, msg: OutboundMessage, attachment: ResolvedAttachment) -> bool:
        if self._max_outbound_image_bytes > 0 and attachment.size > self._max_outbound_image_bytes:
            logger.warning("[WeChat] outbound image too large (%d bytes), skipping: %s", attachment.size, attachment.filename)
            return False

        if not self._bot_token and not await self._ensure_authenticated():
            logger.warning("[WeChat] unable to authenticate before sending image chat=%s", msg.chat_id)
            return False

        context_token = self._resolve_context_token(msg)
        if not context_token:
            logger.warning("[WeChat] missing context_token for image chat=%s", msg.chat_id)
            return False

        try:
            plaintext = attachment.actual_path.read_bytes()
        except OSError:
            logger.exception("[WeChat] failed to read outbound image %s", attachment.actual_path)
            return False

        aes_key = secrets.token_bytes(16)
        filekey = _safe_media_filename("wechat-upload", attachment.actual_path.suffix or ".bin", message_id=msg.thread_id)
        upload_request = self._build_upload_request(
            filekey=filekey,
            media_type=UploadMediaType.IMAGE,
            to_user_id=msg.chat_id,
            plaintext=plaintext,
            aes_key=aes_key,
            no_need_thumb=True,
        )

        try:
            upload_data = await self._request_json(
                "/ilink/bot/getuploadurl",
                {
                    **upload_request,
                    "base_info": self._base_info(),
                },
            )
            self._ensure_success(upload_data, "getuploadurl")

            upload_full_url = self._extract_upload_full_url(upload_data)
            upload_param = self._extract_upload_param(upload_data)
            upload_method = "POST"
            if not upload_full_url:
                if not upload_param:
                    logger.warning("[WeChat] getuploadurl returned no upload URL for image %s", attachment.filename)
                    return False
                upload_full_url = _build_cdn_upload_url(self._cdn_base_url, upload_param, filekey)

            encrypted = _encrypt_aes_128_ecb(plaintext, aes_key)
            download_param = await self._upload_cdn_bytes(
                upload_full_url,
                encrypted,
                content_type=attachment.mime_type,
                method=upload_method,
            )
            if download_param:
                upload_data = dict(upload_data)
                upload_data["upload_param"] = download_param

            image_item = self._build_outbound_image_item(upload_data, aes_key, ciphertext_size=len(encrypted))
            send_payload = {
                "msg": {
                    "from_user_id": "",
                    "to_user_id": msg.chat_id,
                    "client_id": f"deerflow_img_{int(time.time() * 1000)}",
                    "message_type": 2,
                    "message_state": 2,
                    "context_token": context_token,
                    "item_list": [
                        {
                            "type": int(MessageItemType.IMAGE),
                            "image_item": image_item,
                        }
                    ],
                },
                "base_info": self._base_info(),
            }
            response = await self._request_json("/ilink/bot/sendmessage", send_payload)
            self._ensure_success(response, "sendmessage")
            return True
        except Exception:
            logger.exception("[WeChat] failed to send image attachment %s", attachment.filename)
            return False

    async def _send_file_attachment(self, msg: OutboundMessage, attachment: ResolvedAttachment) -> bool:
        if not self._is_allowed_file_type(attachment.filename, attachment.mime_type):
            logger.warning("[WeChat] outbound file type blocked, skipping: %s (%s)", attachment.filename, attachment.mime_type)
            return False

        if self._max_outbound_file_bytes > 0 and attachment.size > self._max_outbound_file_bytes:
            logger.warning("[WeChat] outbound file too large (%d bytes), skipping: %s", attachment.size, attachment.filename)
            return False

        if not self._bot_token and not await self._ensure_authenticated():
            logger.warning("[WeChat] unable to authenticate before sending file chat=%s", msg.chat_id)
            return False

        context_token = self._resolve_context_token(msg)
        if not context_token:
            logger.warning("[WeChat] missing context_token for file chat=%s", msg.chat_id)
            return False

        try:
            plaintext = attachment.actual_path.read_bytes()
        except OSError:
            logger.exception("[WeChat] failed to read outbound file %s", attachment.actual_path)
            return False

        aes_key = secrets.token_bytes(16)
        filekey = _safe_media_filename("wechat-file-upload", attachment.actual_path.suffix or ".bin", message_id=msg.thread_id)
        upload_request = self._build_upload_request(
            filekey=filekey,
            media_type=UploadMediaType.FILE,
            to_user_id=msg.chat_id,
            plaintext=plaintext,
            aes_key=aes_key,
            no_need_thumb=True,
        )

        try:
            upload_data = await self._request_json(
                "/ilink/bot/getuploadurl",
                {
                    **upload_request,
                    "base_info": self._base_info(),
                },
            )
            self._ensure_success(upload_data, "getuploadurl")

            upload_full_url = self._extract_upload_full_url(upload_data)
            upload_param = self._extract_upload_param(upload_data)
            upload_method = "POST"
            if not upload_full_url:
                if not upload_param:
                    logger.warning("[WeChat] getuploadurl returned no upload URL for file %s", attachment.filename)
                    return False
                upload_full_url = _build_cdn_upload_url(self._cdn_base_url, upload_param, filekey)

            encrypted = _encrypt_aes_128_ecb(plaintext, aes_key)
            download_param = await self._upload_cdn_bytes(
                upload_full_url,
                encrypted,
                content_type=attachment.mime_type,
                method=upload_method,
            )
            if download_param:
                upload_data = dict(upload_data)
                upload_data["upload_param"] = download_param

            file_item = self._build_outbound_file_item(upload_data, aes_key, attachment.filename, plaintext)
            send_payload = {
                "msg": {
                    "from_user_id": "",
                    "to_user_id": msg.chat_id,
                    "client_id": f"deerflow_file_{int(time.time() * 1000)}",
                    "message_type": 2,
                    "message_state": 2,
                    "context_token": context_token,
                    "item_list": [
                        {
                            "type": int(MessageItemType.FILE),
                            "file_item": file_item,
                        }
                    ],
                },
                "base_info": self._base_info(),
            }
            response = await self._request_json("/ilink/bot/sendmessage", send_payload)
            self._ensure_success(response, "sendmessage")
            return True
        except Exception:
            logger.exception("[WeChat] failed to send file attachment %s", attachment.filename)
            return False

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                if not await self._ensure_authenticated():
                    await asyncio.sleep(self._retry_delay)
                    continue

                data = await self._request_json(
                    "/ilink/bot/getupdates",
                    {
                        "get_updates_buf": self._get_updates_buf,
                        "base_info": self._base_info(),
                    },
                    timeout=max(self._current_longpoll_timeout_seconds() + 5.0, 10.0),
                )

                ret = data.get("ret", 0)
                if ret not in (0, None):
                    errcode = data.get("errcode")
                    if errcode == -14:
                        self._bot_token = ""
                        self._get_updates_buf = ""
                        self._save_state()
                        self._save_auth_state(status="expired", bot_token="")
                        logger.error("[WeChat] bot token expired; scan again or update bot_token and restart the channel")
                        self._running = False
                        break
                    logger.warning(
                        "[WeChat] getupdates returned ret=%s errcode=%s errmsg=%s",
                        ret,
                        errcode,
                        data.get("errmsg"),
                    )
                    await asyncio.sleep(self._retry_delay)
                    continue

                self._update_longpoll_timeout(data)

                next_buf = data.get("get_updates_buf")
                if isinstance(next_buf, str) and next_buf != self._get_updates_buf:
                    self._get_updates_buf = next_buf
                    self._save_state()

                for raw_message in data.get("msgs", []):
                    await self._handle_update(raw_message)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("[WeChat] polling loop failed")
                await asyncio.sleep(self._retry_delay)

    async def _handle_update(self, raw_message: Any) -> None:
        if not isinstance(raw_message, dict):
            return
        if raw_message.get("message_type") != 1:
            return

        chat_id = str(raw_message.get("from_user_id") or raw_message.get("ilink_user_id") or "").strip()
        if not chat_id or not self._check_user(chat_id):
            return

        text = self._extract_text(raw_message)
        files = await self._extract_inbound_files(raw_message)
        if not text and not files:
            return

        context_token = str(raw_message.get("context_token") or "").strip()
        thread_ts = context_token or str(raw_message.get("client_id") or raw_message.get("msg_id") or "").strip() or None

        if context_token:
            self._context_tokens_by_chat[chat_id] = context_token
            if thread_ts:
                self._context_tokens_by_thread[thread_ts] = context_token

        inbound = self._make_inbound(
            chat_id=chat_id,
            user_id=chat_id,
            text=text,
            msg_type=InboundMessageType.COMMAND if text.startswith("/") else InboundMessageType.CHAT,
            thread_ts=thread_ts,
            files=files,
            metadata={
                "context_token": context_token,
                "ilink_user_id": chat_id,
                "ref_msg": self._extract_ref_message(raw_message),
                "raw_message": raw_message,
            },
        )
        inbound.topic_id = None
        await self.bus.publish_inbound(inbound)

    async def _ensure_authenticated(self) -> bool:
        async with self._auth_lock:
            if self._bot_token:
                return True

            self._load_auth_state()
            if self._bot_token:
                return True

            if not self._qrcode_login_enabled:
                return False

            try:
                auth_state = await self._bind_via_qrcode()
            except Exception:
                logger.exception("[WeChat] QR code binding failed")
                return False
            return bool(auth_state.get("bot_token"))

    async def _bind_via_qrcode(self) -> dict[str, Any]:
        qrcode_data = await self._request_public_get_json(
            "/ilink/bot/get_bot_qrcode",
            params={"bot_type": self._qrcode_bot_type},
        )
        qrcode = str(qrcode_data.get("qrcode") or "").strip()
        if not qrcode:
            raise RuntimeError("iLink get_bot_qrcode did not return qrcode")

        qrcode_img_content = str(qrcode_data.get("qrcode_img_content") or "").strip()
        logger.warning("[WeChat] QR login required. qrcode=%s", qrcode)
        if qrcode_img_content:
            logger.warning("[WeChat] qrcode_img_content=%s", qrcode_img_content)

        self._save_auth_state(
            status="pending",
            qrcode=qrcode,
            qrcode_img_content=qrcode_img_content or None,
        )

        deadline = time.monotonic() + max(self._qrcode_poll_timeout, 1.0)
        while time.monotonic() < deadline:
            status_data = await self._request_public_get_json(
                "/ilink/bot/get_qrcode_status",
                params={"qrcode": qrcode},
            )
            status = str(status_data.get("status") or "").strip().lower()
            if status == "confirmed":
                token = str(status_data.get("bot_token") or "").strip()
                if not token:
                    raise RuntimeError("iLink QR confirmation succeeded without bot_token")
                self._bot_token = token
                ilink_bot_id = str(status_data.get("ilink_bot_id") or "").strip() or None
                if ilink_bot_id:
                    self._ilink_bot_id = ilink_bot_id

                return self._save_auth_state(
                    status="confirmed",
                    bot_token=token,
                    ilink_bot_id=self._ilink_bot_id,
                    qrcode=qrcode,
                    qrcode_img_content=qrcode_img_content or None,
                )

            if status in {"expired", "canceled", "cancelled", "invalid", "failed"}:
                self._save_auth_state(
                    status=status,
                    qrcode=qrcode,
                    qrcode_img_content=qrcode_img_content or None,
                )
                raise RuntimeError(f"iLink QR code flow ended with status={status}")

            await asyncio.sleep(max(self._qrcode_poll_interval, 0.1))

        self._save_auth_state(
            status="timeout",
            qrcode=qrcode,
            qrcode_img_content=qrcode_img_content or None,
        )
        raise TimeoutError("Timed out waiting for WeChat QR confirmation")

    async def _request_json(self, path: str, payload: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
        client = await self._ensure_client()
        response = await client.post(
            f"{self._base_url}{path}",
            json=payload,
            headers=self._auth_headers(),
            timeout=timeout or self.DEFAULT_API_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}

    async def _request_public_get_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        client = await self._ensure_client()
        response = await client.get(
            f"{self._base_url}{path}",
            params=params,
            headers=self._public_headers(),
            timeout=timeout or self.DEFAULT_CONFIG_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            timeout = max(self._polling_timeout + 5.0, 10.0)
            self._client = httpx.AsyncClient(timeout=timeout)
        return self._client

    def _resolve_context_token(self, msg: OutboundMessage) -> str | None:
        metadata_token = msg.metadata.get("context_token")
        if isinstance(metadata_token, str) and metadata_token.strip():
            return metadata_token.strip()
        if msg.thread_ts and msg.thread_ts in self._context_tokens_by_thread:
            return self._context_tokens_by_thread[msg.thread_ts]
        return self._context_tokens_by_chat.get(msg.chat_id)

    def _check_user(self, user_id: str) -> bool:
        if not self._allowed_users:
            return True
        return user_id in self._allowed_users

    def _current_longpoll_timeout_seconds(self) -> float:
        if self._respect_server_longpoll_timeout and self._server_longpoll_timeout_seconds is not None:
            return self._server_longpoll_timeout_seconds
        return self._polling_timeout

    def _update_longpoll_timeout(self, data: Mapping[str, Any]) -> None:
        if not self._respect_server_longpoll_timeout:
            return
        raw_timeout = data.get("longpolling_timeout_ms")
        if raw_timeout is None:
            return
        try:
            timeout_ms = float(raw_timeout)
        except (TypeError, ValueError):
            return
        if timeout_ms <= 0:
            return
        self._server_longpoll_timeout_seconds = timeout_ms / 1000.0

    def _base_info(self) -> dict[str, str]:
        return {"channel_version": self._channel_version}

    def _common_headers(self) -> dict[str, str]:
        headers = {
            "iLink-App-ClientVersion": _build_ilink_client_version(self._channel_version),
            "X-WECHAT-UIN": _build_wechat_uin(),
        }
        if self._ilink_app_id:
            headers["iLink-App-Id"] = self._ilink_app_id
        if self._route_tag:
            headers["SKRouteTag"] = self._route_tag
        return headers

    def _public_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            **self._common_headers(),
        }

    def _auth_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._bot_token}",
            "AuthorizationType": "ilink_bot_token",
            **self._common_headers(),
        }
        return headers

    @staticmethod
    def _extract_cdn_full_url(media: Mapping[str, Any] | None) -> str | None:
        if not isinstance(media, Mapping):
            return None
        full_url = media.get("full_url")
        return full_url.strip() if isinstance(full_url, str) and full_url.strip() else None

    @staticmethod
    def _extract_upload_full_url(upload_data: Mapping[str, Any] | None) -> str | None:
        if not isinstance(upload_data, Mapping):
            return None
        upload_full_url = upload_data.get("upload_full_url")
        return upload_full_url.strip() if isinstance(upload_full_url, str) and upload_full_url.strip() else None

    @staticmethod
    def _extract_upload_param(upload_data: Mapping[str, Any] | None) -> str | None:
        if not isinstance(upload_data, Mapping):
            return None
        upload_param = upload_data.get("upload_param")
        return upload_param.strip() if isinstance(upload_param, str) and upload_param.strip() else None

    def _build_upload_request(
        self,
        *,
        filekey: str,
        media_type: UploadMediaType,
        to_user_id: str,
        plaintext: bytes,
        aes_key: bytes,
        thumb_plaintext: bytes | None = None,
        no_need_thumb: bool = False,
    ) -> dict[str, Any]:
        _validate_aes_128_key(aes_key)
        payload: dict[str, Any] = {
            "filekey": filekey,
            "media_type": int(media_type),
            "to_user_id": to_user_id,
            "rawsize": len(plaintext),
            "rawfilemd5": _md5_hex(plaintext),
            "filesize": _encrypted_size_for_aes_128_ecb(len(plaintext)),
            "aeskey": aes_key.hex(),
        }
        if thumb_plaintext is not None:
            payload.update(
                {
                    "thumb_rawsize": len(thumb_plaintext),
                    "thumb_rawfilemd5": _md5_hex(thumb_plaintext),
                    "thumb_filesize": _encrypted_size_for_aes_128_ecb(len(thumb_plaintext)),
                }
            )
        elif no_need_thumb:
            payload["no_need_thumb"] = True
        return payload

    async def _download_cdn_bytes(self, url: str, *, timeout: float | None = None) -> bytes:
        client = await self._ensure_client()
        response = await client.get(url, timeout=timeout or self.DEFAULT_CDN_TIMEOUT)
        response.raise_for_status()
        return response.content

    async def _upload_cdn_bytes(
        self,
        url: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
        timeout: float | None = None,
        method: str = "PUT",
    ) -> str | None:
        client = await self._ensure_client()
        request_kwargs = {
            "content": content,
            "headers": {"Content-Type": content_type},
            "timeout": timeout or self.DEFAULT_CDN_TIMEOUT,
        }
        if method.upper() == "POST":
            response = await client.post(url, **request_kwargs)
        else:
            response = await client.put(url, **request_kwargs)
        response.raise_for_status()
        return response.headers.get("x-encrypted-param")

    def _build_outbound_image_item(
        self,
        upload_data: Mapping[str, Any],
        aes_key: bytes,
        *,
        ciphertext_size: int,
    ) -> dict[str, Any]:
        encoded_aes_key = _encode_outbound_media_aes_key(aes_key)
        media: dict[str, Any] = {
            "aes_key": encoded_aes_key,
            "encrypt_type": 1,
        }
        upload_param = upload_data.get("upload_param")
        if isinstance(upload_param, str) and upload_param.strip():
            media["encrypt_query_param"] = upload_param.strip()

        return {
            "media": media,
            "mid_size": ciphertext_size,
        }

    def _build_outbound_file_item(
        self,
        upload_data: Mapping[str, Any],
        aes_key: bytes,
        filename: str,
        plaintext: bytes,
    ) -> dict[str, Any]:
        media: dict[str, Any] = {
            "aes_key": _encode_outbound_media_aes_key(aes_key),
            "encrypt_type": 1,
        }
        upload_param = upload_data.get("upload_param")
        if isinstance(upload_param, str) and upload_param.strip():
            media["encrypt_query_param"] = upload_param.strip()
        return {
            "media": media,
            "file_name": filename,
            "md5": _md5_hex(plaintext),
            "len": str(len(plaintext)),
        }

    def _download_dir(self) -> Path | None:
        if not self._state_dir:
            return None
        return self._state_dir / self.DEFAULT_IMAGE_DOWNLOAD_DIRNAME

    async def _extract_inbound_files(self, raw_message: Mapping[str, Any]) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        item_list = raw_message.get("item_list")
        if not isinstance(item_list, list):
            return files

        message_id = str(raw_message.get("message_id") or raw_message.get("msg_id") or raw_message.get("client_id") or "msg")

        for index, item in enumerate(item_list):
            if not isinstance(item, Mapping):
                continue
            if item.get("type") == int(MessageItemType.IMAGE):
                image_file = await self._extract_image_file(item, message_id=message_id, index=index)
                if image_file:
                    files.append(image_file)
            elif item.get("type") == int(MessageItemType.FILE):
                file_info = await self._extract_file_item(item, message_id=message_id, index=index)
                if file_info:
                    files.append(file_info)
        return files

    async def _extract_image_file(self, item: Mapping[str, Any], *, message_id: str, index: int) -> dict[str, Any] | None:
        image_item = item.get("image_item")
        if not isinstance(image_item, Mapping):
            return None

        media = image_item.get("media")
        if not isinstance(media, Mapping):
            return None

        full_url = self._extract_cdn_full_url(media)
        if not full_url:
            logger.warning("[WeChat] inbound image missing full_url, skipping message_id=%s", message_id)
            return None

        aes_key = self._resolve_media_aes_key(item, image_item, media)
        if not aes_key:
            logger.warning(
                "[WeChat] inbound image missing aes key, skipping message_id=%s diagnostics=%s",
                message_id,
                self._describe_media_key_state(item=item, item_payload=image_item, media=media),
            )
            return None

        encrypted = await self._download_cdn_bytes(full_url)
        decrypted = _decrypt_aes_128_ecb(encrypted, aes_key)
        if self._max_inbound_image_bytes > 0 and len(decrypted) > self._max_inbound_image_bytes:
            logger.warning("[WeChat] inbound image exceeds size limit (%d bytes), skipping message_id=%s", len(decrypted), message_id)
            return None

        detected_image = _detect_image_extension_and_mime(decrypted)
        image_extension = detected_image[0] if detected_image else ".jpg"
        filename = _safe_media_filename("wechat-image", image_extension, message_id=message_id, index=index)
        stored_path = self._stage_downloaded_file(filename, decrypted)
        if stored_path is None:
            return None

        mime_type = detected_image[1] if detected_image else mimetypes.guess_type(filename)[0] or "image/jpeg"
        return {
            "type": "image",
            "filename": stored_path.name,
            "size": len(decrypted),
            "path": str(stored_path),
            "mime_type": mime_type,
            "source": "wechat",
            "message_item_type": int(MessageItemType.IMAGE),
            "full_url": full_url,
        }

    async def _extract_file_item(self, item: Mapping[str, Any], *, message_id: str, index: int) -> dict[str, Any] | None:
        file_item = item.get("file_item")
        if not isinstance(file_item, Mapping):
            return None

        media = file_item.get("media")
        if not isinstance(media, Mapping):
            return None

        full_url = self._extract_cdn_full_url(media)
        if not full_url:
            logger.warning("[WeChat] inbound file missing full_url, skipping message_id=%s", message_id)
            return None

        aes_key = self._resolve_media_aes_key(item, file_item, media)
        if not aes_key:
            logger.warning(
                "[WeChat] inbound file missing aes key, skipping message_id=%s diagnostics=%s",
                message_id,
                self._describe_media_key_state(item=item, item_payload=file_item, media=media),
            )
            return None

        filename = self._normalize_inbound_filename(file_item.get("file_name"), default_prefix="wechat-file", message_id=message_id, index=index)
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        if not self._is_allowed_file_type(filename, mime_type):
            logger.warning("[WeChat] inbound file type blocked, skipping message_id=%s filename=%s", message_id, filename)
            return None

        encrypted = await self._download_cdn_bytes(full_url)
        decrypted = _decrypt_aes_128_ecb(encrypted, aes_key)
        if self._max_inbound_file_bytes > 0 and len(decrypted) > self._max_inbound_file_bytes:
            logger.warning("[WeChat] inbound file exceeds size limit (%d bytes), skipping message_id=%s", len(decrypted), message_id)
            return None

        stored_path = self._stage_downloaded_file(filename, decrypted)
        if stored_path is None:
            return None

        return {
            "type": "file",
            "filename": stored_path.name,
            "size": len(decrypted),
            "path": str(stored_path),
            "mime_type": mime_type,
            "source": "wechat",
            "message_item_type": int(MessageItemType.FILE),
            "full_url": full_url,
        }

    def _stage_downloaded_file(self, filename: str, content: bytes) -> Path | None:
        download_dir = self._download_dir()
        if download_dir is None:
            return None
        try:
            download_dir.mkdir(parents=True, exist_ok=True)
            path = download_dir / filename
            path.write_bytes(content)
            return path
        except OSError:
            logger.exception("[WeChat] failed to persist inbound media file %s", filename)
            return None

    @staticmethod
    def _decode_base64_aes_key(value: str) -> bytes | None:
        candidate = value.strip()
        if not candidate:
            return None

        def _normalize_decoded(decoded: bytes) -> bytes | None:
            try:
                _validate_aes_128_key(decoded)
                return decoded
            except ValueError:
                pass

            try:
                decoded_text = decoded.decode("utf-8").strip().strip('"').strip("'")
            except UnicodeDecodeError:
                return None

            if not decoded_text:
                return None

            try:
                key = bytes.fromhex(decoded_text)
                _validate_aes_128_key(key)
                return key
            except ValueError:
                return None

        padded = candidate + ("=" * (-len(candidate) % 4))
        decoders = (
            lambda: base64.b64decode(padded, validate=True),
            lambda: base64.urlsafe_b64decode(padded),
        )
        for decoder in decoders:
            try:
                key = _normalize_decoded(decoder())
                if key is not None:
                    return key
            except (ValueError, TypeError, binascii.Error):
                continue
        return None

    @classmethod
    def _parse_aes_key_candidate(cls, value: Any, *, prefer_hex: bool) -> bytes | None:
        if isinstance(value, bytes):
            try:
                _validate_aes_128_key(value)
                return value
            except ValueError:
                return None

        if isinstance(value, bytearray):
            return cls._parse_aes_key_candidate(bytes(value), prefer_hex=prefer_hex)

        if not isinstance(value, str) or not value.strip():
            return None

        raw = value.strip()
        parsers = (
            (lambda: bytes.fromhex(raw), lambda key: _validate_aes_128_key(key)),
            (lambda: cls._decode_base64_aes_key(raw), None),
        )
        if not prefer_hex:
            parsers = (parsers[1], parsers[0])

        for decoder, validator in parsers:
            try:
                key = decoder()
                if key is None:
                    continue
                if validator is not None:
                    validator(key)
                return key
            except ValueError:
                continue
        return None

    @classmethod
    def _resolve_media_aes_key(cls, *payloads: Mapping[str, Any]) -> bytes | None:
        for payload in payloads:
            if not isinstance(payload, Mapping):
                continue
            for key_name in ("aeskey", "aes_key_hex"):
                key = cls._parse_aes_key_candidate(payload.get(key_name), prefer_hex=True)
                if key:
                    return key
            for key_name in ("aes_key", "aesKey", "encrypt_key", "encryptKey"):
                key = cls._parse_aes_key_candidate(payload.get(key_name), prefer_hex=False)
                if key:
                    return key
            media = payload.get("media")
            if isinstance(media, Mapping):
                key = cls._resolve_media_aes_key(media)
                if key:
                    return key
        return None

    @staticmethod
    def _describe_media_key_state(
        *,
        item: Mapping[str, Any] | None,
        item_payload: Mapping[str, Any] | None,
        media: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        def _interesting(mapping: Mapping[str, Any] | None) -> dict[str, Any]:
            if not isinstance(mapping, Mapping):
                return {}
            details: dict[str, Any] = {}
            for key in (
                "aeskey",
                "aes_key",
                "aesKey",
                "aes_key_hex",
                "encrypt_key",
                "encryptKey",
                "encrypt_query_param",
                "encrypt_type",
                "full_url",
                "file_name",
            ):
                if key not in mapping:
                    continue
                value = mapping.get(key)
                if isinstance(value, str):
                    details[key] = f"str(len={len(value.strip())})"
                elif value is not None:
                    details[key] = type(value).__name__
                else:
                    details[key] = None
            return details

        return {
            "item": _interesting(item),
            "item_payload": _interesting(item_payload),
            "media": _interesting(media),
        }

    @staticmethod
    def _extract_ref_message(raw_message: Mapping[str, Any]) -> dict[str, Any] | None:
        item_list = raw_message.get("item_list")
        if not isinstance(item_list, list):
            return None
        for item in item_list:
            if not isinstance(item, Mapping):
                continue
            ref_msg = item.get("ref_msg")
            if isinstance(ref_msg, Mapping):
                return dict(ref_msg)
        return None

    def _is_allowed_file_type(self, filename: str, mime_type: str) -> bool:
        suffix = Path(filename).suffix.lower()
        if self._allowed_file_extensions and suffix not in self._allowed_file_extensions:
            return False
        if mime_type.startswith("text/"):
            return True
        return mime_type in self.DEFAULT_ALLOWED_FILE_MIME_TYPES

    @staticmethod
    def _normalize_inbound_filename(raw_filename: Any, *, default_prefix: str, message_id: str, index: int) -> str:
        if isinstance(raw_filename, str) and raw_filename.strip():
            candidate = Path(raw_filename.strip()).name
            if candidate:
                return candidate
        return _safe_media_filename(default_prefix, ".bin", message_id=message_id, index=index)

    def _ensure_success(self, data: dict[str, Any], operation: str) -> None:
        ret = data.get("ret", 0)
        if ret in (0, None):
            return
        errcode = data.get("errcode")
        errmsg = data.get("errmsg") or data.get("msg") or "unknown error"
        raise RuntimeError(f"iLink {operation} failed: ret={ret} errcode={errcode} errmsg={errmsg}")

    def _load_state(self) -> None:
        self._load_auth_state()
        if not self._cursor_path or not self._cursor_path.exists():
            return
        try:
            data = json.loads(self._cursor_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("[WeChat] failed to read cursor state from %s", self._cursor_path)
            return
        cursor = data.get("get_updates_buf")
        if isinstance(cursor, str):
            self._get_updates_buf = cursor

    def _save_state(self) -> None:
        if not self._cursor_path:
            return
        try:
            self._cursor_path.parent.mkdir(parents=True, exist_ok=True)
            self._cursor_path.write_text(json.dumps({"get_updates_buf": self._get_updates_buf}, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            logger.warning("[WeChat] failed to persist cursor state to %s", self._cursor_path)

    def _load_auth_state(self) -> None:
        if not self._auth_path or not self._auth_path.exists():
            return
        try:
            data = json.loads(self._auth_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("[WeChat] failed to read auth state from %s", self._auth_path)
            return
        if not isinstance(data, dict):
            return
        self._auth_state = dict(data)

        if not self._bot_token:
            token = data.get("bot_token")
            if isinstance(token, str) and token.strip():
                self._bot_token = token.strip()

        if not self._ilink_bot_id:
            ilink_bot_id = data.get("ilink_bot_id")
            if isinstance(ilink_bot_id, str) and ilink_bot_id.strip():
                self._ilink_bot_id = ilink_bot_id.strip()

    def _save_auth_state(
        self,
        *,
        status: str,
        bot_token: str | None = None,
        ilink_bot_id: str | None = None,
        qrcode: str | None = None,
        qrcode_img_content: str | None = None,
    ) -> dict[str, Any]:
        data = dict(self._auth_state)
        data["status"] = status
        data["updated_at"] = int(time.time())

        if bot_token is not None:
            if bot_token:
                data["bot_token"] = bot_token
            else:
                data.pop("bot_token", None)
        elif self._bot_token:
            data["bot_token"] = self._bot_token

        resolved_ilink_bot_id = ilink_bot_id if ilink_bot_id is not None else self._ilink_bot_id
        if resolved_ilink_bot_id:
            data["ilink_bot_id"] = resolved_ilink_bot_id

        if qrcode is not None:
            data["qrcode"] = qrcode
        if qrcode_img_content is not None:
            data["qrcode_img_content"] = qrcode_img_content

        self._auth_state = data
        if self._auth_path:
            try:
                self._auth_path.parent.mkdir(parents=True, exist_ok=True)
                self._auth_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError:
                logger.warning("[WeChat] failed to persist auth state to %s", self._auth_path)
        return data

    @staticmethod
    def _extract_text(raw_message: dict[str, Any]) -> str:
        parts: list[str] = []
        for item in raw_message.get("item_list", []):
            if not isinstance(item, dict) or item.get("type") != int(MessageItemType.TEXT):
                continue
            text_item = item.get("text_item")
            if not isinstance(text_item, dict):
                continue
            text = text_item.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        return "\n".join(parts)

    @staticmethod
    def _resolve_state_dir(raw_state_dir: Any) -> Path | None:
        if not isinstance(raw_state_dir, str) or not raw_state_dir.strip():
            return None
        return Path(raw_state_dir).expanduser()

    @staticmethod
    def _coerce_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _coerce_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _coerce_str_set(value: Any, default: frozenset[str]) -> set[str]:
        if not isinstance(value, (list, tuple, set, frozenset)):
            return set(default)
        normalized = {str(item).strip().lower() if str(item).strip().startswith(".") else f".{str(item).strip().lower()}" for item in value if str(item).strip()}
        return normalized or set(default)
