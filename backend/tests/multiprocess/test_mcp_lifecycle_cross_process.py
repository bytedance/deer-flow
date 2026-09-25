"""Real multi-process tests for shared MCP lifecycle generations.

Each test drives two or more genuinely independent worker processes (independent
module globals, independent ``MCPSessionPool`` singletons) that share one
``extensions_config.json`` and one sidecar lock inode, so a lifecycle advance
made by one worker must be observed and acted on by another worker's *next*
check.

The headline test below also serves as a control: reverting only the reader-side
consumption (``_lifecycle_transition`` returning "no signal") makes it fail.
``w1``'s next check then reports ``retired=False`` and leaves A's old binding
and session in place, because the generation advance W2 persisted is invisible
to the reader.

Properties that are inherently single-process are pinned elsewhere rather than
duplicated here:

* HTTP cancellation with a blocked subprocess exit is a within-process
  asyncio/thread property, pinned by
  ``tests/test_mcp_cache_reconciliation.py::test_cancelled_delete_worker_still_installs_tombstone``,
  ``::test_blocked_session_exit_does_not_block_next_config_write`` and
  ``::test_delete_then_readd_cannot_interleave_before_tombstone_installation``.
* the mid-write / ``EBUSY`` failure-injection variant is a single-writer property
  pinned by
  ``tests/test_mcp_lifecycle_failures.py::test_indeterminate_commit_retires_local_state_and_reports_unknown_outcome``;
  this module covers the post-write fence/reload failures that a second process
  can actually observe.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from multiprocess.harness import Worker, spawn_worker


def _stdio(command: str = "npx", **extra) -> dict:
    return {"enabled": True, "type": "stdio", "command": command, "args": [], **extra}


@pytest.fixture()
def spawn(tmp_path: Path):
    """Create the shared config file and a factory that spawns tracked workers."""
    config_path = tmp_path / "extensions_config.json"
    config_path.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")
    spawned: list[Worker] = []

    def _spawn(label: str) -> Worker:
        worker = spawn_worker(config_path, label=label)
        spawned.append(worker)
        return worker

    try:
        yield _spawn, config_path
    finally:
        for worker in spawned:
            worker.close()


def _lifecycle(worker: Worker) -> dict:
    raw = worker.send({"cmd": "read_raw"})["raw"]
    return raw["mcpLifecycle"]


# ---------------------------------------------------------------------------
# Delete then identical re-add
# ---------------------------------------------------------------------------


def test_headline_delete_then_identical_readd_retires_only_the_superseded_server(spawn):
    """W2 deletes A and identically re-adds it; W1's next check retires only A.

    The final effective configuration equals W1's baseline byte-for-byte (A's
    connection is identical and its declaration order is restored), so only the
    shared ``serverGenerations`` history can prove that A's resource lifecycle
    advanced. B's binding and session must be untouched.
    """
    spawn_workers, _config_path = spawn
    servers = {"A": _stdio("npx"), "B": _stdio("uvx")}
    w1 = spawn_workers("w1")
    w2 = spawn_workers("w2")

    publish = w1.send({"cmd": "publish", "servers": servers})
    assert publish["cache_initialized"] is True
    assert publish["applied_lifecycle"]["serverGenerations"] == {"A": 1, "B": 1}

    opened_a = w1.send({"cmd": "open", "server": "A", "scope": "t1"})
    opened_b = w1.send({"cmd": "open", "server": "B", "scope": "t1"})
    epoch_a_before = opened_a["bindings"]["A"]["epoch"]
    binding_b_before = opened_b["bindings"]["B"]

    # W2 performs a real delete of A followed by an identical re-add.
    w2.send({"cmd": "commit", "mutation": {"op": "delete", "server": "A"}})
    w2.send(
        {
            "cmd": "commit",
            "mutation": {"op": "add", "server": "A", "server_config": _stdio("npx"), "index": 0},
        }
    )

    after_w2 = w2.send({"cmd": "read_raw"})["raw"]
    assert after_w2["mcpServers"]["A"]["command"] == "npx"
    assert after_w2["mcpLifecycle"]["serverGenerations"] == {"A": 3, "B": 1}

    check = w1.send({"cmd": "check"})
    assert check["retired"] is True
    assert check["bindings"]["A"]["epoch"] > epoch_a_before
    assert check["bindings"]["B"] == binding_b_before
    assert check["sessions"]["A|t1"] is True
    assert check["sessions"]["B|t1"] is False

    # Tool assembly must also succeed afterwards.
    refreshed = w1.send({"cmd": "refresh"})
    assert refreshed["cache_initialized"] is True
    assert refreshed["bindings"]["A"]["epoch"] > epoch_a_before
    assert refreshed["bindings"]["B"] == binding_b_before


def _gated_publish(worker: Worker, servers: dict) -> None:
    """Start a publish whose discovery blocks until ``release_discovery``."""
    worker.write({"cmd": "publish", "servers": servers, "gate_discovery": True})
    worker.wait_event("discovery_entered")


def _publish_and_open(worker: Worker, servers: dict, scopes: dict[str, str] | None = None) -> dict:
    reply = worker.send({"cmd": "publish", "servers": servers})
    assert reply["cache_initialized"] is True, reply
    opened = {}
    for name in servers:
        opened[name] = worker.send({"cmd": "open", "server": name, "scope": (scopes or {}).get(name, "t1")})
    return opened


# ---------------------------------------------------------------------------
# Disable then re-enable
# ---------------------------------------------------------------------------


def test_disable_then_identical_enable_retires_cross_process(spawn):
    """A disable + re-enable is two lifecycle events even though the config is restored."""
    spawn_workers, _config_path = spawn
    servers = {"A": _stdio("npx"), "B": _stdio("uvx")}
    w1 = spawn_workers("w1")
    w2 = spawn_workers("w2")

    opened = _publish_and_open(w1, servers)
    epoch_a_before = opened["A"]["bindings"]["A"]["epoch"]
    binding_b_before = opened["B"]["bindings"]["B"]

    w2.send({"cmd": "commit", "mutation": {"op": "set_enabled", "server": "A", "enabled": False}})
    w2.send({"cmd": "commit", "mutation": {"op": "set_enabled", "server": "A", "enabled": True}})

    raw = w2.send({"cmd": "read_raw"})["raw"]
    assert raw["mcpServers"]["A"]["enabled"] is True
    assert raw["mcpLifecycle"]["serverGenerations"] == {"A": 3, "B": 1}

    check = w1.send({"cmd": "check"})
    assert check["retired"] is True
    assert check["bindings"]["A"]["epoch"] > epoch_a_before
    assert check["bindings"]["B"] == binding_b_before
    assert check["sessions"]["A|t1"] is True
    assert check["sessions"]["B|t1"] is False


# ---------------------------------------------------------------------------
# Connection round trip A1 -> A2 -> A1
# ---------------------------------------------------------------------------


def test_connection_round_trip_a1_a2_a1_is_detected(spawn):
    """The A1->A2->A1 round trip is detected even though the final connection equals A1."""
    spawn_workers, _config_path = spawn
    servers = {"A": _stdio("npx"), "B": _stdio("uvx")}
    w1 = spawn_workers("w1")
    w2 = spawn_workers("w2")

    opened = _publish_and_open(w1, servers)
    epoch_a_before = opened["A"]["bindings"]["A"]["epoch"]
    binding_b_before = opened["B"]["bindings"]["B"]

    w2.send({"cmd": "commit", "mutation": {"op": "set_command", "server": "A", "command": "uvx"}})
    w2.send({"cmd": "commit", "mutation": {"op": "set_command", "server": "A", "command": "npx"}})

    raw = w2.send({"cmd": "read_raw"})["raw"]
    assert raw["mcpServers"]["A"]["command"] == "npx"
    assert raw["mcpLifecycle"]["serverGenerations"] == {"A": 3, "B": 1}

    check = w1.send({"cmd": "check"})
    assert check["retired"] is True
    assert check["bindings"]["A"]["epoch"] > epoch_a_before
    assert check["bindings"]["B"] == binding_b_before
    assert check["sessions"]["A|t1"] is True
    assert check["sessions"]["B|t1"] is False


# ---------------------------------------------------------------------------
# mcpInterceptors round trip X -> Y -> X
# ---------------------------------------------------------------------------


def test_interceptors_x_y_x_forces_a_whole_pool_reset(spawn):
    """An unobserved interceptor round trip still forces the required whole-pool reset."""
    spawn_workers, _config_path = spawn
    servers = {"A": _stdio("npx"), "B": _stdio("uvx")}
    w1 = spawn_workers("w1")
    w2 = spawn_workers("w2")

    publish = w1.send({"cmd": "publish", "servers": servers, "interceptors": ["pkg:X"]})
    assert publish["cache_initialized"] is True
    assert publish["applied_lifecycle"]["globalGeneration"] == 1
    w1.send({"cmd": "open", "server": "A", "scope": "t1"})
    w1.send({"cmd": "open", "server": "B", "scope": "t1"})

    w2.send({"cmd": "commit", "mutation": {"op": "set_interceptors", "interceptors": ["pkg:Y"]}})
    w2.send({"cmd": "commit", "mutation": {"op": "set_interceptors", "interceptors": ["pkg:X"]}})

    raw = w2.send({"cmd": "read_raw"})["raw"]
    assert raw["mcpInterceptors"] == ["pkg:X"]
    assert raw["mcpLifecycle"]["globalGeneration"] == 3

    check = w1.send({"cmd": "check"})
    assert check["retired"] is True
    assert check["bindings"] == {}
    assert check["sessions"]["A|t1"] is True
    assert check["sessions"]["B|t1"] is True


# ---------------------------------------------------------------------------
# Delete/re-add during a worker's tool discovery
# ---------------------------------------------------------------------------


def test_delete_readd_during_gated_discovery_does_not_publish(spawn):
    """A lifecycle advance during W1's discovery discards the stale discovery result."""
    spawn_workers, _config_path = spawn
    servers = {"A": _stdio("npx"), "B": _stdio("uvx")}
    w1 = spawn_workers("w1")
    w2 = spawn_workers("w2")

    _gated_publish(w1, servers)
    # W2 mutates the shared file while W1 is parked mid-discovery.
    w2.send({"cmd": "commit", "mutation": {"op": "delete", "server": "A"}})
    w2.send(
        {
            "cmd": "commit",
            "mutation": {"op": "add", "server": "A", "server_config": _stdio("npx"), "index": 0},
        }
    )

    w1.write({"cmd": "release_discovery"})
    reply = w1.read_reply()
    assert reply["cache_initialized"] is False
    assert reply["bindings"] == {}
    assert reply["applied_lifecycle"] is None


