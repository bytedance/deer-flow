"""Child-process entry point for the cross-process MCP lifecycle harness.

Every worker is a genuinely independent Python process: it imports its own copy
of the ``deerflow`` module globals and builds its own ``MCPSessionPool``. It
installs an in-process fake MCP session context manager (so no real MCP
subprocess is ever spawned) and speaks a deterministic JSON-line command
protocol on stdin/stdout. The *real* cache / commit code drives the shared
``extensions_config.json``.

Protocol
--------
One JSON object per line on stdin produces one or more JSON objects on stdout.
Every reply is ``{"type": "reply", ...}``. A gated discovery additionally emits
``{"type": "event", "event": "discovery_entered"}`` before it blocks reading a
``{"cmd": "release_discovery"}`` line, so the harness can mutate the shared file
*while this worker is mid-discovery* without ever sleeping.

Commands
--------
``publish``       commit ``servers`` (and optional ``interceptors``/``skills``)
                  through the real commit path, then initialize the tool cache.
``commit``        apply one ``mutation`` through the real commit path and fence.
``client_commit`` drive the same mutation family through the embedded client.
``open``          open a pooled session for a server and remember its binding.
``probe_held``    re-enter the session pool with the *held* binding.
``check``         run the lazy cross-process check (``refresh_mcp_cache_if_active``).
``refresh``       run tool assembly (``get_cached_mcp_tools``).
``state``         report the applied lifecycle, binding epochs and closed flags.
``read_raw``      report the on-disk raw document.

No sleeps are used anywhere: ordering is enforced by blocking on stdin or on the
cross-process sidecar config lock.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

# Keep the protocol pipe clean. Logging already defaults to stderr, but a stray
# ``print`` from any library would corrupt a frame, so redirect ``sys.stdout``
# and write replies to the saved protocol handle instead.
_PROTOCOL_OUT = sys.stdout
sys.stdout = sys.stderr

_MISSING = object()


def _emit(message: dict[str, Any]) -> None:
    _PROTOCOL_OUT.write(json.dumps(message) + "\n")
    _PROTOCOL_OUT.flush()


def _read_line() -> str:
    line = sys.stdin.readline()
    if line == "":
        raise EOFError("stdin closed while waiting for a protocol line")
    return line


# ---------------------------------------------------------------------------
# In-process fakes: no real MCP subprocess is ever spawned.
# ---------------------------------------------------------------------------


class _FakeSession:
    def __init__(self, name: str) -> None:
        self.name = name
        self.closed = False

    async def initialize(self) -> None:
        return None


class _FakeSessionCm:
    def __init__(self, connection: dict[str, Any]) -> None:
        self.connection = connection
        self.session = _FakeSession(str(connection.get("command")))

    async def __aenter__(self) -> _FakeSession:
        return self.session

    async def __aexit__(self, *exc: Any) -> bool:
        self.session.closed = True
        return False


def _install_fake_session_cm() -> None:
    import langchain_mcp_adapters.sessions as sessions

    sessions.create_session = _FakeSessionCm  # type: ignore[assignment]


# Set by the ``publish`` command; consumed by the discovery hook below.
_GATE_DISCOVERY = False


async def _fake_get_mcp_tools(*, extensions_config):
    from deerflow.mcp.client import build_server_params
    from deerflow.mcp.session_pool import get_session_pool, normalized_connection_fingerprint

    pool = get_session_pool()
    tools = []
    for name, server in extensions_config.get_enabled_mcp_servers().items():
        params = build_server_params(name, server)
        if params.get("transport") != "stdio":
            continue
        pool.ensure_binding(name, normalized_connection_fingerprint(params))
        tools.append(f"{name}:{server.description or server.command}")
    if _GATE_DISCOVERY:
        _emit({"type": "event", "event": "discovery_entered"})
        command = json.loads(_read_line())
        if command.get("cmd") != "release_discovery":
            raise RuntimeError(f"expected release_discovery, got {command!r}")
    return tools


def _install_fake_discovery() -> None:
    import deerflow.mcp.tools as tools

    tools.get_mcp_tools = _fake_get_mcp_tools  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Mutation helpers
# ---------------------------------------------------------------------------


def _connection(server: str) -> dict[str, Any]:
    return {"transport": "stdio", "command": server, "args": []}


def _apply_mutation(raw: dict[str, Any], mutation: dict[str, Any]) -> dict[str, Any]:
    """Apply one declarative mutation to a deep copy of the raw document."""
    data = copy.deepcopy(raw)
    data.setdefault("mcpServers", {})
    servers = data["mcpServers"]
    op = mutation["op"]
    if op == "noop":
        pass
    elif op == "set_all":
        data["mcpServers"] = copy.deepcopy(mutation["servers"])
        if "interceptors" in mutation:
            data["mcpInterceptors"] = copy.deepcopy(mutation["interceptors"])
        if "skills" in mutation:
            data["skills"] = copy.deepcopy(mutation["skills"])
    elif op == "delete":
        servers.pop(mutation["server"], None)
    elif op == "add":
        name = mutation["server"]
        entry = copy.deepcopy(mutation["server_config"])
        index = mutation.get("index")
        if index is None:
            servers[name] = entry
        else:
            items = [(n, v) for n, v in servers.items() if n != name]
            items.insert(int(index), (name, entry))
            data["mcpServers"] = dict(items)
    elif op == "set_enabled":
        servers[mutation["server"]]["enabled"] = bool(mutation["enabled"])
    elif op == "set_command":
        servers[mutation["server"]]["command"] = mutation["command"]
    elif op == "set_description":
        servers[mutation["server"]]["description"] = mutation["description"]
    elif op == "set_interceptors":
        data["mcpInterceptors"] = copy.deepcopy(mutation["interceptors"])
    elif op == "set_skills":
        data["skills"] = copy.deepcopy(mutation["skills"])
    elif op == "reorder":
        data["mcpServers"] = {name: servers[name] for name in mutation["order"]}
    else:
        raise RuntimeError(f"unknown mutation op {op!r}")
    return data


class _Worker:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.loop = asyncio.new_event_loop()
        self.opened: dict[tuple[str, str], _FakeSession] = {}
        self.held_bindings: dict[str, Any] = {}

    # -- async helpers -----------------------------------------------------

    def run(self, coro):
        return self.loop.run_until_complete(coro)

    def open_session(self, server: str, scope: str):
        from deerflow.mcp.session_pool import get_session_pool

        pool = get_session_pool()
        binding = pool.active_binding(server)
        if binding is None:
            raise RuntimeError(f"{server} has no active binding to open")
        session = self.run(pool.get_session(server, scope, _connection(server), binding=binding))
        self.opened[(server, scope)] = session
        self.held_bindings[server] = binding
        return binding

    def probe_held(self, server: str, scope: str) -> bool:
        """True when the binding captured at ``open`` time is now stale."""
        from deerflow.mcp.session_pool import StaleMCPBindingError, get_session_pool

        binding = self.held_bindings.get(server)
        if binding is None:
            raise RuntimeError(f"no held binding for {server}; run 'open' first")
        pool = get_session_pool()
        try:
            self.run(pool.get_session(server, scope, _connection(server), binding=binding))
        except StaleMCPBindingError:
            return True
        return False

    # -- commit paths ------------------------------------------------------

    def commit(self, mutation: dict[str, Any], *, fault: str | None = None) -> None:
        from deerflow.config.extensions_config import (
            extensions_config_file_lock,
            extensions_config_write_lock,
            read_raw_extensions_config,
            validate_raw_extensions_config,
        )
        from deerflow.mcp.cache import (
            finish_mcp_reconciliation,
            force_local_mcp_invalidation,
            prepare_mcp_reconciliation_from_revision,
        )
        from deerflow.mcp.commit import (
            MCPCommitOutcomeUnknownError,
            MCPCommittedNotReconciledError,
            MCPCommittedReloadFailedError,
            commit_extensions_config,
            validate_previous_config_lenient,
        )
        from deerflow.mcp.tasks.runtime import McpTaskConfigurationError

        path = self.config_path
        pending = None
        try:
            with extensions_config_write_lock, extensions_config_file_lock(path):
                raw = read_raw_extensions_config(path)
                previous = validate_previous_config_lenient(raw)
                new_raw = _apply_mutation(raw, mutation)
                new_config = validate_raw_extensions_config(new_raw)
                committed = commit_extensions_config(
                    config_path=path,
                    raw_data=new_raw,
                    previous_config=previous,
                    new_config=new_config,
                )
                try:
                    if fault == "fence":
                        raise RuntimeError("injected local reconciliation fence failure")
                    pending = prepare_mcp_reconciliation_from_revision(committed)
                except McpTaskConfigurationError as exc:
                    raise MCPCommittedNotReconciledError(
                        "MCP configuration was committed to disk but the local reconciliation fence rejected it against the frozen durable-task snapshot",
                    ) from exc
                except Exception as exc:
                    raise MCPCommittedNotReconciledError(
                        "MCP configuration was committed to disk but the local reconciliation fence failed; the caller must conservatively invalidate local MCP state",
                    ) from exc
                if fault == "reload":
                    raise MCPCommittedReloadFailedError("injected in-process reload failure")
        except (MCPCommitOutcomeUnknownError, MCPCommittedNotReconciledError):
            # Locks are released here; never wait for teardown holding them.
            force_local_mcp_invalidation()
            raise
        finally:
            finish_mcp_reconciliation(pending)

    def client_commit(self, servers: dict[str, Any]) -> None:
        """Drive the embedded-client writer (its own lock + commit + fence)."""
        from unittest.mock import MagicMock

        import deerflow.client as client_module

        app_config = MagicMock()
        app_config.database.checkpoint_channel_mode = "full"
        app_config.database.checkpoint_delta.snapshot_frequency = 10
        original = client_module.get_app_config
        client_module.get_app_config = lambda: app_config  # type: ignore[assignment]
        try:
            client = client_module.DeerFlowClient()
            client.update_mcp_config(servers)
        finally:
            client_module.get_app_config = original  # type: ignore[assignment]

    def publish(
        self,
        servers: dict[str, Any],
        *,
        interceptors: Any = _MISSING,
        skills: Any = _MISSING,
        gate_discovery: bool = False,
    ) -> None:
        global _GATE_DISCOVERY

        mutation: dict[str, Any] = {"op": "set_all", "servers": servers}
        if interceptors is not _MISSING:
            mutation["interceptors"] = interceptors
        if skills is not _MISSING:
            mutation["skills"] = skills
        self.commit(mutation)

        _GATE_DISCOVERY = bool(gate_discovery)
        from deerflow.mcp.cache import initialize_mcp_tools

        self.run(initialize_mcp_tools())
        _GATE_DISCOVERY = False

    def check(self) -> bool:
        from deerflow.mcp.cache import refresh_mcp_cache_if_active

        return bool(refresh_mcp_cache_if_active())

    def refresh(self) -> None:
        from deerflow.mcp.cache import get_cached_mcp_tools

        get_cached_mcp_tools()

    def shutdown(self) -> None:
        from deerflow.mcp.session_pool import get_session_pool

        try:
            get_session_pool().close_all_sync()
        except Exception:  # pragma: no cover - best-effort child cleanup
            pass
        try:
            self.loop.close()
        except Exception:  # pragma: no cover - defensive
            pass


# ---------------------------------------------------------------------------
# Reply assembly + dispatch
# ---------------------------------------------------------------------------


def _state_reply(cmd: Any, worker: _Worker, **extra: Any) -> dict[str, Any]:
    import deerflow.mcp.cache as cache_module
    from deerflow.mcp.session_pool import get_session_pool

    pool = get_session_pool()
    bindings: dict[str, Any] = {}
    with pool._lock:
        for name, binding in pool._bindings.items():
            bindings[name] = {"epoch": binding.epoch, "fingerprint": binding.fingerprint}
    sessions = {f"{name}|{scope}": bool(session.closed) for (name, scope), session in worker.opened.items()}
    applied = cache_module._mcp_applied_lifecycle
    reply = {
        "type": "reply",
        "cmd": cmd,
        "cache_initialized": bool(cache_module._cache_initialized),
        "applied_lifecycle": None if applied is None else applied.model_dump(by_alias=True),
        "applied_lifecycle_invalid": bool(cache_module._mcp_applied_lifecycle_invalid),
        "bindings": bindings,
        "sessions": sessions,
    }
    reply.update(extra)
    return reply


def _dispatch(worker: _Worker, command: dict[str, Any]) -> dict[str, Any]:
    cmd = command.get("cmd")
    if cmd == "publish":
        worker.publish(
            command["servers"],
            interceptors=command.get("interceptors", _MISSING),
            skills=command.get("skills", _MISSING),
            gate_discovery=bool(command.get("gate_discovery", False)),
        )
        return _state_reply(cmd, worker)
    if cmd == "commit":
        worker.commit(command["mutation"], fault=command.get("fault"))
        return _state_reply(cmd, worker)
    if cmd == "client_commit":
        worker.client_commit(command["servers"])
        return _state_reply(cmd, worker)
    if cmd == "open":
        binding = worker.open_session(command["server"], command.get("scope", "t1"))
        return _state_reply(cmd, worker, opened={"server": command["server"], "epoch": binding.epoch})
    if cmd == "probe_held":
        stale = worker.probe_held(command["server"], command.get("scope", "t1"))
        return _state_reply(cmd, worker, stale=stale)
    if cmd == "check":
        retired = worker.check()
        return _state_reply(cmd, worker, retired=retired)
    if cmd == "refresh":
        worker.refresh()
        return _state_reply(cmd, worker)
    if cmd == "state":
        return _state_reply(cmd, worker)
    if cmd == "read_raw":
        from deerflow.config.extensions_config import read_raw_extensions_config

        return {"type": "reply", "cmd": cmd, "raw": read_raw_extensions_config(worker.config_path)}
    raise RuntimeError(f"unknown command {cmd!r}")


def main() -> int:
    config_path = Path(os.environ["DEER_FLOW_EXTENSIONS_CONFIG_PATH"])
    _install_fake_session_cm()
    _install_fake_discovery()
    worker = _Worker(config_path)
    try:
        while True:
            line = sys.stdin.readline()
            if line == "":
                break
            line = line.strip()
            if not line:
                continue
            command = json.loads(line)
            try:
                reply = _dispatch(worker, command)
            except Exception as exc:  # surface the failure *with* the local state
                reply = _state_reply(command.get("cmd"), worker, error=f"{type(exc).__name__}: {exc}")
            _emit(reply)
    finally:
        worker.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
