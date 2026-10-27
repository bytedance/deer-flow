"""Tests for runtime.user_context — contextvar three-state semantics.

These tests opt out of the autouse contextvar fixture (added in
commit 6) because they explicitly test the cases where the contextvar
is set or unset.
"""

from types import SimpleNamespace

import pytest
from langchain_core.runnables import RunnableLambda
from langgraph.runtime import Runtime, ServerInfo

from deerflow.config.paths import Paths, make_safe_user_id
from deerflow.runtime.user_context import (
    DEFAULT_USER_ID,
    CurrentUser,
    get_current_user,
    get_effective_user_id,
    require_current_user,
    reset_current_user,
    resolve_config_user_id,
    resolve_runtime_user_id,
    set_current_user,
)


@pytest.mark.no_auto_user
def test_default_is_none():
    """Before any set, contextvar returns None."""
    assert get_current_user() is None


@pytest.mark.no_auto_user
def test_set_and_reset_roundtrip():
    """set_current_user returns a token that reset restores."""
    user = SimpleNamespace(id="user-1")
    token = set_current_user(user)
    try:
        assert get_current_user() is user
    finally:
        reset_current_user(token)
    assert get_current_user() is None


@pytest.mark.no_auto_user
def test_require_current_user_raises_when_unset():
    """require_current_user raises RuntimeError if contextvar is unset."""
    assert get_current_user() is None
    with pytest.raises(RuntimeError, match="without user context"):
        require_current_user()


@pytest.mark.no_auto_user
def test_require_current_user_returns_user_when_set():
    """require_current_user returns the user when contextvar is set."""
    user = SimpleNamespace(id="user-2")
    token = set_current_user(user)
    try:
        assert require_current_user() is user
    finally:
        reset_current_user(token)


@pytest.mark.no_auto_user
def test_protocol_accepts_duck_typed():
    """CurrentUser is a runtime_checkable Protocol matching any .id-bearing object."""
    user = SimpleNamespace(id="user-3")
    assert isinstance(user, CurrentUser)


@pytest.mark.no_auto_user
def test_protocol_rejects_no_id():
    """Objects without .id do not satisfy CurrentUser Protocol."""
    not_a_user = SimpleNamespace(email="no-id@example.com")
    assert not isinstance(not_a_user, CurrentUser)


# ---------------------------------------------------------------------------
# get_effective_user_id / DEFAULT_USER_ID tests
# ---------------------------------------------------------------------------


def test_default_user_id_is_default():
    assert DEFAULT_USER_ID == "default"


@pytest.mark.no_auto_user
def test_effective_user_id_returns_default_when_no_user():
    """No user in context -> fallback to DEFAULT_USER_ID."""
    assert get_effective_user_id() == "default"


@pytest.mark.no_auto_user
def test_effective_user_id_returns_user_id_when_set():
    user = SimpleNamespace(id="u-abc-123")
    token = set_current_user(user)
    try:
        assert get_effective_user_id() == "u-abc-123"
    finally:
        reset_current_user(token)


@pytest.mark.no_auto_user
def test_effective_user_id_coerces_to_str():
    """User.id might be a UUID object; must come back as str."""
    import uuid

    uid = uuid.uuid4()

    user = SimpleNamespace(id=uid)
    token = set_current_user(user)
    try:
        assert get_effective_user_id() == str(uid)
    finally:
        reset_current_user(token)


# ---------------------------------------------------------------------------
# resolve_runtime_user_id tests
# ---------------------------------------------------------------------------


@pytest.mark.no_auto_user
def test_config_user_id_prefers_server_auth_over_client_user_id():
    config = {
        "configurable": {
            "langgraph_auth_user_id": "authenticated-user",
            "user_id": "spoofed-configurable-user",
        },
        "context": {
            "user_id": "spoofed-context-user",
        },
    }

    assert resolve_config_user_id(config) == "authenticated-user"


@pytest.mark.no_auto_user
def test_config_user_id_normalizes_external_auth_identity_for_storage(tmp_path):
    raw_identity = "alice@example.com"

    resolved = resolve_config_user_id(
        {
            "configurable": {
                "langgraph_auth_user_id": raw_identity,
            }
        }
    )

    assert resolved == make_safe_user_id(raw_identity)
    assert Paths(tmp_path).user_dir(resolved).name == resolved


@pytest.mark.no_auto_user
def test_config_user_id_keeps_colliding_sanitized_auth_identities_distinct():
    dotted = resolve_config_user_id({"configurable": {"langgraph_auth_user_id": "alice.example"}})
    slashed = resolve_config_user_id({"configurable": {"langgraph_auth_user_id": "alice/example"}})

    assert dotted == make_safe_user_id("alice.example")
    assert slashed == make_safe_user_id("alice/example")
    assert dotted != slashed


@pytest.mark.no_auto_user
@pytest.mark.parametrize("invalid_auth_user_id", [123, object()])
def test_config_user_id_ignores_non_string_server_auth_id(invalid_auth_user_id):
    config = {
        "configurable": {
            "langgraph_auth_user_id": invalid_auth_user_id,
        },
        "context": {
            "user_id": "gateway-user",
        },
    }

    assert resolve_config_user_id(config) == "gateway-user"


