"""Tests for per-server MCP session binding identity."""

import asyncio
import threading
from unittest.mock import MagicMock, patch

import pytest

from deerflow.mcp.session_pool import (
    MCPSessionPool,
    PreparedRetirement,
    ServerBinding,
    StaleMCPBindingError,
    normalized_connection_fingerprint,
)


def test_same_fingerprint_is_idempotent():
    pool = MCPSessionPool()
    a = pool.bind_server("A", "fp-1")
    assert pool.bind_server("A", "fp-1") == a


def test_server_binding_repr_hides_fingerprint():
    """Binding reprs must not leak resolved connection secrets into logs."""
    binding = ServerBinding("A", 1, "secret-token-value")
    assert "secret-token-value" not in repr(binding)


def test_changed_fingerprint_mints_new_epoch():
    pool = MCPSessionPool()
    a = pool.bind_server("A", "fp-1")
    b = pool.bind_server("A", "fp-2")
    assert b.epoch > a.epoch and b != a


def test_remove_readd_never_reuses_epoch():
    pool = MCPSessionPool()
    a = pool.bind_server("A", "fp-1")
    removed = pool.remove_server("A")
    readded = pool.bind_server("A", "fp-1")
    assert removed.fingerprint is None
    assert readded.epoch > removed.epoch > a.epoch


def test_fingerprint_tracks_operator_cwd_and_env():
    base = {"transport": "stdio", "command": "x", "args": [], "cwd": "/srv/agent", "env": {"TOKEN": "a"}}
    assert normalized_connection_fingerprint(base) != normalized_connection_fingerprint({**base, "cwd": "/srv/agent-2"})
    assert normalized_connection_fingerprint(base) != normalized_connection_fingerprint({**base, "env": {"TOKEN": "b"}})
    # An operator cwd that happens to contain a "workspace" segment, and an
    # operator TMPDIR env, are still part of the base identity: they must keep
    # distinguishing fingerprints rather than being stripped as per-call plumbing.
    assert normalized_connection_fingerprint({**base, "cwd": "/srv/workspace/agent"}) != normalized_connection_fingerprint({**base, "cwd": "/srv/workspace/agent-2"})
    assert normalized_connection_fingerprint({**base, "env": {"TMPDIR": "/a"}}) != normalized_connection_fingerprint({**base, "env": {"TMPDIR": "/b"}})


def test_fingerprint_is_stable_for_same_base_connection():
    base = {"transport": "stdio", "command": "x", "args": [], "cwd": "/srv/agent", "env": {"TOKEN": "a"}}
    assert normalized_connection_fingerprint(base) == normalized_connection_fingerprint(base)
    assert normalized_connection_fingerprint(base) == normalized_connection_fingerprint(dict(base))


def test_retire_all_marks_pool_retired():
    pool = MCPSessionPool()
    pool.retire_all()
    with pytest.raises(StaleMCPBindingError):
        pool.bind_server("A", "fp-1")


# ---------------------------------------------------------------------------
# Selective retirement, commit fence, cancel-safe teardown
# ---------------------------------------------------------------------------

_CONNECTION = {"transport": "stdio", "command": "x", "args": []}


class _GatedInitCm:
    """Fake session CM with a tracked, gated ``initialize`` and tracked exit."""

    def __init__(self, gate: asyncio.Event | None = None) -> None:
        # ``gate is None`` means initialize() completes immediately.
        self.gate = gate
        self.initialize_started = asyncio.Event()
        self.enter_task: asyncio.Task | None = None
        self.exit_task: asyncio.Task | None = None
        self.entered = False
        self.closed = False
        self.session = MagicMock()
        self.session.initialize = self._initialize

    async def __aenter__(self):
        self.entered = True
        self.enter_task = asyncio.current_task()
        return self.session

    async def _initialize(self):
        self.initialize_started.set()
        if self.gate is not None:
            await self.gate.wait()

    async def __aexit__(self, *args):
        self.exit_task = asyncio.current_task()
        self.closed = True
        return False


class _GatedEnterCm:
    """Fake session CM whose ``__aenter__`` blocks before the CM is entered."""

    def __init__(self, gate: asyncio.Event) -> None:
        self.gate = gate
        self.enter_started = asyncio.Event()
        self.entered = False
        self.closed = False
        self.session = MagicMock()
        self.session.initialize = MagicMock()

    async def __aenter__(self):
        self.enter_started.set()
        await self.gate.wait()
        self.entered = True
        return self.session

    async def __aexit__(self, *args):
        self.closed = True
        return False


