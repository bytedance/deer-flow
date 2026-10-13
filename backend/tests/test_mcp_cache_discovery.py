"""T1 coverage for the per-server MCP discovery-cache scaffolding (F2).

F2 may reuse a server's already-published ``ServerDiscoveryResult`` only when
both of these still hold:

* the server's canonical configuration identity is unchanged
  (``_server_config_snapshot``), and
* the discovery result is still owned by the pool's *current* session binding
  (``_binding_matches``).

These tests pin exactly those two primitives. They deliberately do not exercise
cache selection, eviction or publication — that wiring is T2 and must not be
implied by a green run here.

``ServerBinding`` is declared ``eq=False``: two bindings with identical field
values are still distinct objects, and ABA safety depends on comparing object
identity (``pool._binding_is_current``), never dataclass value equality. The
superseded-binding test below would still pass under value equality and is
therefore the load-bearing one.
"""

from __future__ import annotations

from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp import cache as cache_module
from deerflow.mcp.cache import (
    _AppliedMcpRevision,
    _binding_matches,
    _ServerToolCacheEntry,
)
from deerflow.mcp.session_pool import MCPSessionPool
from deerflow.mcp.tools import ServerDiscoveryResult


def _config(servers: dict[str, dict]) -> ExtensionsConfig:
    return ExtensionsConfig.model_validate({"mcpServers": servers})


def _server(config: ExtensionsConfig, name: str):
    return config.get_enabled_mcp_servers()[name]


def _snapshot(servers: dict[str, dict], name: str) -> str:
    return cache_module._server_config_snapshot(_server(_config(servers), name))


def _pool_with_binding(
    name: str = "A",
    fingerprint: str = "fp",
    domain: str = "deployment",
) -> tuple[MCPSessionPool, object]:
    pool = MCPSessionPool()
    binding = pool.ensure_binding(name, fingerprint, domain=domain)
    return pool, binding


# ---------------------------------------------------------------------------
# Canonical config identity
# ---------------------------------------------------------------------------


def test_server_snapshot_equal_across_transport_alias_and_field_order():
    typed = _snapshot({"A": {"enabled": True, "type": "stdio", "command": "srv", "args": ["x"]}}, "A")
    aliased = _snapshot({"A": {"enabled": True, "transport": "stdio", "command": "srv", "args": ["x"]}}, "A")
    reordered = _snapshot({"A": {"command": "srv", "args": ["x"], "enabled": True, "type": "stdio"}}, "A")

    # ``transport`` is an MCP-spec alias for ``type`` and JSON key order is
    # irrelevant: neither spelling difference may look like a config change.
    assert typed == aliased == reordered


def test_server_snapshot_changes_on_presentation_metadata_change():
    base = _snapshot({"A": {"enabled": True, "type": "stdio", "command": "srv", "description": "one"}}, "A")
    changed = _snapshot({"A": {"enabled": True, "type": "stdio", "command": "srv", "description": "two"}}, "A")

    # Presentation-only fields still change how tools are advertised, so the
    # snapshot must distinguish them (metadata-only updates rebuild the tools).
    assert base != changed


def test_server_snapshot_changes_on_routing_and_connection_change():
    base = _snapshot({"A": {"enabled": True, "type": "stdio", "command": "srv"}}, "A")
    routed = _snapshot({"A": {"enabled": True, "type": "stdio", "command": "srv", "routing": {"mode": "off", "priority": 5}}}, "A")
    reconnected = _snapshot({"A": {"enabled": True, "type": "stdio", "command": "srv2"}}, "A")

    assert base != routed
    assert base != reconnected


def test_server_snapshot_is_stable_string():
    snapshot = _snapshot({"A": {"enabled": True, "type": "http", "url": "https://example.test/mcp"}}, "A")

    assert isinstance(snapshot, str) and snapshot


# ---------------------------------------------------------------------------
# Binding ownership identity
# ---------------------------------------------------------------------------


def test_binding_matches_accepts_http_result_without_pool_or_binding():
    result = ServerDiscoveryResult(tools=(), pool=None, binding=None)

    assert _binding_matches(result, "A", None, None) is True


def test_binding_matches_rejects_http_result_that_carries_ownership():
    pool, binding = _pool_with_binding()

    assert _binding_matches(ServerDiscoveryResult(tools=(), pool=pool, binding=None), "A", None, None) is False
    assert _binding_matches(ServerDiscoveryResult(tools=(), pool=None, binding=binding), "A", None, None) is False
    assert _binding_matches(ServerDiscoveryResult(tools=(), pool=pool, binding=binding), "A", None, None) is False


