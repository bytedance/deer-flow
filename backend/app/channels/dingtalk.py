"""DingTalk channel implementation."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from app.channels.base import Channel
from app.channels.commands import is_known_channel_command, strip_leading_mentions
from app.channels.connection_identity import attach_connection_identity
from app.channels.message_bus import InboundMessage, InboundMessageType, MessageBus, OutboundMessage, ResolvedAttachment
from deerflow.config.paths import VIRTUAL_PATH_PREFIX, get_paths
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.sandbox.sandbox_provider import get_sandbox_provider
from deerflow.uploads.manager import UnsafeUploadPathError, claim_unique_filename, normalize_filename, write_upload_file_no_symlink

logger = logging.getLogger(__name__)

DINGTALK_API_BASE = "https://api.dingtalk.com"

_TOKEN_REFRESH_MARGIN_SECONDS = 300

_CONVERSATION_TYPE_P2P = "1"
_CONVERSATION_TYPE_GROUP = "2"

_MAX_UPLOAD_SIZE_BYTES = 20 * 1024 * 1024

# Inbound attachments are buffered in memory before being persisted and synced
# into the sandbox, so bound them. DingTalk chats accept far larger files than
# an agent can usefully read; oversized ones surface as a failed-load marker.
_MAX_INBOUND_FILE_SIZE_BYTES = 50 * 1024 * 1024


def _normalize_conversation_type(raw: Any) -> str:
    """Normalize ``conversationType`` to ``"1"`` (P2P) or ``"2"`` (group).

    Stream payloads may send int or string values.
    """
    if raw is None:
        return _CONVERSATION_TYPE_P2P
    s = str(raw).strip()
    if s == _CONVERSATION_TYPE_GROUP:
        return _CONVERSATION_TYPE_GROUP
    return _CONVERSATION_TYPE_P2P


def _normalize_allowed_users(allowed_users: Any) -> set[str]:
    if allowed_users is None:
        return set()
    if isinstance(allowed_users, str):
        values = [allowed_users]
    elif isinstance(allowed_users, (list, tuple, set)):
        values = allowed_users
    else:
        logger.warning(
            "DingTalk allowed_users should be a list of user IDs; treating %s as one string value",
            type(allowed_users).__name__,
        )
        values = [allowed_users]
    return {str(uid) for uid in values if str(uid)}


def _is_dingtalk_command(text: str) -> bool:
    return is_known_channel_command(text)


def _display_filename(filename: str) -> str:
    """Collapse whitespace and cap length for embedding a filename in message text.

    ``fileName`` is webhook-supplied data: embedded raw in a failed-load marker,
    a newline could forge a standalone ``/mnt/user-data/uploads/...`` line and an
    over-long name would bloat the message text.
    """
    return re.sub(r"\s+", " ", filename).strip()[:80]


def _extract_text_from_rich_text(rich_text_list: list) -> str:
    parts: list[str] = []
    for item in rich_text_list:
        if isinstance(item, dict) and "text" in item:
            parts.append(item["text"])
    return " ".join(parts)


_FENCED_CODE_BLOCK_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_HORIZONTAL_RULE_RE = re.compile(r"^-{3,}$", re.MULTILINE)
_TABLE_SEPARATOR_RE = re.compile(r"^\|[-:| ]+\|$", re.MULTILINE)


def _convert_markdown_table(text: str) -> str:
    # DingTalk sampleMarkdown does not render pipe-delimited tables.
    lines = text.split("\n")
    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Detect table: header row followed by separator row
        if i + 1 < len(lines) and line.strip().startswith("|") and _TABLE_SEPARATOR_RE.match(lines[i + 1].strip()):
            headers = [h.strip() for h in line.strip().strip("|").split("|")]
            i += 2  # skip header + separator
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                for h, c in zip(headers, cells):
                    result.append(f"> **{h}**: {c}")
                result.append("")
                i += 1
        else:
            result.append(line)
            i += 1
    return "\n".join(result)


def _adapt_markdown_for_dingtalk(text: str) -> str:
    """Adapt markdown for DingTalk's limited sampleMarkdown renderer."""

    def _code_block_to_quote(match: re.Match) -> str:
        lang = match.group(1)
        code = match.group(2).rstrip("\n")
        prefix = f"> **{lang}**\n" if lang else ""
        quoted_lines = "\n".join(f"> {line}" for line in code.split("\n"))
        return f"{prefix}{quoted_lines}\n"

    text = _FENCED_CODE_BLOCK_RE.sub(_code_block_to_quote, text)
    text = _INLINE_CODE_RE.sub(r"**\1**", text)
    text = _convert_markdown_table(text)
    text = _HORIZONTAL_RULE_RE.sub("───────────", text)
    return text


