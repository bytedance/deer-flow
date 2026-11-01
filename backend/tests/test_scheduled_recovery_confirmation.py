"""Unconfirmed scheduled recovery publication must remain observable after commit."""

import logging

import pytest
from test_scheduled_recovery_fencing import prepare_recovery, reconcile
from test_scheduled_recovery_fencing import recovery_db as recovery_db

from deerflow.runtime.events import terminal


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "recovery_path", "repository_logger"),
    [
        ("once", "reconcile_stuck_once_tasks", "deerflow.persistence.scheduled_tasks.sql"),
        ("active", "reconcile_active_runs", "deerflow.persistence.scheduled_task_runs.sql"),
    ],
)
@pytest.mark.parametrize(
    ("failure", "expected_confirmation"),
    [("UNKNOWN", "UNKNOWN"), ("CONFLICT", "CONFLICT"), ("exception", "UNKNOWN")],
)
async def test_unconfirmed_recovery_warns_without_undoing_or_repeating_takeover(recovery_db, path, recovery_path, repository_logger, failure, expected_confirmation, monkeypatch, caplog):
    db = recovery_db
    now, before = await prepare_recovery(db, path)
    committed_at_confirmation = []
    targets = []
    publish = db.publisher.publish

    async def confirm_with_failure(store, **kwargs):
        assert store is db.events
        assert (kwargs["thread_id"], kwargs["run_id"], kwargs["user_id"], kwargs["status"]) == ("thread", "run", "alice", "error")
        assert kwargs["recovered"] is True
        assert kwargs["authorized"]()
        # Read through a separate real session at the confirmation boundary.
        # An uncommitted takeover must not satisfy these assertions.
        row = await db.runs.get("run", user_id="alice")
        assert row["status"] == "error"
        assert row["producer_state"] == "revoked"
        assert row["producer_epoch"] != before["producer_epoch"]
        assert row["run_incarnation"] == before["run_incarnation"]
        assert row["evidence_retention_revision"] == 7
        committed_at_confirmation.append(row)
        if failure == "exception":
            raise RuntimeError("injected confirmation failure")
        return terminal.TerminalEventConfirmation(failure)

    async def observe_publish(target):
        targets.append(target)
        return await publish(target)

    monkeypatch.setattr(terminal, "confirm_terminal_event", confirm_with_failure)
    monkeypatch.setattr(db.publisher, "publish", observe_publish)
    caplog.set_level(logging.WARNING)

    assert await reconcile(db, path, now) == 1
    assert len(committed_at_confirmation) == 1
    committed = await db.runs.get("run", user_id="alice")
    assert committed == committed_at_confirmation[0]
    assert committed["error"] == "owner expired"
    assert committed["evidence_seal_state"] == "partial"

    # Neither a later scan nor reuse of the one-shot target can publish again.
    assert await reconcile(db, path, now) == 0
    assert await db.runs.get("run", user_id="alice") == committed
    assert len(targets) == 1
    with pytest.raises(terminal.RecoveryTerminalTargetConsumed):
        await publish(targets[0])
    assert len(committed_at_confirmation) == 1
    events = await db.events.list_events("thread", "run", user_id="alice")
    assert [event["event_type"] for event in events] == ["run.delivery"]

    warnings = [record for record in caplog.records if record.name == repository_logger and record.levelno == logging.WARNING]
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning.run_id == "run"
    assert warning.recovery_path == recovery_path
    assert warning.confirmation == expected_confirmation
