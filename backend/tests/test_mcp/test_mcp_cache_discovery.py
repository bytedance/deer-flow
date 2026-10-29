"""Coverage for the per-server MCP discovery cache.

The cache may reuse a server's already-published ``ServerDiscoveryResult`` only
when all of these still hold:

* the server's canonical configuration identity is unchanged
  (``_server_config_snapshot``),
* the normalized global interceptor chain is unchanged, and
* the discovery result is still owned by the pool's *current* session binding
  (``_binding_matches``).

This module covers both the reuse predicates and their use by
``initialize_mcp_tools`` (selection, per-server rediscovery, atomic
publication).

``ServerBinding`` is declared ``eq=False``: two bindings with identical field
values are still distinct objects, and ABA safety depends on comparing object
identity (``pool._binding_is_current``), never dataclass value equality. The
superseded-binding test below would still pass under value equality and is
therefore the load-bearing one.
"""

from __future__ import annotations

import asyncio
import builtins
import json
import logging
import threading

import pytest
from langchain_core.tools import StructuredTool

from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp import cache as cache_module
from deerflow.mcp import session_pool as session_pool_module
from deerflow.mcp.cache import (
    _AppliedMcpRevision,
    _binding_matches,
    _ServerToolCacheEntry,
)
from deerflow.mcp.client import build_servers_config
from deerflow.mcp.session_pool import MCPSessionPool, normalized_connection_fingerprint
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
        interceptors="[]",
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


# ---------------------------------------------------------------------------
# Discovery reuse + atomic publication through ``initialize_mcp_tools``
# ---------------------------------------------------------------------------

_DISCOVERY_MISSING = object()
_DISCOVERY_TRACKED_GLOBALS = (
    "_mcp_tools_cache",
    "_cache_initialized",
    "_config_path",
    "_config_signature",
    "_init_lock",
    "_init_condition",
    "_initializing_generation",
    "_cache_generation",
    "_mcp_config_snapshot",
    "_initialized_without_config",
    "_cache_reset_marker_signature",
    "_applied_mcp_revision",
    "_server_tool_cache",
)


@pytest.fixture()
def discovery_cache(tmp_path, monkeypatch):
    """Isolate cache coordination state, ``_server_tool_cache`` and the pool singleton."""
    saved = {name: getattr(cache_module, name, _DISCOVERY_MISSING) for name in _DISCOVERY_TRACKED_GLOBALS}
    cache_module._mcp_tools_cache = None
    cache_module._cache_initialized = False
    cache_module._server_tool_cache = {}
    for name in (
        "_config_path",
        "_config_signature",
        "_mcp_config_snapshot",
        "_initialized_without_config",
        "_cache_reset_marker_signature",
        "_applied_mcp_revision",
    ):
        if hasattr(cache_module, name):
            setattr(cache_module, name, None)
    cache_module._init_lock = threading.RLock()
    cache_module._init_condition = threading.Condition(cache_module._init_lock)
    cache_module._initializing_generation = None
    cache_module._cache_generation = 0
    session_pool_module.reset_session_pool()
    cfg = tmp_path / "extensions_config.json"
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))
    try:
        yield cfg
    finally:
        session_pool_module.reset_session_pool()
        for name, value in saved.items():
            if value is _DISCOVERY_MISSING:
                if hasattr(cache_module, name):
                    delattr(cache_module, name)
            else:
                setattr(cache_module, name, value)


def _stdio(name: str, command: str | None = None, **extra) -> dict:
    return {"enabled": True, "type": "stdio", "command": command or f"cmd-{name}", **extra}


def _write_config(cfg, servers: dict, *, tokens: dict | None = None, interceptors: list[str] | str | None = None) -> None:
    payload: dict = {"mcpServers": servers, "skills": {}}
    if tokens is not None:
        payload["mcpLifecycle"] = {"version": 1, "servers": tokens}
    if interceptors is not None:
        payload["mcpInterceptors"] = interceptors
    cfg.write_text(json.dumps(payload), encoding="utf-8")


class _DevTool:
    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<tool {self.name}>"


