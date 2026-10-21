"""Cross-worker (two-process) coverage for missed-history MCP ABA.

Problem this pins
-----------------
MCP reconciliation is *process-local*.  A Gateway worker installs a binding
epoch only for the transitions it personally observes.  A second worker sharing
the same ``extensions_config.json`` never runs that write, so the only thing it
can observe is the file it finds on its next staleness check.

A single process that commits A(v1) -> delete(A) -> A(v1) still advances A's
epoch: the committed planner compares each committed revision against the applied
baseline and therefore sees the intermediate delete.  That guarantee does not
survive across workers: W2's final file is equivalent to the revision W1 already
applied, so the read-side planner's "effective configuration unchanged" fast path
keeps A's old session.

This file is the end-to-end acceptance test for the shared ``mcpLifecycle``
generation ledger.  The writer is a real ``subprocess`` with its own
module globals, cache and session pool, committing through the same primitive the
Gateway routes use (``plan_mcp_lifecycle`` -> atomic write -> committed fence).
Asserting against one shared in-memory cache would not prove cross-process
behavior, so it is not done here.  No test-side token injection or explicit reset
is used to make these pass.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# Reuse the process-local harness (config writer, recording sessions, fake
# discovery) so reader state is built exactly like the sibling suite.
from test_mcp_cache_reconciliation import (  # noqa: F401  (``reconciler`` fixture)
    _binding,
    _entry,
    _fingerprint,
    _initialize,
    _session_log,
    _stdio,
    _wait_until,
    _write_config,
    reconciler,
)

import deerflow.mcp.cache as cache_module
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp import session_pool as session_pool_module
from deerflow.mcp.session_pool import MCPSessionPool, StaleMCPBindingError

# One Gateway worker committing A's delete + identical re-add against the shared
# config, in a separate interpreter.  It prints its own epochs so the reader can
# prove the writer genuinely retired A before asserting that the reader does not.
_PEER_WORKER_PROGRAM = textwrap.dedent(
    """
    import copy
    import json
    import os
    from pathlib import Path

    from deerflow.config.extensions_config import (
        ExtensionsConfig,
        atomic_write_extensions_config,
        extensions_config_file_lock,
        extensions_config_write_lock,
        reload_extensions_config,
        validate_raw_extensions_config,
    )
    from deerflow.mcp import cache as cache_module
    from deerflow.mcp import session_pool as session_pool_module
    from deerflow.mcp.client import build_servers_config
    from deerflow.mcp.lifecycle import LIFECYCLE_KEY, plan_mcp_lifecycle
    from deerflow.mcp.session_pool import normalized_connection_fingerprint

    cfg = Path(os.environ["DEER_FLOW_EXTENSIONS_CONFIG_PATH"])
    raw = json.loads(cfg.read_text(encoding="utf-8"))
    original_a = raw["mcpServers"]["A"]

    # W2 is a live worker: it already holds deployment bindings for A and B.
    pool = session_pool_module.get_session_pool()
    baseline = ExtensionsConfig.from_file(str(cfg))
    for name, connection in build_servers_config(baseline).items():
        pool.ensure_binding(
            name,
            normalized_connection_fingerprint(connection),
            domain="deployment",
        )
    cache_module.finish_mcp_reconciliation(
        cache_module.prepare_mcp_reconciliation(baseline, config_path=cfg)
    )
    a_epoch_baseline = pool._bindings[("deployment", "A")].epoch
    b_epoch_baseline = pool._bindings[("deployment", "B")].epoch


    def commit(previous, candidate):
        # Mirrors the controlled writer: validate the exact candidate, persist
        # config + ledger atomically, then install the fence under the config
        # write lock and finish teardown after releasing it.
        candidate[LIFECYCLE_KEY] = plan_mcp_lifecycle(previous, candidate)
        candidate_model = validate_raw_extensions_config(candidate)
        with extensions_config_write_lock, extensions_config_file_lock(cfg):
            atomic_write_extensions_config(cfg, candidate)
            reload_extensions_config(str(cfg))
            pending = cache_module.prepare_mcp_reconciliation(
                candidate_model, config_path=cfg
            )
        cache_module.finish_mcp_reconciliation(pending)


    # delete A (candidate is independent of the previous raw dict)
    previous = copy.deepcopy(raw)
    candidate = copy.deepcopy(raw)
    del candidate["mcpServers"]["A"]
    commit(previous, candidate)
    a_epoch_after_delete = pool._bindings[("deployment", "A")].epoch

    # identical re-add, same declaration order as the original file
    previous = copy.deepcopy(candidate)
    candidate = copy.deepcopy(candidate)
    candidate["mcpServers"] = {"A": original_a, **candidate["mcpServers"]}
    commit(previous, candidate)
    a_epoch_after_readd = pool._bindings[("deployment", "A")].epoch
    b_epoch_after_readd = pool._bindings[("deployment", "B")].epoch

    print(json.dumps({
        "a_epoch_baseline": a_epoch_baseline,
        "a_epoch_after_delete": a_epoch_after_delete,
        "a_epoch_after_readd": a_epoch_after_readd,
        "b_epoch_baseline": b_epoch_baseline,
        "b_epoch_after_readd": b_epoch_after_readd,
    }))
    """
)


# A second worker committing the same ABA through the real Gateway mutation
# routes (not the plan/write primitive), so the cross-process test covers the
# full controlled-writer protocol: locks -> read -> candidate -> plan ->
# validate -> write -> committed fence.
_GATEWAY_WRITER_PROGRAM = textwrap.dedent(
    """
    import json
    import os
    from pathlib import Path

    from app.gateway.routers import mcp as mcp_router
    from app.gateway.routers.mcp import McpConfigUpdateRequest, McpServerConfigResponse
    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.mcp import cache as cache_module
    from deerflow.mcp import session_pool as session_pool_module
    from deerflow.mcp.client import build_servers_config
    from deerflow.mcp.session_pool import normalized_connection_fingerprint

    cfg = Path(os.environ["DEER_FLOW_EXTENSIONS_CONFIG_PATH"])
    pool = session_pool_module.get_session_pool()
    baseline = ExtensionsConfig.from_file(str(cfg))
    for name, connection in build_servers_config(baseline).items():
        pool.ensure_binding(
            name,
            normalized_connection_fingerprint(connection),
            domain="deployment",
        )
    cache_module.finish_mcp_reconciliation(
        cache_module.prepare_mcp_reconciliation(baseline, config_path=cfg)
    )
    a_epoch_baseline = pool._bindings[("deployment", "A")].epoch
    b_epoch_baseline = pool._bindings[("deployment", "B")].epoch

    mcp_router._apply_mcp_server_delete("A")
    a_epoch_after_delete = pool._bindings[("deployment", "A")].epoch

    mcp_router._apply_mcp_servers_create(
        McpConfigUpdateRequest(
            mcp_servers={
                "A": McpServerConfigResponse(enabled=True, type="stdio", command="npx")
            }
        )
    )
    a_epoch_after_readd = pool._bindings[("deployment", "A")].epoch
    b_epoch_after_readd = pool._bindings[("deployment", "B")].epoch

    print(json.dumps({
        "a_epoch_baseline": a_epoch_baseline,
        "a_epoch_after_delete": a_epoch_after_delete,
        "a_epoch_after_readd": a_epoch_after_readd,
        "b_epoch_baseline": b_epoch_baseline,
        "b_epoch_after_readd": b_epoch_after_readd,
    }))
    """
)


def _run_worker(program: str, config_path: Path) -> dict:
    """Run one writer program in a second, independent interpreter."""
    env = os.environ.copy()
    env["DEER_FLOW_EXTENSIONS_CONFIG_PATH"] = str(config_path)
    completed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=str(Path(__file__).resolve().parent.parent),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, f"peer worker failed ({completed.returncode})\n--- stdout ---\n{completed.stdout}\n--- stderr ---\n{completed.stderr}"
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _run_peer_worker(config_path: Path) -> dict:
    """Commit delete(A) + identical re-add(A) through the plan/commit primitive."""
    return _run_worker(_PEER_WORKER_PROGRAM, config_path)


def _run_gateway_writer(config_path: Path) -> dict:
    """Commit delete(A) + identical re-add(A) through the real Gateway routes."""
    return _run_worker(_GATEWAY_WRITER_PROGRAM, config_path)


@pytest.mark.asyncio
async def test_peer_worker_delete_then_identical_readd_retires_only_that_server(
    reconciler,  # noqa: F811 - fixture imported from the sibling process-local suite
    monkeypatch,
    tmp_path,
):
    """A worker that never saw the delete must still retire A, and only A."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    servers = {"A": _stdio("cmd-A"), "B": _stdio("cmd-B")}
    await _initialize(monkeypatch, cfg, servers, log)

    snapshot_before = cache_module._mcp_config_snapshot
    binding_a_before = _binding(pool, "A")
    binding_b_before = _binding(pool, "B")
    entry_b_before = _entry(pool, "B")

    peer = _run_peer_worker(cfg)

    # Premise: W2 really committed the history and retired A locally. Its A
    # advances through a tombstone and a fresh binding while B is untouched.
    assert peer["a_epoch_after_delete"] > peer["a_epoch_baseline"]
    assert peer["a_epoch_after_readd"] > peer["a_epoch_after_delete"]
    assert peer["b_epoch_after_readd"] == peer["b_epoch_baseline"]

    # Premise: the final effective MCP slice W1 can read is the one it already
    # applied, yet the file (and its lifecycle ledger) changed underneath it.
    final_config = ExtensionsConfig.from_file(str(cfg))
    assert cache_module._effective_mcp_config_snapshot(final_config) == snapshot_before
    assert cache_module._get_config_signature(cfg) != cache_module._config_signature

    # Contract: observing the shared lifecycle history retires A (new
    # epoch, old session closed) while leaving B's binding/session intact.
    changed = cache_module.refresh_mcp_cache_if_active()
    assert changed is True

    binding_a_after = _binding(pool, "A")
    assert binding_a_after is not binding_a_before
    assert binding_a_after.epoch > binding_a_before.epoch

    assert _binding(pool, "B") is binding_b_before
    assert _entry(pool, "B") is entry_b_before

    await _wait_until(lambda: log["exited"].get("cmd-A") == 1)
    assert log["exited"].get("cmd-B") is None

    # Idempotency: the token is recorded in the applied revision, so observing
    # the same generation again is a no-op (force_rebind is one-shot).
    assert cache_module.refresh_mcp_cache_if_active() is False
    assert _binding(pool, "A") is binding_a_after


