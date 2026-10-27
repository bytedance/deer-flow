import asyncio

import pytest

from deerflow.authz.provider import AuthzRequest, Principal
from deerflow.authz.user_policy import UserAuthorizationProvider
from deerflow.security.store import UserSecurityStore


def test_grants_are_exact_user_scoped_and_revoked_live(tmp_path):
    store = UserSecurityStore(tmp_path)
    policy = UserAuthorizationProvider(store_path=str(tmp_path))
    alice = Principal(user_id="alice", role="user")
    bob = Principal(user_id="bob", role="user")
    req = AuthzRequest(principal=alice, resource="tool", action="call", target="custom_tool")
    assert not policy.authorize(req).allow
    store.set_grant("alice", "tool", "custom_tool", True, actor="admin")
    assert policy.authorize(req).allow
    assert policy.filter_resources(bob, "tool", ["custom_tool"]) == []
    store.set_grant("alice", "tool", "custom_tool", False, actor="admin")
    assert not asyncio.run(policy.aauthorize(req)).allow


def test_missing_identity_and_unknown_role_fail_closed(tmp_path):
    policy = UserAuthorizationProvider(store_path=str(tmp_path))
    for principal in [Principal(role="admin"), Principal(user_id="alice", role="unknown")]:
        assert not policy.authorize(AuthzRequest(principal, "tool", "call", "custom_tool")).allow
    assert policy.authorize(AuthzRequest(Principal(user_id="admin", role="admin"), "tool", "call", "custom_tool")).allow


def test_personal_credentials_are_encrypted_and_bound_to_user_and_server(tmp_path):
    store = UserSecurityStore(tmp_path)
    store.set_credential("alice", "crm", "Bearer alice-secret-value")
    store.set_credential("bob", "crm", "Bearer bob-secret-value")
    assert store.get_credential("alice", "crm") == "Bearer alice-secret-value"
    assert store.get_credential("bob", "crm") == "Bearer bob-secret-value"
    assert store.get_credential("alice", "other") is None
    assert store.credential_status("alice") == ["crm"]
    for file in tmp_path.iterdir():
        assert b"alice-secret-value" not in file.read_bytes()
    store.delete_credential("alice", "crm")
    assert store.get_credential("alice", "crm") is None
    assert store.get_credential("bob", "crm") is not None


def test_missing_key_never_silently_rotates_existing_credentials(tmp_path):
    store = UserSecurityStore(tmp_path)
    store.set_credential("alice", "crm", "private")
    (tmp_path / "master.key").unlink()
    with pytest.raises(RuntimeError, match="key"):
        store.set_credential("bob", "crm", "other")


def test_no_wildcards_or_invalid_resource_grants(tmp_path):
    store = UserSecurityStore(tmp_path)
    for resource, target in [("tool", "*"), ("route", "admin"), ("tool", "")]:
        with pytest.raises(ValueError):
            store.set_grant("alice", resource, target, True, actor="admin")


def test_defaults_open_but_future_tools_and_skills_require_exact_grants(tmp_path):
    policy = UserAuthorizationProvider(store_path=str(tmp_path))
    user = Principal(user_id="alice", role="user")
    for resource, target in [("tool", "bash"), ("sandbox", "*"), ("skill", "public:deep-research")]:
        policy.store.set_override("alice", resource, target, "deny", actor="admin")
        assert policy.authorize(AuthzRequest(user, resource, "use", target)).allow
    for resource, target in [("tool", "future_tool"), ("skill", "public:future-skill"), ("skill", "custom:alice:deep-research")]:
        request = AuthzRequest(user, resource, "use", target)
        assert not policy.authorize(request).allow
        group = policy.store.create_group(target, actor="admin")
        policy.store.set_member(group["id"], "alice", True, actor="admin")
        policy.store.set_group_grant(group["id"], resource, target, True, actor="admin")
        assert policy.authorize(request).allow
        policy.store.set_override("alice", resource, target, "deny", actor="admin")
        assert not policy.authorize(request).allow


def test_default_capabilities_still_require_authenticated_identity(tmp_path):
    policy = UserAuthorizationProvider(store_path=str(tmp_path))
    for user in [Principal(role="admin"), Principal(user_id="default", role="user"), Principal(user_id="alice", role="unknown")]:
        assert not policy.authorize(AuthzRequest(user, "tool", "call", "bash")).allow