class _Discovery:
    """Deterministic grouped-discovery stand-in that records per-call selections."""

    def __init__(self, *, empty=(), fail=()) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.before_return: dict[str, object] = {}
        self.empty = set(empty)
        self.fail = set(fail)

    async def __call__(self, *, extensions_config, server_names=None, session_pool=None, personal_user_id=None):
        connections = build_servers_config(extensions_config)
        selected = [name for name in connections if server_names is None or name in set(server_names)]
        self.calls.append(tuple(selected))
        bindings = {}
        for name in selected:
            connection = connections[name]
            if connection.get("transport", "stdio") == "stdio":
                bindings[name] = session_pool.ensure_binding(name, normalized_connection_fingerprint(connection), domain="deployment")
        for name in selected:
            hook = self.before_return.get(name)
            if hook is not None:
                await hook(session_pool)
        groups = {}
        for name in selected:
            if name in self.fail:
                continue
            is_stdio = connections[name].get("transport", "stdio") == "stdio"
            tools = () if name in self.empty else (_DevTool(name),)
            groups[name] = ServerDiscoveryResult(tools=tools, pool=session_pool if is_stdio else None, binding=bindings.get(name))
        return groups


def _install(monkeypatch, discovery: _Discovery) -> _Discovery:
    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools_by_server", discovery)
    return discovery


def _names(tools) -> list[str]:
    return [getattr(tool, "name", None) for tool in tools]


def _fingerprint(servers: dict, name: str) -> str:
    return normalized_connection_fingerprint(build_servers_config(ExtensionsConfig.model_validate({"mcpServers": servers}))[name])


@pytest.mark.asyncio
async def test_unchanged_server_is_reused_by_identity(discovery_cache, monkeypatch):
    """Changing A re-discovers only A; B keeps its exact tool object and binding."""
    cfg = discovery_cache
    _write_config(cfg, {"A": _stdio("A"), "B": _stdio("B")})
    discovery = _install(monkeypatch, _Discovery())

    tools1 = await cache_module.initialize_mcp_tools()
    assert _names(tools1) == ["A", "B"]
    assert discovery.calls == [("A", "B")]
    tool_b = next(tool for tool in tools1 if tool.name == "B")
    pool = session_pool_module.get_session_pool()
    binding_b = pool._bindings[("deployment", "B")]

    _write_config(cfg, {"A": _stdio("A", command="cmd-A2"), "B": _stdio("B")})
    assert cache_module.refresh_mcp_cache_if_active() is True
    tools2 = await cache_module.initialize_mcp_tools()

    assert discovery.calls == [("A", "B"), ("A",)]
    assert _names(tools2) == ["A", "B"]
    assert next(tool for tool in tools2 if tool.name == "B") is tool_b
    assert pool._bindings[("deployment", "B")] is binding_b


@pytest.mark.asyncio
async def test_metadata_only_change_rebuilds_only_that_server(discovery_cache, monkeypatch):
    """A presentation-only change rebuilds A but reuses B's entry."""
    cfg = discovery_cache
    _write_config(cfg, {"A": _stdio("A"), "B": _stdio("B")})
    discovery = _install(monkeypatch, _Discovery())
    tools1 = await cache_module.initialize_mcp_tools()
    tool_a = next(tool for tool in tools1 if tool.name == "A")
    tool_b = next(tool for tool in tools1 if tool.name == "B")

    _write_config(cfg, {"A": _stdio("A", description="renamed"), "B": _stdio("B")})
    assert cache_module.refresh_mcp_cache_if_active() is True
    tools2 = await cache_module.initialize_mcp_tools()

    assert discovery.calls == [("A", "B"), ("A",)]
    assert next(tool for tool in tools2 if tool.name == "A") is not tool_a
    assert next(tool for tool in tools2 if tool.name == "B") is tool_b


@pytest.mark.asyncio
async def test_lifecycle_token_change_with_identical_connection_rebuilds_only_a(discovery_cache, monkeypatch):
    """A same-fingerprint lifecycle ABA still re-discovers A and reuses B."""
    cfg = discovery_cache
    _write_config(cfg, {"A": _stdio("A"), "B": _stdio("B")}, tokens={"A": "1" * 32, "B": "2" * 32})
    discovery = _install(monkeypatch, _Discovery())
    tools1 = await cache_module.initialize_mcp_tools()
    tool_b = next(tool for tool in tools1 if tool.name == "B")

    _write_config(cfg, {"A": _stdio("A"), "B": _stdio("B")}, tokens={"A": "3" * 32, "B": "2" * 32})
    assert cache_module.refresh_mcp_cache_if_active() is True
    tools2 = await cache_module.initialize_mcp_tools()

    assert discovery.calls == [("A", "B"), ("A",)]
    assert next(tool for tool in tools2 if tool.name == "B") is tool_b


