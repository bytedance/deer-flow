"""HTTP-surface tests for the walkthrough routes.

The lifecycle tests drive ``EvolutionService`` directly, so they cannot see the
FastAPI plumbing at all. That gap is real: with ``from __future__ import
annotations``, a request model defined inside ``build_router`` becomes an
unresolvable forward reference, FastAPI silently treats ``body`` as a query
parameter, and every POST answers 422 while every service-level test stays
green. These tests go through ``TestClient`` so the request models are actually
resolved, validated, and rejected the way a caller experiences them.

They also pin caller binding: the host capability handles the service holds are
operator-scoped, so the routes — not the host — must refuse to act on another
user's skill.
"""

import asyncio
import json

from deerflow_extension_api import ExtensionPrincipal, ExtensionRuntimeDeps, HostCapabilityError
from deerflow_extension_api.auth import EXTENSION_PRINCIPAL_RESOLVER_KEY
from deerflow_extension_api.run_evidence import RUN_EVIDENCE_READER_RESOLVER_KEY, RunStatusView
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_lifecycle import OWNER, FakeEvidence, FakeMutationService

from deerflow_extension_skill_evolution.service import EvolutionService, build_router

SKILL = "example-skill"
PREFIX = "/api/extension-skill-evolution"
BASE_MAIN = "---\nname: example-skill\ndescription: demo\n---\n\nRun `scripts/run.py --fmt json`.\n"
FIXED_MAIN = BASE_MAIN.replace("--fmt json", "--format json")
CASE_JSON = json.dumps({"id": "converter-arg", "description": "SKILL.md must instruct --format json", "checks": [{"kind": "text_contains", "path": "SKILL.md", "needle": "--format json"}]})


def _as(client: TestClient, user_id: str | None) -> None:
    """Switch the request principal this client resolves (``None`` = anonymous)."""

    def resolver(request):
        return None if user_id is None else ExtensionPrincipal(user_id=user_id)

    setattr(client.app.state, EXTENSION_PRINCIPAL_RESOLVER_KEY, resolver)


class _MissingEvidence(FakeEvidence):
    """A host whose sealed-run reader answers ``NOT_FOUND`` for every anchor."""

    async def get_snapshot(self, **kwargs):
        raise HostCapabilityError("NOT_FOUND", "run is unavailable in this scope")


class _ValueErrorOnCheck(FakeMutationService):
    """A host invariant bug raised from ``check`` on the apply route."""

    async def check(self, *, proposal_id: str):
        raise ValueError("host invariant failed")


class _ValueErrorOnGetOperation(FakeMutationService):
    """A host invariant bug raised before ``revert`` can run."""

    async def get_operation(self, *, operation_id: str):
        raise ValueError("host invariant failed")


class _InvisibleRunReader:
    """A request-scoped reader for which the anchor run does not exist."""

    async def get_run_status(self, *, thread_id: str, run_id: str):
        return None


class _VisibleRunReader:
    """A request-scoped reader that confirms the anchor run is visible."""

    async def get_run_status(self, *, thread_id: str, run_id: str):
        return RunStatusView(thread_id=thread_id, run_id=run_id, status="success")


def _client(
    tmp_path,
    mutations: FakeMutationService | None = None,
    *,
    user_id: str | None = OWNER,
    case_text: str = CASE_JSON,
    evidence: FakeEvidence | None = None,
    raise_server_exceptions: bool = True,
) -> tuple[TestClient, FakeMutationService]:
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    (cases_dir / "01-arg.json").write_text(case_text, encoding="utf-8")
    service = EvolutionService(cases_dir=cases_dir)
    host = mutations if mutations is not None else FakeMutationService()
    asyncio.run(service.start(ExtensionRuntimeDeps(skill_mutations=host, completed_run_evidence=evidence if evidence is not None else FakeEvidence())))
    app = FastAPI()
    app.include_router(build_router(service))
    client = TestClient(app, raise_server_exceptions=raise_server_exceptions)
    _as(client, user_id)
    return client, host


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


def test_unknown_operation_returns_404(tmp_path):
    """``NOT_FOUND_OR_FORBIDDEN`` from the real host is a 404, not a conflict."""
    client, _host = _client(tmp_path)

    response = client.post(f"{PREFIX}/operations/does-not-exist/revert", json={})

    assert response.status_code == 404


def test_apply_unknown_proposal_returns_404(tmp_path):
    """A proposal this service never staged is absent, not a conflict."""
    client, _host = _client(tmp_path)

    response = client.post(f"{PREFIX}/proposals/does-not-exist/apply", json={})

    assert response.status_code == 404