async def _commit(pool, server_name, scope_key, binding, cm):
    with patch("langchain_mcp_adapters.sessions.create_session", return_value=cm):
        return await pool.get_session(server_name, scope_key, _CONNECTION, binding=binding)


@pytest.mark.asyncio
async def test_reconcile_detaches_only_changed_server():
    """Changing A detaches only A; B's live session survives untouched."""
    pool = MCPSessionPool()
    loop = asyncio.get_running_loop()
    a = pool.bind_server("A", "a1")
    b = pool.bind_server("B", "b1")
    cm_a, cm_b = _GatedInitCm(), _GatedInitCm()

    session_a = await _commit(pool, "A", "u:t", a, cm_a)
    session_b = await _commit(pool, "B", "u:t", b, cm_b)

    prepared = pool.reconcile_bindings({"A": "a2", "B": "b1"}, ())

    assert [s for s, *_ in prepared.entries] == [session_a]
    assert session_b not in [s for s, *_ in prepared.entries]
    assert prepared.inflight == ()

    # B is still registered and its CM has not been exited.
    assert pool._entries[("B", "u:t", loop)][0] is session_b
    assert cm_b.closed is False, "B's __aexit__ must not run when only A changed"

    # Only A's epoch advanced.
    assert pool.active_binding("A").fingerprint == "a2"
    assert pool.active_binding("A").epoch > a.epoch
    assert pool.active_binding("B") == b
    assert pool.active_binding("B").epoch == b.epoch

    # A's detached owner is signalled and exits in its own task.
    _session, _loop, a_task, _close = prepared.entries[0]
    await asyncio.wait_for(a_task, timeout=1)
    assert cm_a.closed is True
    assert cm_a.exit_task is cm_a.enter_task


@pytest.mark.asyncio
async def test_stale_binding_cannot_get_session():
    """An old binding fails fast and creates no session after reconciliation."""
    pool = MCPSessionPool()
    old = pool.bind_server("A", "a1")
    pool.reconcile_bindings({"A": "a2"}, ())

    with patch("langchain_mcp_adapters.sessions.create_session") as create_session:
        with pytest.raises(StaleMCPBindingError):
            await pool.get_session("A", "u:t", _CONNECTION, binding=old)

    create_session.assert_not_called()
    assert not [k for k in pool._entries if k[0] == "A"]
    assert not [k for k in pool._inflight if k[0] == "A"]


@pytest.mark.asyncio
async def test_blocked_initialize_never_commits_after_reconcile():
    """A creation blocked in initialize() must not promote after A is reconciled."""
    pool = MCPSessionPool()
    old = pool.bind_server("A", "a1")
    gate = asyncio.Event()
    cm = _GatedInitCm(gate)

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=cm):
        call = asyncio.create_task(pool.get_session("A", "u:t", _CONNECTION, binding=old))
        await asyncio.wait_for(cm.initialize_started.wait(), timeout=1)
        assert ("A", "u:t") in {k[:2] for k in pool._inflight}

        # Release the block, then reconcile before the owner resumes: the owner
        # reaches the commit fence with a superseded binding.
        gate.set()
        prepared = pool.reconcile_bindings({"A": "a2"}, ())
        assert len(prepared.inflight) == 1
        assert prepared.entries == ()

        with pytest.raises(StaleMCPBindingError):
            await call

    assert not [k for k in pool._entries if k[0] == "A"], "stale creation must not be promoted"
    assert not [k for k in pool._inflight if k[0] == "A"]
    assert cm.closed is True, "the stale owner must still run __aexit__"
    assert cm.exit_task is cm.enter_task, "__aexit__ must run in the creating task"


@pytest.mark.asyncio
async def test_retired_pool_rejects_get_session():
    """A retired pool refuses sessions even for a previously valid binding."""
    pool = MCPSessionPool()
    binding = pool.bind_server("A", "a1")
    pool.retire_all()

    with pytest.raises(StaleMCPBindingError):
        await pool.get_session("A", "u:t", _CONNECTION, binding=binding)
    # The back-compat (binding-less) path is fenced too.
    with pytest.raises(StaleMCPBindingError):
        await pool.get_session("A", "u:t", _CONNECTION)