@pytest.mark.asyncio
async def test_declaration_reorder_rediscovers_nothing(discovery_cache, monkeypatch):
    """Reordering servers only re-flattens; zero discovery calls happen."""
    cfg = discovery_cache
    _write_config(cfg, {"A": _stdio("A"), "B": _stdio("B")})
    discovery = _install(monkeypatch, _Discovery())
    tools1 = await cache_module.initialize_mcp_tools()
    tool_a = next(tool for tool in tools1 if tool.name == "A")
    tool_b = next(tool for tool in tools1 if tool.name == "B")

    _write_config(cfg, {"B": _stdio("B"), "A": _stdio("A")})
    assert cache_module.refresh_mcp_cache_if_active() is True
    tools2 = await cache_module.initialize_mcp_tools()

    assert discovery.calls == [("A", "B")]
    assert _names(tools2) == ["B", "A"]
    assert tools2[0] is tool_b and tools2[1] is tool_a


@pytest.mark.asyncio
async def test_failed_discovery_publishes_siblings_without_caching_failure(discovery_cache, monkeypatch):
    """A failed server is absent (not a cached empty success); its sibling still publishes."""
    cfg = discovery_cache
    _write_config(cfg, {"A": _stdio("A"), "B": _stdio("B")})
    discovery = _install(monkeypatch, _Discovery())
    await cache_module.initialize_mcp_tools()

    discovery.fail.add("A")
    _write_config(cfg, {"A": _stdio("A", command="cmd-A2"), "B": _stdio("B")})
    assert cache_module.refresh_mcp_cache_if_active() is True
    tools = await cache_module.initialize_mcp_tools()

    assert _names(tools) == ["B"]
    assert "A" not in cache_module._server_tool_cache
    assert "B" in cache_module._server_tool_cache


@pytest.mark.asyncio
async def test_zero_tool_success_is_cached_and_not_rediscovered(discovery_cache, monkeypatch):
    """A successful zero-tool discovery is cached and reused (not re-requested)."""
    cfg = discovery_cache
    _write_config(cfg, {"A": _stdio("A"), "B": _stdio("B")})
    discovery = _install(monkeypatch, _Discovery(empty={"A"}))
    await cache_module.initialize_mcp_tools()

    assert cache_module._server_tool_cache["A"].result.tools == ()

    _write_config(cfg, {"A": _stdio("A"), "B": _stdio("B", command="cmd-B2")})
    assert cache_module.refresh_mcp_cache_if_active() is True
    tools = await cache_module.initialize_mcp_tools()

    assert discovery.calls == [("A", "B"), ("B",)]
    assert _names(tools) == ["B"]


@pytest.mark.asyncio
async def test_candidate_superseded_by_generation_is_not_published(discovery_cache, monkeypatch):
    """A generation bump mid-discovery discards the whole candidate.

    The trigger invalidates the claim without changing the config bytes or
    retiring the pool, so the generation check is the only guard that can reject
    the candidate (the post-read and binding checks would both still pass).
    """
    cfg = discovery_cache
    _write_config(cfg, {"A": _stdio("A")})
    discovery = _install(monkeypatch, _Discovery())

    async def supersede(_pool):
        with cache_module._init_condition:
            cache_module._invalidate_published_tools_locked()

    discovery.before_return["A"] = supersede
    tools = await cache_module.initialize_mcp_tools()

    assert tools == []
    assert cache_module._cache_initialized is False


@pytest.mark.asyncio
async def test_binding_rotation_during_discovery_discards_candidate(discovery_cache, monkeypatch):
    """A rotated binding for a *reused* sibling fails the whole publication."""
    cfg = discovery_cache
    servers = {"A": _stdio("A"), "B": _stdio("B")}
    _write_config(cfg, servers)
    discovery = _install(monkeypatch, _Discovery())
    await cache_module.initialize_mcp_tools()
    tool_b = cache_module._server_tool_cache["B"].result.tools[0]

    _write_config(cfg, {"A": _stdio("A", command="cmd-A2"), "B": _stdio("B")})
    assert cache_module.refresh_mcp_cache_if_active() is True

    async def rotate_b(pool):
        pool.reconcile_bindings({"B": _fingerprint(servers, "B")}, [], domain="deployment", force_rebind=("B",))

    discovery.before_return["A"] = rotate_b
    tools = await cache_module.initialize_mcp_tools()

    assert tools == []
    assert cache_module._cache_initialized is False
    # The stale B entry must never be re-published.
    assert cache_module._server_tool_cache["B"].result.tools[0] is tool_b


