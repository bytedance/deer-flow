import asyncio
import sqlite3

import pytest

from deerflow.authz.provider import AuthzRequest, Principal
from deerflow.authz.user_policy import UserAuthorizationProvider
from deerflow.security.store import UserSecurityStore


def test_group_union_deny_reset_membership_and_deletion_are_live(tmp_path):
    store = UserSecurityStore(tmp_path)
    first = store.create_group("运营", actor="admin")
    second = store.create_group("开发", actor="admin")
    for group in (first, second):
        store.set_member(group["id"], "alice", True, actor="admin")
        store.set_group_grant(group["id"], "tool", "custom_tool", True, actor="admin")
    store.set_group_grant(second["id"], "sandbox", "*", True, actor="admin")
    policy = UserAuthorizationProvider(store_path=str(tmp_path))
    request = AuthzRequest(Principal(user_id="alice", role="user"), "tool", "call", "custom_tool")
    assert policy.authorize(request).allow
    assert store.grants("bob") == set()
    store.set_member(first["id"], "alice", False, actor="admin")
    assert asyncio.run(policy.aauthorize(request)).allow
    store.set_override("alice", "tool", "custom_tool", "deny", actor="admin")
    assert not policy.authorize(request).allow
    assert policy.filter_resources(request.principal, "tool", ["custom_tool"]) == []
    assert ("sandbox", "*") in store.grants("alice")
    store.set_override("alice", "tool", "custom_tool", "inherit", actor="admin")
    assert policy.authorize(request).allow
    store.delete_group(second["id"], actor="admin")
    assert not policy.authorize(request).allow
    assert store.grants("alice") == set()


def test_rename_delete_audits_and_no_orphans(tmp_path):
    store = UserSecurityStore(tmp_path)
    group = store.create_group("  Finance  ", actor="operator")
    assert group["name"] == "Finance"
    store.set_member(group["id"], "alice", True, actor="operator")
    store.set_member(group["id"], "alice", True, actor="operator")
    store.set_group_grant(group["id"], "tool", "custom_tool", True, actor="operator")
    renamed = store.rename_group(group["id"], "财务", actor="operator")
    assert renamed == {"id": group["id"], "name": "财务", "member_count": 1}
    assert store.list_groups() == [renamed]
    assert store.group_details(group["id"])["members"] == ["alice"]
    store.delete_group(group["id"], actor="operator")
    with pytest.raises(KeyError):
        store.set_member(group["id"], "bob", True, actor="operator")
    with pytest.raises(KeyError):
        store.set_group_grant(group["id"], "tool", "custom_tool", True, actor="operator")
    assert store.list_groups() == []
    with store._db() as db:
        assert db.execute("SELECT count(*) FROM group_members").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM group_grants").fetchone()[0] == 0
        actions = db.execute("SELECT action,actor FROM audit").fetchall()
        assert ("group.delete", "operator") in actions


@pytest.mark.parametrize("name", ["", "  ", "a" * 81, "bad\nname"])
def test_invalid_group_names(tmp_path, name):
    with pytest.raises(ValueError):
        UserSecurityStore(tmp_path).create_group(name, actor="admin")


def test_normalized_duplicate_names_and_unknown_groups(tmp_path):
    store = UserSecurityStore(tmp_path)
    group = store.create_group("Finance", actor="admin")
    for name in ("finance", " Finance ", "Ｆｉｎａｎｃｅ"):
        with pytest.raises(ValueError, match="already exists"):
            store.create_group(name, actor="admin")
    other = store.create_group("Other", actor="admin")
    with pytest.raises(ValueError, match="already exists"):
        store.rename_group(other["id"], "FINANCE", actor="admin")
    assert store.group_details(group["id"])["name"] == "Finance"
    with pytest.raises(KeyError):
        store.group_details("unknown")
    with pytest.raises(KeyError):
        store.rename_group("unknown", "unused", actor="admin")
    with pytest.raises(KeyError):
        store.delete_group("unknown", actor="admin")


def test_schema_extension_preserves_legacy_grants_and_credentials(tmp_path):
    # Create exactly the pre-group schema before first opening the new store.
    with sqlite3.connect(tmp_path / "users.db") as db:
        db.execute("CREATE TABLE grants (user_id TEXT, resource TEXT, target TEXT, PRIMARY KEY(user_id,resource,target))")
        db.execute("INSERT INTO grants VALUES ('alice','tool','custom_tool')")
    store = UserSecurityStore(tmp_path)
    store.set_credential("alice", "crm", "private-alice")
    key = (tmp_path / "master.key").read_bytes()
    group = store.create_group("Team", actor="admin")
    for user in ("alice", "bob"):
        store.set_member(group["id"], user, True, actor="admin")
    assert store.grants("alice") == {("tool", "custom_tool")}
    store.set_override("alice", "tool", "custom_tool", "deny", actor="admin")
    assert store.grants("alice") == set()
    assert store.grant_details("alice")["denied"] == [("tool", "custom_tool")]
    store.set_override("alice", "tool", "custom_tool", "allow", actor="admin")
    store.delete_group(group["id"], actor="admin")
    assert store.grants("alice") == {("tool", "custom_tool")}
    assert store.get_credential("alice", "crm") == "private-alice"
    assert store.get_credential("bob", "crm") is None
    assert (tmp_path / "master.key").read_bytes() == key
    store.set_grant("alice", "tool", "custom_tool", False, actor="admin")
    assert store.grants("alice") == set()


def test_direct_revocation_keeps_inheritance_and_invalid_changes_are_atomic(tmp_path):
    store = UserSecurityStore(tmp_path)
    group = store.create_group("Team", actor="admin")
    store.set_member(group["id"], "alice", True, actor="admin")
    store.set_group_grant(group["id"], "tool", "custom_tool", True, actor="admin")
    store.set_grant("alice", "tool", "custom_tool", True, actor="admin")
    store.set_grant("alice", "tool", "custom_tool", False, actor="admin")
    assert store.grants("alice") == {("tool", "custom_tool")}
    for resource, target in [("tool", "*"), ("route", "admin"), ("mcp_server", "*")]:
        with pytest.raises(ValueError):
            store.set_group_grant(group["id"], resource, target, True, actor="admin")
    with pytest.raises(ValueError):
        store.set_override("alice", "tool", "custom_tool", "invalid", actor="admin")
    assert store.grants("alice") == {("tool", "custom_tool")}
    store.set_group_grant(group["id"], "tool", "custom_tool", False, actor="admin")
    assert store.grants("alice") == set()
