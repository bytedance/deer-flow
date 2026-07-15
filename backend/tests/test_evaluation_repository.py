from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.evaluations import EvaluationRepository


async def _repo(tmp_path) -> EvaluationRepository:
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None
    return EvaluationRepository(sf)


@pytest.mark.asyncio
async def test_create_run_is_idempotent_by_owner_and_key(tmp_path):
    repo = await _repo(tmp_path)
    try:
        first = await repo.create_run(
            run_id="eval-run-1",
            owner_id="owner-1",
            idempotency_key="idem-1",
            suite_name="suite",
            suite_digest="sha256:first",
            suite_snapshot={"name": "suite"},
        )
        second = await repo.create_run(
            run_id="eval-run-duplicate",
            owner_id="owner-1",
            idempotency_key="idem-1",
            suite_name="suite",
            suite_digest="sha256:second",
            suite_snapshot={"name": "changed"},
        )

        assert first["id"] == "eval-run-1"
        assert second["id"] == "eval-run-1"
        assert second["suite_digest"] == "sha256:first"
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_create_items_and_attempts_preserve_repeat_and_retry_shape(tmp_path):
    repo = await _repo(tmp_path)
    try:
        await repo.create_run(
            run_id="eval-run-1",
            owner_id="owner-1",
            suite_name="suite",
            suite_digest="sha256:suite",
            suite_snapshot={"name": "suite"},
        )
        item = await repo.create_item(
            item_id="eval-item-1",
            eval_run_id="eval-run-1",
            suite_item_id="case-1",
            variant_id="candidate",
            sample_index=2,
            execution_key="eval-run-1:case-1:candidate:2",
            checks=[{"type": "run_event_exists", "event_type": "run.end"}],
        )
        first_attempt = await repo.create_attempt(
            attempt_id="eval-attempt-1",
            eval_run_id="eval-run-1",
            eval_run_item_id="eval-item-1",
            attempt_index=0,
            metadata={"reason": "initial"},
        )
        retry_attempt = await repo.create_attempt(
            attempt_id="eval-attempt-2",
            eval_run_id="eval-run-1",
            eval_run_item_id="eval-item-1",
            attempt_index=1,
            metadata={"reason": "retry"},
        )

        items = await repo.list_items("eval-run-1")
        attempts = await repo.list_attempts("eval-item-1")

        assert item["sample_index"] == 2
        assert [row["id"] for row in items] == ["eval-item-1"]
        assert items[0]["status"] == "running"
        assert items[0]["attempt_count"] == 2
        assert items[0]["started_at"] is not None
        assert [row["id"] for row in attempts] == ["eval-attempt-1", "eval-attempt-2"]
        assert first_attempt["attempt_index"] == 0
        assert retry_attempt["attempt_index"] == 1
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_claim_renew_and_requeue_stale_eval_runs(tmp_path):
    repo = await _repo(tmp_path)
    try:
        now = datetime(2026, 7, 11, 10, 0, tzinfo=UTC)
        await repo.create_run(
            run_id="eval-run-queued",
            owner_id="owner-1",
            suite_name="suite",
            suite_digest="sha256:suite",
            suite_snapshot={"name": "suite"},
        )

        claimed = await repo.claim_queued_runs(
            now=now,
            lease_owner="worker-1",
            lease_seconds=30,
            limit=10,
        )
        assert [row["id"] for row in claimed] == ["eval-run-queued"]
        assert claimed[0]["status"] == "running"
        assert claimed[0]["lease_owner"] == "worker-1"

        renewed = await repo.renew_lease(
            "eval-run-queued",
            lease_owner="worker-1",
            now=now + timedelta(seconds=10),
            lease_seconds=60,
        )
        assert renewed is True
        assert (
            await repo.renew_lease(
                "eval-run-queued",
                lease_owner="other-worker",
                now=now + timedelta(seconds=20),
                lease_seconds=60,
            )
            is False
        )

        assert await repo.requeue_stale_runs(now=now + timedelta(seconds=30)) == 0
        assert await repo.requeue_stale_runs(now=now + timedelta(seconds=90)) == 1

        row = await repo.get_run("eval-run-queued")
        assert row is not None
        assert row["status"] == "queued"
        assert row["lease_owner"] is None
        assert row["lease_expires_at"] is None
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_requeue_stale_run_closes_incomplete_attempts_for_recovery(tmp_path):
    repo = await _repo(tmp_path)
    try:
        now = datetime(2026, 7, 11, 10, 0, tzinfo=UTC)
        await repo.create_run(
            run_id="eval-run-stale",
            owner_id="owner-1",
            suite_name="suite",
            suite_digest="sha256:suite",
            suite_snapshot={"name": "suite"},
        )
        await repo.create_item(
            item_id="eval-item-stale",
            eval_run_id="eval-run-stale",
            suite_item_id="case-1",
            execution_key="eval-run-stale:case-1:default:0",
        )
        await repo.claim_queued_runs(
            now=now,
            lease_owner="worker-1",
            lease_seconds=30,
            limit=10,
        )
        await repo.create_attempt(
            attempt_id="eval-attempt-stale",
            eval_run_id="eval-run-stale",
            eval_run_item_id="eval-item-stale",
            attempt_index=0,
            status="running",
        )

        assert await repo.requeue_stale_runs(now=now + timedelta(seconds=90)) == 1

        run = await repo.get_run("eval-run-stale")
        items = await repo.list_items("eval-run-stale")
        attempts = await repo.list_attempts("eval-item-stale")

        assert run is not None
        assert run["status"] == "queued"
        assert items[0]["status"] == "queued"
        assert items[0]["attempt_count"] == 1
        assert attempts[0]["status"] == "failed"
        assert attempts[0]["failure_kind"] == "platform_defect"
        assert "stale recovery" in attempts[0]["error"]
        assert attempts[0]["run_event_summary_json"]["recovery"] == "stale_attempt_closed"
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_claiming_stale_running_run_closes_incomplete_attempts(tmp_path):
    repo = await _repo(tmp_path)
    try:
        now = datetime(2026, 7, 11, 10, 0, tzinfo=UTC)
        await repo.create_run(
            run_id="eval-run-stale-claim",
            owner_id="owner-1",
            suite_name="suite",
            suite_digest="sha256:suite",
            suite_snapshot={"name": "suite"},
        )
        await repo.create_item(
            item_id="eval-item-stale-claim",
            eval_run_id="eval-run-stale-claim",
            suite_item_id="case-1",
            execution_key="eval-run-stale-claim:case-1:default:0",
        )
        await repo.claim_queued_runs(now=now, lease_owner="worker-1", lease_seconds=30, limit=10)
        await repo.create_attempt(
            attempt_id="eval-attempt-stale-claim",
            eval_run_id="eval-run-stale-claim",
            eval_run_item_id="eval-item-stale-claim",
            attempt_index=0,
            status="running",
        )

        claimed = await repo.claim_queued_runs(
            now=now + timedelta(seconds=90),
            lease_owner="worker-2",
            lease_seconds=30,
            limit=10,
        )

        attempts = await repo.list_attempts("eval-item-stale-claim")
        assert [row["id"] for row in claimed] == ["eval-run-stale-claim"]
        assert claimed[0]["lease_owner"] == "worker-2"
        assert attempts[0]["status"] == "failed"
        assert attempts[0]["failure_kind"] == "platform_defect"
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_concurrent_claims_do_not_duplicate_eval_run(tmp_path):
    repo = await _repo(tmp_path)
    try:
        now = datetime(2026, 7, 11, 10, 0, tzinfo=UTC)
        await repo.create_run(
            run_id="eval-run-queued",
            owner_id="owner-1",
            suite_name="suite",
            suite_digest="sha256:suite",
            suite_snapshot={"name": "suite"},
        )

        first, second = await asyncio.gather(
            repo.claim_queued_runs(now=now, lease_owner="worker-1", lease_seconds=30, limit=10),
            repo.claim_queued_runs(now=now, lease_owner="worker-2", lease_seconds=30, limit=10),
        )

        claimed_ids = [row["id"] for rows in (first, second) for row in rows]
        assert claimed_ids == ["eval-run-queued"]
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_update_report_writes_summary_and_terminal_status(tmp_path):
    repo = await _repo(tmp_path)
    try:
        finished_at = datetime(2026, 7, 11, 10, 5, tzinfo=UTC)
        await repo.create_run(
            run_id="eval-run-1",
            owner_id="owner-1",
            suite_name="suite",
            suite_digest="sha256:suite",
            suite_snapshot={"name": "suite"},
        )
        updated = await repo.update_report(
            "eval-run-1",
            summary={"pass_rate": 1.0},
            effect_summary={"conclusion_label": "neutral"},
            comparison={"status": "neutral"},
            report_json={"schema_version": "deerflow.evaluation.report.v1"},
            report_markdown="# Report",
            status="completed",
            finished_at=finished_at,
        )

        row = await repo.get_run("eval-run-1")
        assert updated is True
        assert row is not None
        assert row["summary_json"] == {"pass_rate": 1.0}
        assert row["effect_summary_json"] == {"conclusion_label": "neutral"}
        assert row["comparison_json"] == {"status": "neutral"}
        assert row["report_markdown"] == "# Report"
        assert row["status"] == "completed"
    finally:
        await close_engine()