@pytest.mark.asyncio
async def test_explicit_reset_forces_full_rediscovery(discovery_cache, monkeypatch):
    """An explicit reset clears entries so the next init discovers every server again."""
    cfg = discovery_cache
    _write_config(cfg, {"A": _stdio("A"), "B": _stdio("B")})
    discovery = _install(monkeypatch, _Discovery())
    await cache_module.initialize_mcp_tools()

    cache_module.reset_mcp_tools_cache()
    await cache_module.initialize_mcp_tools()

    assert discovery.calls == [("A", "B"), ("A", "B")]


@pytest.mark.asyncio
async def test_cancelled_initializer_releases_claim(discovery_cache, monkeypatch):
    """Cancelling mid-discovery releases the claim so the next initializer proceeds."""
    cfg = discovery_cache
    _write_config(cfg, {"A": _stdio("A")})
    discovery = _install(monkeypatch, _Discovery())

    entered = asyncio.Event()
    release = asyncio.Event()

    async def gate(_pool):
        entered.set()
        await release.wait()

    discovery.before_return["A"] = gate
    task = asyncio.create_task(cache_module.initialize_mcp_tools())
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert cache_module._initializing_generation is None
    assert cache_module._cache_initialized is False

    discovery.before_return.pop("A")
    tools = await cache_module.initialize_mcp_tools()
    assert _names(tools) == ["A"]
    assert cache_module._cache_initialized is True


@pytest.mark.asyncio
async def test_personal_binding_is_never_reused_as_deployment(discovery_cache, monkeypatch):
    """A same-named personal binding must not satisfy the deployment reuse check."""
    cfg = discovery_cache
    _write_config(cfg, {"A": _stdio("A")})
    discovery = _install(monkeypatch, _Discovery())
    await cache_module.initialize_mcp_tools()

    pool = session_pool_module.get_session_pool()
    personal = pool.ensure_binding("A", "personal-fp", domain="personal")
    binding_a = pool._bindings[("deployment", "A")]

    _write_config(cfg, {"A": _stdio("A", command="cmd-A2")})
    assert cache_module.refresh_mcp_cache_if_active() is True
    await cache_module.initialize_mcp_tools()

    assert discovery.calls == [("A",), ("A",)]
    assert pool._bindings[("personal", "A")] is personal
    assert pool._bindings[("deployment", "A")] is not binding_a


def _structured_tool(name: str) -> StructuredTool:
    async def _call() -> str:
        return name

    return StructuredTool.from_function(coroutine=_call, name=name, description=name)


@pytest.mark.asyncio
async def test_unchanged_server_oauth_is_not_refetched(discovery_cache, monkeypatch):
    """A partial re-init only fetches OAuth headers for the re-discovered server."""
    cfg = discovery_cache
    _write_config(cfg, {"A": _stdio("A"), "B": _stdio("B")})

    oauth_requests: list[set[str]] = []

    async def fake_headers(extensions_config, *, token_manager=None, server_names=None):
        oauth_requests.append(set(server_names or ()))
        return {}

    monkeypatch.setattr("deerflow.mcp.tools.get_initial_oauth_headers", fake_headers)
    monkeypatch.setattr("deerflow.mcp.tools.build_mcp_tool_interceptors", lambda *args, **kwargs: [])

    class FakeClient:
        def __init__(self, connections, **kwargs) -> None:
            self.callbacks = kwargs.get("callbacks") or []
            self.tool_interceptors = kwargs.get("tool_interceptors") or []
            self.tool_name_prefix = kwargs.get("tool_name_prefix", True)

        async def get_tools(self, *, server_name=None):
            return [_structured_tool(server_name)]

    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient)

    await cache_module.initialize_mcp_tools()
    assert oauth_requests[-1] == {"A", "B"}

    _write_config(cfg, {"A": _stdio("A", command="cmd-A2"), "B": _stdio("B")})
    assert cache_module.refresh_mcp_cache_if_active() is True
    tools = await cache_module.initialize_mcp_tools()

    assert oauth_requests[-1] == {"A"}  # B's OAuth headers are not refetched
    assert sorted(tool.name for tool in tools) == ["A", "B"]