# ---------------------------------------------------------------------------
# An already-held wrapper
# ---------------------------------------------------------------------------


def test_already_held_wrapper_survives_until_the_next_check(spawn):
    """A held wrapper keeps working until the *next* check retires it.

    There is no immediate cross-process guarantee for a wrapper an agent already
    holds; the next successful check installs the new epoch and fences the old
    binding.
    """
    spawn_workers, _config_path = spawn
    servers = {"A": _stdio("npx"), "B": _stdio("uvx")}
    w1 = spawn_workers("w1")
    w2 = spawn_workers("w2")

    opened = _publish_and_open(w1, servers, scopes={"A": "t1"})
    epoch_a_before = opened["A"]["bindings"]["A"]["epoch"]

    w2.send({"cmd": "commit", "mutation": {"op": "delete", "server": "A"}})
    w2.send(
        {
            "cmd": "commit",
            "mutation": {"op": "add", "server": "A", "server_config": _stdio("npx"), "index": 0},
        }
    )

    # Before the next check the held binding is still current, so the old
    # session may be used (an explicit non-goal).
    held_before_check = w1.send({"cmd": "probe_held", "server": "A", "scope": "t1"})
    assert held_before_check["stale"] is False
    assert held_before_check["sessions"]["A|t1"] is False

    check = w1.send({"cmd": "check"})
    assert check["retired"] is True
    assert check["bindings"]["A"]["epoch"] > epoch_a_before
    assert check["sessions"]["A|t1"] is True

    # After the check the same held binding is fenced.
    held_after_check = w1.send({"cmd": "probe_held", "server": "A", "scope": "t1"})
    assert held_after_check["stale"] is True


