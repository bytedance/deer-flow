"""Trusted workspace identity must never originate in external run config."""

from types import SimpleNamespace

from app.gateway.services import inject_authenticated_user_context


def test_external_workspace_identity_is_removed_before_native_run():
    forged = {
        "workspace_id": "foreign-workspace",
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
