"""HTTP-surface tests for the walkthrough routes.

The lifecycle tests drive ``EvolutionService`` directly, so they cannot see the
FastAPI plumbing at all. That gap is real: with ``from __future__ import
annotations``, a request model defined inside ``build_router`` becomes an
unresolvable forward reference, FastAPI silently treats ``body`` as a query
parameter, and every POST answers 422 while every service-level test stays
green. These tests go through ``TestClient`` so the request models are actually
resolved, validated, and rejected the way a caller experiences them.
"""

import asyncio
import json

from deerflow_extension_api import ExtensionRuntimeDeps
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_lifecycle import FakeEvidence, FakeMutationService

from deerflow_extension_skill_evolution.service import EvolutionService, build_router

SKILL = "example-skill"
PREFIX = "/api/extension-skill-evolution"
BASE_MAIN = "---\nname: example-skill\ndescription: demo\n---\n\nRun `scripts/run.py --fmt json`.\n"
FIXED_MAIN = BASE_MAIN.replace("--fmt json", "--format json")


def _client(tmp_path, mutations: FakeMutationService | None = None) -> tuple[TestClient, FakeMutationService]:
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    (cases_dir / "01-arg.json").write_text(
        json.dumps({"id": "converter-arg", "description": "SKILL.md must instruct --format json", "checks": [{"kind": "text_contains", "path": "SKILL.md", "needle": "--format json"}]}),
        encoding="utf-8",
    )
    service = EvolutionService(cases_dir=cases_dir)
    host = mutations if mutations is not None else FakeMutationService()
    asyncio.run(service.start(ExtensionRuntimeDeps(skill_mutations=host, completed_run_evidence=FakeEvidence())))
    app = FastAPI()
    app.include_router(build_router(service))
    return TestClient(app), host


def _propose(client: TestClient, **overrides):
    body = {"skill_name": SKILL, "candidate_content": FIXED_MAIN, "thread_id": "t", "run_id": "r"} | overrides
    return client.post(f"{PREFIX}/proposals", json=body)


def test_proposals_route_accepts_a_json_body(tmp_path):
    """A documented request body must reach the service, not become a query param."""
    client, _host = _client(tmp_path)

    response = _propose(client)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["decision"] == "justified"
    assert len(payload["report_id"]) == 64


def test_proposals_route_rejects_an_incomplete_body(tmp_path):
    client, _host = _client(tmp_path)

    response = client.post(f"{PREFIX}/proposals", json={"skill_name": SKILL, "candidate_content": FIXED_MAIN})

    assert response.status_code == 422


def test_proposals_route_forbids_unknown_fields(tmp_path):
    client, _host = _client(tmp_path)

    response = _propose(client, unexpected="value")

    assert response.status_code == 422


def test_apply_route_marks_the_proposal_committed_and_refuses_a_second_apply(tmp_path):
    client, _host = _client(tmp_path)
    proposal_id = _propose(client).json()["proposal_id"]

    applied = client.post(f"{PREFIX}/proposals/{proposal_id}/apply", json={})

    assert applied.status_code == 200, applied.text
    assert applied.json()["publication"] == "APPLIED"

    listing = client.get(f"{PREFIX}/proposals").json()["proposals"]
    committed = {item["proposal_id"]: item["committed"] for item in listing}
    assert committed[proposal_id] is True

    again = client.post(f"{PREFIX}/proposals/{proposal_id}/apply", json={})
    assert again.status_code == 409
    assert again.json()["detail"].startswith("ALREADY_COMMITTED")


def test_apply_route_returns_409_for_an_unevidenced_change(tmp_path):
    client, _host = _client(tmp_path)
    broken = FIXED_MAIN.replace("--format json", "--format xml")
    proposal = _propose(client, candidate_content=broken).json()

    assert proposal["decision"] == "failed"
    response = client.post(f"{PREFIX}/proposals/{proposal['proposal_id']}/apply", json={})

    assert response.status_code == 409
    assert response.json()["detail"].startswith("EVIDENCE_REQUIRED")


def test_revert_route_is_append_only(tmp_path):
    client, host = _client(tmp_path)
    proposal_id = _propose(client).json()["proposal_id"]
    operation_id = client.post(f"{PREFIX}/proposals/{proposal_id}/apply", json={}).json()["operation_id"]

    reverted = client.post(f"{PREFIX}/operations/{operation_id}/revert", json={})

    assert reverted.status_code == 200, reverted.text
    assert reverted.json()["reverts"] == operation_id
    assert host._files["SKILL.md"].decode() == BASE_MAIN


def test_unknown_proposal_returns_404(tmp_path):
    client, _host = _client(tmp_path)

    response = client.get(f"{PREFIX}/proposals/does-not-exist")

    assert response.status_code == 404


def test_health_route_reports_the_evaluator(tmp_path):
    client, _host = _client(tmp_path)

    payload = client.get(f"{PREFIX}/health").json()

    assert payload["ready"] is True
    assert payload["evaluator"]
    assert payload["evaluator_version"]
    assert payload["cases"] == 1