# ---------------------------------------------------------------------------
# The embedded client writer
# ---------------------------------------------------------------------------


def test_embedded_client_update_follows_the_shared_protocol(spawn):
    """An embedded client's write advances the same shared generations."""
    spawn_workers, _config_path = spawn
    servers = {"A": _stdio("npx"), "B": _stdio("uvx")}
    w1 = spawn_workers("w1")
    w2 = spawn_workers("w2")

    opened = _publish_and_open(w1, servers)
    epoch_a_before = opened["A"]["bindings"]["A"]["epoch"]
    binding_b_before = opened["B"]["bindings"]["B"]

    w2.send({"cmd": "client_commit", "servers": {"B": _stdio("uvx")}})
    w2.send({"cmd": "client_commit", "servers": servers})

    raw = w2.send({"cmd": "read_raw"})["raw"]
    assert raw["mcpLifecycle"]["serverGenerations"] == {"A": 3, "B": 1}

    check = w1.send({"cmd": "check"})
    assert check["retired"] is True
    assert check["bindings"]["A"]["epoch"] > epoch_a_before
    assert check["bindings"]["B"] == binding_b_before
    assert check["sessions"]["A|t1"] is True
    assert check["sessions"]["B|t1"] is False


# ---------------------------------------------------------------------------
# Post-write fence / reload failure
# ---------------------------------------------------------------------------


def test_post_write_fence_failure_invalidates_and_leaves_no_unfenced_session(spawn):
    """A committed write whose local fence raised must retire local state."""
    spawn_workers, _config_path = spawn
    servers = {"A": _stdio("npx"), "B": _stdio("uvx")}
    w2 = spawn_workers("w2")

    _publish_and_open(w2, servers, scopes={"A": "t1"})

    reply = w2.send({"cmd": "commit", "mutation": {"op": "delete", "server": "A"}, "fault": "fence"})
    assert "MCPCommittedNotReconciledError" in reply["error"]
    assert reply["sessions"]["A|t1"] is True
    assert reply["bindings"] == {}
    # The change did land on disk despite the failed fence.
    raw = w2.send({"cmd": "read_raw"})["raw"]
    assert "A" not in raw["mcpServers"]
    assert raw["mcpLifecycle"]["serverGenerations"]["A"] == 2