@pytest.mark.asyncio
async def test_unchanged_fingerprint_reconcile_is_noop():
    """An unchanged fingerprint leaves the binding, entry, and CM untouched."""
    pool = MCPSessionPool()
    loop = asyncio.get_running_loop()
    a = pool.bind_server("A", "a1")
    cm = _GatedInitCm()
    session = await _commit(pool, "A", "u:t", a, cm)

    prepared = pool.reconcile_bindings({"A": "a1"}, ())

    assert prepared.entries == ()
    assert prepared.inflight == ()
    assert pool.active_binding("A") is a
    assert pool._entries[("A", "u:t", loop)][0] is session
    assert cm.closed is False


@pytest.mark.asyncio
async def test_force_rebind_advances_epoch_for_an_unchanged_fingerprint():
    """A forced rebind mints a new epoch and detaches only the named server.

    The shared lifecycle generation can advance while the normalized base
    connection fingerprint is unchanged (delete + identical re-add). The pool
    must then replace A's epoch and detach its live session, while B -- whose
    generation did not advance -- stays byte-identical.
    """
    pool = MCPSessionPool()
    loop = asyncio.get_running_loop()
    a = pool.bind_server("A", "a1")
    b = pool.bind_server("B", "b1")
    cm_a, cm_b = _GatedInitCm(), _GatedInitCm()

    session_a = await _commit(pool, "A", "u:t", a, cm_a)
    session_b = await _commit(pool, "B", "u:t", b, cm_b)

    prepared = pool.reconcile_bindings({"A": "a1", "B": "b1"}, (), force_rebind={"A"})

    # A is detached and forced to a new epoch even though its fingerprint matches.
    assert [s for s, *_ in prepared.entries] == [session_a]
    assert session_b not in [s for s, *_ in prepared.entries]
    assert prepared.inflight == ()
    assert pool.active_binding("A").fingerprint == "a1"
    assert pool.active_binding("A").epoch > a.epoch

    # B is byte-identical: same binding, same entry, CM not exited.
    assert pool.active_binding("B") is b
    assert pool.active_binding("B").epoch == b.epoch
    assert pool._entries[("B", "u:t", loop)][0] is session_b
    assert cm_b.closed is False

    _session, _loop, a_task, _close = prepared.entries[0]
    await asyncio.wait_for(a_task, timeout=1)
    assert cm_a.closed is True


@pytest.mark.asyncio
async def test_force_rebind_keeps_a_repeated_identical_reconcile_idempotent():
    """Forcing an unchanged fingerprint once must not re-epoch it forever."""
    pool = MCPSessionPool()
    pool.bind_server("A", "a1")

    pool.reconcile_bindings({"A": "a1"}, (), force_rebind={"A"})
    reforced = pool.active_binding("A")

    prepared = pool.reconcile_bindings({"A": "a1"}, (), force_rebind=frozenset())

    assert prepared.entries == ()
    assert prepared.inflight == ()
    assert pool.active_binding("A") is reforced


@pytest.mark.asyncio
async def test_cancelling_close_prepared_owners_sync_keeps_every_owner_signalled():
    """Cancelling the sync teardown caller must not strand a detached owner:
    every prepared owner is signalled before the first teardown wait."""
    pool = MCPSessionPool()
    loop = asyncio.get_running_loop()
    a_close, b_close = asyncio.Event(), asyncio.Event()
    a_release, a_done = asyncio.Event(), asyncio.Event()

    async def a_owner() -> None:
        await a_close.wait()
        await a_release.wait()  # slow __aexit__ stand-in
        a_done.set()

    async def b_owner() -> None:
        await b_close.wait()

    a_task = asyncio.create_task(a_owner())
    b_task = asyncio.create_task(b_owner())
    prepared = PreparedRetirement(
        entries=(
            (MagicMock(), loop, a_task, a_close),
            (MagicMock(), loop, b_task, b_close),
        )
    )

    thread_done = threading.Event()

    def _run() -> None:
        pool.close_prepared_owners_sync(prepared)
        thread_done.set()

    closer = asyncio.create_task(asyncio.to_thread(_run))
    for _ in range(200):
        if a_close.is_set() and b_close.is_set():
            break
        await asyncio.sleep(0.01)
    assert a_close.is_set() and b_close.is_set(), "every prepared owner must be signalled before any teardown wait"

    closer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closer

    a_release.set()
    for _ in range(200):
        if thread_done.is_set():
            break
        await asyncio.sleep(0.01)
    assert a_done.is_set() and b_task.done()
    assert thread_done.is_set(), "the sync teardown must finish once the owner is released"


