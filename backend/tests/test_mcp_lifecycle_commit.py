"""Tests for the shared MCP config commit helper.

``commit_extensions_config`` is the single place where a validated candidate
extensions config, the caller's raw read-modify-write document and the persisted
``mcpLifecycle`` counters are joined into one atomic write. These tests pin the
protocol properties the writers depend on: the block always reflects the
*computed* counters (never a caller-supplied copy), a legacy file is adopted
without counting its existing servers as lifecycle events, a malformed existing
block fails the write closed, and a raw document's ``$VAR`` placeholders and
unknown top-level keys survive byte-for-byte.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from deerflow.config.extensions_config import (
    ExtensionsConfig,
    read_raw_extensions_config,
    validate_raw_extensions_config,
)
from deerflow.config.mcp_lifecycle import parse_mcp_lifecycle
from deerflow.mcp.client import build_server_params
from deerflow.mcp.commit import (
    CommittedMcpRevision,
    commit_extensions_config,
    enabled_stdio_fingerprints,
)
from deerflow.mcp.session_pool import normalized_connection_fingerprint


def _base_raw() -> dict:
    return {
        "mcpServers": {
            "alpha": {"enabled": True, "type": "stdio", "command": "python", "args": ["-m", "alpha"]},
            "beta": {"enabled": True, "type": "stdio", "command": "node", "args": ["beta.js"]},
        },
        "skills": {"existing-skill": {"enabled": True}},
    }


def _write_raw(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _commit(
    config_path: Path,
    raw_data: dict,
    previous_config: ExtensionsConfig,
    new_config: ExtensionsConfig,
) -> CommittedMcpRevision:
    return commit_extensions_config(
        config_path=config_path,
        raw_data=raw_data,
        previous_config=previous_config,
        new_config=new_config,
    )


def test_legacy_file_gains_schema_version_without_counting_existing_servers(tmp_path: Path) -> None:
    config_path = tmp_path / "extensions_config.json"
    raw_data = _base_raw()
    _write_raw(config_path, raw_data)
    previous_config = validate_raw_extensions_config(copy.deepcopy(raw_data))
    mutated = copy.deepcopy(raw_data)
    mutated["mcpServers"]["beta"]["args"] = ["beta-v2.js"]
    new_config = validate_raw_extensions_config(copy.deepcopy(mutated))

    committed = _commit(config_path, mutated, previous_config, new_config)

    assert isinstance(committed, CommittedMcpRevision)
    on_disk = read_raw_extensions_config(config_path)["mcpLifecycle"]
    assert on_disk == {
        "schemaVersion": 1,
        "configRevision": 1,
        "globalGeneration": 0,
        "serverGenerations": {"alpha": 0, "beta": 1},
    }
    assert committed.lifecycle.model_dump(by_alias=True) == on_disk


def test_caller_supplied_lifecycle_block_is_replaced_by_computed_counters(tmp_path: Path) -> None:
    config_path = tmp_path / "extensions_config.json"
    raw_data = _base_raw()
    raw_data["mcpLifecycle"] = {
        "schemaVersion": 1,
        "configRevision": 40,
        "globalGeneration": 7,
        "serverGenerations": {"alpha": 9, "retired": 4},
    }
    _write_raw(config_path, raw_data)
    previous_config = validate_raw_extensions_config(copy.deepcopy(raw_data))
    new_config = validate_raw_extensions_config(copy.deepcopy(raw_data))

    committed = _commit(config_path, raw_data, previous_config, new_config)

    on_disk = read_raw_extensions_config(config_path)["mcpLifecycle"]
    assert on_disk == committed.lifecycle.model_dump(by_alias=True)
    assert on_disk == {
        "schemaVersion": 1,
        "configRevision": 41,
        "globalGeneration": 7,
        "serverGenerations": {"alpha": 9, "beta": 0, "retired": 4},
    }


def test_var_placeholders_and_unknown_top_level_keys_survive_the_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEERFLOW_TEST_MCP_TOKEN", raising=False)
    config_path = tmp_path / "extensions_config.json"
    raw_data = _base_raw()
    raw_data["mcpServers"]["alpha"]["env"] = {"GITHUB_TOKEN": "$DEERFLOW_TEST_MCP_TOKEN"}
    raw_data["mcpInterceptors"] = ["deerflow_extras:CustomInterceptor"]
    raw_data["customTopLevel"] = {"keep": [1, 2, 3]}
    _write_raw(config_path, raw_data)
    previous_config = validate_raw_extensions_config(copy.deepcopy(raw_data))
    new_config = validate_raw_extensions_config(copy.deepcopy(raw_data))

    committed = _commit(config_path, raw_data, previous_config, new_config)

    on_disk = read_raw_extensions_config(config_path)
    assert on_disk["mcpServers"]["alpha"]["env"]["GITHUB_TOKEN"] == "$DEERFLOW_TEST_MCP_TOKEN"
    assert on_disk["mcpInterceptors"] == ["deerflow_extras:CustomInterceptor"]
    assert on_disk["customTopLevel"] == {"keep": [1, 2, 3]}
    assert json.loads(committed.interceptors) == ["deerflow_extras:CustomInterceptor"]


@pytest.mark.parametrize(
    "malformed_block",
    [
        {"schemaVersion": 2, "configRevision": 0, "globalGeneration": 0, "serverGenerations": {}},
        {"schemaVersion": 1, "configRevision": -1, "globalGeneration": 0, "serverGenerations": {}},
        ["not", "an", "object"],
    ],
)
def test_malformed_existing_block_is_replaced_by_a_fresh_baseline(tmp_path: Path, malformed_block: object) -> None:
    """An invalid block must never brick the writer that can repair it."""
    config_path = tmp_path / "extensions_config.json"
    raw_data = _base_raw()
    raw_data["mcpLifecycle"] = malformed_block
    _write_raw(config_path, raw_data)
    previous_config = validate_raw_extensions_config(copy.deepcopy(raw_data))
    new_config = validate_raw_extensions_config(copy.deepcopy(raw_data))

    committed = _commit(config_path, raw_data, previous_config, new_config)

    assert read_raw_extensions_config(config_path)["mcpLifecycle"] == {
        "schemaVersion": 1,
        "configRevision": 1,
        "globalGeneration": 1,
        "serverGenerations": {"alpha": 1, "beta": 1},
    }
    assert committed.lifecycle == parse_mcp_lifecycle(read_raw_extensions_config(config_path)["mcpLifecycle"])


def test_interceptor_change_advances_only_global_generation(tmp_path: Path) -> None:
    config_path = tmp_path / "extensions_config.json"
    raw_data = _base_raw()
    raw_data["mcpInterceptors"] = ["pkg.before:Interceptor"]
    raw_data["mcpLifecycle"] = {
        "schemaVersion": 1,
        "configRevision": 9,
        "globalGeneration": 3,
        "serverGenerations": {"alpha": 2, "beta": 1},
    }
    _write_raw(config_path, raw_data)
    previous_config = validate_raw_extensions_config(copy.deepcopy(raw_data))
    raw_data["mcpInterceptors"] = ["pkg.after:Interceptor"]
    new_config = validate_raw_extensions_config(copy.deepcopy(raw_data))

    _commit(config_path, raw_data, previous_config, new_config)

    on_disk = read_raw_extensions_config(config_path)
    assert on_disk["mcpInterceptors"] == ["pkg.after:Interceptor"]
    assert on_disk["mcpLifecycle"] == {
        "schemaVersion": 1,
        "configRevision": 10,
        "globalGeneration": 4,
        "serverGenerations": {"alpha": 2, "beta": 1},
    }


def test_lifecycle_round_trips_through_the_raw_read_and_parser(tmp_path: Path) -> None:
    config_path = tmp_path / "extensions_config.json"
    raw_data = _base_raw()
    _write_raw(config_path, raw_data)
    previous_config = validate_raw_extensions_config(copy.deepcopy(raw_data))
    mutated = copy.deepcopy(raw_data)
    mutated["mcpServers"]["gamma"] = {"enabled": True, "type": "stdio", "command": "python", "args": ["-m", "gamma"]}
    new_config = validate_raw_extensions_config(copy.deepcopy(mutated))

    committed = _commit(config_path, mutated, previous_config, new_config)

    parsed = parse_mcp_lifecycle(read_raw_extensions_config(config_path)["mcpLifecycle"])
    assert parsed is not None
    assert parsed == committed.lifecycle
    assert parsed.config_revision == 1
    assert parsed.server_generations == {"alpha": 0, "beta": 0, "gamma": 1}


def test_skills_only_write_advances_only_config_revision(tmp_path: Path) -> None:
    config_path = tmp_path / "extensions_config.json"
    raw_data = _base_raw()
    _write_raw(config_path, raw_data)
    previous_config = validate_raw_extensions_config(copy.deepcopy(raw_data))
    mutated = copy.deepcopy(raw_data)
    mutated["skills"]["new-skill"] = {"enabled": False}
    new_config = validate_raw_extensions_config(copy.deepcopy(mutated))

    assert enabled_stdio_fingerprints(previous_config) == enabled_stdio_fingerprints(new_config)
    _commit(config_path, mutated, previous_config, new_config)

    assert read_raw_extensions_config(config_path)["mcpLifecycle"] == {
        "schemaVersion": 1,
        "configRevision": 1,
        "globalGeneration": 0,
        "serverGenerations": {"alpha": 0, "beta": 0},
    }


def test_enabled_stdio_fingerprints_skips_disabled_remote_and_unbuildable_servers() -> None:
    raw_data = {
        "mcpServers": {
            "stdio-ok": {"enabled": True, "type": "stdio", "command": "python", "args": ["-m", "ok"]},
            "stdio-disabled": {"enabled": False, "type": "stdio", "command": "python"},
            "stdio-unbuildable": {"enabled": True, "type": "stdio"},
            "remote": {"enabled": True, "type": "http", "url": "https://mcp.example.com/mcp"},
        }
    }
    config = validate_raw_extensions_config(raw_data)

    fingerprints = enabled_stdio_fingerprints(config)

    assert set(fingerprints) == {"stdio-ok"}
    assert fingerprints["stdio-ok"] == normalized_connection_fingerprint(build_server_params("stdio-ok", config.mcp_servers["stdio-ok"]))