class DingTalkChannel(Channel):
    """DingTalk IM channel using Stream Push (WebSocket, no public IP needed)."""

    def __init__(self, bus: MessageBus, config: dict[str, Any]) -> None:
        super().__init__(name="dingtalk", bus=bus, config=config)
        self._thread: threading.Thread | None = None
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._client_id: str = ""
        self._client_secret: str = ""
        self._allowed_users: set[str] = _normalize_allowed_users(config.get("allowed_users"))
        self._cached_token: str = ""
        self._token_expires_at: float = 0.0
        self._token_lock = asyncio.Lock()
        self._card_template_id: str = config.get("card_template_id", "")
        self._card_track_ids: dict[str, str] = {}
        self._dingtalk_client: Any = None
        self._stream_client: Any = None
        self._incoming_messages: dict[str, Any] = {}
        self._incoming_messages_lock = threading.Lock()
        self._card_repliers: dict[str, Any] = {}
        # Serialize inbound-file writes into the uploads directory to avoid
        # racing writers clobbering one another (mirrors FeishuChannel).
        self._file_write_lock = threading.Lock()

    @property
    def supports_streaming(self) -> bool:
        return bool(self._card_template_id)

    async def start(self) -> None:
        if self._running:
            return

        try:
            import dingtalk_stream  # noqa: F401
        except ImportError:
            logger.error("dingtalk-stream is not installed. Install it with: uv add dingtalk-stream")
            return

        client_id = self.config.get("client_id", "")
        client_secret = self.config.get("client_secret", "")

        if not client_id or not client_secret:
            logger.error("DingTalk channel requires client_id and client_secret")
            return

        self._client_id = client_id
        self._client_secret = client_secret
        self._main_loop = asyncio.get_running_loop()

        if self._card_template_id:
            logger.info("[DingTalk] AI Card mode enabled (template=%s)", self._card_template_id)

        self._running = True
        self.bus.subscribe_outbound(self._on_outbound)

        self._thread = threading.Thread(
            target=self._run_stream,
            args=(client_id, client_secret),
            daemon=True,
        )
        self._thread.start()
        logger.info("DingTalk channel started")

    async def stop(self) -> None:
        self._running = False
        self.bus.unsubscribe_outbound(self._on_outbound)

        stream_client = self._stream_client
        if stream_client is not None:
            try:
                if hasattr(stream_client, "disconnect"):
                    stream_client.disconnect()
            except Exception:
                logger.debug("[DingTalk] error disconnecting stream client", exc_info=True)

        self._dingtalk_client = None
        self._stream_client = None
        with self._incoming_messages_lock:
            self._incoming_messages.clear()
        self._card_repliers.clear()
        self._card_track_ids.clear()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("DingTalk channel stopped")

    def _resolve_routing(self, msg: OutboundMessage) -> tuple[str, str, str]:
        """Return (conversation_type, sender_staff_id, conversation_id).

        Uses msg.chat_id as the primary routing key; metadata as fallback.
        """
        conversation_type = _normalize_conversation_type(msg.metadata.get("conversation_type"))
        sender_staff_id = msg.metadata.get("sender_staff_id", "")
        conversation_id = msg.metadata.get("conversation_id", "")
        if conversation_type == _CONVERSATION_TYPE_GROUP:
            conversation_id = msg.chat_id or conversation_id
        else:
            sender_staff_id = msg.chat_id or sender_staff_id
        return conversation_type, sender_staff_id, conversation_id

    async def send(self, msg: OutboundMessage, *, _max_retries: int = 3) -> None:
        conversation_type, sender_staff_id, conversation_id = self._resolve_routing(msg)
        robot_code = self._client_id

        # Card mode: stream update to existing AI card
        source_key = self._make_card_source_key_from_outbound(msg)
        out_track_id = self._card_track_ids.get(source_key)

        # ``card_template_id`` enables ``runs.stream`` (non-final + final outbounds).
        # If card creation failed, skip non-final chunks to avoid duplicate messages.
        if self._card_template_id and not out_track_id and not msg.is_final:
            return

        if out_track_id:
            try:
                await self._stream_update_card(
                    out_track_id,
                    msg.text,
                    is_finalize=msg.is_final,
                )
            except Exception:
                logger.warning("[DingTalk] card stream failed, falling back to sampleMarkdown")
                if msg.is_final:
                    self._card_track_ids.pop(source_key, None)
                    self._card_repliers.pop(out_track_id, None)
                    await self._send_markdown_fallback(robot_code, conversation_type, sender_staff_id, conversation_id, msg.text)
                    return
            if msg.is_final:
                self._card_track_ids.pop(source_key, None)
                self._card_repliers.pop(out_track_id, None)
            return

        async def send_markdown() -> None:
            if conversation_type == _CONVERSATION_TYPE_GROUP:
                await self._send_group_message(robot_code, conversation_id, msg.text, at_user_ids=[sender_staff_id] if sender_staff_id else None)
            else:
                await self._send_p2p_message(robot_code, sender_staff_id, msg.text)

        # Non-card mode: send sampleMarkdown with retry
        await self._send_with_retry(
            send_markdown,
            max_retries=_max_retries,
            log_prefix="[DingTalk]",
        )
        return

    async def _send_markdown_fallback(
        self,
        robot_code: str,
        conversation_type: str,
        sender_staff_id: str,
        conversation_id: str,
        text: str,
    ) -> None:
        try:
            if conversation_type == _CONVERSATION_TYPE_GROUP:
                await self._send_group_message(robot_code, conversation_id, text)
            else:
                await self._send_p2p_message(robot_code, sender_staff_id, text)
        except Exception:
            logger.exception("[DingTalk] markdown fallback also failed")
            raise

    async def send_file(self, msg: OutboundMessage, attachment: ResolvedAttachment) -> bool:
        if attachment.size > _MAX_UPLOAD_SIZE_BYTES:
            logger.warning("[DingTalk] file too large (%d bytes), skipping: %s", attachment.size, attachment.filename)
            return False

        conversation_type, sender_staff_id, conversation_id = self._resolve_routing(msg)
        robot_code = self._client_id

        try:
            media_id = await self._upload_media(attachment.actual_path, "image" if attachment.is_image else "file")
            if not media_id:
                return False

            if attachment.is_image:
                msg_key = "sampleImageMsg"
                msg_param = json.dumps({"photoURL": media_id})
            else:
                msg_key = "sampleFile"
                msg_param = json.dumps(
                    {
                        "fileUrl": media_id,
                        "fileName": attachment.filename,
                        "fileSize": str(attachment.size),
                    }
                )

            token = await self._get_access_token()
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                if conversation_type == _CONVERSATION_TYPE_GROUP:
                    response = await client.post(
                        f"{DINGTALK_API_BASE}/v1.0/robot/groupMessages/send",
                        headers=self._api_headers(token),
                        json={
                            "msgKey": msg_key,
                            "msgParam": msg_param,
                            "robotCode": robot_code,
                            "openConversationId": conversation_id,
                        },
                    )
                else:
                    response = await client.post(
                        f"{DINGTALK_API_BASE}/v1.0/robot/oToMessages/batchSend",
                        headers=self._api_headers(token),
                        json={
                            "msgKey": msg_key,
                            "msgParam": msg_param,
                            "robotCode": robot_code,
                            "userIds": [sender_staff_id],
                        },
                    )
                response.raise_for_status()

            logger.info("[DingTalk] file sent: %s", attachment.filename)
            return True
        except (httpx.HTTPError, OSError, ValueError, TypeError, AttributeError):
            logger.exception("[DingTalk] failed to send file: %s", attachment.filename)
            return False

    # -- stream client (runs in dedicated thread) --------------------------

    def _run_stream(self, client_id: str, client_secret: str) -> None:
        try:
            import dingtalk_stream

            credential = dingtalk_stream.Credential(client_id, client_secret)
            client = dingtalk_stream.DingTalkStreamClient(credential)
            self._stream_client = client
            client.register_callback_handler(
                dingtalk_stream.chatbot.ChatbotMessage.TOPIC,
                _DingTalkMessageHandler(self),
            )
            client.start_forever()
        except Exception:
            if self._running:
                logger.exception("DingTalk Stream Push error")
        finally:
            self._stream_client = None

    def _on_chatbot_message(self, message: Any) -> None:
        if not self._running:
            return
        try:
            sender_staff_id = message.sender_staff_id or ""
            conversation_type = _normalize_conversation_type(message.conversation_type)
            conversation_id = message.conversation_id or ""
            msg_id = message.message_id or ""
            sender_nick = message.sender_nick or ""

            text = self._extract_text(message)
            files = self._extract_files(message)
            if not text and not files:
                logger.info("[DingTalk] empty message with no files, ignoring")
                return

            connect_code = self._pending_connect_code(text)
            if connect_code:
                if self._main_loop and self._main_loop.is_running():
                    fut = asyncio.run_coroutine_threadsafe(
                        self._bind_connection_from_connect_code(
                            conversation_type=conversation_type,
                            sender_staff_id=sender_staff_id,
                            sender_nick=sender_nick,
                            conversation_id=conversation_id,
                            code=connect_code,
                        ),
                        self._main_loop,
                    )
                    fut.add_done_callback(lambda f, mid=msg_id: self._log_future_error(f, "bind_connection", mid))
                else:
                    logger.warning("[DingTalk] main loop not running, cannot bind channel connection")
                return

            if self._allowed_users and sender_staff_id not in self._allowed_users:
                logger.debug("[DingTalk] ignoring message from non-allowed user: %s", sender_staff_id)
                return

            # Log only metadata (length, not content) so message text never reaches
            # INFO logs, and only after the allowed_users gate so blocked senders are
            # not logged at all.
            logger.info(
                "[DingTalk] parsed message: conv_type=%s, msg_id=%s, sender=%s(%s), text_len=%d, files=%d",
                conversation_type,
                msg_id,
                sender_staff_id,
                sender_nick,
                len(text or ""),
                len(files),
            )

            # DingTalk group chats often deliver "@bot /new" with the mention left
            # in the text (Slack/Discord strip their own bot mention upstream).
            # Skip a leading mention only for the command path so ordinary chat
            # keeps @mentions intact for the agent; the stripped form also flows
            # into the inbound so ChannelManager._handle_command parses the bare
            # command. Mirrors FeishuChannel.
            command_text = strip_leading_mentions(text)
            if _is_dingtalk_command(command_text):
                msg_type = InboundMessageType.COMMAND
                text = command_text
            else:
                msg_type = InboundMessageType.CHAT

            # P2P: topic_id=None (single thread per user, like Telegram private chat)
            # Group: topic_id=msg_id (each new message starts a new topic, like Feishu)
            topic_id: str | None = msg_id if conversation_type == _CONVERSATION_TYPE_GROUP else None

            # chat_id uses conversation_id for groups, sender_staff_id for P2P
            chat_id = conversation_id if conversation_type == _CONVERSATION_TYPE_GROUP else sender_staff_id

            # An empty chat_id does not identify a conversation, and ChannelStore keys on it:
            # a P2P message with no sender keys to the literal "dingtalk:", so every such
            # message from every user shares one thread and one history. Mirrors the guard the
            # WeChat channel already applies (wechat.py, `if not chat_id: return`) and the one
            # this file's own bind path applies before persisting a connection.
            if not chat_id:
                logger.warning(
                    "[DingTalk] ignoring message with no conversation identity: conv_type=%s, msg_id=%s",
                    conversation_type,
                    msg_id,
                )
                return

            inbound = self._make_inbound(
                chat_id=chat_id,
                user_id=sender_staff_id,
                text=text,
                msg_type=msg_type,
                thread_ts=msg_id,
                files=files,
                metadata={
                    "conversation_type": conversation_type,
                    "conversation_id": conversation_id,
                    "sender_staff_id": sender_staff_id,
                    "sender_nick": sender_nick,
                    "message_id": msg_id,
                },
            )
            inbound.topic_id = topic_id

            if self._card_template_id:
                source_key = self._make_card_source_key(inbound)
                with self._incoming_messages_lock:
                    self._incoming_messages[source_key] = message

            if self._main_loop and self._main_loop.is_running():
                logger.info("[DingTalk] publishing inbound message to bus (type=%s, msg_id=%s)", msg_type.value, msg_id)
                fut = asyncio.run_coroutine_threadsafe(
                    self._prepare_inbound(chat_id, inbound),
                    self._main_loop,
                )
                fut.add_done_callback(lambda f, mid=msg_id: self._log_future_error(f, "prepare_inbound", mid))
            else:
                logger.warning("[DingTalk] main loop not running, cannot publish inbound message")
        except Exception:
            logger.exception("[DingTalk] error processing chatbot message")

    @staticmethod
    def _extract_text(message: Any) -> str:
        msg_type = message.message_type
        if msg_type == "text" and message.text:
            return message.text.content.strip()
        if msg_type == "richText" and message.rich_text_content:
            return _extract_text_from_rich_text(message.rich_text_content.rich_text_list).strip()
        return ""

    # -- inbound: file attachments -----------------------------------------

    @staticmethod
    def _extract_files(message: Any) -> list[dict[str, Any]]:
        """Extract inbound file/image descriptors from a DingTalk message.

        Returns a list of dicts shaped for ``InboundMessage.files``; each carries
        ``type`` (``"image"`` or ``"file"``), ``download_code``, and ``filename``.

        Images arrive as ``picture`` messages (a single ``downloadCode``) or as
        inline images inside a ``richText`` message. Documents arrive as ``file``
        messages, which ``dingtalk_stream.ChatbotMessage.from_dict`` does not
        parse — the descriptor (``downloadCode`` / ``fileName``) is read from the
        raw callback payload stashed on the message as ``_df_raw_data`` by
        ``_DingTalkMessageHandler.process``.
        """
        msg_type = getattr(message, "message_type", None)
        files: list[dict[str, Any]] = []

        if msg_type == "picture":
            image_content = getattr(message, "image_content", None)
            code = getattr(image_content, "download_code", None)
            if code:
                files.append({"type": "image", "download_code": code, "filename": "image.png"})
        elif msg_type == "richText":
            try:
                codes = message.get_image_list() or []
            except Exception:
                # Log rather than swallow: without this, a richText message whose
                # SDK image parse fails looks identical to one that simply has no
                # inline images, which is hard to diagnose if the SDK shape changes.
                logger.warning("[DingTalk] failed to read inline images from richText message", exc_info=True)
                codes = []
            for idx, code in enumerate(codes):
                if code:
                    files.append({"type": "image", "download_code": code, "filename": f"image_{idx}.png"})
        elif msg_type == "file":
            raw = getattr(message, "_df_raw_data", None)
            content = raw.get("content") if isinstance(raw, dict) else None
            if isinstance(content, dict):
                code = content.get("downloadCode")
                if code:
                    filename = content.get("fileName") or "file.bin"
                    files.append({"type": "file", "download_code": code, "filename": filename})

        return files

    async def receive_file(self, msg: InboundMessage, thread_id: str, *, user_id: str | None = None) -> InboundMessage:
        """Download inbound DingTalk files into the thread uploads directory.

        Mirrors :meth:`FeishuChannel.receive_file`: each descriptor in
        ``msg.files`` is downloaded by its ``downloadCode``, persisted under the
        thread's uploads bucket, synced into a non-local sandbox, and its sandbox
        virtual path is prepended to ``msg.text`` so downstream models can read
        the file by path. Descriptors are then cleared so the generic
        URL-based ``_ingest_inbound_files`` pass does not try to re-fetch them
        (DingTalk files are downloaded by code, not by URL).

        An attachment that fails to download contributes a short
        ``[failed to load ...]`` marker instead of a path, so the agent can tell
        the user something was sent but could not be read rather than silently
        ignoring it.
        """
        if not msg.files:
            return msg

        virtual_paths: list[str] = []
        failures: list[str] = []
        for f in msg.files:
            if not isinstance(f, dict):
                continue
            download_code = f.get("download_code")
            if not download_code:
                continue
            file_type = "image" if f.get("type") == "image" else "file"
            filename = f.get("filename") if isinstance(f.get("filename"), str) else ""
            # Per-attachment isolation: the manager awaits receive_file without a
            # try, so anything escaping here would kill the chat turn with no
            # reply — the silent-drop failure mode this feature exists to fix.
            try:
                virtual_path = await self._receive_single_file(download_code, file_type, filename, thread_id, user_id=user_id)
            except Exception:
                logger.exception("[DingTalk] unexpected error receiving inbound %s", file_type)
                virtual_path = ""
            if virtual_path:
                virtual_paths.append(virtual_path)
            else:
                display = _display_filename(filename)
                failures.append(f"[failed to load {file_type}: {display}]" if display else f"[failed to load {file_type}]")

        prefix_lines = virtual_paths + failures
        if prefix_lines:
            block = "\n".join(prefix_lines)
            msg.text = f"{block}\n\n{msg.text}".strip() if msg.text else block

        msg.files = []
        return msg

    async def _receive_single_file(
        self,
        download_code: str,
        file_type: str,
        filename: str,
        thread_id: str,
        *,
        user_id: str | None = None,
    ) -> str:
        """Download one file by ``downloadCode`` and persist it into uploads.

        Returns the sandbox virtual path on success, or ``""`` on failure.
        """
        content = await self._download_by_code(download_code)
        if not content:
            return ""

        paths = get_paths()
        effective_user_id = user_id or get_effective_user_id()

        default_ext = "png" if file_type == "image" else "bin"
        # ``download_code`` is attacker-controllable webhook data, so restrict it to
        # a safe character set before embedding it in the fallback name. This keeps
        # the fallback safe by construction instead of relying on a later write
        # failure to reject a name that escaped the uploads directory.
        code_token = re.sub(r"[^A-Za-z0-9_-]", "", download_code)[-12:] or "attachment"
        fallback_name = f"dingtalk_{code_token}.{default_ext}"
        # normalize_filename strips directory components and rejects traversal
        # patterns ("..", backslash paths, over-long names); fall back to the
        # sanitized generated name if the platform-supplied filename is rejected.
        try:
            safe_filename = normalize_filename(filename or fallback_name)
        except ValueError:
            safe_filename = fallback_name

        def _persist() -> Path:
            # Directory prep, the uniqueness claim, and the write are blocking
            # filesystem IO — the whole sequence stays off the event loop. The
            # claim and the write share one lock because generated names repeat
            # across messages ("image.png" for every picture message): without a
            # claim a later attachment silently overwrites an earlier one whose
            # path was already handed to the agent, and letting the claim and
            # write interleave would resolve two attachments to the same free name.
            paths.ensure_thread_dirs(thread_id, user_id=effective_user_id)
            uploads_dir = paths.sandbox_uploads_dir(thread_id, user_id=effective_user_id).resolve()
            with self._file_write_lock:
                seen = {entry.name for entry in uploads_dir.iterdir() if entry.is_file()}
                unique_name = claim_unique_filename(safe_filename, seen)
                # write_upload_file_no_symlink refuses a symlinked destination:
                # uploads dirs can be mounted into local sandboxes, so a sandbox
                # process could otherwise redirect this privileged write outside
                # the bucket.
                return write_upload_file_no_symlink(uploads_dir, unique_name, content)

        try:
            resolved_target = await asyncio.to_thread(_persist)
        except (OSError, UnsafeUploadPathError):
            logger.exception("[DingTalk] failed to persist downloaded file: %s", safe_filename)
            return ""

        virtual_path = f"{VIRTUAL_PATH_PREFIX}/uploads/{resolved_target.name}"

        try:
            sandbox_provider = get_sandbox_provider()
            # acquire_async keeps provider lifecycle work (Docker discovery,
            # readiness polls) off the event loop; update_file is blocking
            # transport IO on remote sandboxes, so it is offloaded too.
            sandbox_id = await sandbox_provider.acquire_async(thread_id, user_id=effective_user_id)
            if sandbox_id != "local":
                sandbox = sandbox_provider.get(sandbox_id)
                if sandbox is None:
                    # Mirror Feishu: the agent's non-local sandbox cannot see this
                    # file, so returning the virtual path would hand the model a
                    # path that reads as nothing — surface a failed-load marker.
                    logger.warning("[DingTalk] sandbox %s not found after acquire, dropping attachment: %s", sandbox_id, virtual_path)
                    return ""
                await asyncio.to_thread(sandbox.update_file, virtual_path, content)
        except Exception:
            # Same failure mode as the sandbox-is-None branch: the bytes never
            # reached the agent's sandbox, so the virtual path would read as
            # nothing. Mirror Feishu and surface a failed-load marker.
            logger.exception("[DingTalk] failed to sync downloaded file into non-local sandbox: %s", virtual_path)
            return ""

        return virtual_path

    async def _download_by_code(self, download_code: str) -> bytes | None:
        """Exchange a DingTalk ``downloadCode`` for the raw file bytes.

        Two steps per the DingTalk robot OpenAPI:
        1. ``POST /v1.0/robot/messageFiles/download`` -> ``{downloadUrl}``
        2. ``GET downloadUrl`` -> binary content
        """
        try:
            # Token acquisition stays inside the try: the manager awaits
            # receive_file without a try, so a token failure escaping here would
            # abort the whole chat turn instead of degrading to a failed-load marker.
            token = await self._get_access_token()
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                response = await client.post(
                    f"{DINGTALK_API_BASE}/v1.0/robot/messageFiles/download",
                    headers={
                        "x-acs-dingtalk-access-token": token,
                        "Content-Type": "application/json",
                    },
                    json={"downloadCode": download_code, "robotCode": self._client_id},
                )
                if response.status_code != 200:
                    logger.warning("[DingTalk] messageFiles/download failed: status=%d, body=%s", response.status_code, response.text[:300])
                    return None
                download_url = response.json().get("downloadUrl")
                if not download_url:
                    logger.warning("[DingTalk] messageFiles/download returned no downloadUrl")
                    return None

                # Stream with a size cap: the bytes are buffered in memory before
                # being persisted, so an oversized attachment must be refused
                # before it is fully read, not after.
                chunks: list[bytes] = []
                total = 0
                async with client.stream("GET", download_url, follow_redirects=True) as file_response:
                    file_response.raise_for_status()
                    async for chunk in file_response.aiter_bytes():
                        total += len(chunk)
                        if total > _MAX_INBOUND_FILE_SIZE_BYTES:
                            logger.warning("[DingTalk] inbound file exceeds %d bytes, dropping", _MAX_INBOUND_FILE_SIZE_BYTES)
                            return None
                        chunks.append(chunk)
                return b"".join(chunks)
        except (httpx.HTTPError, ValueError):
            logger.exception("[DingTalk] failed to download file by code")
            return None

    async def _prepare_inbound(self, chat_id: str, inbound: InboundMessage) -> None:
        inbound = await self._attach_connection_identity(inbound)
        # Running reply must finish before publish_inbound so AI card tracks are
        # registered before the manager emits streaming outbounds.
        await self._send_running_reply(chat_id, inbound)
        await self.bus.publish_inbound(inbound)

    @staticmethod
    def _connection_workspace_id(conversation_type: str, conversation_id: str) -> str | None:
        if conversation_type == _CONVERSATION_TYPE_GROUP and conversation_id:
            return conversation_id
        return None

    async def _attach_connection_identity(self, inbound: InboundMessage) -> InboundMessage:
        conversation_type = str(inbound.metadata.get("conversation_type") or _CONVERSATION_TYPE_P2P)
        conversation_id = str(inbound.metadata.get("conversation_id") or "")
        return await attach_connection_identity(
            inbound,
            repo=self._connection_repo,
            provider="dingtalk",
            workspace_id=self._connection_workspace_id(conversation_type, conversation_id),
            fallback_without_workspace=True,
        )

    async def _bind_connection_from_connect_code(
        self,
        *,
        conversation_type: str,
        sender_staff_id: str,
        sender_nick: str,
        conversation_id: str,
        code: str,
    ) -> bool:
        if self._connection_repo is None or not code:
            return False

        state = await self._connection_repo.consume_oauth_state(provider="dingtalk", state=code)
        if state is None:
            await self._send_connection_reply(
                conversation_type,
                sender_staff_id,
                conversation_id,
                "DingTalk connection code is invalid or expired.",
            )
            return True

        if not sender_staff_id:
            await self._send_connection_reply(
                conversation_type,
                sender_staff_id,
                conversation_id,
                "DingTalk connection could not be completed from this message.",
            )
            return True

        await self._connection_repo.upsert_connection(
            owner_user_id=state["owner_user_id"],
            provider="dingtalk",
            external_account_id=sender_staff_id,
            external_account_name=sender_nick or None,
            workspace_id=self._connection_workspace_id(conversation_type, conversation_id),
            metadata={
                "conversation_type": conversation_type,
                "conversation_id": conversation_id,
            },
            status="connected",
        )
        await self._send_connection_reply(
            conversation_type,
            sender_staff_id,
            conversation_id,
            "DingTalk connected to DeerFlow.",
        )
        return True

    async def _send_connection_reply(
        self,
        conversation_type: str,
        sender_staff_id: str,
        conversation_id: str,
        text: str,
    ) -> None:
        robot_code = self._client_id
        if conversation_type == _CONVERSATION_TYPE_GROUP:
            if conversation_id:
                await self._send_text_message_to_group(robot_code, conversation_id, text)
            return
        if sender_staff_id:
            await self._send_text_message_to_user(robot_code, sender_staff_id, text)

    async def _send_running_reply(self, chat_id: str, inbound: InboundMessage) -> None:
        conversation_type = inbound.metadata.get("conversation_type", _CONVERSATION_TYPE_P2P)
        sender_staff_id = inbound.metadata.get("sender_staff_id", "")
        conversation_id = inbound.metadata.get("conversation_id", "")
        text = "\u23f3 Working on it..."

        try:
            if self._card_template_id:
                source_key = self._make_card_source_key(inbound)
                with self._incoming_messages_lock:
                    chatbot_message = self._incoming_messages.pop(source_key, None)
                out_track_id = await self._create_and_deliver_card(
                    text,
                    chatbot_message=chatbot_message,
                )
                if out_track_id:
                    self._card_track_ids[source_key] = out_track_id
                    logger.info("[DingTalk] AI card running reply sent for chat=%s", chat_id)
                    return

            robot_code = self._client_id
            if conversation_type == _CONVERSATION_TYPE_GROUP:
                await self._send_text_message_to_group(robot_code, conversation_id, text)
            else:
                await self._send_text_message_to_user(robot_code, sender_staff_id, text)
            logger.info("[DingTalk] 'Working on it...' reply sent for chat=%s", chat_id)
        except Exception:
            logger.exception("[DingTalk] failed to send running reply for chat=%s", chat_id)

    # -- DingTalk API helpers ----------------------------------------------

    async def _get_access_token(self) -> str:
        if self._cached_token and time.monotonic() < self._token_expires_at:
            return self._cached_token
        async with self._token_lock:
            if self._cached_token and time.monotonic() < self._token_expires_at:
                return self._cached_token
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                response = await client.post(
                    f"{DINGTALK_API_BASE}/v1.0/oauth2/accessToken",
                    json={"appKey": self._client_id, "appSecret": self._client_secret},  # DingTalk API field names
                )
                response.raise_for_status()
                data = response.json()

                if not isinstance(data, dict):
                    raise ValueError(f"DingTalk access token response must be a JSON object, got {type(data).__name__}")

                access_token = data.get("accessToken")
                if not isinstance(access_token, str) or not access_token.strip():
                    raise ValueError("DingTalk access token response did not contain a usable accessToken")

                raw_expires_in = data.get("expireIn", 7200)
                try:
                    expires_in = int(raw_expires_in)
                except (TypeError, ValueError):
                    logger.warning("[DingTalk] invalid expireIn value %r, using default 7200s", raw_expires_in)
                    expires_in = 7200

                self._cached_token = access_token.strip()
                self._token_expires_at = time.monotonic() + expires_in - _TOKEN_REFRESH_MARGIN_SECONDS
                return self._cached_token

    @staticmethod
    def _api_headers(token: str) -> dict[str, str]:
        return {
            "x-acs-dingtalk-access-token": token,
            "Content-Type": "application/json",
        }

    async def _send_text_message_to_user(self, robot_code: str, user_id: str, text: str) -> None:
        token = await self._get_access_token()
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.post(
                f"{DINGTALK_API_BASE}/v1.0/robot/oToMessages/batchSend",
                headers=self._api_headers(token),
                json={
                    "msgKey": "sampleText",
                    "msgParam": json.dumps({"content": text}),
                    "robotCode": robot_code,
                    "userIds": [user_id],
                },
            )
            response.raise_for_status()

    async def _send_text_message_to_group(self, robot_code: str, conversation_id: str, text: str) -> None:
        token = await self._get_access_token()
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.post(
                f"{DINGTALK_API_BASE}/v1.0/robot/groupMessages/send",
                headers=self._api_headers(token),
                json={
                    "msgKey": "sampleText",
                    "msgParam": json.dumps({"content": text}),
                    "robotCode": robot_code,
                    "openConversationId": conversation_id,
                },
            )
            response.raise_for_status()

    async def _send_p2p_message(self, robot_code: str, user_id: str, text: str) -> None:
        text = _adapt_markdown_for_dingtalk(text)
        token = await self._get_access_token()
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.post(
                f"{DINGTALK_API_BASE}/v1.0/robot/oToMessages/batchSend",
                headers=self._api_headers(token),
                json={
                    "msgKey": "sampleMarkdown",
                    "msgParam": json.dumps({"title": "DeerFlow", "text": text}),
                    "robotCode": robot_code,
                    "userIds": [user_id],
                },
            )
            response.raise_for_status()
            data = response.json()
            if data.get("processQueryKey"):
                logger.info("[DingTalk] P2P message sent to user=%s", user_id)
            else:
                logger.warning("[DingTalk] P2P send response: %s", data)

    async def _send_group_message(
        self,
        robot_code: str,
        conversation_id: str,
        text: str,
        *,
        at_user_ids: list[str] | None = None,  # noqa: ARG002
    ) -> None:
        # at_user_ids accepted for call-site compatibility but not passed to the API
        # (sampleMarkdown does not support @mentions).
        text = _adapt_markdown_for_dingtalk(text)
        token = await self._get_access_token()

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.post(
                f"{DINGTALK_API_BASE}/v1.0/robot/groupMessages/send",
                headers=self._api_headers(token),
                json={
                    "msgKey": "sampleMarkdown",
                    "msgParam": json.dumps({"title": "DeerFlow", "text": text}),
                    "robotCode": robot_code,
                    "openConversationId": conversation_id,
                },
            )
            response.raise_for_status()
            data = response.json()
            if data.get("processQueryKey"):
                logger.info("[DingTalk] group message sent to conversation=%s", conversation_id)
            else:
                logger.warning("[DingTalk] group send response: %s", data)

    # -- AI Card streaming helpers -------------------------------------------

    def _make_card_source_key(self, inbound: InboundMessage) -> str:
        m = inbound.metadata
        return f"{m.get('conversation_type', '')}:{m.get('sender_staff_id', '')}:{m.get('conversation_id', '')}:{m.get('message_id', '')}"

    def _make_card_source_key_from_outbound(self, msg: OutboundMessage) -> str:
        m = msg.metadata
        correlation_id = m.get("message_id") or msg.thread_ts or ""
        return f"{m.get('conversation_type', '')}:{m.get('sender_staff_id', '')}:{m.get('conversation_id', '')}:{correlation_id}"

    async def _create_and_deliver_card(
        self,
        initial_text: str,
        *,
        chatbot_message: Any = None,
    ) -> str | None:
        if self._dingtalk_client is None or chatbot_message is None:
            logger.warning("[DingTalk] SDK client or chatbot_message unavailable, skipping AI card")
            return None

        try:
            from dingtalk_stream.card_replier import AICardReplier
        except ImportError:
            logger.warning("[DingTalk] dingtalk-stream card_replier not available")
            return None

        try:
            replier = AICardReplier(self._dingtalk_client, chatbot_message)
            card_instance_id = await replier.async_create_and_deliver_card(
                card_template_id=self._card_template_id,
                card_data={"content": initial_text},
            )
            if not card_instance_id:
                return None

            self._card_repliers[card_instance_id] = replier
            logger.info("[DingTalk] AI card created: outTrackId=%s", card_instance_id)
            return card_instance_id
        except Exception:
            logger.exception("[DingTalk] failed to create AI card")
            return None

    async def _stream_update_card(
        self,
        out_track_id: str,
        content: str,
        *,
        is_finalize: bool = False,
        is_error: bool = False,
    ) -> None:
        replier = self._card_repliers.get(out_track_id)
        if not replier:
            raise RuntimeError(f"No AICardReplier found for track ID {out_track_id}")

        await replier.async_streaming(
            card_instance_id=out_track_id,
            content_key="content",
            content_value=content,
            append=False,
            finished=is_finalize,
            failed=is_error,
        )

    # -- media upload --------------------------------------------------------

    async def _upload_media(self, file_path: str | Path, media_type: str) -> str | None:
        try:
            file_bytes = await asyncio.to_thread(Path(file_path).read_bytes)
            token = await self._get_access_token()
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                response = await client.post(
                    f"{DINGTALK_API_BASE}/v1.0/files/upload",
                    headers={"x-acs-dingtalk-access-token": token},
                    files={"file": ("upload", file_bytes)},
                    data={"type": media_type},
                )
                response.raise_for_status()
                try:
                    payload = response.json()
                except json.JSONDecodeError:
                    logger.exception("[DingTalk] failed to decode upload response JSON: %s", file_path)
                    return None
                if not isinstance(payload, dict):
                    logger.warning("[DingTalk] unexpected upload response type %s for %s", type(payload).__name__, file_path)
                    return None
                return payload.get("mediaId")
        except (httpx.HTTPError, OSError):
            logger.exception("[DingTalk] failed to upload media: %s", file_path)
            return None


