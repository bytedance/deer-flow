"""Abstract base class for IM channels."""

from __future__ import annotations

import asyncio
import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Coroutine
from concurrent.futures import CancelledError as FutureCancelledError
from concurrent.futures import Future
from dataclasses import dataclass, replace
from typing import Any, TypeVar

from app.channels.commands import extract_connect_code
from app.channels.message_bus import (
    HUMAN_INPUT_REQUEST_METADATA_KEY,
    PENDING_CLARIFICATION_METADATA_KEY,
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


def attachment_delivery_text(msg: OutboundMessage, failed: list[ResolvedAttachment], *, unsupported: bool = False) -> str:
    """Format shared feedback without host paths or provider errors.

    Built-in IM outbounds do not populate ``locale``; their notices follow
    the first non-empty reply line. An explicit locale remains an override.
    """
    locale = msg.metadata.get("locale")
    first_line = next((line for line in msg.text.splitlines() if line.strip()), "")
    chinese = locale.lower().startswith("zh") if isinstance(locale, str) else any("\u4e00" <= char <= "\u9fff" for char in first_line)
    if unsupported:
        return "当前渠道不支持发送附件。请到 DeerFlow 会话下载文件。" if chinese else "This channel does not support sending files. Open the DeerFlow conversation to download them."
    filenames = "\n".join("- " + " ".join(attachment.filename.split()) for attachment in failed)
    sent = len(msg.attachments) - len(failed)
    if chinese:
        status = f"已发送 {sent}/{len(msg.attachments)} 个附件，以下附件未能发送：" if sent else "附件未能发送："
        return f"{status}\n{filenames}\n文件仍保留在 DeerFlow 会话中，可前往下载。"
    status = f"Sent {sent}/{len(msg.attachments)} files. These files could not be sent:" if sent else "These files could not be sent in this chat:"
    return f"{status}\n{filenames}\nThe files remain available in the DeerFlow conversation."


class ChannelUnavailable(Exception):
    """Local connectivity failure: the channel cannot accept traffic right now.

    Distinct from a platform rejection of a well-formed send. Delivery workers
    park outbox rows with ``count_attempt=False`` on this error so a transport
    outage cannot exhaust the retry budget.
    """


class ChannelStopTimeout(RuntimeError):
    """A channel still owns a live provider worker after bounded teardown."""


PRIVATE_LOOP_DRAIN_TIMEOUT_SECONDS = 1.0


def shutdown_private_loop(loop: asyncio.AbstractEventLoop, *, drain_timeout: float = PRIVATE_LOOP_DRAIN_TIMEOUT_SECONDS) -> None:
    """Cancel what is still scheduled on a thread-private SDK loop, then close it.

    Runs on the thread that owns ``loop`` once its ``run_until_complete`` or
    ``run_forever`` has returned. Provider SDKs leave their own tasks behind
    (lark-oapi's ping and receive loops, dingtalk-stream's keepalive); cancelling
    them with a bounded drain keeps the thread exit inside the channel's stop
    budget, and a task that refuses to finish is abandoned with the loop rather
    than joined.
    """
    try:
        pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.wait(pending, timeout=drain_timeout))
        loop.run_until_complete(loop.shutdown_asyncgens())
    except Exception:
        logger.debug("Error draining a private channel loop before close", exc_info=True)
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def abort_connection_transport(connection: Any) -> bool:
    """Tear down a ``websockets`` connection's transport if its close handshake did not finish.

    ``connection.close()`` waits for the peer's close frame and only aborts the
    transport after its own ``close_timeout``; a caller that bounds that wait more
    tightly (channel stop budgets do) cancels before the abort, and the socket
    then lives until garbage collection. Returns True when a transport was
    aborted; the caller should yield to its loop once so ``connection_lost``
    runs before the loop is stopped.
    """
    transport = getattr(connection, "transport", None)
    if transport is None or transport.is_closing():
        return False
    transport.abort()
    return True