def _http(name: str, url: str | None = None) -> dict:
    return {"enabled": True, "type": "http", "url": url or f"https://{name.lower()}.test/mcp"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "before,after,fail_once",
    [
        ([], ["pkg.one:build"], False),
        (["pkg.one:build"], [], False),
        (["pkg.one:build"], ["pkg.two:build"], False),
        (["pkg.one:build", "pkg.two:build"], ["pkg.two:build", "pkg.one:build"], False),
        ("pkg.one:build", ["pkg.one:build"], False),
        ([], ["pkg.one:build"], True),
    ],
    ids=["add", "remove", "replace", "reorder", "equivalent-spelling", "failed-claim-retry"],
)
async def test_claim_time_interceptor_change_rewraps_unchanged_servers(discovery_cache, monkeypatch, before, after, fail_once):
    """A global change between reconciliation and the claim must reach every tool."""
    from langchain_mcp_adapters.tools import convert_mcp_tool_to_langchain_tool
    from mcp.types import CallToolResult, TextContent, Tool

    cfg = discovery_cache
    servers = {"A": _http("A"), "B": _http("B")}
    _write_config(cfg, servers, interceptors=before)
    discovered: list[str] = []
    invoked: list[tuple[str, str]] = []
    fail_discovery = False

    class OfflineSession:
        async def call_tool(self, name, arguments, **kwargs):
            return CallToolResult(content=[TextContent(type="text", text="ok")])

    class OfflineClient:
        def __init__(self, connections, *, tool_interceptors, **kwargs):
            self.tool_interceptors = tool_interceptors

        async def get_tools(self, *, server_name):
            discovered.append(server_name)
            if fail_discovery:
                raise RuntimeError("offline discovery failure")
            return [
                convert_mcp_tool_to_langchain_tool(
                    OfflineSession(),
                    Tool(name="probe", inputSchema={"type": "object", "properties": {}}),
                    server_name=server_name,
                    tool_interceptors=self.tool_interceptors,
                    tool_name_prefix=True,
                )
            ]

    def resolve_builder(path):
        async def interceptor(request, handler):
            invoked.append((request.server_name, path))
            return await handler(request)

        return lambda: interceptor

    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", OfflineClient)
    monkeypatch.setattr("deerflow.mcp.tools.resolve_variable", resolve_builder)
    initial_tools = await cache_module.initialize_mcp_tools()
    initial_b = next(tool for tool in initial_tools if tool.name == "B_probe")

    servers["A"] = _http("A", url="https://a.test/changed")
    _write_config(cfg, servers, interceptors=before)
    assert cache_module.refresh_mcp_cache_if_active() is True
    assert "B" in cache_module._server_tool_cache

    real_from_file = ExtensionsConfig.from_file
    change_pending = True

    def change_before_claim(*args, **kwargs):
        nonlocal change_pending
        if change_pending:
            change_pending = False
            _write_config(cfg, servers, interceptors=after)
        return real_from_file(*args, **kwargs)

    monkeypatch.setattr(ExtensionsConfig, "from_file", change_before_claim)
    if fail_once:
        fail_discovery = True
        with pytest.raises(RuntimeError, match="no results"):
            await cache_module.initialize_mcp_tools()
        assert cache_module._initializing_generation is None
        fail_discovery = False

    updated_tools = await cache_module.initialize_mcp_tools()
    for tool in updated_tools:
        await tool.ainvoke({})
    assert invoked == [(name, path) for name in ("A", "B") for path in after]

    repeated_tools = await asyncio.to_thread(cache_module.get_cached_mcp_tools)
    assert all(current is repeated for current, repeated in zip(updated_tools, repeated_tools, strict=True))
    invoked.clear()
    for tool in repeated_tools:
        await tool.ainvoke({})
    assert invoked == [(name, path) for name in ("A", "B") for path in after]

    changed = ([before] if isinstance(before, str) else before) != after
    assert discovered == ["A", "B", *(["A", "B"] if fail_once else []), "A", *(["B"] if changed else [])]
    updated_b = next(tool for tool in updated_tools if tool.name == "B_probe")
    assert (updated_b is initial_b) is (not changed)