@pytest.mark.asyncio
async def test_real_gateway_writer_delete_then_identical_readd_is_consumed_cross_process(
    reconciler,  # noqa: F811 - fixture imported from the sibling process-local suite
    monkeypatch,
    tmp_path,
):
    """The real Gateway delete/create writers must produce a cross-process-consumable ABA."""
    cfg = tmp_path / "extensions_config.json"
    pool = MCPSessionPool()
    session_pool_module._pool = pool
    log = _session_log()
    # Initial order is B, A because the real create route appends the re-added A
    # at the end, which then reproduces this exact declaration order.
    servers = {"B": _stdio("cmd-B"), "A": _stdio("npx")}
    await _initialize(monkeypatch, cfg, servers, log)

    snapshot_before = cache_module._mcp_config_snapshot
    binding_a_before = _binding(pool, "A")
    binding_b_before = _binding(pool, "B")
    entry_b_before = _entry(pool, "B")

    peer = _run_gateway_writer(cfg)

    assert peer["a_epoch_after_delete"] > peer["a_epoch_baseline"]
    assert peer["a_epoch_after_readd"] > peer["a_epoch_after_delete"]
    assert peer["b_epoch_after_readd"] == peer["b_epoch_baseline"]

    final_config = ExtensionsConfig.from_file(str(cfg))
    assert cache_module._effective_mcp_config_snapshot(final_config) == snapshot_before

    assert cache_module.refresh_mcp_cache_if_active() is True
    binding_a_after = _binding(pool, "A")
    assert binding_a_after is not binding_a_before
    assert _binding(pool, "B") is binding_b_before
    assert _entry(pool, "B") is entry_b_before
    await _wait_until(lambda: log["exited"].get("npx") == 1)
    assert log["exited"].get("cmd-B") is None

    assert cache_module.refresh_mcp_cache_if_active() is False
    assert _binding(pool, "A") is binding_a_after