@pytest.mark.asyncio
async def test_retire_all_while_initializing_fails_creation_without_hanging():
    """A whole-pool retirement fences an in-flight creation too.

    ``retire_all`` does not detach or signal in-flight owners, so the commit
    fence must unwind the abandoned owner itself rather than park it on a close
    event nobody will ever set (which would strand the waiting caller).
    """
    pool = MCPSessionPool()
    binding = pool.bind_server("A", "a1")
    gate = asyncio.Event()
    cm = _GatedInitCm(gate)

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=cm):
        call = asyncio.create_task(pool.get_session("A", "u:t", _CONNECTION, binding=binding))
        await asyncio.wait_for(cm.initialize_started.wait(), timeout=1)

        pool.retire_all()
        gate.set()

        with pytest.raises(StaleMCPBindingError):
            await asyncio.wait_for(call, timeout=2)

    assert not [k for k in pool._entries if k[0] == "A"]
    assert not [k for k in pool._inflight if k[0] == "A"]
    assert cm.closed is True
    assert cm.exit_task is cm.enter_task


@pytest.mark.asyncio
async def test_remove_server_rejects_retired_pool():
    """remove_server is fenced by the same retired-pool check as bind_server."""
    pool = MCPSessionPool()
    pool.retire_all()
    with pytest.raises(StaleMCPBindingError):
        pool.remove_server("A")


# ---------------------------------------------------------------------------
# Review fixes: cancellation fence, compat hardening, capture, idempotent removal
# ---------------------------------------------------------------------------

_OLD_CONNECTION = {"transport": "stdio", "command": "old", "args": []}
_NEW_CONNECTION = {"transport": "stdio", "command": "new", "args": []}


@pytest.mark.asyncio
async def test_reconcile_while_initializing_fails_creator_and_joiner_as_stale():
    """reconcile cancels the in-flight owner; the fence must still win.

    The owner is parked inside initialize() when reconcile cancels it, so the
    cancellation surfaces through _run_session's outer handler. That handler
    must re-check the fence and publish StaleMCPBindingError — for the creator
    AND for a joiner sharing the same creation — rather than CancelledError.
    """
    pool = MCPSessionPool()
    old = pool.bind_server("A", "a1")
    gate = asyncio.Event()
    cm = _GatedInitCm(gate)

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=cm):
        creator = asyncio.create_task(pool.get_session("A", "u:t", _CONNECTION, binding=old))
        await asyncio.wait_for(cm.initialize_started.wait(), timeout=1)

        joiner = asyncio.create_task(pool.get_session("A", "u:t", _CONNECTION, binding=old))
        await asyncio.sleep(0.05)  # let the joiner park on the in-flight future
        assert ("A", "u:t") in {k[:2] for k in pool._inflight}

        prepared = pool.reconcile_bindings({"A": "a2"}, ())
        assert len(prepared.inflight) == 1
        gate.set()

        with pytest.raises(StaleMCPBindingError):
            await asyncio.wait_for(creator, timeout=2)
        with pytest.raises(StaleMCPBindingError):
            await asyncio.wait_for(joiner, timeout=2)

    assert not [k for k in pool._entries if k[0] == "A"]
    assert not [k for k in pool._inflight if k[0] == "A"]
    assert cm.closed is True, "the stale owner must still run __aexit__"
    assert cm.exit_task is cm.enter_task


@pytest.mark.asyncio
async def test_reconcile_while_entering_fails_creator_and_joiner_as_stale():
    """A reconcile that cancels a creation parked in ``__aenter__`` is stale.

    The CM never entered, so no ``__aexit__`` is required; the owner must still
    publish ``StaleMCPBindingError`` rather than the raw CancelledError for both
    the creator and a joiner sharing the creation.
    """
    pool = MCPSessionPool()
    old = pool.bind_server("A", "a1")
    gate = asyncio.Event()
    cm = _GatedEnterCm(gate)

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=cm):
        creator = asyncio.create_task(pool.get_session("A", "u:t", _CONNECTION, binding=old))
        await asyncio.wait_for(cm.enter_started.wait(), timeout=1)

        joiner = asyncio.create_task(pool.get_session("A", "u:t", _CONNECTION, binding=old))
        await asyncio.sleep(0.05)  # let the joiner park on the in-flight future
        assert ("A", "u:t") in {k[:2] for k in pool._inflight}

        prepared = pool.reconcile_bindings({"A": "a2"}, ())
        assert len(prepared.inflight) == 1

        with pytest.raises(StaleMCPBindingError):
            await asyncio.wait_for(creator, timeout=2)
        with pytest.raises(StaleMCPBindingError):
            await asyncio.wait_for(joiner, timeout=2)

    gate.set()
    assert cm.entered is False, "the cancelled __aenter__ must not complete into an entered CM"
    assert cm.closed is False, "a CM that never entered must not require __aexit__"
    assert not [k for k in pool._entries if k[0] == "A"]
    assert not [k for k in pool._inflight if k[0] == "A"]