@dataclass(eq=False, slots=True)
class _ThreadsafeSubmission:
    coroutine: Coroutine[Any, Any, Any]
    loop: asyncio.AbstractEventLoop
    name: str
    msg_id: Any
    reservation: InboundReservation | None
    completion: Future[Any]
    task: asyncio.Task[Any] | None = None
    cancel_requested: bool = False


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
        # Language of the /connect replies (a ReplyLocaleResolver); ChannelService injects it.
        self._reply_locale: Any = config.get("reply_locale")
        # Provider SDK callbacks often run on a dedicated thread and submit
        # preparation work to the Gateway loop. Submission and shutdown share
        # this lock so stop() cannot miss a future created concurrently.
        self._threadsafe_submissions: set[_ThreadsafeSubmission] = set()
        self._threadsafe_submissions_lock = threading.Lock()
        self._threadsafe_submission_intake_open = True

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

    def on_thread_replaced(self, old_thread_id: str) -> None:
        """Notify the adapter that a conversation's thread was replaced (e.g. ``/new``).

        Subclasses override this to clean up per-thread state such as pending
        interactive card registrations.  The default is a no-op.
        """

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

    async def send_notification(self, *, target: str, text_markdown: str) -> None:
        """Push a proactive notification to an external identity (issue #4254).

        Unlike ``send``, there is no inbound frame to reply to: *target* is a
        platform identity (e.g. the ``external_account_id`` recorded by the
        bind flow). Used by the notification delivery worker to deliver
        scheduled-task outcomes. Channels without proactive push support keep
        the default, which raises so a stray delivery is recorded as a failure
        instead of being silently dropped.

        Connectivity preconditions should raise :class:`ChannelUnavailable`
        (not a generic ``RuntimeError``) so the outbox can park the row without
        consuming its retry budget. Platform rejections of a well-formed send
        remain ordinary exceptions that count as attempts.

        The scheduler never imports channel classes: it reads the static
        ``proactive_notifications`` flag in ``app/channels/capabilities.py``,
        and providers without it get no outbox rows at all. To add proactive
        push to a provider:

        1. override this method and return only after the platform ACKs the send;
        2. raise :class:`ChannelUnavailable` for transient transport failures
           (not connected, socket closed, timeout); any other exception counts
           against the retry budget;
        3. set ``proactive_notifications`` to ``True`` for that provider in
           ``CHANNEL_CAPABILITIES`` (a test fails while the flag and this
           override disagree).

        The outbox, deduplication, retries, localized text and the Settings
        label are shared and need no provider code.
        """
        if not self.is_running:
            raise ChannelUnavailable(f"channel '{self.name}' is not running")
        raise NotImplementedError(f"channel '{self.name}' does not support proactive notifications")

    async def send_notification_for_owner(self, *, owner_user_id: str | None, target: str, text_markdown: str) -> None:
        """Deliver to an already-verified identity, with owner context for routing.

        Providers may resolve a private conversation from that owner's current
        bindings. The outbox target remains the external account identity.
        """
        await self.send_notification(target=target, text_markdown=text_markdown)

    async def send_group_notification_for_owner(self, *, owner_user_id: str | None, target: str, text_markdown: str) -> None:
        """Push to an explicitly selected group binding, never a personal fallback.

        ``target`` is the owner's connection ID, not a provider chat ID.
        Providers must revalidate that binding before sending to its group.
        """
        raise NotImplementedError(f"channel '{self.name}' does not support group notifications")

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
        with self._threadsafe_submissions_lock:
            if self._threadsafe_submissions:
                raise RuntimeError(f"cannot restart {self.name} while cross-thread work is still running")
            self._threadsafe_submission_intake_open = True

    def _submit_threadsafe_coroutine(
        self,
        coroutine: Coroutine[Any, Any, T],
        loop: asyncio.AbstractEventLoop | None,
        *,
        name: str,
        msg_id: Any,
        reservation: InboundReservation | None = None,
    ) -> bool:
        """Submit provider-thread work while retaining its real asyncio Task."""
        return (
            self._submit_threadsafe_coroutine_future(
                coroutine,
                loop,
                name=name,
                msg_id=msg_id,
                reservation=reservation,
            )
            is not None
        )

    def _submit_threadsafe_coroutine_future(
        self,
        coroutine: Coroutine[Any, Any, T],
        loop: asyncio.AbstractEventLoop | None,
        *,
        name: str,
        msg_id: Any,
        reservation: InboundReservation | None = None,
    ) -> Future[T] | None:
        """Like ``_submit_threadsafe_coroutine``, returning the completion future.

        ``None`` means the work was refused (and the reservation released).
        The future settles on every path: the task's result or exception, or
        cancellation when ``_close_and_drain_threadsafe_futures`` stops the
        work before or while it runs. Await it from another loop through
        ``asyncio.shield(asyncio.wrap_future(...))`` so cancelling the waiter
        never cancels the shared future the finalizer still has to settle.
        """

        with self._threadsafe_submissions_lock:
            if not self._threadsafe_submission_intake_open or loop is None or not loop.is_running():
                coroutine.close()
                if reservation is not None:
                    reservation.release()
                return None

            submission = _ThreadsafeSubmission(
                coroutine=coroutine,
                loop=loop,
                name=name,
                msg_id=msg_id,
                reservation=reservation,
                completion=Future(),
            )
            self._threadsafe_submissions.add(submission)
            try:
                loop.call_soon_threadsafe(self._start_threadsafe_submission, submission)
            except RuntimeError:
                self._threadsafe_submissions.discard(submission)
                coroutine.close()
                if reservation is not None:
                    reservation.release()
                return None
        return submission.completion

    def _start_threadsafe_submission(self, submission: _ThreadsafeSubmission) -> None:
        """Create the owned Task on its event loop or finish a pre-start cancel."""
        task: asyncio.Task[Any] | None = None
        startup_error: BaseException | None = None
        with self._threadsafe_submissions_lock:
            if submission.cancel_requested:
                self._threadsafe_submissions.discard(submission)
                cancelled_before_start = True
            else:
                cancelled_before_start = False
                try:
                    task = submission.loop.create_task(submission.coroutine)
                except BaseException as exc:
                    self._threadsafe_submissions.discard(submission)
                    startup_error = exc
                else:
                    submission.task = task

        if cancelled_before_start:
            submission.coroutine.close()
            if submission.reservation is not None:
                submission.reservation.release()
            submission.completion.cancel()
            return

        if startup_error is not None:
            submission.coroutine.close()
            if submission.reservation is not None:
                submission.reservation.release()
            submission.completion.set_exception(startup_error)
            self._log_future_error(submission.completion, submission.name, submission.msg_id)
            return

        assert task is not None
        task.add_done_callback(lambda completed: self._finalize_threadsafe_submission(submission, completed))

    def _finalize_threadsafe_submission(
        self,
        submission: _ThreadsafeSubmission,
        task: asyncio.Task[Any],
    ) -> None:
        with self._threadsafe_submissions_lock:
            self._threadsafe_submissions.discard(submission)
        if submission.reservation is not None:
            submission.reservation.release()

        if task.cancelled():
            submission.completion.cancel()
        else:
            try:
                submission.completion.set_result(task.result())
            except BaseException as exc:
                submission.completion.set_exception(exc)
        self._log_future_error(submission.completion, submission.name, submission.msg_id)

    async def _close_and_drain_threadsafe_futures(self) -> None:
        """Close submission, then cancel and await the owned asyncio Tasks."""
        with self._threadsafe_submissions_lock:
            self._threadsafe_submission_intake_open = False
            submissions = tuple(self._threadsafe_submissions)
            tasks: list[tuple[asyncio.AbstractEventLoop, asyncio.Task[Any]]] = []
            for submission in submissions:
                submission.cancel_requested = True
                if submission.task is not None:
                    tasks.append((submission.loop, submission.task))

        for loop, task in tasks:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                logger.warning("[%s] event loop closed before cross-thread task cancellation", self.name)
        if submissions:
            await asyncio.gather(
                *(asyncio.shield(asyncio.wrap_future(submission.completion)) for submission in submissions),
                return_exceptions=True,
            )

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

    async def _connect_reply_text(self, key: str, *, owner_user_id: str | None = None) -> str:
        """A ``/connect`` (Telegram ``/start``) reply in its reader's language.

        Once the code is consumed, pass its ``owner_user_id``: the reply follows
        that user's web UI language. Before that (an invalid or expired code)
        it uses ``channel_connections.notification_locale``. Never raises.
        """
        # Deferred: it loads the scheduler's locale list, and importing
        # app.channels must stay light (tests/test_channel_capabilities.py).
        from app.channels.reply_locale import ReplyLocaleResolver, connect_reply_text

        resolver = self._reply_locale or ReplyLocaleResolver()
        return connect_reply_text(key, provider=self.name, locale=await resolver.locale_for(owner_user_id))

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
            # The inherited implementation explicitly means "unsupported".
            # Inspect the bound method so custom and instance overrides keep
            # working without a second provider-capabilities registry.
            unsupported = bool(msg.attachments) and getattr(self.send_file, "__func__", None) is Channel.send_file
            reply = msg
            if unsupported:
                notice = attachment_delivery_text(msg, msg.attachments, unsupported=True)
                reply = replace(msg, text=f"{notice}\n\n{msg.text}" if msg.text else notice, attachments=[])
            try:
                await self.send(reply)
            except Exception:
                logger.exception("Failed to send outbound message on channel %s", self.name)
                return  # Do not attempt file uploads when the text message failed

            if unsupported:
                return
            failed = await self._send_attachments(msg)
            if failed:
                await self._send_attachment_feedback(msg, failed)

    async def _send_attachments(self, msg: OutboundMessage) -> list[ResolvedAttachment]:
        """Try each upload once; platform-specific retries stay in the adapter."""
        failed: list[ResolvedAttachment] = []
        for attachment in msg.attachments:
            try:
                if await self.send_file(msg, attachment):
                    continue
                logger.warning("[%s] file upload skipped for %s", self.name, attachment.filename)
            except Exception:
                logger.exception("[%s] failed to upload file %s", self.name, attachment.filename)
            failed.append(attachment)
        return failed

    async def _send_attachment_feedback(self, msg: OutboundMessage, failed: list[ResolvedAttachment]) -> None:
        """Reply in the same conversation; never resubmit files or push elsewhere."""
        metadata = {key: value for key, value in msg.metadata.items() if key not in {PENDING_CLARIFICATION_METADATA_KEY, HUMAN_INPUT_REQUEST_METADATA_KEY}}
        feedback = replace(msg, text=attachment_delivery_text(msg, failed), attachments=[], artifacts=[], metadata=metadata)
        try:
            await self.send(feedback)
        except Exception:
            # The platform may no longer accept a reply. Retain files and logs;
            # do not turn this into a proactive notification.
            logger.exception("[%s] failed to send attachment delivery feedback", self.name)

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
