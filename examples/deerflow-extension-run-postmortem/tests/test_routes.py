"""HTTP surface: authentication, owner binding, JSON and Markdown responses."""

from __future__ import annotations

import asyncio
import json

from deerflow_extension_api import CompletedRunEvent, CompletedRunEventPage, CompletedRunSnapshot, EvidenceLimits, ExtensionPrincipal, ExtensionRuntimeDeps, HostCapabilityError
from deerflow_extension_api.auth import EXTENSION_PRINCIPAL_RESOLVER_KEY
from deerflow_extension_api.run_evidence import RUN_EVIDENCE_READER_RESOLVER_KEY, RunPage, RunStatusView
from fastapi import FastAPI
from fastapi.testclient import TestClient

from deerflow_extension_run_postmortem.service import PostmortemService, build_router


def event(seq: int, event_type: str, category: str, content) -> CompletedRunEvent:
    return CompletedRunEvent(event_id=f"e{seq}", seq=seq, event_type=event_type, category=category, content_json=json.dumps(content), content_bytes=0, content_sha256="")


class FakeEvidence:
    def __init__(self, *, owner: str = "alice", missing: bool = False) -> None:
        self.owner = owner
        self.missing = missing
        self.snapshot_calls = 0

    async def list_changed_runs(self, *, cursor: str | None = None, limit: int = 200) -> RunPage:
        return RunPage(items=())

    async def get_snapshot(self, *, thread_id: str, run_id: str, limits: EvidenceLimits = EvidenceLimits()) -> CompletedRunSnapshot:
        self.snapshot_calls += 1
        if self.missing:
            raise HostCapabilityError("NOT_FOUND", "run is unavailable in this scope")
        return CompletedRunSnapshot(snapshot_ref="snap", evidence_revision="rev", thread_id=thread_id, run_id=run_id, owner_id=self.owner, agent_id="lead_agent", origin="interactive", status="error", seal_state="sealed", event_count=2)

    async def read_events(self, *, snapshot_ref: str, cursor: str | None = None, limits: EvidenceLimits = EvidenceLimits()) -> CompletedRunEventPage:
        if cursor is not None:
            return CompletedRunEventPage()
        return CompletedRunEventPage(items=(event(1, "run.start", "trace", {}), event(2, "run.error", "error", {"message": "boom"})))


def client_for(evidence: FakeEvidence, *, user_id: str | None = "alice") -> TestClient:
    service = PostmortemService()
    asyncio.run(service.start(ExtensionRuntimeDeps(completed_run_evidence=evidence)))
    app = FastAPI()
    app.include_router(build_router(service))
    client = TestClient(app)

    def resolver(request):
        return None if user_id is None else ExtensionPrincipal(user_id=user_id)

    setattr(client.app.state, EXTENSION_PRINCIPAL_RESOLVER_KEY, resolver)
    return client


def test_health_reports_readiness():
    response = client_for(FakeEvidence()).get("/api/extension-run-postmortem/health")

    assert response.status_code == 200
    assert response.json()["ready"] is True


def test_anonymous_callers_are_rejected():
    response = client_for(FakeEvidence(), user_id=None).get("/api/extension-run-postmortem/runs/t1/r1")

    assert response.status_code == 401


def test_json_report_carries_the_verdict_and_timeline():
    response = client_for(FakeEvidence()).get("/api/extension-run-postmortem/runs/t1/r1")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == "r1"
    assert body["verdict"] == "Run ended with status error."
    assert [item["event_type"] for item in body["timeline"]] == ["run.start", "run.error"]
    assert {anomaly["code"] for anomaly in body["anomalies"]} == {"run_failed", "run_or_model_errors"}


def test_markdown_route_returns_a_document():
    response = client_for(FakeEvidence()).get("/api/extension-run-postmortem/runs/t1/r1/markdown")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.text.startswith("# Run postmortem — `r1`")


def test_another_owners_run_reads_as_missing():
    response = client_for(FakeEvidence(owner="bob")).get("/api/extension-run-postmortem/runs/t1/r1")

    assert response.status_code == 404


def test_an_unavailable_run_reads_as_missing():
    response = client_for(FakeEvidence(missing=True)).get("/api/extension-run-postmortem/runs/t1/r1")

    assert response.status_code == 404


def test_out_of_range_max_events_is_rejected():
    response = client_for(FakeEvidence()).get("/api/extension-run-postmortem/runs/t1/r1?max_events=0")

    assert response.status_code == 422


class _InvisibleRunReader:
    """A request-scoped reader for which the anchor run does not exist."""

    async def get_run_status(self, *, thread_id: str, run_id: str):
        return None


class _VisibleRunReader:
    """A request-scoped reader that confirms the anchor run is visible."""

    async def get_run_status(self, *, thread_id: str, run_id: str):
        return RunStatusView(thread_id=thread_id, run_id=run_id, status="success")


def install_visibility_reader(client: TestClient, reader) -> None:
    setattr(client.app.state, RUN_EVIDENCE_READER_RESOLVER_KEY, lambda request: reader)


def test_an_invisible_run_is_refused_before_any_evidence_is_read():
    evidence = FakeEvidence()
    client = client_for(evidence)
    install_visibility_reader(client, _InvisibleRunReader())

    response = client.get("/api/extension-run-postmortem/runs/t1/r1")

    assert response.status_code == 404
    assert evidence.snapshot_calls == 0


def test_a_visible_run_proceeds_through_the_reader_branch():
    evidence = FakeEvidence()
    client = client_for(evidence)
    install_visibility_reader(client, _VisibleRunReader())

    response = client.get("/api/extension-run-postmortem/runs/t1/r1")

    assert response.status_code == 200
    assert evidence.snapshot_calls == 1
