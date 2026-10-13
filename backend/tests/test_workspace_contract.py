"""Trusted workspace identity must never originate in external run config."""

import importlib
import importlib.util
import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.gateway.services import inject_authenticated_user_context


def test_external_workspace_identity_is_removed_before_native_run():
    forged = {
        "workspace_id": "foreign-workspace",
        "actor_user_id": "victim",
        "workspace_context": {
            "workspace_id": "foreign-workspace",
            "actor_user_id": "victim",
        },
        "membership_version": 999,
        "policy_version": 999,
    }
    config = {"context": dict(forged), "configurable": dict(forged)}
    request = SimpleNamespace(state=SimpleNamespace(user=None, auth_source="session"))

    inject_authenticated_user_context(config, request)

    for section in ("context", "configurable"):
        assert not forged.keys() & config[section].keys(), "external workspace identity survived admission"
    assert config["context"]["is_internal"] is False


def _workspace_module():
    name = "deerflow.authz.workspace"
    assert importlib.util.find_spec(name) is not None, "trusted workspace context boundary is not implemented"
    return importlib.import_module(name)


def test_workspace_context_is_immutable_and_actor_bound():
    module = _workspace_module()
    context = module.WorkspaceContext("bb7cc038-790e-4dd7-bac5-ac8d24d0d96e", "actual-user", 1, 1)
    with pytest.raises(FrozenInstanceError):
        context.actor_user_id = "victim"
    token = module.set_current_workspace(context)
    try:
        assert module.require_current_workspace(actor_user_id="actual-user", enabled=True) is context
        with pytest.raises(PermissionError):
            module.require_current_workspace(actor_user_id="victim", enabled=True)
    finally:
        module.reset_current_workspace(token)
    with pytest.raises(PermissionError):
        module.require_current_workspace(actor_user_id="actual-user", enabled=True)
    assert module.require_current_workspace(actor_user_id="actual-user", enabled=False) is None


def test_mapping_cannot_bind_trusted_workspace_context():
    module = _workspace_module()
    with pytest.raises(TypeError):
        module.set_current_workspace({"workspace_id": "bb7cc038-790e-4dd7-bac5-ac8d24d0d96e", "actor_user_id": "actual-user", "membership_version": 1, "policy_version": 1})
    with pytest.raises(ValueError):
        module.WorkspaceContext("../foreign", "actual-user", 1, 1)
    with pytest.raises(ValueError):
        module.WorkspaceContext("bb7cc038-790e-4dd7-bac5-ac8d24d0d96e", "actual-user", True, 0)


def test_public_contract_matches_workspace_identity():
    module = _workspace_module()
    contract = Path(__file__).resolve().parents[2] / "contracts/workspace_scope.v1.json"
    assert contract.exists(), "workspace scope JSON contract is not implemented"
    schema = json.loads(contract.read_text())
    assert set(schema["required"]) == set(module.WorkspaceContext.__dataclass_fields__)
    assert schema["additionalProperties"] is False
    assert schema["properties"]["membership_version"]["minimum"] == 1
    assert schema["properties"]["policy_version"]["minimum"] == 1