class _DingTalkMessageHandler:
    """Callback handler registered with dingtalk-stream."""

    def __init__(self, channel: DingTalkChannel) -> None:
        self._channel = channel

    def pre_start(self) -> None:
        if hasattr(self, "dingtalk_client") and self.dingtalk_client is not None:
            self._channel._dingtalk_client = self.dingtalk_client

    async def raw_process(self, callback_message: Any) -> Any:
        import dingtalk_stream
        from dingtalk_stream.frames import Headers

        code, message = await self.process(callback_message)
        ack_message = dingtalk_stream.AckMessage()
        ack_message.code = code
        ack_message.headers.message_id = callback_message.headers.message_id
        ack_message.headers.content_type = Headers.CONTENT_TYPE_APPLICATION_JSON
        ack_message.data = {"response": message}
        return ack_message

    async def process(self, callback: Any) -> tuple[int, str]:
        import dingtalk_stream

        incoming_message = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
        # Stash the raw callback payload: dingtalk_stream does not parse ``file``
        # (document) messages, so DingTalkChannel._extract_files reads the file
        # descriptor (downloadCode / fileName) from it.
        incoming_message._df_raw_data = callback.data
        self._channel._on_chatbot_message(incoming_message)
        return dingtalk_stream.AckMessage.STATUS_OK, "OK"