@pytest.mark.asyncio
async def test_durable_only_without_baseline_is_retired_conservatively(
    reconciler,  # noqa: F811 - fixture imported from the sibling process-local suite
    monkeypatch,
    tmp_path,
):
    """No published cache and no applied baseline -> conservative deployment rebind."""
    cfg = tmp_path / "extensions_config.json"
    servers = {"A": _stdio("cmd-A"), "B": _stdio("cmd-B")}
    _write_config(cfg, servers)
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))

    pool = MCPSessionPool()
    session_pool_module._pool = pool
    durable_a = pool.ensure_binding("A", _fingerprint(servers, "A"), domain="deployment")
    durable_b = pool.ensure_binding("B", _fingerprint(servers, "B"), domain="deployment")

    # Durable-only worker: state exists, but nothing was published and no
    # applied revision was ever recorded.
    assert cache_module._cache_initialized is False
    assert cache_module._applied_mcp_revision is None

    peer = _run_peer_worker(cfg)
    assert peer["a_epoch_after_readd"] > peer["a_epoch_after_delete"] > peer["a_epoch_baseline"]

    # No trustworthy baseline, so the whole deployment domain is conservatively
    # re-epoched (personal state is untouched); selective preservation is not
    # claimed for this first observation.
    assert cache_module.refresh_mcp_cache_if_active() is True
    rebound_a = _binding(pool, "A")
    rebound_b = _binding(pool, "B")
    assert rebound_a is not durable_a and rebound_a.epoch > durable_a.epoch
    assert rebound_b is not durable_b and rebound_b.epoch > durable_b.epoch
    assert cache_module._applied_mcp_revision is not None
    assert cache_module._cache_initialized is False

    with pytest.raises(StaleMCPBindingError):
        await pool.get_session("A", "u:t", servers["A"], binding=durable_a)

    # The conservative rebind installed a stable baseline: the same revision is
    # now a no-op instead of resetting on every refresh.
    assert cache_module.refresh_mcp_cache_if_active() is False
