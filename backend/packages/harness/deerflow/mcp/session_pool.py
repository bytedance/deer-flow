"""Persistent MCP session pool for stateful tool calls.

When MCP tools are loaded via langchain-mcp-adapters with ``session=None``,
each tool call creates a new MCP session. For stateful servers like Playwright,
this means browser state (opened pages, filled forms) is lost between calls.

This module provides a session pool that maintains persistent MCP sessions,
scoped by ``(server_name, scope_key)`` — typically scope_key is the thread_id —
so that consecutive tool calls share the same session and server-side state.
Sessions are evicted in LRU order when the pool reaches capacity.

Lifecycle model (owner task)
----------------------------
An MCP ``ClientSession`` is implemented on top of an ``anyio`` task group, and
anyio enforces that a cancel scope must be exited from the *same task* that
entered it. Calling ``cm.__aexit__`` from any task other than the one that ran
``cm.__aenter__`` raises::

    RuntimeError: Attempted to exit cancel scope in a different task than it
    was entered in

The sync-tool path (``make_sync_tool_wrapper``) drives each call through a fresh
``asyncio.run`` event loop, so a session entered while answering one call would
otherwise be exited while answering another — from a different task — and crash
(GitHub issue #3379).

To make this impossible, every pooled session is owned by a dedicated
``_run_session`` task. That task enters the context manager, hands the live
session back to the caller, and then *waits* on a close event. All shutdown
paths only ever **signal** that event; the owner task performs ``__aexit__``
itself, guaranteeing enter and exit always happen in the same task.

The owner task is also the only writer that promotes a creation into the pool:
once ``initialize()`` succeeds it registers the session in ``_entries`` and
resolves the creation's future in one atomic critical section, so callers can
only ever receive a session the pool already owns (and will retire via LRU
eviction or the close_* paths) — never one whose lifetime is still tied to a
single caller that might get cancelled.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import OrderedDict
from typing import Any

import anyio
from mcp import ClientSession
from mcp.shared.exceptions import McpError
from mcp.types import CONNECTION_CLOSED

logger = logging.getLogger(__name__)

_MCP_CLOSED_STREAM_ERRORS = (
    anyio.ClosedResourceError,
    anyio.BrokenResourceError,
    anyio.EndOfStream,
)


def _is_mcp_transport_disconnect(error: Exception) -> bool:
    if isinstance(error, _MCP_CLOSED_STREAM_ERRORS):
        return True
    return isinstance(error, McpError) and error.error.code == CONNECTION_CLOSED and error.error.message == "Connection closed"


async def _finish_session_cleanup(cleanup: asyncio.Task[Any], server_name: str) -> bool:
    """Wait for cleanup despite cancellation and report whether it was requested."""
    cancelled = False
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            logger.warning(
                "Failed to close disconnected MCP session for server '%s'",
                server_name,
                exc_info=True,
            )
            return cancelled

    if cleanup.cancelled():
        logger.warning(
            "Disconnected MCP session cleanup was cancelled for server '%s'",
            server_name,
        )
    else:
        cleanup_error = cleanup.exception()
        if cleanup_error is not None:
            logger.warning(
                "Failed to close disconnected MCP session for server '%s'",
                server_name,
                exc_info=(type(cleanup_error), cleanup_error, cleanup_error.__traceback__),
            )
    return cancelled


async def call_pooled_session_tool(
    session: ClientSession,
    pool: MCPSessionPool,
    *,
    server_name: str,
    scope_key: str,
    tool_name: str,
    arguments: dict[str, Any],
    call_kwargs: dict[str, Any],
) -> Any:
    """Call a pooled session and evict it only after an explicit disconnect."""
    try:
        return await session.call_tool(tool_name, arguments, **call_kwargs)
    except Exception as error:
        if _is_mcp_transport_disconnect(error):
            cleanup = asyncio.create_task(pool.close_session_if_current(server_name, scope_key, session))
            if await _finish_session_cleanup(cleanup, server_name):
                raise asyncio.CancelledError
        raise


class MCPSessionPool:
    """Manages persistent MCP sessions scoped by ``(server_name, scope_key)``."""

    MAX_SESSIONS = 256
    SESSION_CLOSE_TIMEOUT = 5.0  # seconds to wait when closing a session on a foreign loop

    def __init__(self) -> None:
        # Each entry: (session, owning_loop, owner_task, close_event).
        self._entries: OrderedDict[
            tuple[str, str],
            tuple[
                ClientSession,
                asyncio.AbstractEventLoop,
                asyncio.Task[Any],
                asyncio.Event,
            ],
        ] = OrderedDict()
        # In-flight creations, keyed by (server, scope). Lets concurrent callers
        # on the same loop share a single creation instead of each spawning a
        # duplicate session. Value: (loop, ready_future, owner_task, close_event).
        # The owner task promotes the record into ``_entries`` and resolves
        # ``ready`` with the session in one atomic critical section (see
        # ``_run_session``), so ``ready`` resolving with a *result* always means
        # the session is registered — never merely handed to one caller.
        self._inflight: dict[
            tuple[str, str],
            tuple[
                asyncio.AbstractEventLoop,
                asyncio.Future[ClientSession],
                asyncio.Task[Any],
                asyncio.Event,
            ],
        ] = {}
        # threading.Lock is not bound to any event loop, so it is safe to
        # acquire from both async paths and sync/worker-thread paths.
        self._lock = threading.Lock()
        # Strong references to detached teardown reaper tasks. The event loop
        # only keeps weak references to tasks, so an unheld reaper — and with
        # it the owner it is awaiting, mid-__aexit__ — could be
        # garbage-collected before teardown completes; the done callback keeps
        # the set from growing without bound.
        self._teardown_tasks: set[asyncio.Task[Any]] = set()

    # ------------------------------------------------------------------
    # Session owner task
    # ------------------------------------------------------------------

    async def _run_session(
        self,
        key: tuple[str, str],
        connection: dict[str, Any],
        ready: asyncio.Future[ClientSession],
        close_evt: asyncio.Event,
    ) -> None:
        """Own a single MCP session for its entire lifetime.

        Enters the session context manager, initializes it, and *commits* the
        session: promotes the in-flight record into ``_entries`` and resolves
        ``ready`` with the live session in one atomic critical section, then
        blocks until ``close_evt`` is set. The context manager is *always*
        exited from this task, satisfying anyio's cancel-scope same-task
        requirement.
        """
        from langchain_mcp_adapters.sessions import create_session

        cm = create_session(connection)
        try:
            session = await cm.__aenter__()
        except BaseException as e:
            # Never entered the cancel scope, so there is nothing to exit.
            if not ready.done():
                ready.set_exception(e)
            return

        # The context manager is now entered. From here on __aexit__ MUST run in
        # this task — on init failure, on cancellation, or on the close signal —
        # to satisfy anyio's same-task cancel-scope requirement and to avoid
        # leaking the session/subprocess.
        try:
            await session.initialize()
            # Commit point. ``ready`` resolves with a *result* only inside the
            # critical section that also registers the session in ``_entries``:
            # a resolved-with-result future therefore means the session is
            # pool-owned (visible to LRU eviction and the close_* paths), never
            # the private property of one caller. Joiners waiting on ``ready``
            # can only ever receive a committed session, and an unwind path can
            # check the outcome race-free. If the record was already removed
            # (the creator unwound or a close_* ran), the creation is aborted:
            # ``ready`` carries the cancellation instead, so no caller can end
            # up holding an unmanaged session.
            loop = asyncio.get_running_loop()
            task = asyncio.current_task()
            with self._lock:
                still_ours = self._inflight.get(key) == (loop, ready, task, close_evt)
                if still_ours:
                    self._inflight.pop(key)
                    self._entries[key] = (session, loop, task, close_evt)
                    if not ready.done():
                        ready.set_result(session)
            if still_ours:
                logger.info("Created persistent MCP session for %s/%s", key[0], key[1])
            elif not ready.done():
                ready.set_exception(asyncio.CancelledError("MCP session pool was closed while the session was being created"))
            await close_evt.wait()
        except BaseException as e:
            if not ready.done():
                ready.set_exception(e)
        finally:
            try:
                await cm.__aexit__(None, None, None)
            except Exception:
                logger.warning("Error closing MCP session", exc_info=True)

    async def get_session(
        self,
        server_name: str,
        scope_key: str,
        connection: dict[str, Any],
    ) -> ClientSession:
        """Get or create a persistent MCP session.

        If an existing session was created in a different (or closed) event
        loop, it is evicted and replaced with a fresh one owned by a task on
        the current loop.

        Args:
            server_name: MCP server name.
            scope_key: Isolation key (typically thread_id).
            connection: Connection configuration for ``create_session``.

        Returns:
            An initialized ``ClientSession``.
        """
        key = (server_name, scope_key)
        current_loop = asyncio.get_running_loop()

        # Phase 1: inspect/mutate the registry under the thread lock (no awaits).
        # Decide one of three outcomes atomically: return an existing session,
        # join an in-flight creation, or become the creator for this key.
        # Each item: (loop, owner_task, close_event, cancel, ready_future).
        # ``cancel`` is True for in-flight creations, whose owner may be blocked
        # inside ``initialize()`` where close_evt cannot wake it — it must be
        # cancelled (guarded: never when the owner already failed and is
        # unwinding in __aexit__). ``ready`` is the creation's future, used only
        # for that guard.
        evicted: list[tuple[asyncio.AbstractEventLoop, asyncio.Task[Any], asyncio.Event, bool, asyncio.Future[ClientSession] | None]] = []
        join: asyncio.Future[ClientSession] | None = None
        ready: asyncio.Future[ClientSession] | None = None
        close_evt: asyncio.Event | None = None
        task: asyncio.Task[Any] | None = None
        with self._lock:
            if key in self._entries:
                session, loop, ent_task, ent_close = self._entries[key]
                if loop is current_loop and not loop.is_closed():
                    self._entries.move_to_end(key)
                    return session
                # Session belongs to a different/closed event loop – evict it.
                self._entries.pop(key)
                evicted.append((loop, ent_task, ent_close, False, None))

            inflight = self._inflight.get(key)
            if inflight is not None and inflight[0] is current_loop and not inflight[0].is_closed():
                # Another caller on this loop is already creating the session;
                # wait for the same result instead of building a duplicate.
                join = inflight[1]
            else:
                if inflight is not None:
                    # Stale in-flight creation owned by a different/closed loop.
                    # Drop the record and tear its owner down; because that owner
                    # may be blocked inside initialize() (where close_evt cannot
                    # wake it), it must be cancelled. We then create a fresh
                    # session here.
                    self._inflight.pop(key)
                    evicted.append((inflight[0], inflight[2], inflight[3], True, inflight[1]))
                # Become the creator: publish an in-flight record before any
                # await so concurrent callers join us instead of racing.
                ready = current_loop.create_future()
                close_evt = asyncio.Event()
                task = current_loop.create_task(self._run_session(key, connection, ready, close_evt))
                self._inflight[key] = (current_loop, ready, task, close_evt)

            # Evict LRU entries when at capacity.
            while len(self._entries) >= self.MAX_SESSIONS:
                oldest_key, (_, loop, ent_task, ent_close) = next(iter(self._entries.items()))
                self._entries.pop(oldest_key)
                evicted.append((loop, ent_task, ent_close, False, None))

        # Phase 2: shut down evicted sessions/creations. Signal EVERY removed
        # owner first — the signal loop contains no awaits, so it completes
        # atomically and a cancellation during the teardown awaits below can
        # never strand an owner that was already removed from the registries.
        # Then await teardowns (same-loop deterministically; foreign-loop
        # in-flight creations routed to their loop). In every case the owner
        # task — never this one — runs __aexit__.
        for loop, ent_task, ent_close, cancel, ent_ready in evicted:
            self._signal_close(loop, ent_close)
            if cancel:
                self._cancel_owner(loop, ent_task, ent_ready)
        try:
            for loop, ent_task, ent_close, cancel, ent_ready in evicted:
                if loop is current_loop and not loop.is_closed():
                    await self._shutdown(ent_close, ent_task, cancel=False, ready=ent_ready)
                elif cancel:
                    await self._shutdown_entry(loop, ent_task, ent_close, cancel=False, ready=ent_ready)
                # else: foreign-loop registered entry — already signalled above;
                # its teardown completes on its own loop.
        except BaseException:
            # We may already be the creator for ``key``: the in-flight record
            # and owner task were published under the lock *before* these
            # awaits. A cancellation here (routine — both production call
            # sites wrap get_session in asyncio.wait_for(session_init_timeout))
            # would otherwise orphan that owner: it finishes initialize(),
            # commits, and blocks on close_evt forever — invisible to LRU
            # eviction, which only scans _entries. Unwind exactly like the
            # Phase-3 path — unless the owner already committed while we were
            # parked here: then the session is registered in _entries and may
            # already be in a joiner's hands, so tearing it down would close it
            # underneath them. A committed session is pool property; LRU
            # eviction and the close_* paths own it from here on. Every evicted
            # owner was already signalled in the atomic loop above, so skipping
            # the remaining teardown *awaits* (not signals) on unwind is safe:
            # each victim still tears down in its own task.
            if task is not None and not self._creation_committed(ready):
                assert ready is not None and close_evt is not None
                try:
                    await self._shutdown(close_evt, task, cancel=True, ready=ready)
                except BaseException:
                    logger.debug("Owner teardown interrupted during eviction unwind", exc_info=True)
                with self._lock:
                    if self._inflight.get(key) == (current_loop, ready, task, close_evt):
                        self._inflight.pop(key)
            raise

        # Phase 2b: a concurrent creation for this key is already in progress on
        # this loop — share its result rather than create a duplicate session.
        # The creator's owner task resolves ``ready`` with a result only at the
        # commit critical section that also registers the session, so a value
        # returned here is always pool-owned; if the creation is aborted (the
        # creator unwound or a close_* ran), ``ready`` carries the exception and
        # this joiner fails with it instead of holding an unmanaged session.
        if join is not None:
            return await asyncio.shield(join)

        assert ready is not None and close_evt is not None and task is not None

        # Phase 3: wait for our owner task to commit the initialized session.
        # A successful result means the session is already registered in
        # _entries — the commit critical section did both — so from that moment
        # the pool, not this call, owns its lifetime.
        try:
            session = await asyncio.shield(ready)
        except BaseException:
            # Three distinct cases reach here:
            #
            # 1. The owner task failed (e.g. connect/initialize error) and
            #    reported it via ready.set_exception(). It is *already* in its
            #    finally block running cm.__aexit__ in its own task, so we must
            #    NOT cancel it — doing so would interrupt that cleanup. We only
            #    wait for it to finish unwinding.
            # 2. This call itself was cancelled (CancelledError) while the
            #    creation was still in flight. Because of the shield, `ready`
            #    is still pending and the owner task is alive. We signal close
            #    and cancel it so it exits the cancel scope in its own task,
            #    then wait for it to finish.
            # 3. This call was cancelled at the very moment the owner
            #    committed: `ready` resolved with a result and the session is
            #    registered in _entries. Joiners may already hold it, so we
            #    must NOT tear it down — just propagate the cancellation and
            #    leave the pooled session to LRU eviction / close_*.
            if not self._creation_committed(ready):
                owner_already_failed = ready.done() and not ready.cancelled() and ready.exception() is not None
                if not owner_already_failed:
                    close_evt.set()
                    task.cancel()
                try:
                    await asyncio.shield(task)
                except BaseException:
                    logger.debug("Owner task ended during get_session unwind", exc_info=True)
                with self._lock:
                    if self._inflight.get(key) == (current_loop, ready, task, close_evt):
                        self._inflight.pop(key)
            raise

        # Phase 4: the commit inside the owner task already promoted the
        # creation into a registered entry; nothing left to decide here.
        return session

    # ------------------------------------------------------------------
    # Cleanup helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _signal_close(loop: asyncio.AbstractEventLoop, close_evt: asyncio.Event) -> None:
        """Ask an owner task to shut down without waiting.

        ``asyncio.Event.set`` is not thread-safe, so it is scheduled on the
        owning loop. A closed loop means the owner task is already gone.
        """
        if loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(close_evt.set)
        except RuntimeError:
            # Loop was closed between the is_closed() check and now.
            pass

    @staticmethod
    def _owner_unwinding_after_failure(ready: asyncio.Future[ClientSession] | None) -> bool:
        """True when the owner already failed and is running ``__aexit__``.

        Cancelling such an owner would interrupt that in-task cleanup — the
        same-task exit anyio requires — so callers must skip the cancel.
        """
        return ready is not None and ready.done() and not ready.cancelled() and ready.exception() is not None

    @staticmethod
    def _creation_committed(ready: asyncio.Future[ClientSession] | None) -> bool:
        """True once the creation's session is registered in ``_entries``.

        ``_run_session`` resolves ``ready`` with a *result* only inside the
        commit critical section that also moves the record into ``_entries``,
        so this is exactly the state in which the session is pool-owned —
        visible to LRU eviction and the close_* paths, and possibly already
        handed to a joiner. Unwind paths must not tear such a session down:
        closing it here would yank a live session from a joiner's hands
        (#5008 review).
        """
        return ready is not None and ready.done() and not ready.cancelled() and ready.exception() is None

    @classmethod
    def _cancel_owner(cls, loop: asyncio.AbstractEventLoop, task: asyncio.Task[Any], ready: asyncio.Future[ClientSession] | None = None) -> None:
        """Thread-safe guarded cancel of an owner task on its owning loop.

        The failure-state recheck runs INSIDE the callback that executes on the
        owning loop, immediately before ``task.cancel()``: evaluating it on the
        caller's loop first and queueing the cancel after opens a
        time-of-check/time-of-use window in which the owner can fail, publish
        the exception to ``ready``, and enter ``__aexit__`` — the already-queued
        cancel would then interrupt that in-task cleanup. On the owning loop
        the check and the cancel are atomic with respect to owner-task
        progress (the owner cannot advance between two non-awaiting
        statements), so an owner already unwinding after failure is never
        cancelled.
        """

        def _guarded_cancel() -> None:
            if cls._owner_unwinding_after_failure(ready):
                return
            task.cancel()

        if loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(_guarded_cancel)
        except RuntimeError:
            # Loop was closed between the is_closed() check and now.
            pass

    def _track_owner_teardown(self, task: asyncio.Task[Any]) -> None:
        """Keep an owner's teardown observable after its awaiter was cancelled.

        The awaiter unwinds, but the owner still has to finish ``__aexit__`` in
        its own task; the reaper awaits that completion so exceptions are
        retrieved and the teardown stays observable instead of dangling. The
        reaper is strongly retained in ``_teardown_tasks`` until it finishes —
        the loop only keeps weak task references, so an unheld reaper (and
        transitively the owner mid-``__aexit__``) could be garbage-collected
        before the exit completes (#5008 review).
        """

        async def _reap() -> None:
            try:
                await task
            except BaseException:
                logger.debug("Owner task ended after caller cancellation", exc_info=True)

        try:
            reaper = asyncio.get_running_loop().create_task(_reap(), name=f"mcp-session-owner-reap:{task.get_name()}")
        except RuntimeError:
            return
        self._teardown_tasks.add(reaper)
        reaper.add_done_callback(self._teardown_tasks.discard)

    async def _shutdown(
        self,
        close_evt: asyncio.Event,
        task: asyncio.Task[Any],
        cancel: bool = False,
        ready: asyncio.Future[ClientSession] | None = None,
    ) -> None:
        """Signal an owner task and wait for it to finish (runs on its loop).

        ``cancel=True`` is used for in-flight creations: the owner task may be
        blocked inside ``initialize()`` where ``close_evt`` cannot wake it, so it
        must be cancelled — unless it already failed and is unwinding in its
        ``finally`` block (``ready`` carries an exception), where a cancel would
        interrupt the in-task ``__aexit__``. The exit always runs in the owner
        task itself, satisfying anyio's same-task cancel-scope requirement.

        The await is shielded: a cancellation of *this* awaiting task
        propagates immediately without cancelling the owner, whose teardown
        keeps running under a tracked reaper task. The victim's own
        cancellation or exception is swallowed and logged as before.
        """
        close_evt.set()
        if cancel and not self._owner_unwinding_after_failure(ready):
            task.cancel()
        caller = asyncio.current_task()
        caller_cancels = caller.cancelling() if caller is not None else 0
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            # ``shield`` surfaces the victim's cancellation (we cancelled it
            # above, or someone else did). But if the count rose, the
            # cancellation belongs to US — the awaiting task was cancelled
            # while waiting (e.g. a get_session parked in eviction teardown
            # under asyncio.wait_for). Propagate it while keeping the owner's
            # teardown tracked so __aexit__ still completes.
            if caller is not None and caller.cancelling() > caller_cancels:
                self._track_owner_teardown(task)
                raise
            logger.debug("Owner task cancelled during shutdown")
        except Exception:
            logger.debug("Owner task ended during shutdown", exc_info=True)

    async def _shutdown_entry(
        self,
        loop: asyncio.AbstractEventLoop,
        task: asyncio.Task[Any],
        close_evt: asyncio.Event,
        cancel: bool = False,
        ready: asyncio.Future[ClientSession] | None = None,
    ) -> None:
        """Shut down one entry, routing the close to its owning loop."""
        if loop.is_closed():
            return
        current_loop = asyncio.get_running_loop()
        if loop is current_loop:
            await self._shutdown(close_evt, task, cancel, ready=ready)
        elif loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._shutdown(close_evt, task, cancel, ready=ready), loop)
            try:
                await asyncio.wrap_future(future)
            except Exception:
                logger.warning("Error closing MCP session on owning loop", exc_info=True)
        else:
            # Owning loop exists but is neither the current loop nor running.
            # We are inside an async context here, so run_until_complete() would
            # raise "Cannot run the event loop while another loop is running";
            # and the loop may belong to another thread, where driving it from
            # here is unsafe. This branch is not expected in practice — a
            # session's owning loop is either the long-lived gateway loop (which
            # is running) or a short-lived asyncio.run loop (which is closed and
            # caught above). Fall back to a best-effort thread-safe signal so the
            # owner task tears down if/when its loop runs again.
            logger.warning("Owning loop for MCP session is idle; signalling close best-effort. Session may leak until the loop runs again.")
            self._signal_close(loop, close_evt)
            if cancel:
                self._cancel_owner(loop, task, ready)

    async def _close_owners(
        self,
        entries: list[tuple[ClientSession, asyncio.AbstractEventLoop, asyncio.Task[Any], asyncio.Event]],
        inflight: list[tuple[asyncio.AbstractEventLoop, asyncio.Future[ClientSession], asyncio.Task[Any], asyncio.Event]],
    ) -> None:
        """Shut down already-removed owners: signal all first, then await.

        Signalling every removed owner BEFORE awaiting any teardown guarantees
        a cancellation of the close call can never strand an owner that is no
        longer reachable through the registries: each has its close event (and,
        for in-flight creations, its guarded cancel) in hand and tears down in
        its own task regardless. The awaiting phase adds best-effort
        determinism on top; skipping the remaining awaits on unwind is safe.
        """
        for _session, loop, ent_task, ent_close in entries:
            self._signal_close(loop, ent_close)
        for loop, ent_ready, ent_task, ent_close in inflight:
            self._signal_close(loop, ent_close)
            self._cancel_owner(loop, ent_task, ent_ready)
        for _session, loop, ent_task, ent_close in entries:
            await self._shutdown_entry(loop, ent_task, ent_close)
        for loop, ent_ready, ent_task, ent_close in inflight:
            await self._shutdown_entry(loop, ent_task, ent_close, ready=ent_ready)

    async def close_scope(self, scope_key: str) -> None:
        """Close all sessions for a given scope (e.g. thread_id)."""
        with self._lock:
            keys = [k for k in self._entries if k[1] == scope_key]
            entries = [(self._entries.pop(k)) for k in keys]
            inflight_keys = [k for k in self._inflight if k[1] == scope_key]
            inflight = [self._inflight.pop(k) for k in inflight_keys]
        await self._close_owners(entries, inflight)

    async def close_session(self, server_name: str, scope_key: str) -> None:
        """Close one exact server/scope session so a retry reconnects cleanly."""
        key = (server_name, scope_key)
        with self._lock:
            entry = self._entries.pop(key, None)
            inflight = self._inflight.pop(key, None)
        await self._close_owners([entry] if entry is not None else [], [inflight] if inflight is not None else [])

    async def close_session_if_current(
        self,
        server_name: str,
        scope_key: str,
        session: ClientSession,
    ) -> bool:
        """Close *session* only if it is still the registered entry for the key."""
        key = (server_name, scope_key)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry[0] is not session:
                return False
            self._entries.pop(key)
        _session, loop, task, close_evt = entry
        await self._shutdown_entry(loop, task, close_evt)
        return True

    async def close_server(self, server_name: str) -> None:
        """Close all sessions for a given server."""
        with self._lock:
            keys = [k for k in self._entries if k[0] == server_name]
            entries = [(self._entries.pop(k)) for k in keys]
            inflight_keys = [k for k in self._inflight if k[0] == server_name]
            inflight = [self._inflight.pop(k) for k in inflight_keys]
        await self._close_owners(entries, inflight)

    async def close_all(self) -> None:
        """Close every managed session."""
        with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
            inflight = list(self._inflight.values())
            self._inflight.clear()
        await self._close_owners(entries, inflight)

    def close_all_sync(self) -> None:
        """Close all sessions on their owning event loops (synchronous).

        Each session is closed by its owner task on the loop it was created in,
        avoiding cross-loop and cross-task errors. Safe to call from any thread
        without an active event loop.

        Closing semantics differ by where the owning loop runs:

        * Owning loop is idle, or running on another thread — this call blocks
          until teardown completes (or ``SESSION_CLOSE_TIMEOUT`` elapses).
        * Owning loop is the one currently running on *this* thread — we cannot
          block on it without deadlocking, so teardown is only *signalled* here
          and completes asynchronously once control returns to that loop. The
          caller must therefore keep that loop running afterwards; if it stops
          the loop immediately, the owner task's ``__aexit__`` may not run. When
          a deterministic close is required from inside a running loop, ``await
          close_all()`` instead.
        """
        with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
            inflight = list(self._inflight.values())
            self._inflight.clear()

        # Entries are initialized (gentle close_evt path). In-flight creations
        # may be blocked mid-init, so they are cancelled to unblock teardown —
        # but every guard below re-checks on the owning loop (or atomically on
        # this thread for the current-loop branch), so an owner that has since
        # failed and is unwinding in __aexit__ is never cancelled.
        owners = [(loop, task, close_evt, False, None) for _s, loop, task, close_evt in entries]
        owners += [(loop, task, ent_close, True, ent_ready) for loop, ent_ready, task, ent_close in inflight]
        try:
            current_running_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_running_loop = None
        for loop, task, close_evt, cancel, ent_ready in owners:
            if loop.is_closed():
                continue
            try:
                if loop is current_running_loop:
                    # We are executing inside this loop's thread, so synchronously
                    # waiting on run_coroutine_threadsafe(...).result() would
                    # deadlock until timeout. Signal the owner task directly and
                    # let it finish once this synchronous call returns control to
                    # the running loop. Same-thread, no yield between the guard
                    # and the cancel, so the check is atomic here.
                    close_evt.set()
                    if cancel and not self._owner_unwinding_after_failure(ent_ready):
                        task.cancel()
                elif loop.is_running():
                    # Schedule the shutdown on the owning loop from this thread;
                    # _shutdown applies the failure guard on that loop.
                    future = asyncio.run_coroutine_threadsafe(self._shutdown(close_evt, task, cancel, ready=ent_ready), loop)
                    future.result(timeout=self.SESSION_CLOSE_TIMEOUT)
                else:
                    loop.run_until_complete(self._shutdown(close_evt, task, cancel, ready=ent_ready))
            except Exception:
                logger.debug("Error closing MCP session during sync close", exc_info=True)


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------

_pool: MCPSessionPool | None = None
_pool_lock = threading.Lock()


def get_session_pool() -> MCPSessionPool:
    """Return the global session-pool singleton."""
    global _pool
    # Build and return under the lock so racing cold-start callers construct
    # exactly one pool and reset_session_pool() can't null the global between
    # reading it and returning it (which previously could hand back None). The
    # critical section is tiny and never awaits, so a threading.Lock is safe to
    # hold from both the async and sync/worker-thread paths.
    with _pool_lock:
        if _pool is None:
            _pool = MCPSessionPool()
        return _pool


def reset_session_pool() -> None:
    """Reset the singleton (used in tests and the MCP cache reset path)."""
    global _pool
    with _pool_lock:
        _pool = None