def test_post_write_reload_failure_keeps_the_fence_and_reports_the_commit(spawn):
    """A reload failure after a successful fence reports the commit, not a rollback."""
    spawn_workers, _config_path = spawn
    servers = {"A": _stdio("npx"), "B": _stdio("uvx")}
    w3 = spawn_workers("w3")

    _publish_and_open(w3, servers, scopes={"A": "t1"})

    reply = w3.send({"cmd": "commit", "mutation": {"op": "delete", "server": "A"}, "fault": "reload"})
    assert "MCPCommittedReloadFailedError" in reply["error"]
    # The fence ran before the reload raised, so A is tombstoned (not revived).
    assert reply["sessions"]["A|t1"] is True
    assert reply["bindings"]["A"]["fingerprint"] is None
    raw = w3.send({"cmd": "read_raw"})["raw"]
    assert "A" not in raw["mcpServers"]


# ---------------------------------------------------------------------------
# Metadata / declaration order / skills are not lifecycle events
# ---------------------------------------------------------------------------


def test_metadata_order_and_skills_never_retire_sessions(spawn):
    """Metadata, declaration order and skills edits must not retire any session."""
    spawn_workers, _config_path = spawn
    servers = {"A": _stdio("npx"), "B": _stdio("uvx")}
    w1 = spawn_workers("w1")
    w2 = spawn_workers("w2")

    opened = _publish_and_open(w1, servers)
    bindings_before = opened["A"]["bindings"]

    w2.send({"cmd": "commit", "mutation": {"op": "set_description", "server": "A", "description": "renamed"}})
    metadata = w1.send({"cmd": "check"})
    assert metadata["bindings"] == bindings_before
    assert metadata["sessions"]["A|t1"] is False
    assert metadata["sessions"]["B|t1"] is False

    w2.send({"cmd": "commit", "mutation": {"op": "reorder", "order": ["B", "A"]}})
    reordered = w1.send({"cmd": "check"})
    assert reordered["bindings"] == bindings_before
    assert reordered["sessions"]["A|t1"] is False
    assert reordered["sessions"]["B|t1"] is False

    w2.send({"cmd": "commit", "mutation": {"op": "set_skills", "skills": {"demo": {"enabled": True}}}})
    skills = w1.send({"cmd": "check"})
    assert skills["retired"] is False
    assert skills["bindings"] == bindings_before
    assert skills["sessions"]["A|t1"] is False
    assert skills["sessions"]["B|t1"] is False

    # The skills-only commit advanced configRevision but no generation.
    raw = w2.send({"cmd": "read_raw"})["raw"]
    assert raw["mcpLifecycle"]["configRevision"] == 4
    assert raw["mcpLifecycle"]["globalGeneration"] == 0
    assert raw["mcpLifecycle"]["serverGenerations"] == {"A": 1, "B": 1}


# ---------------------------------------------------------------------------
# Legacy config upgrade
# ---------------------------------------------------------------------------


def test_legacy_upgrade_initializes_versions_and_preserves_placeholders(spawn):
    """The first commit over a legacy file adopts a baseline without a retirement.

    This case is inherently single-process (it is about the commit protocol
    preserving bytes, not about cross-process observation); the existing
    ``tests/test_mcp_lifecycle_commit.py`` cases pin the same property directly.
    It is still driven through a real worker here for an end-to-end check.
    """
    spawn_workers, config_path = spawn
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "A": {
                        "enabled": True,
                        "type": "stdio",
                        "command": "npx",
                        "args": [],
                        "env": {"TOKEN": "$DEERFLOW_LEGACY_TOKEN"},
                    }
                },
                "skills": {},
                "customTopLevel": {"keep": [1, 2, 3]},
            }
        ),
        encoding="utf-8",
    )
    w1 = spawn_workers("w1")

    reply = w1.send({"cmd": "commit", "mutation": {"op": "noop"}})
    raw = reply["raw"] if "raw" in reply else w1.send({"cmd": "read_raw"})["raw"]

    assert raw["mcpLifecycle"] == {
        "schemaVersion": 1,
        "configRevision": 1,
        "globalGeneration": 0,
        "serverGenerations": {"A": 0},
    }
    assert raw["mcpServers"]["A"]["env"]["TOKEN"] == "$DEERFLOW_LEGACY_TOKEN"
    assert raw["customTopLevel"] == {"keep": [1, 2, 3]}