def test_binding_matches_accepts_current_stdio_binding():
    pool, binding = _pool_with_binding(name="A", fingerprint="fp")
    result = ServerDiscoveryResult(tools=(), pool=pool, binding=binding)

    assert _binding_matches(result, "A", "fp", pool) is True


def test_binding_matches_rejects_foreign_pool():
    pool, binding = _pool_with_binding(name="A", fingerprint="fp")
    foreign = MCPSessionPool()
    result = ServerDiscoveryResult(tools=(), pool=pool, binding=binding)

    assert _binding_matches(result, "A", "fp", foreign) is False
    assert _binding_matches(result, "A", "fp", None) is False


def test_binding_matches_rejects_mismatched_pool_and_binding_handles():
    owner = MCPSessionPool()
    binding = owner.ensure_binding("A", "fp", domain="deployment")
    other_pool = MCPSessionPool()
    # A result whose pool handle disagrees with the binding's owning pool must
    # never be trusted, even when the *passed* pool still considers that exact
    # binding current. This makes the ``result.pool is pool`` guard load-bearing.
    result = ServerDiscoveryResult(tools=(), pool=other_pool, binding=binding)

    assert _binding_matches(result, "A", "fp", owner) is False


def test_binding_matches_rejects_fingerprint_and_name_mismatch():
    pool, binding = _pool_with_binding(name="A", fingerprint="fp")
    result = ServerDiscoveryResult(tools=(), pool=pool, binding=binding)

    assert _binding_matches(result, "A", "other-fp", pool) is False
    assert _binding_matches(result, "B", "fp", pool) is False


def test_binding_matches_rejects_superseded_binding_object_with_same_fingerprint():
    pool = MCPSessionPool()
    stale = pool.ensure_binding("A", "fp", domain="deployment")
    # A cross-worker delete/re-add of an identical server re-epochs the binding
    # to a *new object* carrying the same fingerprint (the ABA case).
    pool.reconcile_bindings({"A": "fp"}, [], domain="deployment", force_rebind=("A",))
    current = pool._bindings[("deployment", "A")]

    assert current is not stale
    assert current.fingerprint == stale.fingerprint

    # The stale object has identical field values but is no longer current, so
    # value equality must never let it through.
    assert _binding_matches(ServerDiscoveryResult(tools=(), pool=pool, binding=stale), "A", "fp", pool) is False
    assert _binding_matches(ServerDiscoveryResult(tools=(), pool=pool, binding=current), "A", "fp", pool) is True


def test_binding_matches_rejects_retired_pool_binding():
    pool, binding = _pool_with_binding(name="A", fingerprint="fp")
    pool.retire_all()
    result = ServerDiscoveryResult(tools=(), pool=pool, binding=binding)

    assert _binding_matches(result, "A", "fp", pool) is False


def test_binding_matches_rejects_personal_domain_binding():
    pool = MCPSessionPool()
    personal = pool.ensure_binding("A", "fp", domain="personal")
    result = ServerDiscoveryResult(tools=(), pool=pool, binding=personal)

    # A deployment discovery may never reuse a same-named personal binding.
    assert _binding_matches(result, "A", "fp", pool) is False


# ---------------------------------------------------------------------------
# Cache entry scaffolding + repr secrecy
# ---------------------------------------------------------------------------


def test_server_tool_cache_starts_as_a_dict():
    assert isinstance(cache_module._server_tool_cache, dict)


def test_server_cache_entry_repr_hides_snapshot_and_ownership_handles():
    pool, binding = _pool_with_binding(name="A", fingerprint="secret-fingerprint")
    entry = _ServerToolCacheEntry(
        snapshot='{"env": {"TOKEN": "super-secret-token"}}',
        result=ServerDiscoveryResult(tools=(), pool=pool, binding=binding),
    )

    rendered = repr(entry)

    assert "super-secret-token" not in rendered
    assert "secret-fingerprint" not in rendered
    assert "snapshot" not in rendered


def test_applied_revision_repr_hides_resolved_server_snapshots():
    revision = _AppliedMcpRevision(
        effective_snapshot='{"env": {"TOKEN": "super-secret-token"}}',
        interceptors="[]",
        stdio_connections={"A": "digest"},
        lifecycle_tokens={},
        server_snapshots={"A": '{"env": {"TOKEN": "super-secret-token"}}'},
    )

    rendered = repr(revision)

    assert "super-secret-token" not in rendered
    assert "server_snapshots" not in rendered
    assert "effective_snapshot" not in rendered
