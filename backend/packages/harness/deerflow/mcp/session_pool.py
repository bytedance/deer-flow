"""Persistent MCP session pool for stateful tool calls.

When MCP tools are loaded via langchain-mcp-adapters with ``session=None``,
each tool call creates a new MCP session. For stateful servers like Playwright,
this means browser state (opened pages, filled forms) is lost between calls.

This module provides a session pool that maintains persistent MCP sessions,
scoped by ``(server_name, scope_key, owning_loop, ownership_domain)``. Consecutive calls on
the same loop share server-side state; independent loops use separate sessions.
The sync wrapper uses a fresh loop per call, so it does not preserve that state.
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
import hashlib
import json
import logging
import threading
from collections import OrderedDict
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

import anyio
from mcp import ClientSession
from mcp.shared.exceptions import McpError
from mcp.types import CONNECTION_CLOSED

from deerflow.mcp_scope import mcp_scope_belongs_to_thread

logger = logging.getLogger(__name__)

MCPPoolDomain = Literal["deployment", "personal"]

_STDIO_IDENTITY_KEYS = ("transport", "command", "args", "cwd", "env")


def normalized_connection_fingerprint(connection: Mapping[str, Any]) -> str:
    """Return a secret-safe digest of the stdio process identity."""
    identity = {key: connection[key] for key in _STDIO_IDENTITY_KEYS if key in connection}
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True, eq=False)
class ServerBinding:
    """Opaque capability naming one configuration epoch for a pooled server."""

    domain: MCPPoolDomain
    server_name: str
    epoch: int
    fingerprint: str | None = field(repr=False)


@dataclass(frozen=True, slots=True)
class PreparedRetirement:
    """Owners atomically detached and signalled by a binding transition."""

    entries: tuple[
        tuple[ClientSession, asyncio.AbstractEventLoop, asyncio.Task[Any], asyncio.Event],
        ...,
    ] = ()
    inflight: tuple[
        tuple[
            asyncio.AbstractEventLoop,
            asyncio.Future[ClientSession],
            asyncio.Task[Any],
            asyncio.Event,
        ],
        ...,
    ] = ()


class StaleMCPBindingError(RuntimeError):
    """Raised when a caller holds a superseded stdio server binding."""

    def __init__(self, server_name: str) -> None:
        super().__init__(f"MCP server '{server_name}' configuration changed; rebuild the MCP tools before calling it again")
        self.server_name = server_name


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
    domain: MCPPoolDomain = "deployment",
) -> Any:
    """Call a pooled session and evict it only after an explicit disconnect."""
    try:
        return await session.call_tool(tool_name, arguments, **call_kwargs)
    except Exception as error:
        if _is_mcp_transport_disconnect(error):
            cleanup_call = pool.close_session_if_current(server_name, scope_key, session) if domain == "deployment" else pool.close_session_if_current(server_name, scope_key, session, domain=domain)
            cleanup = asyncio.create_task(cleanup_call)
            if await _finish_session_cleanup(cleanup, server_name):
                raise asyncio.CancelledError
        raise


class MCPSessionPool:
    """Manages persistent MCP sessions scoped by ``(server_name, scope_key, owning_loop, ownership_domain)``."""

    MAX_SESSIONS = 256
    SESSION_CLOSE_TIMEOUT = 5.0  # seconds to wait when closing a session on a foreign loop

    def __init__(self) -> None:
        # Each entry: (session, owning_loop, owner_task, close_event).
        self._entries: OrderedDict[
            tuple[str, str, asyncio.AbstractEventLoop, MCPPoolDomain],
            tuple[
                ClientSession,
                asyncio.AbstractEventLoop,
                asyncio.Task[Any],
                asyncio.Event,
            ],
        ] = OrderedDict()
        # In-flight creations, keyed by (server, scope, owning_loop, ownership_domain). Lets concurrent callers
        # on the same loop share a single creation instead of each spawning a
        # duplicate session. Value: (loop, ready_future, owner_task, close_event).
        # The owner task promotes the record into ``_entries`` and resolves
        # ``ready`` with the session in one atomic critical section (see
        # ``_run_session``), so ``ready`` resolving with a *result* always means
        # the session is registered — never merely handed to one caller.
        self._inflight: dict[
            tuple[str, str, asyncio.AbstractEventLoop, MCPPoolDomain],
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
        # Per-(ownership-domain, server-name) configuration capability.
        # Session registry keys remain the four-tuple introduced by PR A.
        self._bindings: dict[tuple[MCPPoolDomain, str], ServerBinding] = {}
        self._binding_lifecycle_servers: set[tuple[MCPPoolDomain, str]] = set()
        self._next_binding_epoch = 1
        self._retired = False

    # ------------------------------------------------------------------
    # Server binding identity
    # ------------------------------------------------------------------

    def _install_binding_locked(
        self,
        binding_key: tuple[MCPPoolDomain, str],
        fingerprint: str | None,
    ) -> ServerBinding:
        domain, server_name = binding_key
        binding = ServerBinding(
            domain=domain,
            server_name=server_name,
            epoch=self._next_binding_epoch,
            fingerprint=fingerprint,
        )
        self._next_binding_epoch += 1
        self._bindings[binding_key] = binding
        return binding

    def _binding_is_current(self, expected: ServerBinding) -> bool:
        with self._lock:
            return not self._retired and self._bindings.get((expected.domain, expected.server_name)) is expected

    def ensure_binding(
        self,
        server_name: str,
        fingerprint: str,
        *,
        domain: MCPPoolDomain = "deployment",
    ) -> ServerBinding:
        """Resolve the discovery/task binding atomically without overwriting newer state."""
        binding_key = (domain, server_name)
        with self._lock:
            self._binding_lifecycle_servers.add(binding_key)
            if self._retired:
                raise StaleMCPBindingError(server_name)
            current = self._bindings.get(binding_key)
            if current is None:
                return self._install_binding_locked(binding_key, fingerprint)
            if current.fingerprint != fingerprint:
                raise StaleMCPBindingError(server_name)
            return current

    def reconcile_bindings(
        self,
        active: Mapping[str, str],
        removed: Collection[str],
        *,
        domain: MCPPoolDomain = "deployment",
    ) -> PreparedRetirement:
        """Apply already-classified binding changes and detach only changed owners.

        This method deliberately does not inspect configuration. A higher layer
        supplies current fingerprints and removed names. Epoch installation,
        registry detach and owner signalling are one non-awaiting critical
        section, so a stale creator cannot resurrect after the transition.
        """
        entries: list[tuple[ClientSession, asyncio.AbstractEventLoop, asyncio.Task[Any], asyncio.Event]] = []
        inflight: list[tuple[asyncio.AbstractEventLoop, asyncio.Future[ClientSession], asyncio.Task[Any], asyncio.Event]] = []
        changed: set[str] = set()

        with self._lock:
            for server_name, fingerprint in active.items():
                binding_key = (domain, server_name)
                self._binding_lifecycle_servers.add(binding_key)
                current = self._bindings.get(binding_key)
                if current is not None and current.fingerprint == fingerprint:
                    continue
                self._install_binding_locked(binding_key, fingerprint)
                changed.add(server_name)

            for server_name in removed:
                binding_key = (domain, server_name)
                self._binding_lifecycle_servers.add(binding_key)
                current = self._bindings.get(binding_key)
                if current is not None and current.fingerprint is None:
                    continue
                self._install_binding_locked(binding_key, None)
                changed.add(server_name)

            for key in [k for k in self._entries if k[3] == domain and k[0] in changed]:
                entries.append(self._entries.pop(key))
            for key in [k for k in self._inflight if k[3] == domain and k[0] in changed]:
                inflight.append(self._inflight.pop(key))

            for _session, loop, _task, close_evt in entries:
                self._signal_close(loop, close_evt)
            for loop, ready, task, close_evt in inflight:
                self._signal_close(loop, close_evt)
                self._cancel_owner(loop, task, ready)

        # Owners are already out of the registry, so retain their teardown even
        # if the caller never awaits the returned PreparedRetirement.
        for _session, loop, task, _close_evt in entries:
            self._track_detached_owner(loop, task)
        for loop, _ready, task, _close_evt in inflight:
            self._track_detached_owner(loop, task)

        return PreparedRetirement(entries=tuple(entries), inflight=tuple(inflight))

    def retire_all(self) -> None:
        """Fence this pool so stale wrappers cannot create sessions after reset."""
        with self._lock:
            self._retired = True

    # ------------------------------------------------------------------
    # Session owner task
    # ------------------------------------------------------------------

    def _discard_owner(
        self,
        key: tuple[str, str, asyncio.AbstractEventLoop, MCPPoolDomain],
        owner: asyncio.Task[Any],
    ) -> None:
        """Retire only this owner, including after asyncio.run shuts its loop down."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry[2] is owner:
                self._entries.pop(key)
            inflight = self._inflight.get(key)
            if inflight is not None and inflight[2] is owner:
                self._inflight.pop(key)

    async def _run_session(
        self,
        key: tuple[str, str, asyncio.AbstractEventLoop, MCPPoolDomain],
        connection: dict[str, Any],
        ready: asyncio.Future[ClientSession],
        close_evt: asyncio.Event,
        expected_binding: ServerBinding,
    ) -> None:
        """Own one MCP session and fence promotion against binding replacement."""
        from langchain_mcp_adapters.sessions import create_session

        cm = create_session(connection)
        try:
            session = await cm.__aenter__()
        except BaseException as error:
            if not ready.done():
                if self._binding_is_current(expected_binding):
                    ready.set_exception(error)
                else:
                    logger.debug(
                        "Suppressing MCP session error for superseded binding '%s'",
                        expected_binding.server_name,
                        exc_info=(type(error), error, error.__traceback__),
                    )
                    ready.set_exception(StaleMCPBindingError(expected_binding.server_name))
            return

        try:
            await session.initialize()
            loop = asyncio.get_running_loop()
            task = asyncio.current_task()
            promoted_evicted: list[tuple[asyncio.AbstractEventLoop, asyncio.Task[Any], asyncio.Event]] = []
            binding_key = (expected_binding.domain, expected_binding.server_name)
            with self._lock:
                binding_ok = not self._retired and self._bindings.get(binding_key) is expected_binding
                still_ours = self._inflight.get(key) == (loop, ready, task, close_evt)
                if still_ours and binding_ok:
                    self._inflight.pop(key)
                    while len(self._entries) >= self.MAX_SESSIONS:
                        oldest_key, (_, ent_loop, ent_task, ent_close) = next(iter(self._entries.items()))
                        self._entries.pop(oldest_key)
                        promoted_evicted.append((ent_loop, ent_task, ent_close))
                    self._entries[key] = (session, loop, task, close_evt)
                    if not ready.done():
                        ready.set_result(session)
                elif still_ours:
                    self._inflight.pop(key)

            if still_ours and binding_ok:
                for ent_loop, _ent_task, ent_close in promoted_evicted:
                    self._signal_close(ent_loop, ent_close)
                for ent_loop, ent_task, _ent_close in promoted_evicted:
                    if ent_loop is loop:
                        self._track_owner_teardown(ent_task)
                    elif not ent_loop.is_closed():
                        try:
                            ent_loop.call_soon_threadsafe(self._track_owner_teardown, ent_task)
                        except RuntimeError:
                            pass
                logger.info("Created persistent MCP session for %s/%s", key[0], key[1])
                await close_evt.wait()
            elif not binding_ok:
                if not ready.done():
                    ready.set_exception(StaleMCPBindingError(expected_binding.server_name))
            else:
                if not ready.done():
                    ready.set_exception(asyncio.CancelledError("MCP session pool was closed while the session was being created"))
                await close_evt.wait()
        except BaseException as error:
            if not ready.done():
                if self._binding_is_current(expected_binding):
                    ready.set_exception(error)
                else:
                    logger.debug(
                        "Suppressing MCP session error for superseded binding '%s'",
                        expected_binding.server_name,
                        exc_info=(type(error), error, error.__traceback__),
                    )
                    ready.set_exception(StaleMCPBindingError(expected_binding.server_name))
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
        *,
        binding: ServerBinding | None = None,
        domain: MCPPoolDomain = "deployment",
    ) -> ClientSession:
        """Get/create a pooled session while proving the caller owns the current binding."""
        effective_domain = binding.domain if binding is not None else domain
        if binding is not None and binding.server_name != server_name:
            raise StaleMCPBindingError(server_name)

        current_loop = asyncio.get_running_loop()
        key = (server_name, scope_key, current_loop, effective_domain)
        binding_key = (effective_domain, server_name)

        evicted: list[tuple[asyncio.AbstractEventLoop, asyncio.Task[Any], asyncio.Event]] = []
        join: asyncio.Future[ClientSession] | None = None
        ready: asyncio.Future[ClientSession] | None = None
        close_evt: asyncio.Event | None = None
        task: asyncio.Task[Any] | None = None

        with self._lock:
            if self._retired:
                raise StaleMCPBindingError(server_name)

            if binding is not None:
                if self._bindings.get(binding_key) is not binding:
                    raise StaleMCPBindingError(server_name)
                expected_binding = binding
            else:
                # Compatibility for callers not yet binding-aware. Once a
                # server participates in explicit binding lifecycle, callers
                # must present the opaque capability; fingerprint equality
                # alone cannot distinguish remove/re-add ABA.
                if binding_key in self._binding_lifecycle_servers:
                    raise StaleMCPBindingError(server_name)
                expected_binding = self._bindings.get(binding_key)
                fingerprint = normalized_connection_fingerprint(connection)
                if expected_binding is None:
                    expected_binding = self._install_binding_locked(binding_key, fingerprint)
                elif expected_binding.fingerprint != fingerprint:
                    raise StaleMCPBindingError(server_name)

            if key in self._entries:
                session, _loop, ent_task, _ent_close = self._entries[key]
                if not ent_task.done():
                    self._entries.move_to_end(key)
                    return session
                self._entries.pop(key)

            inflight = self._inflight.get(key)
            if inflight is not None:
                join = inflight[1]
            else:
                ready = current_loop.create_future()
                close_evt = asyncio.Event()
                task = current_loop.create_task(self._run_session(key, connection, ready, close_evt, expected_binding))
                self._inflight[key] = (current_loop, ready, task, close_evt)
                task.add_done_callback(lambda owner: self._discard_owner(key, owner))

            while len(self._entries) >= self.MAX_SESSIONS:
                oldest_key, (_, loop, ent_task, ent_close) = next(iter(self._entries.items()))
                self._entries.pop(oldest_key)
                evicted.append((loop, ent_task, ent_close))

        for loop, _ent_task, ent_close in evicted:
            self._signal_close(loop, ent_close)
        try:
            for loop, ent_task, ent_close in evicted:
                if loop is current_loop and not loop.is_closed():
                    await self._shutdown(ent_close, ent_task)
        except BaseException:
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

        if join is not None:
            session = await asyncio.shield(join)
            # Check-before-return fence, not a lease across subsequent caller
            # use: a reconcile racing after this check detaches and closes the
            # owner, and the caller then fails through the existing transport
            # disconnect path.
            if not self._binding_is_current(expected_binding):
                raise StaleMCPBindingError(server_name)
            return session

        assert ready is not None and close_evt is not None and task is not None
        try:
            session = await asyncio.shield(ready)
        except BaseException:
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

        # Same check-before-return fence as the joiner path above; not a lease.
        if not self._binding_is_current(expected_binding):
            raise StaleMCPBindingError(server_name)
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

    def _track_detached_owner(
        self,
        loop: asyncio.AbstractEventLoop,
        task: asyncio.Task[Any],
    ) -> None:
        """Keep an owner detached by binding reconciliation strongly retained.

        ``reconcile_bindings()`` removes owners from the registry without
        awaiting their teardown, so the pool itself must keep that teardown
        observable even when the caller drops the returned
        ``PreparedRetirement``. The reaper has to run on the owner's loop, which
        is where ``__aexit__`` executes.
        """
        try:
            current_loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if loop is current_loop:
            self._track_owner_teardown(task)
        elif not loop.is_closed():
            try:
                loop.call_soon_threadsafe(self._track_owner_teardown, task)
            except RuntimeError:
                # Loop was closed between the is_closed() check and now.
                pass

    def _track_owner_teardown(self, task: asyncio.Task[Any]) -> None:
        """Keep detached eviction or cancelled-caller teardown observable.

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
                logger.debug("Owner task ended during detached teardown", exc_info=True)

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
        """Close all sessions for a scope across ownership domains."""
        with self._lock:
            keys = [k for k in self._entries if k[1] == scope_key]
            entries = [(self._entries.pop(k)) for k in keys]
            inflight_keys = [k for k in self._inflight if k[1] == scope_key]
            inflight = [self._inflight.pop(k) for k in inflight_keys]
        await self._close_owners(entries, inflight)

    async def close_thread_scope(self, *, user_id: str, thread_id: str) -> None:
        """Close every session scoped to one user/thread identity across ownership domains.

        Differs from :meth:`close_scope` in matching *all incarnations* of the
        thread rather than one exact scope key. A thread-deletion path knows the
        user and thread but not reliably the incarnation: the record may predate
        incarnation tracking (legacy ``user:thread`` scope), and a new
        incarnation can be minted between reading the record and tearing down.
        Keying cleanup on a read incarnation would therefore both miss legacy
        sessions and race a concurrent incarnation. Every generation of a
        deleted thread is equally stale, so all of them are closed.

        ``user_id`` must be the same string used by
        ``resolve_runtime_user_id(runtime)`` when minting the session scope.
        The Gateway delete route passes ``get_effective_user_id()`` and relies
        on both resolving to the same identity in its embedded runtime.

        Sessions belonging to another user or thread are left untouched.
        """
        with self._lock:
            keys = [k for k in self._entries if mcp_scope_belongs_to_thread(k[1], user_id=user_id, thread_id=thread_id)]
            entries = [self._entries.pop(k) for k in keys]
            inflight_keys = [k for k in self._inflight if mcp_scope_belongs_to_thread(k[1], user_id=user_id, thread_id=thread_id)]
            inflight = [self._inflight.pop(k) for k in inflight_keys]
        await self._close_owners(entries, inflight)

    async def close_session(
        self,
        server_name: str,
        scope_key: str,
        *,
        domain: MCPPoolDomain = "deployment",
    ) -> None:
        """Close this ownership domain's session for a server/scope across loops."""
        with self._lock:
            keys = [k for k in self._entries if k[:2] == (server_name, scope_key) and k[3] == domain]
            entries = [self._entries.pop(k) for k in keys]
            keys = [k for k in self._inflight if k[:2] == (server_name, scope_key) and k[3] == domain]
            inflight = [self._inflight.pop(k) for k in keys]
        await self._close_owners(entries, inflight)

    async def close_session_if_current(
        self,
        server_name: str,
        scope_key: str,
        session: ClientSession,
        *,
        domain: MCPPoolDomain = "deployment",
    ) -> bool:
        """Close *session* only if it is current in the requested ownership domain."""
        with self._lock:
            key = next(
                (k for k, entry in self._entries.items() if k[:2] == (server_name, scope_key) and k[3] == domain and entry[0] is session),
                None,
            )
            if key is None:
                return False
            entry = self._entries.pop(key)
        _session, loop, task, close_evt = entry
        await self._shutdown_entry(loop, task, close_evt)
        return True

    async def close_server(self, server_name: str, *, domain: MCPPoolDomain = "deployment") -> None:
        """Close one ownership domain's sessions for a given server."""
        with self._lock:
            keys = [k for k in self._entries if k[0] == server_name and k[3] == domain]
            entries = [(self._entries.pop(k)) for k in keys]
            inflight_keys = [k for k in self._inflight if k[0] == server_name and k[3] == domain]
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


def reset_session_pool() -> MCPSessionPool | None:
    """Reset the singleton and return the retired pool, if any.

    The old pool is fenced before publication of the replacement so wrappers
    that captured it cannot create a post-reset session.
    """
    global _pool
    with _pool_lock:
        retired = _pool
        if retired is not None:
            retired.retire_all()
        _pool = None
        return retired