def test_unknown_evidence_run_returns_404(tmp_path):
    """``NOT_FOUND`` from the sealed-run reader is a 404 as well."""
    client, _host = _client(tmp_path, evidence=_MissingEvidence())

    response = _propose(client)

    assert response.status_code == 404


def test_health_route_reports_the_evaluator(tmp_path):
    client, _host = _client(tmp_path)

    payload = client.get(f"{PREFIX}/health").json()

    assert payload["ready"] is True
    assert payload["evaluator"]
    assert payload["evaluator_version"]
    assert payload["cases"] == 1


def test_routes_require_an_authenticated_principal(tmp_path):
    client, _host = _client(tmp_path, user_id=None)

    assert client.get(f"{PREFIX}/proposals").status_code == 401
    assert _propose(client).status_code == 401


def test_propose_refuses_a_skill_owned_by_someone_else(tmp_path):
    """The injected host capability is allowlist-scoped, so the route binds the owner."""
    client, _host = _client(tmp_path, user_id="someone-else")

    response = _propose(client)

    assert response.status_code == 403
    assert response.json()["detail"].startswith("FORBIDDEN")


def test_proposals_are_scoped_to_their_owner(tmp_path):
    client, _host = _client(tmp_path)
    proposal_id = _propose(client).json()["proposal_id"]

    _as(client, "someone-else")

    assert client.get(f"{PREFIX}/proposals").json()["proposals"] == []
    # Another owner's proposal is not disclosed — not even its existence.
    assert client.get(f"{PREFIX}/proposals/{proposal_id}").status_code == 404
    applied = client.post(f"{PREFIX}/proposals/{proposal_id}/apply", json={})
    assert applied.status_code == 403
    assert applied.json()["detail"].startswith("FORBIDDEN")


def test_revert_is_scoped_to_the_operation_owner(tmp_path):
    client, _host = _client(tmp_path)
    proposal_id = _propose(client).json()["proposal_id"]
    operation_id = client.post(f"{PREFIX}/proposals/{proposal_id}/apply", json={}).json()["operation_id"]

    _as(client, "someone-else")
    response = client.post(f"{PREFIX}/operations/{operation_id}/revert", json={})

    assert response.status_code == 403
    assert response.json()["detail"].startswith("FORBIDDEN")


def test_a_broken_case_file_is_a_400_diagnostic(tmp_path):
    """A malformed operator case file fails closed, but not as a 500 traceback."""
    client, _host = _client(tmp_path, case_text="{ not json")

    health = client.get(f"{PREFIX}/health")
    proposed = _propose(client)

    assert health.status_code == 400
    assert health.json()["detail"].startswith("CASE_INVALID")
    assert proposed.status_code == 400
    assert proposed.json()["detail"].startswith("CASE_INVALID")


def test_apply_does_not_label_a_host_value_error_as_case_invalid(tmp_path):
    """Apply never reads the case files, so a host bug must surface as a 500."""
    client, _host = _client(tmp_path, mutations=_ValueErrorOnCheck(), raise_server_exceptions=False)
    proposal_id = _propose(client).json()["proposal_id"]

    response = client.post(f"{PREFIX}/proposals/{proposal_id}/apply", json={})

    assert response.status_code == 500


def test_revert_does_not_label_a_host_value_error_as_case_invalid(tmp_path):
    """Revert never reads the case files either."""
    client, _host = _client(tmp_path, mutations=_ValueErrorOnGetOperation(), raise_server_exceptions=False)

    response = client.post(f"{PREFIX}/operations/does-not-matter/revert", json={})

    assert response.status_code == 500


def test_hidden_run_anchor_is_403_before_the_host_is_touched(tmp_path):
    """The request-scoped reader is the production path; None means not visible."""
    client, host = _client(tmp_path)
    setattr(client.app.state, RUN_EVIDENCE_READER_RESOLVER_KEY, lambda request: _InvisibleRunReader())

    response = _propose(client)

    assert response.status_code == 403
    assert response.json()["detail"].startswith("SOURCE_NOT_VISIBLE")
    assert host._proposals == {}


def test_denied_run_reader_is_403(tmp_path):
    """The Gateway's resolver raises PermissionError without ``runs:read``."""
    client, _host = _client(tmp_path)

    def denied(request):
        raise PermissionError("run evidence requires runs:read")

    setattr(client.app.state, RUN_EVIDENCE_READER_RESOLVER_KEY, denied)

    response = _propose(client)

    assert response.status_code == 403


def test_visible_run_anchor_still_reaches_the_service(tmp_path):
    """A visible anchor must not be blocked by the new reader check."""
    client, _host = _client(tmp_path)
    setattr(client.app.state, RUN_EVIDENCE_READER_RESOLVER_KEY, lambda request: _VisibleRunReader())

    response = _propose(client)

    assert response.status_code == 200
