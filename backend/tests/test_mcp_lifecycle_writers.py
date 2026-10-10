"""Gateway writer coverage for the shared ``mcpLifecycle`` generation."""

from __future__ import annotations

import json

import pytest

# Reuse the process-local isolation fixture so these writer tests do not leak
# cache globals or the session-pool singleton.
from test_mcp_cache_reconciliation import reconciler  # noqa: F401

from app.gateway.routers import mcp as mcp_router
from app.gateway.routers.mcp import (
    McpConfigUpdateRequest,
    McpServerConfigResponse,
    McpServerConfigUpdateRequest,
    McpServerStateUpdateRequest,
)
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.lifecycle import _stdio_fingerprints, legacy_token, parse_mcp_lifecycle


def _stdio(command: str) -> dict:
    return {"enabled": True, "type": "stdio", "command": command}


def _write(cfg, servers: dict) -> None:
    cfg.write_text(json.dumps({"mcpServers": servers, "skills": {}}), encoding="utf-8")


def _ledger(cfg):
    return parse_mcp_lifecycle(json.loads(cfg.read_text(encoding="utf-8")))


def _legacy(cfg, name: str) -> str:
    fingerprint = _stdio_fingerprints(ExtensionsConfig.from_file(str(cfg)))[name]
    return legacy_token(name, fingerprint)


def test_state_disable_and_reenable_advance_the_generation(
    reconciler,  # noqa: F811 - fixture imported from the sibling suite
    monkeypatch,
    tmp_path,
):
    """Raw in-place mutation must not hide the enabled -> disabled transition."""
    cfg = tmp_path / "extensions_config.json"
    _write(cfg, {"A": _stdio("npx")})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))
    baseline = _legacy(cfg, "A")

    mcp_router._apply_mcp_server_state_update(McpServerStateUpdateRequest(server_name="A", enabled=False))
    disabled = _ledger(cfg).servers["A"]
    assert disabled != baseline

    mcp_router._apply_mcp_server_state_update(McpServerStateUpdateRequest(server_name="A", enabled=True))
    reenabled = _ledger(cfg).servers["A"]
    assert reenabled not in {baseline, disabled}


def test_delete_then_identical_readd_advance_the_generation(
    reconciler,  # noqa: F811 - fixture imported from the sibling suite
    monkeypatch,
    tmp_path,
):
    """Delete tombstones the token and an identical re-add must rotate it again."""
    cfg = tmp_path / "extensions_config.json"
    _write(cfg, {"A": _stdio("npx")})
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    mcp_router._apply_mcp_server_delete("A")
    tombstone = _ledger(cfg).servers["A"]

    mcp_router._apply_mcp_servers_create(
        McpConfigUpdateRequest(
            mcp_servers={"A": McpServerConfigResponse(enabled=True, type="stdio", command="npx")},
        )
    )
    rebound = _ledger(cfg).servers["A"]
    assert rebound != tombstone


def test_commit_helper_requires_previous_raw():
    """A controlled write must not be able to skip the lifecycle commit."""
    import inspect

    parameters = inspect.signature(mcp_router._commit_mcp_config_write).parameters
    assert parameters["previous_raw"].default is inspect.Parameter.empty


def test_bulk_update_rotates_only_the_changed_server_token(
    reconciler,  # noqa: F811 - fixture imported from the sibling suite
    monkeypatch,
    tmp_path,
):
    """A connection change rotates only that server's token; $VAR stays raw."""
    cfg = tmp_path / "extensions_config.json"
    cfg.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "A": {"enabled": True, "type": "stdio", "command": "npx", "args": ["pkg-v1"]},
                    "B": {"enabled": True, "type": "stdio", "command": "npx", "args": ["pkg-b"], "env": {"TOKEN": "$PE_VAR"}},
                },
                "skills": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))
    monkeypatch.setenv("PE_VAR", "secret-value")
    baseline_a = _legacy(cfg, "A")

    mcp_router._apply_mcp_config_update(
        McpConfigUpdateRequest(
            mcp_servers={
                "A": McpServerConfigResponse(enabled=True, type="stdio", command="npx", args=["pkg-v2"]),
                "B": McpServerConfigResponse(enabled=True, type="stdio", command="npx", args=["pkg-b"], env={"TOKEN": "$PE_VAR"}),
            }
        )
    )

    ledger = _ledger(cfg)
    assert ledger is not None
    assert ledger.servers["A"] != baseline_a  # the connection changed
    assert "B" not in ledger.servers  # unchanged legacy server stays derived
    written = cfg.read_text(encoding="utf-8")
    assert "$PE_VAR" in written
    assert "secret-value" not in written


@pytest.mark.asyncio
async def test_targeted_metadata_update_keeps_token_and_session(
    reconciler,  # noqa: F811 - fixture imported from the sibling suite
    monkeypatch,
    tmp_path,
):
    """A metadata-only targeted update must not rotate the token or the session."""
    import test_mcp_cache_reconciliation as harness

    from deerflow.mcp import session_pool as session_pool_module
    from deerflow.mcp.session_pool import MCPSessionPool

    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = harness._session_log()
    await harness._initialize(monkeypatch, cfg, {"A": _stdio("npx")}, log)

    binding_before = harness._binding(pool, "A")
    entry_before = harness._entry(pool, "A")

    mcp_router._apply_mcp_server_config_update(
        McpServerConfigUpdateRequest(
            server_name="A",
            server=McpServerConfigResponse(enabled=True, type="stdio", command="npx", description="renamed"),
        )
    )

    ledger = _ledger(cfg)
    assert ledger is not None and "A" not in ledger.servers  # metadata-only: no token
    assert harness._binding(pool, "A") is binding_before
    assert harness._entry(pool, "A") is entry_before
    assert json.loads(cfg.read_text(encoding="utf-8"))["mcpServers"]["A"]["description"] == "renamed"