@pytest.mark.asyncio
async def test_interceptor_change_without_baseline_drops_retained_entries(discovery_cache, monkeypatch):
    """With no applied baseline, a retained HTTP entry must not outlive an interceptor change."""
    cfg = discovery_cache
    _write_config(cfg, {"A": _http("A")})
    _install(monkeypatch, _Discovery())
    await cache_module.initialize_mcp_tools()
    assert "A" in cache_module._server_tool_cache

    # Conservative state: entries retained but the comparing baseline is gone.
    cache_module._applied_mcp_revision = None
    cache_module._cache_initialized = False

    cfg.write_text(json.dumps({"mcpServers": {"A": _http("A")}, "skills": {}, "mcpInterceptors": ["pkg.mod:build"]}), encoding="utf-8")
    assert cache_module.refresh_mcp_cache_if_active() is True

    assert cache_module._server_tool_cache == {}


def test_shared_reset_counts_retained_entries(discovery_cache):
    """A retained per-server entry must make a shared reset consider local state."""
    pool = session_pool_module.get_session_pool()
    assert cache_module._shared_reset_has_local_state_locked(pool) is False

    cache_module._server_tool_cache["A"] = cache_module._ServerToolCacheEntry(
        snapshot="orphan",
        interceptors="[]",
        result=ServerDiscoveryResult(tools=()),
    )

    assert cache_module._shared_reset_has_local_state_locked(pool) is True


@pytest.mark.asyncio
async def test_total_discovery_failure_does_not_publish_empty_success(discovery_cache, monkeypatch):
    """Every enabled server failing is a phase-level failure, not a cached empty success."""
    cfg = discovery_cache
    _write_config(cfg, {"A": _stdio("A"), "B": _stdio("B")})
    _install(monkeypatch, _Discovery(fail={"A", "B"}))

    with pytest.raises(RuntimeError):
        await cache_module.initialize_mcp_tools()

    assert cache_module._cache_initialized is False
    assert cache_module._initializing_generation is None
    assert cache_module._server_tool_cache == {}


@pytest.mark.asyncio
async def test_import_failure_after_claim_releases_generation(discovery_cache, monkeypatch):
    """A lazy-import failure must not strand the initialization claim."""
    cfg = discovery_cache
    _write_config(cfg, {"A": _stdio("A")})
    real_import = builtins.__import__

    def failing_import(name, *args, **kwargs):
        if name == "deerflow.mcp.tools":
            raise ImportError("simulated missing adapter module")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", failing_import)

    with pytest.raises(ImportError):
        await cache_module.initialize_mcp_tools()

    assert cache_module._initializing_generation is None


def test_lazy_init_failure_does_not_log_resolved_credentials(discovery_cache, monkeypatch, caplog):
    """A stage-level discovery failure must not print a resolved-credential message."""
    cfg = discovery_cache
    _write_config(cfg, {"A": _http("A")})
    secret = "s3cr3t-pass-123"

    async def boom(*args, **kwargs):
        raise RuntimeError(f"discovery failed for url 'https://alice:{secret}@remote.test/mcp'")

    monkeypatch.setattr("deerflow.mcp.tools.get_mcp_tools_by_server", boom)

    with caplog.at_level(logging.DEBUG):
        assert cache_module.get_cached_mcp_tools() == []

    assert secret not in caplog.text


@pytest.mark.asyncio
async def test_committed_interceptor_change_without_baseline_drops_retained_entries(discovery_cache, monkeypatch):
    """The committed-writer path mirrors the reader's no-baseline interceptor guard."""
    cfg = discovery_cache
    _write_config(cfg, {"A": _http("A")})
    _install(monkeypatch, _Discovery())
    await cache_module.initialize_mcp_tools()
    assert "A" in cache_module._server_tool_cache

    cache_module._applied_mcp_revision = None
    cache_module._cache_initialized = False

    committed = ExtensionsConfig.model_validate({"mcpServers": {"A": _http("A")}, "mcpInterceptors": ["pkg.mod:build"]})
    cache_module.finish_mcp_reconciliation(cache_module.prepare_mcp_reconciliation(committed, config_path=cfg))

    assert cache_module._server_tool_cache == {}
