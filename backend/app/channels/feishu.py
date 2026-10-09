"""Feishu/Lark channel — connects to Feishu via WebSocket (no public IP needed)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import stat
import threading
import time
from collections import deque
from collections.abc import Callable, Coroutine
from concurrent.futures import CancelledError as FutureCancelledError
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

from app.channels.base import Channel, ChannelStopTimeout
from app.channels.commands import is_known_channel_command, strip_leading_mentions
from app.channels.connection_identity import attach_connection_identity
from app.channels.message_bus import (
    PENDING_CLARIFICATION_METADATA_KEY,
    RESOLVED_FROM_PENDING_CLARIFICATION_METADATA_KEY,
    InboundMessage,
    InboundMessageType,
    InboundReservation,
    MessageBus,
    OutboundMessage,
    ResolvedAttachment,
)
from app.channels.sandbox_files import sync_file_to_thread_sandbox
from deerflow.config.paths import VIRTUAL_PATH_PREFIX, get_paths
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.sandbox.sandbox_provider import get_sandbox_provider
from deerflow.uploads.manager import (
    apply_upload_sandbox_permits,
    claim_unique_filename,
    normalize_filename,
    write_upload_file_no_symlink,
)

logger = logging.getLogger(__name__)
PENDING_CLARIFICATION_TTL_SECONDS = 30 * 60
# Channel-store deadlines. ``_on_message`` runs on lark-oapi's private event loop,
# which also carries the SDK's websocket reads, pongs and its 120s ping loop:
# every second the bridge blocks that loop is a second the connection cannot
# service keepalives, so the bound is a few seconds (one indexed SELECT per
# candidate), not the database's 30s command timeout. The deadline lives on the
# Gateway-loop side (``asyncio.wait_for`` around the store calls, which actually
# cancels them); the bridge wait only adds slack for a stalled Gateway loop.
FEISHU_STORE_LOOKUP_TIMEOUT_SECONDS = 3.0
FEISHU_STORE_BRIDGE_TIMEOUT_SECONDS = FEISHU_STORE_LOOKUP_TIMEOUT_SECONDS + 1.0
# A lookup that missed its deadline (or failed) is *unresolved*, never a miss:
# the message is deferred to the Gateway loop, which retries with backoff up to
# the database's own command budget and then drops it rather than opening a new
# conversation for a reply whose mapping the database could still have served.
FEISHU_STORE_RESOLVE_TOTAL_BUDGET_SECONDS = 30.0
FEISHU_STORE_RESOLVE_RETRY_BACKOFF_SECONDS = 1.0
FEISHU_STORE_RESOLVE_RETRY_MAX_BACKOFF_SECONDS = 8.0
_T = TypeVar("_T")


class StoreLookupUnresolved(Exception):
    """A channel-store call produced no answer: deadline, store error, no Gateway loop, or channel stop.

    Distinct from a *miss* (the store answered "no mapping"): an unresolved lookup
    must never route a message as if the mapping did not exist.
    """

    def __init__(self, reason: str, *, future: Future[Any] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        # The still-running bridge future when the lark-thread wait gave up before
        # the coroutine's own deadline; the deferred path awaits its outcome first.
        self.future = future


@dataclass(slots=True)
class _ParsedMessage:
    """The content of one lark message event, independent of how it is routed."""

    chat_id: str
    msg_id: str
    sender_id: str
    root_id: str | None
    parent_id: str | None
    feishu_thread_id: str | None
    chat_type: str | None
    text: str
    files: list[dict[str, Any]]
    msg_type: InboundMessageType = InboundMessageType.CHAT


@dataclass(frozen=True, slots=True)
class _Routing:
    """Where a parsed message goes: resolved (stored mapping), plain miss, or pending clarification."""

    topic_id: str | None
    from_stored_mapping: bool
    from_pending: bool


@dataclass(slots=True)
class _RoutingAttempt:
    """Retry state for one message: once a pending clarification is consumed the route is decided."""

    parsed: _ParsedMessage
    pending: dict[str, Any] | None = None
    attempted: bool = False


FEISHU_INBOUND_BATCH_WINDOW_SECONDS = 0.75
FEISHU_MAX_INBOUND_FILE_BYTES = 20_000_000
SOURCE_PREVIEW_METADATA_KEY = "feishu_source_preview"


def _is_feishu_command(text: str) -> bool:
    return is_known_channel_command(text)


class FeishuChannel(Channel):
    """Feishu/Lark IM channel using the ``lark-oapi`` WebSocket client.

    Configuration keys (in ``config.yaml`` under ``channels.feishu``):
        - ``app_id``: Feishu app ID.
        - ``app_secret``: Feishu app secret.
        - ``verification_token``: (optional) Event verification token.

    The channel uses WebSocket long-connection mode so no public IP is required.

    Message flow:
        1. User sends a message → bot adds "OK" emoji reaction
        2. Bot replies with a card: "Working on it......"
        3. Agent processes the message and returns a result
        4. Bot updates the card with the result
        5. Bot adds "DONE" emoji reaction to the original message
    """

    def __init__(self, bus: MessageBus, config: dict[str, Any]) -> None:
        super().__init__(name="feishu", bus=bus, config=config)
        self._thread: threading.Thread | None = None
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._api_client = None
        self._CreateMessageReactionRequest = None
        self._CreateMessageReactionRequestBody = None
        self._Emoji = None
        self._PatchMessageRequest = None
        self._PatchMessageRequestBody = None
        self._background_tasks: set[asyncio.Task] = set()
        self._running_card_ids: dict[str, str] = {}
        self._running_card_tasks: dict[str, asyncio.Task] = {}
        self._pending_clarifications: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._pending_inbound_batches: dict[tuple[str, str], dict[str, Any]] = {}
        self._CreateFileRequest = None
        self._CreateFileRequestBody = None
        self._CreateImageRequest = None
        self._CreateImageRequestBody = None
        self._GetMessageResourceRequest = None
        self._thread_lock = threading.Lock()
        # Per-chat FIFO of messages whose routing is deferred to the Gateway loop
        # (unresolved store lookups); guarded by ``_thread_lock``. A chat with a
        # queue has one drain task owning that deque.
        self._deferred_routing: dict[str, deque[_RoutingAttempt]] = {}

    @staticmethod
    def _non_empty_str(value: Any) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @staticmethod
    def _pending_key(chat_id: str, user_id: str) -> tuple[str, str]:
        return (chat_id, user_id)

    @staticmethod
    def _should_include_source_preview(
        *,
        chat_type: str | None,
        root_id: str | None,
        parent_id: str | None,
        thread_id: str | None,
    ) -> bool:
        if chat_type == "p2p":
            return False
        return bool(root_id or parent_id or thread_id)

    @staticmethod
    def _compact_source_preview(text: str) -> str | None:
        stripped = text.strip()
        if not stripped:
            return None

        lines = [line.strip() for line in stripped.splitlines() if line.strip()]
        if not lines:
            return None
        preview = "\n".join(lines[:3])
        if len(preview) > 240:
            preview = preview[:237].rstrip() + "..."
        return preview

    @classmethod
    def _compose_card_text(cls, text: str, metadata: dict[str, Any] | None = None) -> str:
        preview = None
        if isinstance(metadata, dict):
            raw_preview = metadata.get(SOURCE_PREVIEW_METADATA_KEY)
            if isinstance(raw_preview, str) and raw_preview.strip():
                preview = raw_preview.strip()
        if not preview:
            return text

        quoted_preview = "\n".join(f"> {line}" for line in preview.splitlines())
        return f"{quoted_preview}\n\n{text}"

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def is_running(self) -> bool:
        if not self._running:
            return False
        return self._thread is not None and self._thread.is_alive()

    def _build_event_handler(self, lark):
        return (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_message)
            .register_p2_im_message_message_read_v1(self._on_ignored_message_event)
            .register_p2_im_message_reaction_created_v1(self._on_ignored_message_event)
            .register_p2_im_message_reaction_deleted_v1(self._on_ignored_message_event)
            .register_p2_im_message_recalled_v1(self._on_ignored_message_event)
            .build()
        )

    async def start(self) -> None:
        if self._running:
            return

        try:
            import lark_oapi as lark
            from lark_oapi.api.im.v1 import (
                CreateFileRequest,
                CreateFileRequestBody,
                CreateImageRequest,
                CreateImageRequestBody,
                CreateMessageReactionRequest,
                CreateMessageReactionRequestBody,
                CreateMessageRequest,
                CreateMessageRequestBody,
                Emoji,
                GetMessageResourceRequest,
                PatchMessageRequest,
                PatchMessageRequestBody,
                ReplyMessageRequest,
                ReplyMessageRequestBody,
            )
        except ImportError:
            logger.error("lark-oapi is not installed. Install it with: uv add lark-oapi")
            return

        self._lark = lark
        self._CreateMessageRequest = CreateMessageRequest
        self._CreateMessageRequestBody = CreateMessageRequestBody
        self._ReplyMessageRequest = ReplyMessageRequest
        self._ReplyMessageRequestBody = ReplyMessageRequestBody
        self._CreateMessageReactionRequest = CreateMessageReactionRequest
        self._CreateMessageReactionRequestBody = CreateMessageReactionRequestBody
        self._Emoji = Emoji
        self._PatchMessageRequest = PatchMessageRequest
        self._PatchMessageRequestBody = PatchMessageRequestBody
        self._CreateFileRequest = CreateFileRequest
        self._CreateFileRequestBody = CreateFileRequestBody
        self._CreateImageRequest = CreateImageRequest
        self._CreateImageRequestBody = CreateImageRequestBody
        self._GetMessageResourceRequest = GetMessageResourceRequest

        app_id = self.config.get("app_id", "")
        app_secret = self.config.get("app_secret", "")
        domain = self.config.get("domain", "https://open.feishu.cn")

        if not app_id or not app_secret:
            logger.error("Feishu channel requires app_id and app_secret")
            return

        self._api_client = lark.Client.builder().app_id(app_id).app_secret(app_secret).domain(domain).build()
        logger.info("[Feishu] using domain: %s", domain)
        self._main_loop = asyncio.get_event_loop()

        self._open_threadsafe_future_intake()
        self._running = True
        self.bus.subscribe_outbound(self._on_outbound)

        # Both ws.Client construction and start() must happen in a dedicated
        # thread with its own event loop.  lark-oapi caches the running loop
        # at construction time and later calls loop.run_until_complete(),
        # which conflicts with an already-running uvloop.
        self._thread = threading.Thread(
            target=self._run_ws,
            args=(app_id, app_secret, domain),
            daemon=True,
        )
        self._thread.start()
        logger.info("Feishu channel started")

    def _run_ws(self, app_id: str, app_secret: str, domain: str) -> None:
        """Construct and run the lark WS client in a thread with a fresh event loop.

        The lark-oapi SDK captures a module-level event loop at import time
        (``lark_oapi.ws.client.loop``).  When uvicorn uses uvloop, that
        captured loop is the *main* thread's uvloop — which is already
        running, so ``loop.run_until_complete()`` inside ``Client.start()``
        raises ``RuntimeError``.

        We work around this by creating a plain asyncio event loop for this
        thread and patching the SDK's module-level reference before calling
        ``start()``.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            import lark_oapi as lark
            import lark_oapi.ws.client as _ws_client_mod

            # Replace the SDK's module-level loop so Client.start() uses
            # this thread's (non-running) event loop instead of the main
            # thread's uvloop.
            _ws_client_mod.loop = loop

            event_handler = self._build_event_handler(lark)
            ws_client = lark.ws.Client(
                app_id=app_id,
                app_secret=app_secret,
                event_handler=event_handler,
                log_level=lark.LogLevel.INFO,
                domain=domain,
            )
            ws_client.start()
        except Exception:
            if self._running:
                logger.exception("Feishu WebSocket error")
            self._running = False

    def _on_ignored_message_event(self, event) -> None:
        logger.debug("[Feishu] ignoring non-content message event: %s", type(event).__name__)

    async def stop(self) -> None:
        self._running = False
        self.bus.unsubscribe_outbound(self._on_outbound)
        await self._close_and_drain_threadsafe_futures()

        background_tasks = tuple(self._background_tasks)
        running_card_tasks = tuple(self._running_card_tasks.values())
        for task in background_tasks:
            task.cancel()
        for task in running_card_tasks:
            task.cancel()
        if background_tasks or running_card_tasks:
            await asyncio.gather(*background_tasks, *running_card_tasks, return_exceptions=True)
        self._background_tasks.clear()
        self._running_card_tasks.clear()
        if self._thread:
            # The SDK thread only returns on a fatal error, so this join
            # normally waits out its full timeout; keep it off the event loop.
            thread = self._thread
            await asyncio.to_thread(thread.join, timeout=5)
            if thread.is_alive():
                raise ChannelStopTimeout("Feishu SDK thread is still running after stop timeout")
            if self._thread is thread:
                self._thread = None
        logger.info("Feishu channel stopped")

    async def send(self, msg: OutboundMessage, *, _max_retries: int = 3) -> None:
        if not self._api_client:
            logger.warning("[Feishu] send called but no api_client available")
            return

        logger.info(
            "[Feishu] sending reply: chat_id=%s, thread_ts=%s, text_len=%d",
            msg.chat_id,
            msg.thread_ts,
            len(msg.text),
        )

        await self._send_with_retry(
            lambda: self._send_card_message(msg),
            max_retries=_max_retries,
            log_prefix="[Feishu]",
        )

    async def send_file(self, msg: OutboundMessage, attachment: ResolvedAttachment) -> bool:
        if not self._api_client:
            return False

        # Check size limits (image: 10MB, file: 30MB)
        if attachment.is_image and attachment.size > 10 * 1024 * 1024:
            logger.warning("[Feishu] image too large (%d bytes), skipping: %s", attachment.size, attachment.filename)
            return False
        if not attachment.is_image and attachment.size > 30 * 1024 * 1024:
            logger.warning("[Feishu] file too large (%d bytes), skipping: %s", attachment.size, attachment.filename)
            return False

        try:
            if attachment.is_image:
                file_key = await self._upload_image(attachment.actual_path)
                msg_type = "image"
                content = json.dumps({"image_key": file_key})
            else:
                file_key = await self._upload_file(attachment.actual_path, attachment.filename)
                msg_type = "file"
                content = json.dumps({"file_key": file_key})

            if msg.thread_ts:
                request = self._ReplyMessageRequest.builder().message_id(msg.thread_ts).request_body(self._ReplyMessageRequestBody.builder().msg_type(msg_type).content(content).build()).build()
                response = await asyncio.to_thread(self._api_client.im.v1.message.reply, request)
            else:
                request = self._CreateMessageRequest.builder().receive_id_type("chat_id").request_body(self._CreateMessageRequestBody.builder().receive_id(msg.chat_id).msg_type(msg_type).content(content).build()).build()
                response = await asyncio.to_thread(self._api_client.im.v1.message.create, request)
            if not response.success():
                raise RuntimeError(f"Feishu file send failed: code={response.code}, msg={response.msg}, log_id={response.get_log_id()}")

            logger.info("[Feishu] file sent: %s (type=%s)", attachment.filename, msg_type)
            return True
        except Exception:
            logger.exception("[Feishu] failed to upload/send file: %s", attachment.filename)
            return False

    def _upload_image_sync(self, path):
        with open(str(path), "rb") as f:
            request = self._CreateImageRequest.builder().request_body(self._CreateImageRequestBody.builder().image_type("message").image(f).build()).build()
            return self._api_client.im.v1.image.create(request)

    async def _upload_image(self, path) -> str:
        """Upload an image to Feishu and return the image_key."""
        response = await asyncio.to_thread(self._upload_image_sync, path)
        if not response.success():
            raise RuntimeError(f"Feishu image upload failed: code={response.code}, msg={response.msg}")
        return response.data.image_key

    def _upload_file_sync(self, path, filename: str, file_type: str):
        with open(str(path), "rb") as f:
            request = self._CreateFileRequest.builder().request_body(self._CreateFileRequestBody.builder().file_type(file_type).file_name(filename).file(f).build()).build()
            return self._api_client.im.v1.file.create(request)

    async def _upload_file(self, path, filename: str) -> str:
        """Upload a file to Feishu and return the file_key."""
        suffix = path.suffix.lower() if hasattr(path, "suffix") else ""
        if suffix in (".xls", ".xlsx", ".csv"):
            file_type = "xls"
        elif suffix in (".ppt", ".pptx"):
            file_type = "ppt"
        elif suffix == ".pdf":
            file_type = "pdf"
        elif suffix in (".doc", ".docx"):
            file_type = "doc"
        else:
            file_type = "stream"

        response = await asyncio.to_thread(self._upload_file_sync, path, filename, file_type)
        if not response.success():
            raise RuntimeError(f"Feishu file upload failed: code={response.code}, msg={response.msg}")
        return response.data.file_key

    async def receive_file(self, msg: InboundMessage, thread_id: str, *, user_id: str | None = None) -> InboundMessage:
        """Download a Feishu file into the thread uploads directory.

        Returns the sandbox virtual path when the image is persisted successfully.
        """
        if not msg.thread_ts:
            logger.warning("[Feishu] received file message without thread_ts, cannot associate with conversation: %s", msg)
            return msg
        files = msg.files
        if not files:
            logger.warning("[Feishu] received message with no files: %s", msg)
            return msg
        text = msg.text
        search_from = 0

        def replace_next_placeholder(placeholder: str, replacement: str) -> None:
            nonlocal search_from, text
            idx = text.find(placeholder, search_from)
            if idx < 0:
                return
            text = f"{text[:idx]}{replacement}{text[idx + len(placeholder) :]}"
            search_from = idx + len(replacement)

        for file in files:
            if file.get("image_key"):
                virtual_path = await self._receive_single_file(msg.thread_ts, file["image_key"], "image", thread_id, user_id=user_id)
                replace_next_placeholder("[image]", virtual_path)
            elif file.get("file_key"):
                virtual_path = await self._receive_single_file(msg.thread_ts, file["file_key"], "file", thread_id, user_id=user_id)
                replace_next_placeholder("[file]", virtual_path)
        msg.text = text
        return msg

    async def _receive_single_file(
        self,
        message_id: str,
        file_key: str,
        type: Literal["image", "file"],
        thread_id: str,
        *,
        user_id: str | None = None,
    ) -> str:
        request = self._GetMessageResourceRequest.builder().message_id(message_id).file_key(file_key).type(type).build()

        def inner():
            return self._api_client.im.v1.message_resource.get(request)

        try:
            response = await asyncio.to_thread(inner)
        except Exception:
            logger.exception("[Feishu] resource get request failed for resource_key=%s type=%s", file_key, type)
            return f"Failed to obtain the [{type}]"

        if not response.success():
            logger.warning(
                "[Feishu] resource get failed: resource_key=%s, type=%s, code=%s, msg=%s, log_id=%s ",
                file_key,
                type,
                response.code,
                response.msg,
                response.get_log_id(),
            )
            return f"Failed to obtain the [{type}]"

        image_stream = getattr(response, "file", None)
        if image_stream is None:
            logger.warning("[Feishu] resource get returned no file stream: resource_key=%s, type=%s", file_key, type)
            return f"Failed to obtain the [{type}]"

        try:
            content = await asyncio.to_thread(image_stream.read, FEISHU_MAX_INBOUND_FILE_BYTES + 1)
        except Exception:
            logger.exception("[Feishu] failed to read resource stream: resource_key=%s, type=%s", file_key, type)
            return f"Failed to obtain the [{type}]"

        if isinstance(content, bytearray):
            content = bytes(content)
        elif isinstance(content, memoryview):
            content = content.tobytes()

        if not content:
            logger.warning("[Feishu] empty resource content: resource_key=%s, type=%s", file_key, type)
            return f"Failed to obtain the [{type}]"
        if not isinstance(content, bytes):
            logger.warning("[Feishu] resource stream returned non-bytes content: resource_key=%s, type=%s", file_key, type)
            return f"Failed to obtain the [{type}]"
        if len(content) > FEISHU_MAX_INBOUND_FILE_BYTES:
            logger.warning(
                "[Feishu] inbound resource exceeds 20 MB download limit, skipping: resource_key=%s, type=%s",
                file_key,
                type,
            )
            return f"Failed to obtain the [{type}]"

        effective_user_id = user_id or get_effective_user_id()
        paths = await asyncio.to_thread(get_paths)

        default_ext = "png" if type == "image" else "bin"
        key_token = re.sub(r"[^A-Za-z0-9_-]", "", file_key)[-12:] or "attachment"
        fallback_name = f"feishu_{key_token}.{default_ext}"
        raw_filename = getattr(response, "file_name", "") or fallback_name
        try:
            safe_filename = normalize_filename(raw_filename)
        except (TypeError, ValueError):
            safe_filename = fallback_name

        def _persist():
            paths.ensure_thread_dirs(thread_id, user_id=effective_user_id)
            uploads_dir = paths.sandbox_uploads_dir(thread_id, user_id=effective_user_id).resolve()
            with self._thread_lock:
                seen = {entry.name for entry in uploads_dir.iterdir()}
                unique_name = claim_unique_filename(safe_filename, seen)
                return write_upload_file_no_symlink(uploads_dir, unique_name, content)

        try:
            resolved_target = await asyncio.to_thread(_persist)
            # Root-written uploads are 0o600, which the non-root sandbox cannot
            # read on a bind-mounted thread dir; grant group/other read like the
            # channel manager's inbound-file path and the HTTP upload route.
            await asyncio.to_thread(apply_upload_sandbox_permits, resolved_target, stat.S_IRGRP | stat.S_IROTH)
        except (OSError, ValueError, RuntimeError):
            logger.exception("[Feishu] failed to persist downloaded resource: %s, type=%s", safe_filename, type)
            return f"Failed to obtain the [{type}]"

        virtual_path = f"{VIRTUAL_PATH_PREFIX}/uploads/{resolved_target.name}"

        try:
            sandbox_provider = await asyncio.to_thread(get_sandbox_provider)
            synced = await sync_file_to_thread_sandbox(
                sandbox_provider,
                thread_id=thread_id,
                user_id=effective_user_id,
                virtual_path=virtual_path,
                content=content,
                owner_prefix="feishu-upload",
                release_on_last=True,
            )
            if not synced:
                logger.warning("[Feishu] sandbox not found for thread_id=%s", thread_id)
                return f"Failed to obtain the [{type}]"
        except Exception:
            logger.exception("[Feishu] failed to sync resource into non-local sandbox: %s", virtual_path)
            return f"Failed to obtain the [{type}]"

        logger.info("[Feishu] downloaded resource mapped: file_key=%s -> %s", file_key, virtual_path)
        return virtual_path

    # -- message formatting ------------------------------------------------

    @staticmethod
    def _build_card_content(text: str) -> str:
        """Build a Feishu interactive card with markdown content.

        Feishu's interactive card format natively renders markdown, including
        headers, bold/italic, code blocks, lists, and links.
        """
        card = {
            "config": {"wide_screen_mode": True, "update_multi": True},
            "elements": [{"tag": "markdown", "content": text}],
        }
        return json.dumps(card)

    # -- reaction helpers --------------------------------------------------

    async def _add_reaction(self, message_id: str, emoji_type: str = "THUMBSUP") -> None:
        """Add an emoji reaction to a message."""
        if not self._api_client or not self._CreateMessageReactionRequest:
            return
        try:
            request = self._CreateMessageReactionRequest.builder().message_id(message_id).request_body(self._CreateMessageReactionRequestBody.builder().reaction_type(self._Emoji.builder().emoji_type(emoji_type).build()).build()).build()
            response = await asyncio.to_thread(self._api_client.im.v1.message_reaction.create, request)
            if not response.success():
                logger.warning(
                    "[Feishu] reaction '%s' add failed for message %s: code=%s, msg=%s, log_id=%s",
                    emoji_type,
                    message_id,
                    response.code,
                    response.msg,
                    response.get_log_id(),
                )
                return
            logger.info("[Feishu] reaction '%s' added to message %s", emoji_type, message_id)
        except Exception:
            logger.exception("[Feishu] failed to add reaction '%s' to message %s", emoji_type, message_id)

    async def _reply_card(self, message_id: str, text: str) -> str | None:
        """Reply with an interactive card and return the created card message ID."""
        if not self._api_client:
            return None

        content = self._build_card_content(text)
        request = self._ReplyMessageRequest.builder().message_id(message_id).request_body(self._ReplyMessageRequestBody.builder().msg_type("interactive").content(content).build()).build()
        response = await asyncio.to_thread(self._api_client.im.v1.message.reply, request)
        if not response.success():
            raise RuntimeError(f"Feishu card reply failed: code={response.code}, msg={response.msg}, log_id={response.get_log_id()}")
        response_data = getattr(response, "data", None)
        return getattr(response_data, "message_id", None)

    async def _create_card(self, chat_id: str, text: str) -> None:
        """Create a new card message in the target chat."""
        if not self._api_client:
            return

        content = self._build_card_content(text)
        request = self._CreateMessageRequest.builder().receive_id_type("chat_id").request_body(self._CreateMessageRequestBody.builder().receive_id(chat_id).msg_type("interactive").content(content).build()).build()
        response = await asyncio.to_thread(self._api_client.im.v1.message.create, request)
        if not response.success():
            raise RuntimeError(f"Feishu card creation failed: code={response.code}, msg={response.msg}, log_id={response.get_log_id()}")

    async def _update_card(self, message_id: str, text: str) -> None:
        """Patch an existing card message in place."""
        if not self._api_client or not self._PatchMessageRequest:
            return

        content = self._build_card_content(text)
        request = self._PatchMessageRequest.builder().message_id(message_id).request_body(self._PatchMessageRequestBody.builder().content(content).build()).build()
        response = await asyncio.to_thread(self._api_client.im.v1.message.patch, request)
        if not response.success():
            raise RuntimeError(f"Feishu card update failed: code={response.code}, msg={response.msg}, log_id={response.get_log_id()}")

    def _track_background_task(self, task: asyncio.Task, *, name: str, msg_id: str) -> None:
        """Keep a strong reference to fire-and-forget tasks and surface errors."""
        self._background_tasks.add(task)
        task.add_done_callback(lambda done_task, task_name=name, mid=msg_id: self._finalize_background_task(done_task, task_name, mid))

    def _finalize_background_task(self, task: asyncio.Task, name: str, msg_id: str) -> None:
        self._background_tasks.discard(task)
        self._log_task_error(task, name, msg_id)

    async def _create_running_card(
        self,
        source_message_id: str,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """Create the running card and cache its message ID when available."""
        running_card_id = await self._reply_card(source_message_id, self._compose_card_text(text, metadata))
        if running_card_id:
            self._running_card_ids[source_message_id] = running_card_id
            logger.info("[Feishu] running card created: source=%s card=%s", source_message_id, running_card_id)
        else:
            logger.warning("[Feishu] running card creation returned no message_id for source=%s, subsequent updates will fall back to new replies", source_message_id)
        return running_card_id

    def _ensure_running_card_started(
        self,
        source_message_id: str,
        text: str = "thinking...",
        *,
        metadata: dict[str, Any] | None = None,
    ) -> asyncio.Task | None:
        """Start running-card creation once per source message."""
        running_card_id = self._running_card_ids.get(source_message_id)
        if running_card_id:
            return None

        running_card_task = self._running_card_tasks.get(source_message_id)
        if running_card_task:
            return running_card_task

        running_card_task = asyncio.create_task(self._create_running_card(source_message_id, text, metadata=metadata))
        self._running_card_tasks[source_message_id] = running_card_task
        running_card_task.add_done_callback(lambda done_task, mid=source_message_id: self._finalize_running_card_task(mid, done_task))
        return running_card_task

    def _finalize_running_card_task(self, source_message_id: str, task: asyncio.Task) -> None:
        if self._running_card_tasks.get(source_message_id) is task:
            self._running_card_tasks.pop(source_message_id, None)
        self._log_task_error(task, "create_running_card", source_message_id)

    async def _ensure_running_card(
        self,
        source_message_id: str,
        text: str = "thinking...",
        *,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """Ensure the in-thread running card exists and track its message ID."""
        running_card_id = self._running_card_ids.get(source_message_id)
        if running_card_id:
            return running_card_id

        running_card_task = self._ensure_running_card_started(
            source_message_id,
            text,
            metadata=metadata,
        )
        if running_card_task is None:
            return self._running_card_ids.get(source_message_id)
        return await running_card_task

    async def _send_running_reply(self, message_id: str, *, metadata: dict[str, Any] | None = None) -> None:
        """Reply to a message in-thread with a running card."""
        try:
            await self._ensure_running_card(message_id, metadata=metadata)
        except Exception:
            logger.exception("[Feishu] failed to send running reply for message %s", message_id)

    async def _send_card_message(self, msg: OutboundMessage) -> None:
        """Send or update the Feishu card tied to the current request."""
        source_message_id = msg.thread_ts
        if source_message_id:
            running_card_id = self._running_card_ids.get(source_message_id)
            awaited_running_card_task = False

            if not running_card_id:
                running_card_task = self._running_card_tasks.get(source_message_id)
                if running_card_task:
                    awaited_running_card_task = True
                    running_card_id = await running_card_task

            if running_card_id:
                card_text = self._compose_card_text(msg.text, msg.metadata)
                try:
                    await self._update_card(running_card_id, card_text)
                except Exception:
                    if not msg.is_final:
                        raise
                    logger.exception(
                        "[Feishu] failed to patch running card %s, falling back to final reply",
                        running_card_id,
                    )
                    fallback_card_id = await self._reply_card(source_message_id, card_text)
                    await self._remember_thread_mapping(msg, source_message_id, fallback_card_id)
                    self._remember_pending_clarification(msg, fallback_card_id)
                else:
                    await self._remember_thread_mapping(msg, source_message_id, running_card_id)
                    self._remember_pending_clarification(msg, running_card_id)
                    logger.info("[Feishu] running card updated: source=%s card=%s", source_message_id, running_card_id)
            elif msg.is_final:
                final_card_id = await self._reply_card(
                    source_message_id,
                    self._compose_card_text(msg.text, msg.metadata),
                )
                await self._remember_thread_mapping(msg, source_message_id, final_card_id)
                self._remember_pending_clarification(msg, final_card_id)
            elif awaited_running_card_task:
                logger.warning(
                    "[Feishu] running card task finished without message_id for source=%s, skipping duplicate non-final creation",
                    source_message_id,
                )
            else:
                created_card_id = await self._ensure_running_card(
                    source_message_id,
                    msg.text,
                    metadata=msg.metadata,
                )
                await self._remember_thread_mapping(msg, source_message_id, created_card_id)

            if msg.is_final:
                self._running_card_ids.pop(source_message_id, None)
                await self._add_reaction(source_message_id, "DONE")
            return

        await self._create_card(msg.chat_id, msg.text)

    # -- internal ----------------------------------------------------------

    async def _remember_thread_mapping(self, msg: OutboundMessage, *topic_ids: str | None) -> None:
        store = self.config.get("channel_store")
        if store is None or not msg.thread_id:
            return

        metadata_topic_ids = [
            msg.metadata.get("message_id"),
            msg.metadata.get("root_id"),
            msg.metadata.get("parent_id"),
            msg.metadata.get("thread_id"),
            msg.metadata.get("topic_id"),
        ]
        user_id = ""
        raw_user_id = msg.metadata.get("user_id")
        if isinstance(raw_user_id, str):
            user_id = raw_user_id

        seen: set[str] = set()
        for topic_id in [*topic_ids, *metadata_topic_ids]:
            topic_id = self._non_empty_str(topic_id)
            if not topic_id or topic_id in seen:
                continue
            seen.add(topic_id)
            try:
                await store.set_thread_id(
                    self.name,
                    msg.chat_id,
                    msg.thread_id,
                    topic_id=topic_id,
                    user_id=user_id,
                )
            except Exception:
                logger.exception("[Feishu] failed to remember thread mapping for topic_id=%s", topic_id)

    def _run_store_call(self, make_coroutine: Callable[[], Coroutine[Any, Any, _T]], *, name: str, msg_id: Any) -> _T:
        """Run an async ``channel_store`` call from the synchronous lark callback.

        The store is async (it may be the shared database table). ``_on_message``
        runs on lark-oapi's thread, so the call is submitted to the Gateway loop
        (``_main_loop``) through the tracked threadsafe-future helper (``stop()``
        drains or cancels it) and awaited here for at most
        ``FEISHU_STORE_BRIDGE_TIMEOUT_SECONDS``.

        That callback does run inside an event loop: ``_run_ws`` gives the SDK
        thread its own loop and lark-oapi 1.5.5 calls ``_on_message``
        synchronously from its async frame handler, so ``get_running_loop()``
        succeeds here on every real message. Blocking that loop briefly is fine —
        it is the SDK's private loop in its own thread, the one that used to block
        on the JSON file rewrite the store did inline — because the coroutine runs
        on the Gateway loop, not on it. The only wait that must be refused is one
        issued from the Gateway loop itself (``get_running_loop() is _main_loop``):
        it would block the loop that has to execute the submitted coroutine.

        Every way of *not* getting an answer — no running Gateway loop, called on
        the Gateway loop, channel stopping, bridge wait exhausted, cancelled by
        stop, or the coroutine's own ``StoreLookupUnresolved`` — raises
        ``StoreLookupUnresolved`` so the caller can defer the message; a timed-out
        wait is never reported as "no mapping". Other exceptions the coroutine
        raised propagate unchanged.
        """
        loop = self._main_loop
        if loop is None or not loop.is_running():
            logger.warning("[Feishu] main loop not running, cannot %s", name)
            raise StoreLookupUnresolved("main loop not running")
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if current is loop:
            logger.warning("[Feishu] %s requested on the Gateway loop itself; a blocking wait here would deadlock it, skipping the channel store call", name)
            raise StoreLookupUnresolved("called on the Gateway loop")
        future = self._submit_threadsafe_coroutine_future(make_coroutine(), loop, name=name, msg_id=msg_id)
        if future is None:
            logger.info("[Feishu] channel stopping, skipped %s", name)
            raise StoreLookupUnresolved("channel stopping")
        try:
            return future.result(timeout=FEISHU_STORE_BRIDGE_TIMEOUT_SECONDS)
        except TimeoutError:
            # Not cancelled: the coroutine carries its own deadline and the
            # deferred path awaits its outcome before retrying.
            logger.warning("[Feishu] %s did not answer within %.0fs; deferring message %s", name, FEISHU_STORE_BRIDGE_TIMEOUT_SECONDS, msg_id)
            raise StoreLookupUnresolved("bridge wait exhausted", future=future) from None
        except FutureCancelledError:
            logger.info("[Feishu] %s cancelled by channel stop", name)
            raise StoreLookupUnresolved("cancelled by channel stop") from None

    def _remember_pending_clarification(self, msg: OutboundMessage, card_message_id: str | None) -> None:
        if not msg.is_final or msg.metadata.get(PENDING_CLARIFICATION_METADATA_KEY) is not True:
            return

        user_id = self._non_empty_str(msg.metadata.get("user_id"))
        topic_id = self._non_empty_str(msg.metadata.get("topic_id"))
        source_message_id = self._non_empty_str(msg.thread_ts) or self._non_empty_str(msg.metadata.get("message_id"))
        if not (user_id and topic_id and msg.thread_id and source_message_id and card_message_id):
            return

        key = self._pending_key(msg.chat_id, user_id)
        pending = {
            "thread_id": msg.thread_id,
            "topic_id": topic_id,
            "source_message_id": source_message_id,
            "card_message_id": card_message_id,
            "created_at": time.time(),
        }
        with self._thread_lock:
            # Plain-message clarification continuity is a short-lived in-memory
            # hint; explicit Feishu replies are still covered by persisted
            # message-id mappings.
            self._pending_clarifications.setdefault(key, []).append(pending)
        logger.info(
            "[Feishu] pending clarification remembered: chat_id=%s user_id=%s topic_id=%s thread_id=%s",
            msg.chat_id,
            user_id,
            topic_id,
            msg.thread_id,
        )

    def _consume_pending_clarification(self, chat_id: str, user_id: str) -> dict[str, Any] | None:
        key = self._pending_key(chat_id, user_id)
        with self._thread_lock:
            pending_items = self._pending_clarifications.get(key)
            if not pending_items:
                return None

            now = time.time()
            while pending_items:
                pending = pending_items.pop(0)
                created_at = pending.get("created_at")
                if isinstance(created_at, (int, float)) and now - created_at <= PENDING_CLARIFICATION_TTL_SECONDS:
                    if pending_items:
                        self._pending_clarifications[key] = pending_items
                    else:
                        self._pending_clarifications.pop(key, None)
                    return pending
                logger.info("[Feishu] pending clarification expired: chat_id=%s user_id=%s", chat_id, user_id)

            self._pending_clarifications.pop(key, None)
            return None

    def _route_without_store(self, parsed: _ParsedMessage) -> _Routing:
        """Routing for a channel constructed without a ``channel_store`` (no lookups possible)."""
        topic_id: str | None = parsed.root_id or parsed.msg_id
        if parsed.chat_type == "p2p":
            topic_id = None
        if parsed.msg_type != InboundMessageType.CHAT:
            return _Routing(topic_id, False, False)
        pending = self._consume_pending_clarification(parsed.chat_id, parsed.sender_id)
        pending_topic_id = self._non_empty_str(pending.get("topic_id")) if pending else None
        if not pending_topic_id:
            return _Routing(topic_id, False, False)
        return _Routing(pending_topic_id, False, True)

    async def _resolve_routing(self, attempt: _RoutingAttempt) -> _Routing:
        """Decide a message's topic on the Gateway loop, consulting and updating the channel store.

        Stored mappings for the root / parent / thread ids win (``_first_stored_topic``);
        otherwise the route is the root (or the message itself; ``None`` in P2P chats),
        unless a pending clarification for the sender names a topic — that topic's
        mapping is then persisted so the manager finds the clarified thread. The
        pending clarification is consumed once: a retried attempt keeps the decision
        and only redoes the write.
        """
        store = self.config.get("channel_store")
        parsed = attempt.parsed
        if attempt.pending is None:
            candidates = [candidate for candidate in (self._non_empty_str(parsed.root_id), parsed.parent_id, parsed.feishu_thread_id) if candidate]
            if candidates:
                stored = await self._first_stored_topic(store, parsed.chat_id, candidates)
                if stored:
                    return _Routing(stored, True, False)
            topic_id: str | None = parsed.root_id or parsed.msg_id
            if parsed.chat_type == "p2p":
                topic_id = None
            if parsed.msg_type != InboundMessageType.CHAT:
                return _Routing(topic_id, False, False)
            pending = self._consume_pending_clarification(parsed.chat_id, parsed.sender_id)
            if not (pending and self._non_empty_str(pending.get("topic_id"))):
                return _Routing(topic_id, False, False)
            attempt.pending = pending
        pending_topic_id = self._non_empty_str(attempt.pending.get("topic_id"))
        thread_id = self._non_empty_str(attempt.pending.get("thread_id"))
        if thread_id:
            await store.set_thread_id(self.name, parsed.chat_id, thread_id, topic_id=pending_topic_id, user_id=parsed.sender_id)
        return _Routing(pending_topic_id, False, True)

    async def _resolve_routing_bounded(self, attempt: _RoutingAttempt) -> _Routing:
        """``_resolve_routing`` under the store deadline; no answer in time (or a store error) is *unresolved*."""
        attempt.attempted = True
        try:
            return await asyncio.wait_for(self._resolve_routing(attempt), FEISHU_STORE_LOOKUP_TIMEOUT_SECONDS)
        except TimeoutError:
            raise StoreLookupUnresolved(f"channel store did not answer within {FEISHU_STORE_LOOKUP_TIMEOUT_SECONDS:.0f}s") from None
        except StoreLookupUnresolved:
            raise
        except Exception as exc:
            # A failing store is not "no mapping": routing on it would open a new
            # conversation for a reply whose thread the database still knows.
            logger.warning("[Feishu] channel store call failed for message %s (%s); treating the lookup as unresolved", attempt.parsed.msg_id, exc.__class__.__name__, exc_info=True)
            raise StoreLookupUnresolved(f"channel store error: {exc.__class__.__name__}") from exc

    async def _first_stored_topic(self, store: Any, chat_id: str, candidates: list[str]) -> str | None:
        """The first candidate topic id the store already maps to a thread, in priority order."""
        for candidate in candidates:
            if await store.get_thread_id(self.name, chat_id, topic_id=candidate):
                return candidate
        return None

    def _defer_routing(self, attempt: _RoutingAttempt, unresolved: StoreLookupUnresolved) -> None:
        """Hand an unresolved message to the Gateway loop (lark thread; never blocks).

        The chat gets a FIFO deque and one drain task; later messages for the same
        chat queue behind it in ``_on_message`` so none overtakes a deferred
        predecessor onto a different thread. Without a running Gateway loop the
        message is dropped (logged) — nothing could dispatch it anyway.
        """
        parsed = attempt.parsed
        loop = self._main_loop
        if loop is None or not loop.is_running():
            logger.warning("[Feishu] dropping message %s for chat %s: %s and no Gateway loop to defer it to", parsed.msg_id, parsed.chat_id, unresolved.reason)
            return
        queue: deque[_RoutingAttempt] = deque([attempt])
        with self._thread_lock:
            existing = self._deferred_routing.get(parsed.chat_id)
            if existing is not None:
                existing.append(attempt)
                return
            self._deferred_routing[parsed.chat_id] = queue
        scheduled = self._submit_threadsafe_coroutine(
            self._drain_deferred_routing(parsed.chat_id, queue, unresolved.future),
            loop,
            name="deferred_routing",
            msg_id=parsed.msg_id,
        )
        if not scheduled:
            with self._thread_lock:
                if self._deferred_routing.get(parsed.chat_id) is queue:
                    del self._deferred_routing[parsed.chat_id]
            logger.warning("[Feishu] dropping message %s for chat %s: %s and the channel is stopping", parsed.msg_id, parsed.chat_id, unresolved.reason)
            return
        logger.info("[Feishu] deferred message %s for chat %s: %s; retrying on the Gateway loop for up to %.0fs", parsed.msg_id, parsed.chat_id, unresolved.reason, FEISHU_STORE_RESOLVE_TOTAL_BUDGET_SECONDS)

    async def _drain_deferred_routing(self, chat_id: str, queue: deque[_RoutingAttempt], first_future: Future[Any] | None) -> None:
        """Resolve and dispatch a chat's deferred messages in order, then retire the queue."""
        try:
            while True:
                with self._thread_lock:
                    if not queue:
                        if self._deferred_routing.get(chat_id) is queue:
                            del self._deferred_routing[chat_id]
                        return
                    attempt = queue[0]
                routing: _Routing | None = None
                if first_future is not None:
                    # The lark thread's own call may still finish (its deadline is
                    # the coroutine's); use that answer before spending retries.
                    pending_first, first_future = first_future, None
                    try:
                        routing = await asyncio.shield(asyncio.wrap_future(pending_first))
                    except StoreLookupUnresolved:
                        routing = None
                if routing is None:
                    routing = await self._retry_routing(attempt)
                try:
                    if routing is None:
                        logger.warning(
                            "[Feishu] dropping message %s for chat %s: the channel store did not answer within %.0fs; not routing it as a new conversation",
                            attempt.parsed.msg_id,
                            chat_id,
                            FEISHU_STORE_RESOLVE_TOTAL_BUDGET_SECONDS,
                        )
                    else:
                        self._dispatch_inbound(attempt.parsed, routing)
                finally:
                    with self._thread_lock:
                        if queue and queue[0] is attempt:
                            queue.popleft()
        finally:
            with self._thread_lock:
                leftover = len(queue)
                queue.clear()
                if self._deferred_routing.get(chat_id) is queue:
                    del self._deferred_routing[chat_id]
            if leftover:
                logger.warning("[Feishu] dropping %d deferred messages for chat %s: the channel is stopping", leftover, chat_id)

    async def _retry_routing(self, attempt: _RoutingAttempt) -> _Routing | None:
        """Retry the bounded resolution with backoff until the total budget; ``None`` when it never answered."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + FEISHU_STORE_RESOLVE_TOTAL_BUDGET_SECONDS
        backoff = FEISHU_STORE_RESOLVE_RETRY_BACKOFF_SECONDS
        while True:
            if attempt.attempted:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return None
                await asyncio.sleep(min(backoff, remaining))
                backoff = min(backoff * 2, FEISHU_STORE_RESOLVE_RETRY_MAX_BACKOFF_SECONDS)
            try:
                return await self._resolve_routing_bounded(attempt)
            except StoreLookupUnresolved as exc:
                logger.debug("[Feishu] retrying routing for message %s: %s", attempt.parsed.msg_id, exc.reason)

    def _dispatch_inbound(self, parsed: _ParsedMessage, routing: _Routing) -> None:
        """Build the inbound for a routed message and hand it to batching / the Gateway loop."""
        try:
            source_preview = None
            if self._should_include_source_preview(chat_type=parsed.chat_type, root_id=parsed.root_id, parent_id=parsed.parent_id, thread_id=parsed.feishu_thread_id):
                source_preview = self._compact_source_preview(parsed.text)

            metadata = {
                "message_id": parsed.msg_id,
                "root_id": parsed.root_id,
                "parent_id": parsed.parent_id,
                "thread_id": parsed.feishu_thread_id,
                "topic_id": routing.topic_id,
                "user_id": parsed.sender_id,
                RESOLVED_FROM_PENDING_CLARIFICATION_METADATA_KEY: routing.from_pending,
            }
            if source_preview:
                metadata[SOURCE_PREVIEW_METADATA_KEY] = source_preview

            inbound = self._make_inbound(
                chat_id=parsed.chat_id,
                user_id=parsed.sender_id,
                text=parsed.text,
                msg_type=parsed.msg_type,
                thread_ts=parsed.msg_id,
                files=parsed.files,
                metadata=metadata,
            )
            inbound.topic_id = routing.topic_id

            if self._is_batchable_file_inbound(
                msg_type=parsed.msg_type,
                text=parsed.text,
                files=parsed.files,
                root_id=parsed.root_id,
                parent_id=parsed.parent_id,
                thread_id=parsed.feishu_thread_id,
            ):
                self._queue_file_inbound_batch(parsed.msg_id, inbound)
                return

            self._schedule_prepare_inbound(parsed.msg_id, inbound)
        except Exception:
            logger.exception("[Feishu] error dispatching message %s", parsed.msg_id)

    @staticmethod
    def _is_batchable_file_inbound(
        *,
        msg_type: InboundMessageType,
        text: str,
        files: list[dict[str, Any]],
        root_id: str | None,
        parent_id: str | None,
        thread_id: str | None,
    ) -> bool:
        return msg_type == InboundMessageType.CHAT and text in {"[file]", "[image]"} and len(files) == 1 and not (root_id or parent_id or thread_id)

    def _schedule_prepare_inbound(
        self,
        msg_id: str,
        inbound: InboundMessage,
        *,
        source_message_ids: list[str] | None = None,
    ) -> None:
        if self._main_loop and self._main_loop.is_running():
            reservation = self._reserve_inbound(inbound)
            if reservation is None:
                return
            logger.info("[Feishu] publishing inbound message to bus (type=%s, msg_id=%s)", inbound.msg_type.value, msg_id)
            scheduled = self._submit_threadsafe_coroutine(
                self._prepare_inbound(
                    msg_id,
                    inbound,
                    source_message_ids=source_message_ids,
                    reservation=reservation,
                ),
                self._main_loop,
                name="prepare_inbound",
                msg_id=msg_id,
                reservation=reservation,
            )
            if not scheduled:
                logger.info("[Feishu] main loop stopped before reserved inbound could be scheduled")
        else:
            logger.warning("[Feishu] main loop not running, cannot publish inbound message")

    def _schedule_batch_flush(self, key: tuple[str, str], source_message_id: str) -> None:
        if self._main_loop and self._main_loop.is_running():
            scheduled = self._submit_threadsafe_coroutine(
                self._flush_pending_inbound_batch_after(key, source_message_id),
                self._main_loop,
                name="flush_inbound_batch",
                msg_id=source_message_id,
            )
            if not scheduled:
                logger.info("[Feishu] main loop stopped before inbound batch flush could be scheduled")
        else:
            logger.warning("[Feishu] main loop not running, cannot flush inbound batch")

    def _queue_file_inbound_batch(self, msg_id: str, inbound: InboundMessage) -> bool:
        key = self._pending_key(inbound.chat_id, inbound.user_id)
        should_schedule_flush = False
        expired_batch: tuple[str, InboundMessage, list[str]] | None = None

        with self._thread_lock:
            batch = self._pending_inbound_batches.get(key)
            now = time.time()
            if batch:
                if now - batch["created_at"] <= FEISHU_INBOUND_BATCH_WINDOW_SECONDS:
                    batched_inbound = batch["inbound"]
                    batch["message_ids"].append(msg_id)
                    batch["text_parts"].append(inbound.text)
                    batched_inbound.text = "\n\n".join(part for part in batch["text_parts"] if part)
                    batched_inbound.files.extend(inbound.files)
                    batched_inbound.metadata["batched_message_ids"] = list(batch["message_ids"])
                    logger.info(
                        "[Feishu] batched inbound file message: chat_id=%s user_id=%s anchor=%s msg_id=%s files=%d",
                        inbound.chat_id,
                        inbound.user_id,
                        batch["anchor_message_id"],
                        msg_id,
                        len(batched_inbound.files),
                    )
                    return True

                expired_batch = (batch["anchor_message_id"], batch["inbound"], list(batch["message_ids"]))

            self._pending_inbound_batches[key] = {
                "anchor_message_id": msg_id,
                "created_at": now,
                "inbound": inbound,
                "message_ids": [msg_id],
                "text_parts": [inbound.text],
            }
            inbound.metadata["batched_message_ids"] = [msg_id]
            should_schedule_flush = True

        if should_schedule_flush:
            self._schedule_batch_flush(key, msg_id)
        if expired_batch:
            anchor_message_id, expired_inbound, source_message_ids = expired_batch
            self._schedule_prepare_inbound(anchor_message_id, expired_inbound, source_message_ids=source_message_ids)
        return True

    def _pop_pending_inbound_batch(self, key: tuple[str, str], *, anchor_message_id: str | None = None) -> tuple[str, InboundMessage, list[str]] | None:
        with self._thread_lock:
            batch = self._pending_inbound_batches.get(key)
            if not batch:
                return None
            if anchor_message_id is not None and batch["anchor_message_id"] != anchor_message_id:
                return None
            self._pending_inbound_batches.pop(key, None)
            return batch["anchor_message_id"], batch["inbound"], list(batch["message_ids"])

    async def _flush_pending_inbound_batch_after(self, key: tuple[str, str], anchor_message_id: str) -> None:
        await asyncio.sleep(FEISHU_INBOUND_BATCH_WINDOW_SECONDS)
        batch = self._pop_pending_inbound_batch(key, anchor_message_id=anchor_message_id)
        if not batch:
            return
        anchor_message_id, inbound, source_message_ids = batch
        reservation = self._reserve_inbound(inbound)
        if reservation is None:
            return
        logger.info(
            "[Feishu] flushing inbound file batch: chat_id=%s user_id=%s anchor=%s messages=%d files=%d",
            inbound.chat_id,
            inbound.user_id,
            anchor_message_id,
            len(source_message_ids),
            len(inbound.files),
        )
        await self._prepare_inbound(
            anchor_message_id,
            inbound,
            source_message_ids=source_message_ids,
            reservation=reservation,
        )

    @staticmethod
    def _log_task_error(task: asyncio.Task, name: str, msg_id: str) -> None:
        """Callback for background asyncio tasks to surface errors."""
        try:
            exc = task.exception()
            if exc:
                logger.error("[Feishu] %s failed for msg_id=%s: %s", name, msg_id, exc)
        except asyncio.CancelledError:
            logger.info("[Feishu] %s cancelled for msg_id=%s", name, msg_id)
        except Exception:
            pass

    async def _prepare_inbound(
        self,
        msg_id: str,
        inbound,
        *,
        source_message_ids: list[str] | None = None,
        reservation: InboundReservation | None = None,
    ) -> None:
        """Kick off Feishu side effects without delaying inbound dispatch."""
        try:
            inbound = await self._attach_connection_identity(inbound)
            reaction_message_ids = source_message_ids or [msg_id]
            for reaction_message_id in reaction_message_ids:
                reaction_task = asyncio.create_task(self._add_reaction(reaction_message_id, "OK"))
                self._track_background_task(reaction_task, name="add_reaction", msg_id=reaction_message_id)
            self._ensure_running_card_started(msg_id, metadata=inbound.metadata)
            if reservation is None:
                await self.bus.publish_inbound(inbound)
            else:
                self._commit_reserved_inbound(reservation, inbound)
        finally:
            if reservation is not None:
                reservation.release()

    async def _attach_connection_identity(self, inbound: InboundMessage) -> InboundMessage:
        return await attach_connection_identity(
            inbound,
            repo=self._connection_repo,
            provider="feishu",
            workspace_id=inbound.chat_id,
        )

    async def _bind_connection_from_connect_code(self, *, message_id: str, chat_id: str, user_id: str, code: str) -> bool:
        if self._connection_repo is None or not code:
            return False

        state = await self._connection_repo.consume_oauth_state(provider="feishu", state=code)
        if state is None:
            await self._reply_card(message_id, "Feishu connection code is invalid or expired.")
            return True

        if not user_id or not chat_id:
            await self._reply_card(message_id, "Feishu connection could not be completed from this message.")
            return True

        await self._connection_repo.upsert_connection(
            owner_user_id=state["owner_user_id"],
            provider="feishu",
            external_account_id=user_id,
            workspace_id=chat_id,
            metadata={
                "chat_id": chat_id,
                "message_id": message_id,
            },
            status="connected",
        )
        await self._reply_card(message_id, "Feishu connected to DeerFlow.")
        return True

    def _parse_message_event(self, event) -> _ParsedMessage | None:
        """Extract text, attachments and ids from a lark message event; ``None`` for an empty message."""
        message = event.event.message
        chat_id = message.chat_id
        msg_id = message.message_id
        sender_id = event.event.sender.sender_id.open_id

        root_id = getattr(message, "root_id", None) or None
        chat_type = getattr(message, "chat_type", None)
        parent_id = self._non_empty_str(getattr(message, "parent_id", None))
        feishu_thread_id = self._non_empty_str(getattr(message, "thread_id", None))

        # Parse message content
        content = json.loads(message.content)

        # files_list store the any-file-key in feishu messages, which can be used to download the file content later
        # In Feishu channel, image_keys are independent of file_keys.
        # The file_key includes files, videos, and audio, but does not include stickers.
        files_list = []

        if "text" in content:
            # Handle plain text messages
            text = content["text"]
        elif "file_key" in content:
            file_key = content.get("file_key")
            if isinstance(file_key, str) and file_key:
                files_list.append({"file_key": file_key})
                text = "[file]"
            else:
                text = ""
        elif "image_key" in content:
            image_key = content.get("image_key")
            if isinstance(image_key, str) and image_key:
                files_list.append({"image_key": image_key})
                text = "[image]"
            else:
                text = ""
        elif "content" in content and isinstance(content["content"], list):
            # Handle rich-text messages with a top-level "content" list (e.g., topic groups/posts)
            text_paragraphs: list[str] = []
            for paragraph in content["content"]:
                if isinstance(paragraph, list):
                    paragraph_text_parts: list[str] = []
                    for element in paragraph:
                        if isinstance(element, dict):
                            # Include both normal text and @ mentions
                            if element.get("tag") in ("text", "at"):
                                text_value = element.get("text", "")
                                if text_value:
                                    paragraph_text_parts.append(text_value)
                            elif element.get("tag") == "img":
                                image_key = element.get("image_key")
                                if isinstance(image_key, str) and image_key:
                                    files_list.append({"image_key": image_key})
                                    paragraph_text_parts.append("[image]")
                            elif element.get("tag") in ("file", "media"):
                                file_key = element.get("file_key")
                                if isinstance(file_key, str) and file_key:
                                    files_list.append({"file_key": file_key})
                                    paragraph_text_parts.append("[file]")
                    if paragraph_text_parts:
                        # Join text segments within a paragraph with spaces to avoid "helloworld"
                        text_paragraphs.append(" ".join(paragraph_text_parts))

            # Join paragraphs with blank lines to preserve paragraph boundaries
            text = "\n\n".join(text_paragraphs)
        else:
            text = ""
        text = text.strip()

        logger.info(
            "[Feishu] parsed message: chat_id=%s, msg_id=%s, root_id=%s, parent_id=%s, thread_id=%s, chat_type=%s, sender=%s, text_len=%d",
            chat_id,
            msg_id,
            root_id,
            parent_id,
            feishu_thread_id,
            chat_type,
            sender_id,
            len(text or ""),
        )

        if not (text or files_list):
            logger.info("[Feishu] empty text, ignoring message")
            return None
        return _ParsedMessage(
            chat_id=chat_id,
            msg_id=msg_id,
            sender_id=sender_id,
            root_id=root_id,
            parent_id=parent_id,
            feishu_thread_id=feishu_thread_id,
            chat_type=chat_type,
            text=text,
            files=files_list,
        )

    def _on_message(self, event) -> None:
        """Called by lark-oapi when a message is received (runs synchronously on the SDK's loop thread)."""
        try:
            parsed = self._parse_message_event(event)
            if parsed is None:
                return
            msg_id, chat_id, sender_id, text = parsed.msg_id, parsed.chat_id, parsed.sender_id, parsed.text

            connect_code = self._pending_connect_code(text)
            if connect_code:
                if self._main_loop and self._main_loop.is_running():
                    scheduled = self._submit_threadsafe_coroutine(
                        self._bind_connection_from_connect_code(
                            message_id=msg_id,
                            chat_id=chat_id,
                            user_id=sender_id,
                            code=connect_code,
                        ),
                        self._main_loop,
                        name="bind_connection",
                        msg_id=msg_id,
                    )
                    if not scheduled:
                        logger.info("[Feishu] main loop stopped before channel connection bind could be scheduled")
                else:
                    logger.warning("[Feishu] main loop not running, cannot bind channel connection")
                return

            # Only treat known slash commands as commands; absolute paths and
            # other slash-prefixed text should be handled as normal chat.
            # Feishu group chats deliver "@bot /goal" with the mention left in the
            # text (Slack/Discord strip their own bot mention upstream). Skip a
            # leading mention only for the command path so ordinary chat keeps any
            # @mentions intact for the agent; the stripped form also flows into the
            # inbound so ChannelManager._handle_command parses the bare command.
            command_text = strip_leading_mentions(text)
            if _is_feishu_command(command_text):
                parsed.msg_type = InboundMessageType.COMMAND
                parsed.text = command_text

            # topic_id determines which LangGraph thread the message maps to.
            # P2P chats: topic_id=None so all messages share one thread (like Telegram DMs).
            # But check stored mappings first for backward compatibility with pre-upgrade P2P threads.
            if self.config.get("channel_store") is None:
                self._dispatch_inbound(parsed, self._route_without_store(parsed))
                return

            attempt = _RoutingAttempt(parsed)
            with self._thread_lock:
                queue = self._deferred_routing.get(chat_id)
                if queue is not None:
                    # Per-chat FIFO: never overtake a deferred predecessor onto another thread.
                    queue.append(attempt)
                    logger.info("[Feishu] queued message %s behind a deferred message for chat %s", msg_id, chat_id)
                    return
            try:
                routing = self._run_store_call(lambda: self._resolve_routing_bounded(attempt), name="resolve_topic_mapping", msg_id=msg_id)
            except StoreLookupUnresolved as unresolved:
                self._defer_routing(attempt, unresolved)
                return
            self._dispatch_inbound(parsed, routing)
        except Exception:
            logger.exception("[Feishu] error processing message")
