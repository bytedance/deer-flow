from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.evaluation import EvalDispatcher, EvaluationService
from app.gateway.routers.evals import EvalCreateRequest, _require_eval_operator, _test_request, create_eval_run
from deerflow.config.database_config import DatabaseConfig
from deerflow.evaluation.results import FailureKind
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.evaluations import EvaluationRepository
from deerflow.persistence.evaluations.model import EvalRunItemRow


def _suite() -> dict:
    return {
        "name": "gateway_eval",
        "version": 1,
        "variants": [{"id": "baseline"}, {"id": "candidate"}],
        "items": [
            {
                "id": "trace-case",
                "type": "task",
                "metric_tags": ["task_success"],
                "input": {"prompt": "produce an answer"},
                "checks": [
                    {"type": "run_event_exists", "event_type": "run.start"},
                    {"type": "run_event_exists", "event_type": "llm.ai.response"},
                    {"type": "run_event_exists", "event_type": "run.end"},
                ],
            }
        ],
    }


def _single_trace_suite() -> dict:
    return {
        "name": "gateway_single_trace_eval",
        "version": 1,
        "variants": [{"id": "default"}],
        "items": [
            {
                "id": "trace-case",
                "type": "task",
                "metric_tags": ["task_success"],
                "input": {"prompt": "produce an answer"},
                "checks": [
                    {"type": "run_event_exists", "event_type": "run.start"},
                    {"type": "run_event_exists", "event_type": "llm.ai.response"},
                    {"type": "run_event_exists", "event_type": "run.end"},
                ],
            }
        ],
    }


def _seeded_suite() -> dict:
    return {
        "name": "gateway_seed_eval",
        "version": 1,
        "variants": [{"id": "default"}],
        "items": [
            {
                "id": "seeded-case",
                "type": "task",
                "input": {"prompt": "use the seeded fixture"},
                "workspace_seed": {"provider": "local_fixture", "path": "fixtures"},
                "checks": [
                    {"type": "workspace_file_exists", "path": "fixture.txt"},
                    {"type": "workspace_file_contains", "path": "fixture.txt", "contains": "seeded evidence"},
                ],
            }
        ],
    }


def _mixed_failure_suite() -> dict:
    return {
        "name": "gateway_mixed_failure_eval",
        "version": 1,
        "variants": [{"id": "default"}],
        "items": [
            {
                "id": "mixed-failure-case",
                "type": "task",
                "input": {"prompt": "produce a file"},
                "checks": [
                    {"type": "workspace_file_exists", "path": "resolution.json"},
                    {"type": "run_event_exists", "event_type": "run.start"},
                    {"type": "run_event_exists", "event_type": "llm.ai.response"},
                    {"type": "run_event_exists", "event_type": "run.end"},
                ],
            }
        ],
    }


async def _repo(tmp_path) -> EvaluationRepository:
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None
    return EvaluationRepository(sf)