@pytest.mark.no_auto_user
def test_config_user_id_uses_gateway_runtime_context_without_server_auth():
    config = {
        "configurable": {
            "user_id": "legacy-configurable-user",
        },
        "context": {
            "user_id": "gateway-user",
        },
    }

    assert resolve_config_user_id(config) == "gateway-user"


@pytest.mark.no_auto_user
def test_config_user_id_falls_back_to_legacy_configurable_user():
    assert resolve_config_user_id({"configurable": {"user_id": "legacy-user"}}) == "legacy-user"


@pytest.mark.no_auto_user
def test_runtime_langgraph_auth_takes_precedence_over_context_user_id(monkeypatch):
    monkeypatch.setattr(
        "langgraph.config.get_config",
        lambda: {"configurable": {"langgraph_auth_user_id": "langgraph-user"}},
    )

    runtime = SimpleNamespace(context={"user_id": "runtime-user"})

    assert resolve_runtime_user_id(runtime) == "langgraph-user"


@pytest.mark.no_auto_user
def test_runtime_user_id_uses_gateway_context_without_langgraph_auth(monkeypatch):
    monkeypatch.setattr(
        "langgraph.config.get_config",
        lambda: {"configurable": {}},
    )

    runtime = SimpleNamespace(context={"user_id": "runtime-user"})

    assert resolve_runtime_user_id(runtime) == "runtime-user"


@pytest.mark.no_auto_user
def test_runtime_server_info_identity_takes_precedence_over_runtime_context(monkeypatch):
    monkeypatch.setattr(
        "langgraph.config.get_config",
        lambda: {"configurable": {"langgraph_auth_user_id": "config-auth-user"}},
    )
    runtime = Runtime(
        server_info=ServerInfo(
            assistant_id="assistant-1",
            graph_id="graph-1",
            user=SimpleNamespace(identity="server-info-user"),
        ),
        context={"user_id": "runtime-user"},
    )

    assert resolve_runtime_user_id(runtime) == "server-info-user"


@pytest.mark.no_auto_user
def test_runtime_server_info_normalizes_external_auth_identity(monkeypatch):
    monkeypatch.setattr("langgraph.config.get_config", lambda: {"configurable": {}})
    raw_identity = "alice@example.com"
    runtime = Runtime(
        server_info=ServerInfo(
            assistant_id="assistant-1",
            graph_id="graph-1",
            user=SimpleNamespace(identity=raw_identity),
        ),
    )

    assert resolve_runtime_user_id(runtime) == make_safe_user_id(raw_identity)


@pytest.mark.no_auto_user
def test_runtime_server_info_ignores_non_string_identity():
    runtime = Runtime(
        server_info=ServerInfo(
            assistant_id="assistant-1",
            graph_id="graph-1",
            user=SimpleNamespace(identity=object()),
        ),
        context={"user_id": "runtime-user"},
    )

    assert resolve_runtime_user_id(runtime) == "runtime-user"


@pytest.mark.no_auto_user
def test_runtime_user_id_uses_langgraph_auth_user_id(monkeypatch):
    monkeypatch.setattr(
        "langgraph.config.get_config",
        lambda: {"configurable": {"langgraph_auth_user_id": "langgraph-user"}},
    )

    assert resolve_runtime_user_id(None) == "langgraph-user"


@pytest.mark.no_auto_user
def test_runtime_user_id_reads_langgraph_auth_from_real_runnable_config():
    resolver = RunnableLambda(lambda _: resolve_runtime_user_id(None))
    raw_identity = "runnable@example.com"

    result = resolver.invoke(
        None,
        config={
            "configurable": {
                "langgraph_auth_user_id": raw_identity,
            }
        },
    )

    assert result == make_safe_user_id(raw_identity)


@pytest.mark.no_auto_user
def test_runtime_user_id_falls_back_to_langgraph_auth_user_identity(monkeypatch):
    monkeypatch.setattr(
        "langgraph.config.get_config",
        lambda: {
            "configurable": {
                "langgraph_auth_user": SimpleNamespace(identity="identity-user"),
            }
        },
    )

    assert resolve_runtime_user_id(None) == "identity-user"


@pytest.mark.no_auto_user
def test_runtime_user_id_falls_back_to_contextvar(monkeypatch):
    monkeypatch.setattr("langgraph.config.get_config", lambda: {"configurable": {}})
    token = set_current_user(SimpleNamespace(id="context-user"))
    try:
        assert resolve_runtime_user_id(None) == "context-user"
    finally:
        reset_current_user(token)


@pytest.mark.no_auto_user
def test_runtime_user_id_falls_back_to_default_outside_runnable_context(monkeypatch):
    def raise_no_config():
        raise RuntimeError("no runnable config")

    monkeypatch.setattr("langgraph.config.get_config", raise_no_config)

    assert resolve_runtime_user_id(None) == DEFAULT_USER_ID