@pytest.mark.asyncio
async def test_close_all_while_initializing_still_reports_cancelled():
    """A plain close (no binding change) keeps reporting CancelledError."""
    pool = MCPSessionPool()
    binding = pool.bind_server("A", "a1")
    gate = asyncio.Event()
    cm = _GatedInitCm(gate)

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=cm):
        call = asyncio.create_task(pool.get_session("A", "u:t", _CONNECTION, binding=binding))
        await asyncio.wait_for(cm.initialize_started.wait(), timeout=1)

        await pool.close_all()
        gate.set()

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(call, timeout=2)

    assert not pool._entries
    assert not pool._inflight
    assert cm.closed is True


@pytest.mark.asyncio
async def test_bindingless_old_connection_after_epoch_change_raises_and_creates_nothing():
    """A stale connection cannot slip in through the binding-less compat path."""
    pool = MCPSessionPool()
    cm = _GatedInitCm()
    with patch("langchain_mcp_adapters.sessions.create_session", return_value=cm):
        await pool.get_session("A", "u:t", _OLD_CONNECTION)

    pool.reconcile_bindings({"A": normalized_connection_fingerprint(_NEW_CONNECTION)}, ())

    with patch("langchain_mcp_adapters.sessions.create_session") as create_session:
        with pytest.raises(StaleMCPBindingError):
            await pool.get_session("A", "u:t", _OLD_CONNECTION)

    create_session.assert_not_called()
    assert not [k for k in pool._entries if k[0] == "A"]
    assert not [k for k in pool._inflight if k[0] == "A"]


@pytest.mark.asyncio
async def test_bindingless_connection_against_removal_tombstone_raises():
    """A binding-less caller must not resurrect a removed server."""
    pool = MCPSessionPool()
    pool.remove_server("A")

    with patch("langchain_mcp_adapters.sessions.create_session") as create_session:
        with pytest.raises(StaleMCPBindingError):
            await pool.get_session("A", "u:t", _CONNECTION)

    create_session.assert_not_called()
    assert not [k for k in pool._entries if k[0] == "A"]


@pytest.mark.asyncio
async def test_bindingless_readd_same_fingerprint_is_fenced():
    """The binding-less compatibility path must not survive an ABA cycle."""
    pool = MCPSessionPool()
    fingerprint = normalized_connection_fingerprint(_CONNECTION)
    pool.bind_server("A", fingerprint)
    pool.remove_server("A")
    readded = pool.bind_server("A", fingerprint)

    with patch("langchain_mcp_adapters.sessions.create_session") as create_session:
        with pytest.raises(StaleMCPBindingError):
            await pool.get_session("A", "u:t", _CONNECTION)

    create_session.assert_not_called()
    assert not [k for k in pool._entries if k[0] == "A"]
    assert not [k for k in pool._inflight if k[0] == "A"]

    # An explicit current binding is still the supported production path.
    cm = _GatedInitCm()
    with patch("langchain_mcp_adapters.sessions.create_session", return_value=cm):
        session = await pool.get_session("A", "u:t", _CONNECTION, binding=readded)

    assert pool._entries[("A", "u:t", asyncio.get_running_loop())][0] is session


@pytest.mark.asyncio
async def test_bindingless_first_seen_still_installs_binding():
    """The first-seen compat path still installs a binding (no behaviour change)."""
    pool = MCPSessionPool()
    cm = _GatedInitCm()
    with patch("langchain_mcp_adapters.sessions.create_session", return_value=cm):
        session = await pool.get_session("A", "u:t", _CONNECTION)

    binding = pool.active_binding("A")
    assert binding is not None
    assert binding.fingerprint == normalized_connection_fingerprint(_CONNECTION)
    assert pool._entries[("A", "u:t", asyncio.get_running_loop())][0] is session