@pytest.mark.asyncio
async def test_evaluation_service_creates_items_and_executes_with_internal_launcher(tmp_path):
    repo = await _repo(tmp_path)
    launches = []

    async def fake_launch(**kwargs):
        launches.append(kwargs)
        return {
            "thread_id": kwargs["thread_id"],
            "run_id": "run-1",
            "run_events": [
                {"event_type": "run.start"},
                {"event_type": "llm.ai.response"},
                {"event_type": "run.end"},
            ],
        }

    try:
        service = EvaluationService(repository=repo, launch_run=fake_launch, workspaces_root=tmp_path / "workspaces")
        created = await service.create_eval_run(
            owner_id="owner-1",
            suite_data=_suite(),
            idempotency_key="idem-1",
        )
        assert created["total_items"] == 2

        completed = await service.run_eval(created["id"])
        items = await repo.list_items(created["id"])
        attempts = []
        for item in items:
            attempts.extend(await repo.list_attempts(item["id"]))

        assert completed["status"] == "completed"
        assert completed["environment_fingerprint_json"]["source"] == "gateway-eval-p0"
        assert len(launches) == 2
        assert all(call["metadata"]["non_interactive"] is True for call in launches)
        assert {call["run_config"]["recursion_limit"] for call in launches} == {300}
        assert {item["status"] for item in items} == {"passed"}
        assert {attempt["status"] for attempt in attempts} == {"success"}
        assert completed["report_json"]["summary"]["pass_rate"] == 1.0
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_evaluation_service_materializes_workspace_seed_before_checks(tmp_path):
    repo = await _repo(tmp_path)
    suite_dir = tmp_path / "suite"
    fixture_dir = suite_dir / "fixtures"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "fixture.txt").write_text("seeded evidence\n", encoding="utf-8")
    suite_path = suite_dir / "suite.yaml"
    suite_path.write_text("name: gateway_seed_eval\n", encoding="utf-8")

    try:
        service = EvaluationService(repository=repo, workspaces_root=tmp_path / "workspaces")
        created = await service.create_eval_run(
            owner_id="owner-1",
            suite_data=_seeded_suite(),
            idempotency_key=None,
            config={"suite_path": str(suite_path)},
        )

        completed = await service.run_eval(created["id"])
        items = await repo.list_items(created["id"])
        attempts = await repo.list_attempts(items[0]["id"])

        assert completed["status"] == "completed"
        assert items[0]["status"] == "passed"
        workspace_path = Path(attempts[0]["workspace_path"])
        assert (workspace_path / "fixture.txt").read_text(encoding="utf-8") == "seeded evidence\n"
        assert attempts[0]["check_results_json"][0]["passed"] is True
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_evaluation_service_passes_materialized_seed_workspace_to_internal_run(tmp_path):
    repo = await _repo(tmp_path)
    suite_dir = tmp_path / "suite"
    fixture_dir = suite_dir / "fixtures"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "fixture.txt").write_text("seeded evidence\n", encoding="utf-8")
    suite_path = suite_dir / "suite.yaml"
    suite_path.write_text("name: gateway_seed_eval\n", encoding="utf-8")
    launches = []

    async def fake_launch(**kwargs):
        launches.append(kwargs)
        workspace_path = Path(kwargs["eval_workspace_path"])
        assert (workspace_path / "fixture.txt").read_text(encoding="utf-8") == "seeded evidence\n"
        return {"thread_id": kwargs["thread_id"], "run_id": "run-1"}

    try:
        service = EvaluationService(
            repository=repo,
            launch_run=fake_launch,
            workspaces_root=tmp_path / "workspaces",
        )
        created = await service.create_eval_run(
            owner_id="owner-1",
            suite_data=_seeded_suite(),
            idempotency_key=None,
            config={"suite_path": str(suite_path)},
        )

        await service.run_eval(created["id"])

        assert len(launches) == 1
        assert launches[0]["eval_workspace_path"].endswith("/workspace")
        assert launches[0]["metadata"]["non_interactive"] is True
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_evaluation_service_reads_run_events_from_provider_when_launcher_returns_ids_only(tmp_path):
    repo = await _repo(tmp_path)

    async def fake_launch(**kwargs):
        return {"thread_id": kwargs["thread_id"], "run_id": "run-from-store"}

    async def fake_run_events_provider(*, thread_id, run_id):
        assert run_id == "run-from-store"
        return [
            {"thread_id": thread_id, "run_id": run_id, "event_type": "run.start"},
            {"thread_id": thread_id, "run_id": run_id, "event_type": "llm.ai.response"},
            {"thread_id": thread_id, "run_id": run_id, "event_type": "run.end"},
        ]

    try:
        service = EvaluationService(
            repository=repo,
            launch_run=fake_launch,
            run_events_provider=fake_run_events_provider,
            workspaces_root=tmp_path / "workspaces",
        )
        created = await service.create_eval_run(owner_id="owner-1", suite_data=_suite(), idempotency_key=None)

        completed = await service.run_eval(created["id"])
        items = await repo.list_items(created["id"])
        attempts = []
        for item in items:
            attempts.extend(await repo.list_attempts(item["id"]))

        assert completed["status"] == "completed"
        assert {item["status"] for item in items} == {"passed"}
        assert {attempt["run_event_summary_json"]["event_count"] for attempt in attempts} == {3}
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_evaluation_service_recovery_uses_next_attempt_index_when_item_count_is_stale(tmp_path):
    repo = await _repo(tmp_path)
    launches = []

    async def fake_launch(**kwargs):
        launches.append(kwargs)
        return {
            "thread_id": kwargs["thread_id"],
            "run_id": "run-after-recovery",
            "run_events": [
                {"event_type": "run.start"},
                {"event_type": "llm.ai.response"},
                {"event_type": "run.end"},
            ],
        }

    try:
        service = EvaluationService(repository=repo, launch_run=fake_launch, workspaces_root=tmp_path / "workspaces")
        created = await service.create_eval_run(owner_id="owner-1", suite_data=_single_trace_suite(), idempotency_key=None)
        item = (await repo.list_items(created["id"]))[0]
        await repo.create_attempt(
            attempt_id="eval-attempt-existing",
            eval_run_id=created["id"],
            eval_run_item_id=item["id"],
            attempt_index=0,
            status="running",
            metadata={"reason": "pre-recovery running attempt"},
        )

        sf = get_session_factory()
        assert sf is not None
        async with sf() as session:
            item_row = await session.get(EvalRunItemRow, item["id"])
            assert item_row is not None
            item_row.status = "queued"
            item_row.attempt_count = 0
            item_row.thread_id = None
            item_row.run_id = None
            item_row.workspace_path = None
            await session.commit()

        completed = await service.run_eval(created["id"])
        items = await repo.list_items(created["id"])
        attempts = await repo.list_attempts(item["id"])

        assert completed["status"] == "completed"
        assert len(launches) == 1
        assert [attempt["attempt_index"] for attempt in attempts] == [0, 1]
        assert attempts[0]["status"] == "failed"
        assert attempts[0]["failure_kind"] == FailureKind.PLATFORM_DEFECT.value
        assert "incomplete attempt" in attempts[0]["error"]
        assert attempts[1]["status"] == "success"
        assert items[0]["status"] == "passed"
        assert items[0]["attempt_count"] == 2
        assert items[0]["selected_attempt_index"] == 1
        assert completed["report_json"]["items"][0]["attempt_index"] == 1
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_evaluation_service_classifies_missing_run_event_evidence_as_platform_gap(tmp_path):
    repo = await _repo(tmp_path)

    async def fake_launch(**kwargs):
        return {"thread_id": kwargs["thread_id"], "run_id": "run-without-events"}

    try:
        service = EvaluationService(repository=repo, launch_run=fake_launch, workspaces_root=tmp_path / "workspaces")
        created = await service.create_eval_run(owner_id="owner-1", suite_data=_suite(), idempotency_key=None)

        completed = await service.run_eval(created["id"])
        items = await repo.list_items(created["id"])
        attempts = []
        for item in items:
            attempts.extend(await repo.list_attempts(item["id"]))

        assert completed["status"] == "failed"
        assert {attempt["failure_kind"] for attempt in attempts} == {"platform_evidence_missing"}
        assert all("run_events evidence missing" in attempt["error"] for attempt in attempts)
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_evaluation_service_classifies_incomplete_non_empty_run_events_as_trace_gate_failure(tmp_path):
    repo = await _repo(tmp_path)

    async def fake_launch(**kwargs):
        return {
            "thread_id": kwargs["thread_id"],
            "run_id": "run-with-partial-events",
            "run_events": [{"event_type": "run.start"}],
        }

    try:
        service = EvaluationService(repository=repo, launch_run=fake_launch, workspaces_root=tmp_path / "workspaces")
        created = await service.create_eval_run(owner_id="owner-1", suite_data=_suite(), idempotency_key=None)

        completed = await service.run_eval(created["id"])
        items = await repo.list_items(created["id"])
        attempts = []
        for item in items:
            attempts.extend(await repo.list_attempts(item["id"]))

        assert completed["status"] == "failed"
        assert {attempt["failure_kind"] for attempt in attempts} == {FailureKind.TRACE_GATE.value}
        assert {attempt["run_event_summary_json"]["event_count"] for attempt in attempts} == {1}
        assert {item["failure_kind"] for item in completed["report_json"]["items"]} == {FailureKind.TRACE_GATE.value}
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_evaluation_service_prioritizes_llm_error_over_follow_on_check_failures(tmp_path):
    repo = await _repo(tmp_path)

    async def fake_launch(**kwargs):
        return {
            "thread_id": kwargs["thread_id"],
            "run_id": "run-auth-fails",
            "run_events": [
                {"event_type": "run.start"},
                {"event_type": "llm.error", "content": "Error code: 401 - invalid api key"},
                {"event_type": "run.end"},
            ],
        }

    try:
        service = EvaluationService(repository=repo, launch_run=fake_launch, workspaces_root=tmp_path / "workspaces")
        created = await service.create_eval_run(owner_id="owner-1", suite_data=_mixed_failure_suite(), idempotency_key=None)

        completed = await service.run_eval(created["id"])
        items = await repo.list_items(created["id"])
        attempts = []
        for item in items:
            attempts.extend(await repo.list_attempts(item["id"]))

        assert completed["status"] == "failed"
        assert {attempt["failure_kind"] for attempt in attempts} == {FailureKind.EXTERNAL_BLOCKED.value}
        assert all("llm.error event present" in attempt["error"] for attempt in attempts)
        assert {item["failure_kind"] for item in completed["report_json"]["items"]} == {FailureKind.EXTERNAL_BLOCKED.value}
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_evaluation_service_records_external_blocked_launcher_failures(tmp_path):
    repo = await _repo(tmp_path)

    async def fake_launch(**kwargs):
        raise RuntimeError("missing credential for external service")

    try:
        service = EvaluationService(repository=repo, launch_run=fake_launch, workspaces_root=tmp_path / "workspaces")
        created = await service.create_eval_run(owner_id="owner-1", suite_data=_suite(), idempotency_key=None)

        completed = await service.run_eval(created["id"])
        items = await repo.list_items(created["id"])
        attempts = []
        for item in items:
            attempts.extend(await repo.list_attempts(item["id"]))

        assert completed["status"] == "failed"
        assert {attempt["failure_kind"] for attempt in attempts} == {FailureKind.EXTERNAL_BLOCKED.value}
        assert all("missing credential" in attempt["error"] for attempt in attempts)
        assert {item["failure_kind"] for item in completed["report_json"]["items"]} == {FailureKind.EXTERNAL_BLOCKED.value}
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_evaluation_service_records_platform_defect_run_events_provider_failures(tmp_path):
    repo = await _repo(tmp_path)

    async def fake_launch(**kwargs):
        return {"thread_id": kwargs["thread_id"], "run_id": "run-provider-fails"}

    async def fake_run_events_provider(*, thread_id, run_id):
        raise RuntimeError(f"eval platform run_events provider failed for {run_id}")

    try:
        service = EvaluationService(
            repository=repo,
            launch_run=fake_launch,
            run_events_provider=fake_run_events_provider,
            workspaces_root=tmp_path / "workspaces",
        )
        created = await service.create_eval_run(owner_id="owner-1", suite_data=_suite(), idempotency_key=None)

        completed = await service.run_eval(created["id"])
        items = await repo.list_items(created["id"])
        attempts = []
        for item in items:
            attempts.extend(await repo.list_attempts(item["id"]))

        assert completed["status"] == "failed"
        assert {attempt["failure_kind"] for attempt in attempts} == {FailureKind.PLATFORM_DEFECT.value}
        assert all("run_events provider failed" in attempt["error"] for attempt in attempts)
        assert {item["failure_kind"] for item in completed["report_json"]["items"]} == {FailureKind.PLATFORM_DEFECT.value}
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_eval_dispatcher_claims_queued_run_and_updates_report(tmp_path):
    repo = await _repo(tmp_path)

    async def fake_launch(**kwargs):
        return {
            "thread_id": kwargs["thread_id"],
            "run_id": "run-1",
            "run_events": [
                {"event_type": "run.start"},
                {"event_type": "llm.ai.response"},
                {"event_type": "run.end"},
            ],
        }

    try:
        service = EvaluationService(repository=repo, launch_run=fake_launch, workspaces_root=tmp_path / "workspaces")
        created = await service.create_eval_run(owner_id="owner-1", suite_data=_suite(), idempotency_key=None)
        dispatcher = EvalDispatcher(repository=repo, service=service, lease_seconds=30)

        await dispatcher.run_once(now=datetime(2026, 7, 11, 12, 0, tzinfo=UTC))

        row = await repo.get_run(created["id"])
        assert row is not None
        assert row["status"] == "completed"
        assert row["lease_owner"] == dispatcher.lease_owner
        assert row["report_json"]["schema_version"] == "deerflow.evaluation.report.v1"
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_eval_router_create_is_idempotent_and_admin_scoped(tmp_path):
    repo = await _repo(tmp_path)
    try:
        request = _test_request(repo)
        body = EvalCreateRequest(suite=_suite())

        first = await create_eval_run(body, request, idempotency_key="idem-1")
        second = await create_eval_run(body, request, idempotency_key="idem-1")

        assert first.eval_run_id == second.eval_run_id
        assert first.total_items == 2
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_eval_router_rejects_memory_run_events_backend(tmp_path):
    repo = await _repo(tmp_path)
    try:
        request = _test_request(repo)
        request.app.state.run_events_config = type("RunEvents", (), {"backend": "memory"})()

        with pytest.raises(HTTPException) as exc:
            await create_eval_run(EvalCreateRequest(suite=_suite()), request, idempotency_key=None)

        assert exc.value.status_code == 409
        assert "persistent run_events" in exc.value.detail
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_eval_operator_rejects_regular_user():
    request = _test_request(repo=None, role="user")
    with pytest.raises(HTTPException) as exc:
        await _require_eval_operator(request)
    assert exc.value.status_code == 403
