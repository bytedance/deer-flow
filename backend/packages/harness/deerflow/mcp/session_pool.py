"""Persistent MCP session pool for stateful tool calls.

When MCP tools are loaded via langchain-mcp-adapters with ``session=None``,
each tool call creates a new MCP session. For stateful servers like Playwright,
this means browser state (opened pages, filled forms) is lost between calls.

This module provides a session pool that maintains persistent MCP sessions,
scoped by ``(server_name, scope_key, owning_loop)``. Consecutive calls on
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
import json
import logging
import threading
from collections import OrderedDict
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
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


# Bare connection keys that define a stdio server's identity. Everything else
# in a connection dict (or an unknown transport) is left out of the fingerprint.
STDIO_IDENTITY_KEYS = ("transport", "command", "args", "cwd", "env")


def normalized_connection_fingerprint(connection: Mapping[str, Any]) -> str:
    """Hash the base connection's identity keys exactly as given.

    The per-call workspace ``cwd``/``TMPDIR`` are applied to a copy in
    ``_make_session_pool_tool`` (see ``session_connection``), so the base
    connection never contains them; they must not be heuristically stripped here
    or an operator-configured ``cwd``/``TMPDIR`` would become invisible to
    identity changes.
    """
    base = {key: connection[key] for key in STDIO_IDENTITY_KEYS if key in connection}
    return json.dumps(base, sort_keys=True, default=str, ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class ServerBinding:
    """Opaque identity for one server configuration epoch.

    ``fingerprint is None`` is a removal tombstone: the name was removed but its
    epoch must never be reused, so a stale wrapper holding a pre-removal binding
    can never match a later re-add.
    """

    server_name: str
    epoch: int
    fingerprint: str | None = field(repr=False)


@dataclass(frozen=True, slots=True)
class PreparedRetirement:
    """Owners detached by :meth:`MCPSessionPool.reconcile_bindings`.

    The pool removes them from ``_entries``/``_inflight`` and signals each one
    inside the same ``_lock`` critical section, then hands them back here so the
    caller can await teardown *outside* every lock (see
    :meth:`MCPSessionPool.close_prepared_owners_sync`). Signalling before the
    hand-off means a cancellation of that teardown can never strand an owner
    that is no longer reachable through the registries.
    """

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
    """Raised when a stale MCP wrapper targets a retired or replaced binding."""

    def __init__(self, server_name: str) -> None:
        super().__init__(f"MCP server '{server_name}' configuration changed; rebuild the MCP tools before calling it again")
        self.server_name = server_name


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
    """Manages persistent MCP sessions scoped by ``(server_name, scope_key, owning_loop)``."""

    MAX_SESSIONS = 256
    SESSION_CLOSE_TIMEOUT = 5.0  # seconds to wait when closing a session on a foreign loop

    def __init__(self) -> None:
        # Each entry: (session, owning_loop, owner_task, close_event).
        self._entries: OrderedDict[
            tuple[str, str, asyncio.AbstractEventLoop],
            tuple[
                ClientSession,
                asyncio.AbstractEventLoop,
                asyncio.Task[Any],
                asyncio.Event,
            ],
        ] = OrderedDict()
        # In-flight creations, keyed by (server, scope, owning_loop). Lets concurrent callers
        # on the same loop share a single creation instead of each spawning a
        # duplicate session. Value: (loop, ready_future, owner_task, close_event).
        # The owner task promotes the record into ``_entries`` and resolves
        # ``ready`` with the session in one atomic critical section (see
        # ``_run_session``), so ``ready`` resolving with a *result* always means
        # the session is registered — never merely handed to one caller.
        self._inflight: dict[
            tuple[str, str, asyncio.AbstractEventLoop],
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
        # Per-server configuration identity. ``_next_epoch`` is a single
        # monotonic counter shared by every server and never reset, so a name
        # removed and later re-added can never observe a reused epoch (ABA
        # safe). ``_retired`` fences a whole pool that a global reset replaced.
        self._bindings: dict[str, ServerBinding] = {}
        # Names that have gone through an explicit bind/reconcile lifecycle.
        # The binding-less compatibility path is valid only before this set
        # contains the name; after a real lifecycle, even an ABA-equal epoch
        # must be rejected unless the caller supplies the current binding.
        self._binding_lifecycle_servers: set[str] = set()
        self._next_epoch = 1
        self._retired = False

    # ------------------------------------------------------------------
    # Server binding identity
    # ------------------------------------------------------------------

    def active_binding(self, server_name: str) -> ServerBinding | None:
        """Return the current binding for *server_name*, or ``None`` if unknown."""
        with self._lock:
            return self._bindings.get(server_name)

    def _binding_is_current(self, server_name: str, expected_binding: ServerBinding) -> bool:
        """True while *expected_binding* is still the server's live epoch.

        Used to re-check an awaited creation/join before handing the session
        back: a reconcile that lands while a caller is parked on ``ready``
        supersedes the epoch, so the caller must fail rather than return a
        session the pool has already detached for teardown.
        """
        with self._lock:
            return not self._retired and self._bindings.get(server_name) == expected_binding

    def _install_binding_locked(self, server_name: str, fingerprint: str | None) -> ServerBinding:
        """Install a fresh binding for *server_name*.

        Caller MUST already hold ``_lock`` (a non-reentrant ``threading.Lock``),
        so this helper never acquires it — that is what lets the public methods
        and :meth:`reconcile_bindings` share one critical section without
        calling back into ``bind_server``/``remove_server``/``active_binding``
        while the lock is held.
        """
        binding = ServerBinding(server_name=server_name, epoch=self._next_epoch, fingerprint=fingerprint)
        self._next_epoch += 1
        self._bindings[server_name] = binding
        return binding

    def capture_binding(self, server_name: str) -> ServerBinding:
        """Return the server's active binding for a discovery path to hold.

        Read-only: it never installs, replaces, or revives a binding. Callers
        capture the binding before their first discovery ``await`` and pass it
        back to :meth:`get_session`, so a configuration change that lands
        mid-discovery fences them instead of silently rebinding their old
        connection to the new epoch.

        Raises:
            StaleMCPBindingError: The pool is retired, the server is unknown, or
                the server's binding is a removal tombstone.
        """
        with self._lock:
            if self._retired:
                raise StaleMCPBindingError(server_name)
            binding = self._bindings.get(server_name)
            if binding is None or binding.fingerprint is None:
                raise StaleMCPBindingError(server_name)
            return binding

    def ensure_binding(self, server_name: str, fingerprint: str) -> ServerBinding:
        """Resolve *server_name*'s binding for a discovery path in ONE lock hold.

        Discovery-side counterpart to :meth:`bind_server`, closing the
        read-then-install race that ``active_binding()`` + ``bind_server()`` left
        open: a reconciliation could install a newer epoch between the read and
        the install, and ``bind_server`` would then overwrite it with the stale
        discovery fingerprint. Here the read and the install happen under a
        single ``_lock`` acquisition, so a reconciled binding can never be
        clobbered by a superseded discovery.

        - unknown name -> install a fresh binding from *fingerprint*
        - same fingerprint -> return the current binding (idempotent)
        - tombstone or differing fingerprint -> ``StaleMCPBindingError`` (the
          reconciled state is newer; discovery must never overwrite it)
        - retired pool -> ``StaleMCPBindingError``

        Raises:
            StaleMCPBindingError: The pool is retired, the server is a removal
                tombstone, or *fingerprint* is not the server's active identity.
        """
        with self._lock:
            self._binding_lifecycle_servers.add(server_name)
            if self._retired:
                raise StaleMCPBindingError(server_name)
            current = self._bindings.get(server_name)
            if current is None:
                return self._install_binding_locked(server_name, fingerprint)
            if current.fingerprint is None or current.fingerprint != fingerprint:
                raise StaleMCPBindingError(server_name)
            return current

    def bind_server(self, server_name: str, fingerprint: str) -> ServerBinding:
        """Install/replace *server_name*'s identity from a reconciliation pass.

        Idempotent for an unchanged fingerprint. A changed fingerprint (or a
        name re-added after removal) mints a fresh monotonic epoch so stale
        wrappers can detect that they no longer own the server.

        This is a reconciliation-internal identity installer, NOT a discovery
        API: discovery must use :meth:`capture_binding` so a wrapper cannot mint
        an epoch for itself and thereby re-authorize a superseded connection.
        """
        with self._lock:
            self._binding_lifecycle_servers.add(server_name)
            if self._retired:
                raise StaleMCPBindingError(server_name)
            current = self._bindings.get(server_name)
            if current is not None and current.fingerprint == fingerprint:
                return current
            return self._install_binding_locked(server_name, fingerprint)

    def remove_server(self, server_name: str) -> ServerBinding:
        """Tombstone *server_name* with a fresh epoch and a ``None`` fingerprint.

        Reconciliation-internal, like :meth:`bind_server` — a tombstone must only
        be installed by the config path that observed the removal, never by a
        discovery path trying to resolve its own identity.
        """
        with self._lock:
            self._binding_lifecycle_servers.add(server_name)
            if self._retired:
                raise StaleMCPBindingError(server_name)
            return self._install_binding_locked(server_name, None)

    def reconcile_bindings(
        self,
        active: Mapping[str, str],
        removed: Collection[str],
        *,
        force_rebind: Collection[str] = (),
    ) -> PreparedRetirement:
        """Reconcile per-server epochs and detach the retired servers' owners.

        *active* maps every still-enabled server name to its new normalized
        connection fingerprint; *removed* lists names that were disabled or
        deleted. A name whose fingerprint is unchanged is left completely
        untouched — no epoch, no detach — so an unrelated server edit cannot
        tear down a live session.

        *force_rebind* names servers in *active* whose shared lifecycle
        generation advanced even though their normalized connection fingerprint
        is unchanged (delete + identical re-add, disable + re-enable, or an
        A1 -> A2 -> A1 round trip). Those names must mint a fresh epoch and
        detach their current owner, so a superseded wrapper can never
        re-authorize the old connection.

        This only widens the condition under which a name is treated as changed;
        the admission/commit/join fencing below is unchanged.

        Everything happens in ONE ``_lock`` critical section: install the new
        epochs / removal tombstones, pop the changed servers' ``_entries`` and
        ``_inflight``, and immediately signal every detached owner (plus the
        guarded cancel for in-flight creations). Signalling inside the section
        means an owner is never left unreachable-but-unsignalled if the caller
        is cancelled before it awaits the returned teardown. No awaits happen
        here; the caller closes the returned owners outside every lock.
        """
        entries: list[tuple[ClientSession, asyncio.AbstractEventLoop, asyncio.Task[Any], asyncio.Event]] = []
        inflight: list[tuple[asyncio.AbstractEventLoop, asyncio.Future[ClientSession], asyncio.Task[Any], asyncio.Event]] = []
        changed: list[str] = []
        forced = set(force_rebind)
        with self._lock:
            self._binding_lifecycle_servers.update(active)
            self._binding_lifecycle_servers.update(removed)
            for server_name, fingerprint in active.items():
                current = self._bindings.get(server_name)
                if current is not None and current.fingerprint == fingerprint and server_name not in forced:
                    continue  # Unchanged and not force-rebound: never touched.
                self._install_binding_locked(server_name, fingerprint)
                changed.append(server_name)
            for server_name in removed:
                current = self._bindings.get(server_name)
                if current is not None and current.fingerprint is None:
                    # Already tombstoned: a repeat of the same removal must not
                    # burn another epoch or detach anything.
                    continue
                self._install_binding_locked(server_name, None)
                changed.append(server_name)

            for server_name in changed:
                for entry_key in [k for k in self._entries if k[0] == server_name]:
                    entries.append(self._entries.pop(entry_key))
                for inflight_key in [k for k in self._inflight if k[0] == server_name]:
                    inflight.append(self._inflight.pop(inflight_key))

            # Signal every detached owner inside this same critical section: it
            # is already unreachable through the registries, so a cancellation
            # before the caller awaits teardown must not be able to strand it.
            for _session, loop, _task, close_evt in entries:
                self._signal_close(loop, close_evt)
            for loop, ent_ready, task, close_evt in inflight:
                self._signal_close(loop, close_evt)
                self._cancel_owner(loop, task, ent_ready)

        return PreparedRetirement(entries=tuple(entries), inflight=tuple(inflight))

    def retire_all(self) -> None:
        """Fence the whole pool; a retired pool must not mint fresh bindings."""
        with self._lock:
            self._retired = True

    def prepare_retire_all(self) -> PreparedRetirement:
        """Fence, detach, and signal every owner in one critical section.

        Whole-pool retirement has the same cancellation hazard as per-server
        reconciliation: once an owner is removed from ``_entries``/``_inflight``
        it is no longer reachable, so its close signal must be delivered before
        the caller can be cancelled or the returned teardown can be skipped.
        This method performs only that non-waiting hand-off; callers wait for the
        returned owners outside every lock via ``close_prepared_owners_sync``.
        """
        entries: list[tuple[ClientSession, asyncio.AbstractEventLoop, asyncio.Task[Any], asyncio.Event]] = []
        inflight: list[tuple[asyncio.AbstractEventLoop, asyncio.Future[ClientSession], asyncio.Task[Any], asyncio.Event]] = []
        with self._lock:
            self._retired = True
            entries = list(self._entries.values())
            self._entries.clear()
            inflight = list(self._inflight.values())
            self._inflight.clear()

            for _session, loop, _task, close_evt in entries:
                self._signal_close(loop, close_evt)
            for loop, ready, task, close_evt in inflight:
                self._signal_close(loop, close_evt)
                self._cancel_owner(loop, task, ready)

        return PreparedRetirement(entries=tuple(entries), inflight=tuple(inflight))

    # ------------------------------------------------------------------
    # Session owner task
    # ------------------------------------------------------------------

    def _discard_owner(self, key: tuple[str, str, asyncio.AbstractEventLoop], owner: asyncio.Task[Any]) -> None:
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
        key: tuple[str, str, asyncio.AbstractEventLoop],
        connection: dict[str, Any],
        ready: asyncio.Future[ClientSession],
        close_evt: asyncio.Event,
        expected_binding: ServerBinding,
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
            # Re-check the fence: a reconcile may have cancelled this owner
            # while it was parked before entry, and that must surface as stale
            # rather than as a raw CancelledError.
            if not ready.done():
                if self._binding_is_current(key[0], expected_binding):
                    ready.set_exception(e)
                else:
                    ready.set_exception(StaleMCPBindingError(key[0]))
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
            server_name = key[0]
            promoted_evicted: list[tuple[asyncio.AbstractEventLoop, asyncio.Task[Any], asyncio.Event]] = []
            binding_ok = False
            still_ours = False
            with self._lock:
                # Commit fence: promote ONLY while the pool is live and this
                # creation's epoch is still the server's active one. A reconcile
                # that ran while initialize() was in flight leaves the epoch
                # superseded here, so the old configuration can never publish a
                # session for a fresh wrapper to reuse.
                binding_ok = not self._retired and self._bindings.get(server_name) == expected_binding
                still_ours = self._inflight.get(key) == (loop, ready, task, close_evt)
                if still_ours and binding_ok:
                    self._inflight.pop(key)
                    # Different keys can finish initialization concurrently.
                    # They may all pass the earlier capacity check while no
                    # session is registered, so enforce the cap again at the
                    # single owner-controlled commit point.
                    while len(self._entries) >= self.MAX_SESSIONS:
                        oldest_key, (_, ent_loop, ent_task, ent_close) = next(iter(self._entries.items()))
                        self._entries.pop(oldest_key)
                        promoted_evicted.append((ent_loop, ent_task, ent_close))
                    self._entries[key] = (session, loop, task, close_evt)
                    if not ready.done():
                        ready.set_result(session)
                elif still_ours:
                    # Reconciled away mid-initialize: drop the record so the
                    # abandoned creation is not left half-registered.
                    self._inflight.pop(key)
            if still_ours and binding_ok:
                # Drain victims independently: a blocked victim's __aexit__
                # must not prevent this owner from handling its own close.
                for ent_loop, _ent_task, ent_close in promoted_evicted:
                    self._signal_close(ent_loop, ent_close)
                for ent_loop, ent_task, ent_close in promoted_evicted:
                    if ent_loop is loop:
                        self._track_owner_teardown(ent_task)
                    elif not ent_loop.is_closed():
                        try:
                            ent_loop.call_soon_threadsafe(self._track_owner_teardown, ent_task)
                        except RuntimeError:
                            pass  # The owning loop closed before scheduling.
                logger.info("Created persistent MCP session for %s/%s", key[0], key[1])
                # Wait for the pool (or an LRU/close path) to signal teardown.
                await close_evt.wait()
            elif not binding_ok:
                # The server was reconciled away (or the whole pool retired)
                # while this creation was initializing: fail the stale creation
                # clearly instead of promoting an obsolete session. Nothing will
                # ever signal this abandoned creation, so unwind straight to the
                # finally block — which runs __aexit__ in THIS task — rather than
                # parking on close_evt and stranding the caller that is waiting
                # for the owner to finish.
                if not ready.done():
                    ready.set_exception(StaleMCPBindingError(server_name))
            else:
                # The record was already removed by a close path, which also
                # signalled close_evt; report the abort and wait for it.
                if not ready.done():
                    ready.set_exception(asyncio.CancelledError("MCP session pool was closed while the session was being created"))
                await close_evt.wait()
        except BaseException as e:
            if not ready.done():
                # reconcile detaches the in-flight record AND cancels the owner,
                # so a creation parked inside initialize() surfaces here as a
                # CancelledError before the commit fence can run. Re-check the
                # fence: a superseded/retired creation must report the stale
                # binding instead. A plain close leaves the epoch current, so it
                # keeps publishing the original exception (CancelledError).
                if self._binding_is_current(key[0], expected_binding):
                    ready.set_exception(e)
                else:
                    ready.set_exception(StaleMCPBindingError(key[0]))
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
    ) -> ClientSession:
        """Get or create a persistent MCP session.

        Reuse sessions and in-flight creations only on the current loop.
        Other live loops retain their own independent sessions.

        Args:
            server_name: MCP server name.
            scope_key: Isolation key (typically thread_id).
            connection: Connection configuration for ``create_session``.
            binding: The server's binding captured by the caller before its
                first discovery await. When ``None`` the pool resolves (or
                installs) the current binding itself, which keeps callers that
                predate per-server identity working unchanged.

        Returns:
            An initialized ``ClientSession``.

        Raises:
            StaleMCPBindingError: The pool was retired, or *binding* is not the
                server's active epoch.
        """
        current_loop = asyncio.get_running_loop()
        key = (server_name, scope_key, current_loop)

        # Phase 1: inspect/mutate the registry under the thread lock (no awaits).
        # Decide one of three outcomes atomically: return an existing session,
        # join an in-flight creation, or become the creator for this key.
        # LRU victims are established sessions: (loop, owner_task, close_event).
        evicted: list[tuple[asyncio.AbstractEventLoop, asyncio.Task[Any], asyncio.Event]] = []
        join: asyncio.Future[ClientSession] | None = None
        ready: asyncio.Future[ClientSession] | None = None
        close_evt: asyncio.Event | None = None
        task: asyncio.Task[Any] | None = None
        with self._lock:
            # Binding fence FIRST, before touching _entries/_inflight/LRU: a
            # retired pool, or a caller holding a superseded epoch, must never
            # observe — let alone create — a session. Fingerprints are never
            # logged here: they can carry resolved environment secrets.
            if self._retired:
                raise StaleMCPBindingError(server_name)
            if binding is not None:
                if self._bindings.get(server_name) != binding:
                    raise StaleMCPBindingError(server_name)
                expected_binding = binding
            else:
                # Back-compat: a caller with no binding is honoured only while it
                # still describes the server's ACTIVE configuration. Once a
                # server has entered a real bind/reconcile lifecycle, the
                # binding-less path is no longer valid: it cannot distinguish an
                # ABA-equal replacement epoch from the original. First sight
                # installs the binding; a superseded epoch, a removal tombstone,
                # or a connection that is not the active config is fenced rather
                # than silently rebound to whatever epoch is current.
                if server_name in self._binding_lifecycle_servers:
                    raise StaleMCPBindingError(server_name)
                expected_binding = self._bindings.get(server_name)
                if expected_binding is None:
                    expected_binding = self._install_binding_locked(server_name, normalized_connection_fingerprint(connection))
                elif expected_binding.fingerprint is None or expected_binding.fingerprint != normalized_connection_fingerprint(connection):
                    raise StaleMCPBindingError(server_name)

            if key in self._entries:
                session, _loop, ent_task, _ent_close = self._entries[key]
                if not ent_task.done():
                    self._entries.move_to_end(key)
                    return session
                self._entries.pop(key)

            inflight = self._inflight.get(key)
            if inflight is not None:
                # Only callers on this same loop share the creation future.
                join = inflight[1]
            else:
                # Become the creator: publish an in-flight record before any
                # await so concurrent callers join us instead of racing.
                ready = current_loop.create_future()
                close_evt = asyncio.Event()
                task = current_loop.create_task(self._run_session(key, connection, ready, close_evt, expected_binding))
                self._inflight[key] = (current_loop, ready, task, close_evt)
                task.add_done_callback(lambda owner: self._discard_owner(key, owner))

            # Evict LRU entries when at capacity.
            while len(self._entries) >= self.MAX_SESSIONS:
                oldest_key, (_, loop, ent_task, ent_close) = next(iter(self._entries.items()))
                self._entries.pop(oldest_key)
                evicted.append((loop, ent_task, ent_close))

        # Phase 2: shut down evicted sessions. Signal EVERY removed
        # owner first — the signal loop contains no awaits, so it completes
        # atomically and a cancellation during the teardown awaits below can
        # never strand an owner that was already removed from the registries.
        # Then await same-loop teardowns; foreign-loop owners finish on their
        # own loops. The owner task — never this one — runs __aexit__.
        for loop, _ent_task, ent_close in evicted:
            self._signal_close(loop, ent_close)
        try:
            for loop, ent_task, ent_close in evicted:
                if loop is current_loop and not loop.is_closed():
                    await self._shutdown(ent_close, ent_task)
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
            session = await asyncio.shield(join)
            if not self._binding_is_current(server_name, expected_binding):
                raise StaleMCPBindingError(server_name)
            return session

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

        # Phase 4: the owner task already promoted the initialized session and
        # enforced capacity in the same commit critical section. Re-check the
        # epoch before handing it back: a reconcile may have landed while this
        # caller was parked on ``ready``, in which case the session was already
        # detached and must not be returned as if it were current.
        if not self._binding_is_current(server_name, expected_binding):
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
        """Close all sessions for a given scope (e.g. thread_id)."""
        with self._lock:
            keys = [k for k in self._entries if k[1] == scope_key]
            entries = [(self._entries.pop(k)) for k in keys]
            inflight_keys = [k for k in self._inflight if k[1] == scope_key]
            inflight = [self._inflight.pop(k) for k in inflight_keys]
        await self._close_owners(entries, inflight)

    async def close_session(self, server_name: str, scope_key: str) -> None:
        """Close every session for this server/scope across all owning loops."""
        with self._lock:
            keys = [k for k in self._entries if k[:2] == (server_name, scope_key)]
            entries = [self._entries.pop(k) for k in keys]
            keys = [k for k in self._inflight if k[:2] == (server_name, scope_key)]
            inflight = [self._inflight.pop(k) for k in keys]
        await self._close_owners(entries, inflight)

    async def close_session_if_current(
        self,
        server_name: str,
        scope_key: str,
        session: ClientSession,
    ) -> bool:
        """Close *session* only if it is still the registered entry for the key."""
        with self._lock:
            key = next((k for k, entry in self._entries.items() if k[:2] == (server_name, scope_key) and entry[0] is session), None)
            if key is None:
                return False
            entry = self._entries.pop(key)
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

    def close_prepared_owners_sync(self, prepared: PreparedRetirement) -> None:
        """Close already-detached owners on their owning loops (synchronous).

        The owner-closing loop shared with :meth:`close_all_sync`. Each session
        is closed by its owner task on the loop it was created in, avoiding
        cross-loop and cross-task errors. Safe to call from any thread without
        an active event loop.

        Signalling happens for EVERY prepared owner before any teardown is
        awaited: a detached owner is no longer reachable through the
        registries, so if the caller is cancelled (or a foreign-loop teardown
        is slow) it must already hold its close signal — otherwise nothing
        would ever wake it. The owner task — never this one — runs
        ``__aexit__``.

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
        # Entries are initialized (gentle close_evt path). In-flight creations
        # may be blocked mid-init, so they are cancelled to unblock teardown —
        # but every guard below re-checks on the owning loop (or atomically on
        # this thread for the current-loop branch), so an owner that has since
        # failed and is unwinding in __aexit__ is never cancelled.
        owners = [(loop, task, close_evt, False, None) for _s, loop, task, close_evt in prepared.entries]
        owners += [(loop, task, ent_close, True, ent_ready) for loop, ent_ready, task, ent_close in prepared.inflight]
        try:
            current_running_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_running_loop = None

        # Signal every detached owner first. No waits in this pass.
        for loop, task, close_evt, cancel, ent_ready in owners:
            if loop.is_closed():
                continue
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
            else:
                # Thread-safe signal; _shutdown applies the failure guard on
                # the owning loop in the wait pass below.
                self._signal_close(loop, close_evt)
                if cancel:
                    self._cancel_owner(loop, task, ent_ready)

        # Then await teardown, except on the loop running this thread.
        for loop, task, close_evt, cancel, ent_ready in owners:
            if loop.is_closed() or loop is current_running_loop:
                continue
            try:
                if loop.is_running():
                    # Schedule the shutdown on the owning loop from this thread;
                    # _shutdown applies the failure guard on that loop.
                    future = asyncio.run_coroutine_threadsafe(self._shutdown(close_evt, task, cancel, ready=ent_ready), loop)
                    future.result(timeout=self.SESSION_CLOSE_TIMEOUT)
                else:
                    loop.run_until_complete(self._shutdown(close_evt, task, cancel, ready=ent_ready))
            except Exception:
                logger.debug("Error closing MCP session during sync close", exc_info=True)

    def close_all_sync(self) -> None:
        """Close all sessions on their owning event loops (synchronous).

        Detaches every owner under ``_lock`` and hands it to
        :meth:`close_prepared_owners_sync`, which signals each one before
        awaiting any teardown. Safe to call from any thread without an active
        event loop.
        """
        with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
            inflight = list(self._inflight.values())
            self._inflight.clear()
        self.close_prepared_owners_sync(PreparedRetirement(entries=tuple(entries), inflight=tuple(inflight)))


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

    The retired pool is fenced atomically *before* the replacement is published:
    a stale wrapper holding the old pool must never be able to mint a fresh
    session in the window between the singleton swap and its teardown. Lock
    order stays ``cache._init_condition -> _pool_lock -> pool._lock``.
    """
    global _pool
    with _pool_lock:
        retired = _pool
        if retired is not None:
            retired.retire_all()
        _pool = None
        return retired