def test_capture_binding_returns_active_binding():
    pool = MCPSessionPool()
    a = pool.bind_server("A", "a1")
    assert pool.capture_binding("A") == a
    assert isinstance(pool.capture_binding("A"), ServerBinding)


def test_capture_binding_rejects_unknown_server():
    pool = MCPSessionPool()
    with pytest.raises(StaleMCPBindingError):
        pool.capture_binding("A")


def test_capture_binding_rejects_tombstone():
    pool = MCPSessionPool()
    pool.remove_server("A")
    with pytest.raises(StaleMCPBindingError):
        pool.capture_binding("A")


def test_capture_binding_rejects_retired_pool():
    pool = MCPSessionPool()
    pool.bind_server("A", "a1")
    pool.retire_all()
    with pytest.raises(StaleMCPBindingError):
        pool.capture_binding("A")


def test_repeated_removal_does_not_mint_new_epochs():
    """Reconciling the same removal twice must be idempotent."""
    pool = MCPSessionPool()
    a = pool.bind_server("A", "a1")

    first = pool.reconcile_bindings({}, {"A"})
    after_first = pool.active_binding("A")
    second = pool.reconcile_bindings({}, {"A"})
    after_second = pool.active_binding("A")

    assert after_first.fingerprint is None
    assert after_first.epoch == a.epoch + 1
    assert after_second is after_first, "a second identical removal must not advance the epoch"
    assert first.entries == () and first.inflight == ()
    assert second.entries == () and second.inflight == ()


# ---------------------------------------------------------------------------
# Single-lock ensure_binding closes the read/install race
# ---------------------------------------------------------------------------


def test_ensure_binding_installs_first_seen():
    """A name the pool has never seen is seeded from the discovery fingerprint."""
    pool = MCPSessionPool()
    binding = pool.ensure_binding("A", "fp-1")
    assert binding.fingerprint == "fp-1"
    assert pool.active_binding("A") is binding


def test_ensure_binding_same_fingerprint_is_idempotent():
    """Re-resolving an unchanged server must not advance its epoch."""
    pool = MCPSessionPool()
    first = pool.ensure_binding("A", "fp-1")
    second = pool.ensure_binding("A", "fp-1")
    assert second is first


def test_ensure_binding_rejects_different_fingerprint_without_overwrite():
    """A stale discovery fingerprint must never overwrite the reconciled one."""
    pool = MCPSessionPool()
    installed = pool.ensure_binding("A", "fp-1")
    with pytest.raises(StaleMCPBindingError):
        pool.ensure_binding("A", "fp-2")
    assert pool.active_binding("A") is installed
    assert pool.active_binding("A").fingerprint == "fp-1"
    assert pool.active_binding("A").epoch == installed.epoch


def test_ensure_binding_rejects_tombstone():
    """A removal tombstone must not be resurrected by a discovery install."""
    pool = MCPSessionPool()
    tombstone = pool.remove_server("A")
    with pytest.raises(StaleMCPBindingError):
        pool.ensure_binding("A", "fp-1")
    assert pool.active_binding("A") is tombstone


def test_ensure_binding_rejects_retired_pool():
    pool = MCPSessionPool()
    pool.retire_all()
    with pytest.raises(StaleMCPBindingError):
        pool.ensure_binding("A", "fp-1")


def test_ensure_binding_cannot_overwrite_a_reconciled_binding():
    """A reconciled binding must not be overwritten by a stale discovery install.

    This pins the OBSERVABLE outcome: once a reconciliation has committed a
    newer epoch, a discovery still holding the superseded fingerprint is
    rejected and the reconciled binding object is left unchanged. The
    single-lock atomicity that makes the interleaving impossible is established
    by the ``ensure_binding`` implementation itself, not by this test.
    """
    pool = MCPSessionPool()

    # Discovery's first read: no binding exists yet.
    assert pool.active_binding("A") is None

    # A reconciliation commits a newer epoch before discovery installs its own.
    prepared = pool.reconcile_bindings({"A": "reconciled-fp"}, ())
    assert prepared.entries == () and prepared.inflight == ()
    reconciled = pool.active_binding("A")
    assert reconciled.fingerprint == "reconciled-fp"

    # The stale discovery install must now be rejected, not mint a new epoch.
    with pytest.raises(StaleMCPBindingError):
        pool.ensure_binding("A", "stale-discovery-fp")

    assert pool.active_binding("A") is reconciled
    assert pool.active_binding("A").fingerprint == "reconciled-fp"
