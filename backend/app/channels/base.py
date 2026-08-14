"""Abstract base class for IM channels."""

from __future__ import annotations

import asyncio
import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Coroutine
from concurrent.futures import CancelledError as FutureCancelledError
from concurrent.futures import Future
from typing import Any, TypeVar

from app.channels.commands import extract_connect_code
from app.channels.message_bus import (
    InboundMessage,
    InboundMessageType,
    InboundQueueClosedError,
    InboundQueueFullError,
    InboundReservation,
    InboundReservationExpiredError,
    MessageBus,
    OutboundMessage,
    ResolvedAttachment,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class Channel(ABC):
    """Base class for all IM channel implementations.

    Each channel connects to an external messaging platform and:
    1. Receives messages, wraps them as InboundMessage, publishes to the bus.
    2. Subscribes to outbound messages and sends replies back to the platform.

    Subclasses must implement ``start``, ``stop``, and ``send``.
    """

    def __init__(self, name: str, bus: MessageBus, config: dict[str, Any]) -> None:
        self.name = name
        self.bus = bus
        self.config = config
        self._running = False
        self._connection_repo: Any = config.get("connection_repo")
        # Provider SDK callbacks often run on a dedicated thread and submit
        # preparation work to the Gateway loop. Submission and shutdown share
        # this lock so stop() cannot miss a future created concurrently.
        self._threadsafe_futures: set[Future[Any]] = set()
        self._threadsafe_futures_lock = threading.Lock()
        self._threadsafe_future_intake_open = True

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def supports_streaming(self) -> bool:
        return False

    # -- lifecycle ---------------------------------------------------------

    @abstractmethod
    async def start(self) -> None:
        """Start listening for messages from the external platform."""

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop the channel."""

    # -- outbound ----------------------------------------------------------

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        """Send a message back to the external platform.

        The implementation should use ``msg.chat_id`` and ``msg.thread_ts``
        to route the reply to the correct conversation/thread.
        """

    async def send_file(self, msg: OutboundMessage, attachment: ResolvedAttachment) -> bool:
        """Upload a single file attachment to the platform.

        Returns True if the upload succeeded, False otherwise.
        Default implementation returns False (no file upload support).
        """
        return False

    # -- helpers -----------------------------------------------------------

    async def _send_with_retry(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        max_retries: int,
        log_prefix: str | None = None,
        operation_name: str = "send",
    ) -> T:
        """Run an outbound send operation with the shared channel retry policy."""
        prefix = log_prefix or f"[{self.name}]"
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                return await operation()
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries - 1:
                    delay = 2**attempt
                    logger.warning(
                        "%s %s failed (attempt %d/%d), retrying in %ds: %s",
                        prefix,
                        operation_name,
                        attempt + 1,
                        max_retries,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)

        logger.error("%s %s failed after %d attempts: %s", prefix, operation_name, max_retries, last_exc)
        if last_exc is None:
            raise RuntimeError(f"{self.name} {operation_name} failed without an exception from any attempt")
        raise last_exc

    def _log_future_error(self, fut: Any, name: str, msg_id: Any) -> None:
        """Callback for concurrent futures scheduled from channel worker threads."""
        try:
            exc = fut.exception()
        except (asyncio.CancelledError, FutureCancelledError, asyncio.InvalidStateError):
            return
        except Exception:
            logger.exception("[%s] failed to inspect future for %s (msg_id=%s)", self.name, name, msg_id)
            return

        if exc:
            logger.error("[%s] %s failed for msg_id=%s: %s", self.name, name, msg_id, exc)

    def _open_threadsafe_future_intake(self) -> None:
        """Allow a newly started provider to submit work to its main loop."""
        with self._threadsafe_futures_lock:
            pending = [future for future in self._threadsafe_futures if not future.done()]
            if pending:
                raise RuntimeError(f"cannot restart {self.name} while cross-thread work is still running")
            self._threadsafe_futures.clear()
            self._threadsafe_future_intake_open = True

    def _submit_threadsafe_coroutine(
        self,
        coroutine: Coroutine[Any, Any, T],
        loop: asyncio.AbstractEventLoop | None,
        *,
        name: str,
        msg_id: Any,
        reservation: InboundReservation | None = None,
    ) -> Future[T] | None:
        """Submit and retain provider-thread work until completion or shutdown."""

        with self._threadsafe_futures_lock:
            if not self._threadsafe_future_intake_open or loop is None or not loop.is_running():
                coroutine.close()
                if reservation is not None:
                    reservation.release()
                return None
            try:
                future = asyncio.run_coroutine_threadsafe(coroutine, loop)
            except RuntimeError:
                coroutine.close()
                if reservation is not None:
                    reservation.release()
                return None
            self._threadsafe_futures.add(future)

        future.add_done_callback(
            lambda completed: self._finalize_threadsafe_future(
                completed,
                name=name,
                msg_id=msg_id,
                reservation=reservation,
            )
        )
        return future

    def _finalize_threadsafe_future(
        self,
        future: Future[Any],
        *,
        name: str,
        msg_id: Any,
        reservation: InboundReservation | None,
    ) -> None:
        with self._threadsafe_futures_lock:
            self._threadsafe_futures.discard(future)
        if reservation is not None:
            reservation.release()
        self._log_future_error(future, name, msg_id)

    async def _close_and_drain_threadsafe_futures(self) -> None:
        """Close cross-thread submission, then cancel and await owned futures."""
        with self._threadsafe_futures_lock:
            self._threadsafe_future_intake_open = False
            futures = tuple(self._threadsafe_futures)

        for future in futures:
            future.cancel()
        if futures:
            await asyncio.gather(*(asyncio.wrap_future(future) for future in futures), return_exceptions=True)
            with self._threadsafe_futures_lock:
                self._threadsafe_futures.difference_update(future for future in futures if future.done())

    def _pending_connect_code(self, text: str) -> str | None:
        """Return the one-time bind code if *text* is a ``/connect <code>`` command
        and channel connections are configured, else ``None``.

        Adapters MUST consult this **before** applying their ``allowed_users`` /
        ``_check_user`` gate, so a browser-initiated bind can bootstrap an external
        identity that the platform bot has never seen and is therefore not yet
        authorized. (Telegram uses its deep-link ``/start <token>`` flow instead.)
        """
        if self._connection_repo is None:
            return None
        return extract_connect_code(text)

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
        """Convenience factory for creating InboundMessage instances."""
        return InboundMessage(
            channel_name=self.name,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            msg_type=msg_type,
            thread_ts=thread_ts,
            files=files or [],
            metadata=metadata or {},
        )

    def _reserve_inbound(self, msg: InboundMessage) -> InboundReservation | None:
        """Reserve bounded intake capacity or explicitly drop under overload.

        Real-time socket/polling providers do not expose a reliable delivery
        retry contract to this adapter layer. They therefore drop a message
        that cannot be admitted immediately. ``MessageBus`` emits a
        rate-limited warning with the cumulative rejection count.
        """
        try:
            return self.bus.reserve_inbound(msg)
        except InboundQueueFullError:
            return None
        except (InboundQueueClosedError, InboundReservationExpiredError):
            logger.debug("[%s] inbound ignored because channel intake is closed", self.name)
            return None

    def _commit_reserved_inbound(
        self,
        reservation: InboundReservation,
        msg: InboundMessage,
    ) -> bool:
        """Commit a reservation on the MessageBus loop, releasing on failure."""
        try:
            reservation.commit(msg)
            return True
        except (InboundQueueClosedError, InboundReservationExpiredError):
            logger.debug("[%s] inbound reservation expired during shutdown", self.name)
            return False
        finally:
            reservation.release()

    async def _publish_inbound_or_drop(self, msg: InboundMessage) -> bool:
        """Publish from an already-serialized provider loop without waiting."""
        try:
            await self.bus.publish_inbound(msg)
            return True
        except InboundQueueFullError:
            return False
        except InboundQueueClosedError:
            logger.debug("[%s] inbound ignored because channel intake is closed", self.name)
            return False

    async def _on_outbound(self, msg: OutboundMessage) -> None:
        """Outbound callback registered with the bus.

        Only forwards messages targeted at this channel.
        Sends the text message first, then uploads any file attachments.
        File uploads are skipped entirely when the text send fails to avoid
        partial deliveries (files without accompanying text).
        """
        if msg.channel_name == self.name:
            try:
                await self.send(msg)
            except Exception:
                logger.exception("Failed to send outbound message on channel %s", self.name)
                return  # Do not attempt file uploads when the text message failed

            for attachment in msg.attachments:
                try:
                    success = await self.send_file(msg, attachment)
                    if not success:
                        logger.warning("[%s] file upload skipped for %s", self.name, attachment.filename)
                except Exception:
                    logger.exception("[%s] failed to upload file %s", self.name, attachment.filename)

    async def receive_file(self, msg: InboundMessage, thread_id: str, *, user_id: str | None = None) -> InboundMessage:
        """
        Optionally process and materialize inbound file attachments for this channel.

        By default, this method does nothing and simply returns the original message.
        Subclasses (e.g. FeishuChannel) may override this to download files (images, documents, etc)
        referenced in msg.files, save them to the sandbox, and update msg.text to include
        the sandbox file paths for downstream model consumption.

        Args:
            msg: The inbound message, possibly containing file metadata in msg.files.
            thread_id: The resolved DeerFlow thread ID for sandbox path context.
            user_id: Optional DeerFlow storage user ID for user-scoped channel workers.

        Returns:
            The (possibly modified) InboundMessage, with text and/or files updated as needed.
        """
        del user_id
        return msg
