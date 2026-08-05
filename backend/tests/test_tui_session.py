"""Tests for Session thread resolution (id-or-title) and lifecycle."""

from unittest.mock import patch, sentinel

from deerflow.tui.cli import LaunchPlan
from deerflow.tui.session import Session, open_session


class _Client:
    def __init__(self, threads):
        self._threads = threads

    def list_threads(self, limit=10):
        return {"thread_list": self._threads}


def _session(threads):
    return Session(client=_Client(threads))


THREADS = [
    {"thread_id": "thread-aaaa", "title": "Bug triage"},
    {"thread_id": "thread-bbbb", "title": "Write docs"},
]


def test_resolve_ref_matches_id():
    assert _session(THREADS).resolve_ref("thread-bbbb") == "thread-bbbb"


def test_resolve_ref_matches_title():
    assert _session(THREADS).resolve_ref("Bug triage") == "thread-aaaa"


def test_resolve_ref_unknown_falls_back_to_literal_id():
    assert _session(THREADS).resolve_ref("brand-new-id") == "brand-new-id"


def test_resolve_thread_resolves_title_from_plan():
    plan = LaunchPlan(mode="tui", thread_id="Write docs")
    assert _session(THREADS).resolve_thread(plan) == "thread-bbbb"


def test_resolve_thread_continue_returns_most_recent():
    plan = LaunchPlan(mode="tui", continue_recent=True)
    assert _session(THREADS).resolve_thread(plan) == "thread-aaaa"


def test_close_is_a_noop_without_a_loop():
    # Headless sessions have no persistence loop; close() must be safe.
    _session(THREADS).close()


def test_close_stops_the_background_loop():
    from deerflow.tui.persistence import ThreadMetaWriter, _LoopThread

    loop = _LoopThread()
    session = Session(
        client=_Client(THREADS), writer=ThreadMetaWriter(loop, None), _loop=loop
    )
    session.close()
    assert session._loop is None
    session.close()  # idempotent


def test_open_session_enables_subagent_delegation():
    with (
        patch("deerflow.client.DeerFlowClient") as client_cls,
        patch(
            "deerflow.runtime.checkpointer.provider.get_checkpointer",
            return_value=sentinel.checkpointer,
        ),
    ):
        session = open_session(persistence=False)

    client_cls.assert_called_once_with(
        checkpointer=sentinel.checkpointer, subagent_enabled=True
    )
    assert session.client is client_cls.return_value
