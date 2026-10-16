"""Workspace execution transport; live runtime authorization is a separate gate."""

import base64
import hmac
import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from deerflow.authz.workspace import WorkspaceContext

SECRET = b"synthetic-workspace-scope-secret-32-bytes"
WORKSPACE = WorkspaceContext("22222222-2222-2222-2222-222222222222", "alice", 3, 5)


@pytest.fixture(autouse=True)
def _executor_source(monkeypatch):
    source = Path(__file__).resolve().parents[1] / "packages" / "ecs-executor"
    monkeypatch.syspath_prepend(str(source))
    import ecs_executor.scope

    assert Path(ecs_executor.scope.__file__).resolve() == source / "ecs_executor" / "scope.py"


def _mint(**overrides):
    from ecs_executor.scope import mint_execution_scope

    return mint_execution_scope(
        **{
            "secret": SECRET,
            "audience": "ecs-worker",
            "user_id": "alice",
            "thread_id": "thread-1",
            "incarnation": "generation-1",
            "run_id": "run-1",
            "operation": "submit",
            "arguments": {"command": "echo report"},
            "workspace_context": WORKSPACE,
            "now": 100,
            **overrides,
        }
    )


def _verify(token, **overrides):
    from ecs_executor.scope import verify_execution_scope

    return verify_execution_scope(
        token,
        **{
            "secret": SECRET,
            "authenticated_user_id": "alice",
            "arguments": {"command": "echo report"},
            "expected_audience": "ecs-worker",
            "expected_operation": "submit",
            "expected_workspace_context": WORKSPACE,
            "now": 120,
            **overrides,
        },
    )


def test_execution_signature_preserves_trusted_workspace_snapshot():
    claims = _verify(_mint())
    assert claims["version"] == 2
    assert claims["workspace_context"] == asdict(WORKSPACE)
    assert (claims["user_id"], claims["thread_id"], claims["incarnation"], claims["run_id"]) == (
        "alice",
        "thread-1",
        "generation-1",
        "run-1",
    )


def test_execution_signature_refuses_retargeting_stale_versions_and_downgrade():
    token = _mint()
    for expected in (
        None,
        replace(WORKSPACE, workspace_id="33333333-3333-3333-3333-333333333333"),
        replace(WORKSPACE, actor_user_id="bob"),
        replace(WORKSPACE, membership_version=4),
        replace(WORKSPACE, policy_version=6),
        asdict(WORKSPACE),
    ):
        with pytest.raises(ValueError, match="workspace"):
            _verify(token, expected_workspace_context=expected)
    legacy = _mint(workspace_context=None)
    with pytest.raises(ValueError, match="workspace"):
        _verify(legacy)
    assert "workspace_context" not in _verify(legacy, expected_workspace_context=None)
    for overrides in (
        {"workspace_context": asdict(WORKSPACE)},
        {"workspace_context": replace(WORKSPACE, actor_user_id="bob")},
        {"incarnation": None},
    ):
        with pytest.raises(ValueError):
            _mint(**overrides)


def test_execution_signature_rejects_signed_malformed_workspace_protocol():
    token = _mint()
    payload, signature = token.split(".")
    original = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))

    def encode(claims):
        raw = json.dumps(claims, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    malformed = [
        {**original, "version": 3},
        {**original, "version": True},
        {key: value for key, value in original.items() if key != "version"},
        {**original, "workspace_context": {**asdict(WORKSPACE), "membership_version": True}},
        {**original, "workspace_context": {**asdict(WORKSPACE), "policy_version": 0}},
        {**original, "workspace_context": {**asdict(WORKSPACE), "actor_user_id": "bob"}},
        {**original, "workspace_context": {**asdict(WORKSPACE), "untrusted": "extra"}},
        {**original, "workspace_context": {**asdict(WORKSPACE), "workspace_id": "not-a-uuid"}},
        {**original, "workspace_context": []},
        {**original, "incarnation": None},
    ]
    for claims in malformed:
        encoded = encode(claims)
        signed = base64.urlsafe_b64encode(hmac.digest(SECRET, encoded.encode(), "sha256")).decode().rstrip("=")
        with pytest.raises(ValueError):
            _verify(encoded + "." + signed)
    # A transport attacker cannot replace the original workspace without the key.
    changed = encode({**original, "workspace_context": {**asdict(WORKSPACE), "policy_version": 6}})
    with pytest.raises(ValueError, match="signature"):
        _verify(changed + "." + signature)
