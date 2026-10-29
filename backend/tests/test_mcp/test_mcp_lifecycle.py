"""Unit coverage for the shared ``mcpLifecycle`` generation ledger."""

from __future__ import annotations

import pytest

from deerflow.config.extensions_config import validate_raw_extensions_config
from deerflow.mcp.lifecycle import (
    LIFECYCLE_KEY,
    InvalidMcpLifecycle,
    _stdio_fingerprints,
    effective_tokens,
    legacy_token,
    lifecycle_delta,
    new_token,
    parse_mcp_lifecycle,
    plan_mcp_lifecycle,
)


def _stdio(command: str, **extra) -> dict:
    return {"enabled": True, "type": "stdio", "command": command, **extra}


def _config(servers: dict) -> dict:
    return {"mcpServers": servers, "skills": {}}


def _ledger(**servers: str) -> dict:
    return {LIFECYCLE_KEY: {"version": 1, "servers": dict(servers)}}


def _fingerprint(config: dict, name: str) -> str:
    return _stdio_fingerprints(validate_raw_extensions_config(config))[name]


# ---------------------------------------------------------------------------
# Strict parsing (tri-state)
# ---------------------------------------------------------------------------


def test_absent_ledger_is_legacy_none():
    assert parse_mcp_lifecycle({"mcpServers": {}}) is None
    assert parse_mcp_lifecycle(None) is None


def test_valid_ledger_parses_with_servers():
    ledger = parse_mcp_lifecycle(_ledger(A="a" * 32, B="b" * 32))
    assert ledger is not None
    assert ledger.version == 1
    assert ledger.servers == {"A": "a" * 32, "B": "b" * 32}


@pytest.mark.parametrize(
    "block",
    [
        {"version": True, "servers": {}},
        {"version": 2, "servers": {}},
        {"version": "1", "servers": {}},
        {"version": 1.0, "servers": {}},
        {"version": 1, "servers": []},
        {"version": 1, "servers": {"A": "A" * 32}},  # uppercase
        {"version": 1, "servers": {"A": "abc"}},  # too short
        {"version": 1, "servers": {"A": "a" * 31}},  # 31 chars
        {"version": 1, "servers": {"A": "a" * 33}},  # 33 chars
        {"version": 1, "servers": {"A": "a" * 32 + "\n"}},  # trailing newline
        {"version": 1, "servers": {"A": "\n" + "a" * 32}},  # leading newline
        {"version": 1, "servers": {"A": "a" * 32 + " "}},  # trailing space
        {"version": 1, "servers": {"A": 1}},  # wrong type
        {"version": 1, "servers": {"": "a" * 32}},  # empty name
        {"version": 1, "servers": {}, "extra": True},
    ],
)
def test_invalid_ledger_fails_closed(block):
    with pytest.raises(InvalidMcpLifecycle):
        parse_mcp_lifecycle({LIFECYCLE_KEY: block})


# ---------------------------------------------------------------------------
# Legacy derivation and planner
# ---------------------------------------------------------------------------


def test_legacy_token_is_deterministic_and_name_fingerprint_sensitive():
    fp = "f" * 64
    assert legacy_token("A", fp) == legacy_token("A", fp)
    assert legacy_token("A", fp) != legacy_token("B", fp)
    assert legacy_token("A", fp) != legacy_token("A", "e" * 64)
    assert len(legacy_token("A", fp)) == 64


def test_unchanged_legacy_servers_are_not_retired():
    previous = _config({"A": _stdio("cmd-A1"), "B": _stdio("cmd-B1")})
    candidate = _config({"A": _stdio("cmd-A2"), "B": _stdio("cmd-B1")})

    plan = plan_mcp_lifecycle(previous, candidate)
    assert plan["version"] == 1
    # Only A changed; B stays a derived legacy token (no explicit entry).
    assert set(plan["servers"]) == {"A"}

    tokens = effective_tokens(validate_raw_extensions_config(candidate), parse_mcp_lifecycle(plan))
    assert tokens["B"] == legacy_token("B", _fingerprint(candidate, "B"))


def test_delete_and_identical_readd_each_advance_the_generation():
    original = _config({"A": _stdio("cmd-A1")})
    first = plan_mcp_lifecycle(None, original)["servers"]["A"]

    deleted = _config({})
    after_delete = plan_mcp_lifecycle(original, deleted)["servers"]["A"]
    assert after_delete != first

    re_added = plan_mcp_lifecycle(deleted, original)["servers"]["A"]
    assert re_added not in {first, after_delete}


def test_metadata_only_change_does_not_advance():
    previous = _config({"A": _stdio("cmd-A1")})
    candidate = _config({"A": _stdio("cmd-A1", description="renamed", tool_name_prefix=False)})
    assert plan_mcp_lifecycle(previous, candidate)["servers"] == {}


def test_schema_invalid_previous_config_is_a_conservative_migration():
    # Raw JSON is valid, but the server map has the wrong shape.
    previous = {"mcpServers": "not-a-dict", "skills": {}}
    candidate = _config({"A": _stdio("cmd-A1"), "B": _stdio("cmd-B1")})

    plan = plan_mcp_lifecycle(previous, candidate)
    assert set(plan["servers"]) == {"A", "B"}
    assert all(token != "" for token in plan["servers"].values())


def test_effective_tokens_keeps_tombstones():
    candidate = _config({"A": _stdio("cmd-A1")})
    ledger = parse_mcp_lifecycle(_ledger(A="a" * 32, B="b" * 32))
    tokens = effective_tokens(validate_raw_extensions_config(candidate), ledger)
    assert tokens["A"] == "a" * 32  # explicit ledger token wins
    assert tokens["B"] == "b" * 32  # tombstone retained


def test_lifecycle_delta_reports_only_changed_active_servers():
    delta = lifecycle_delta(
        previous_tokens={"A": "1" * 32, "B": "2" * 32},
        candidate_tokens={"A": "3" * 32, "B": "2" * 32, "C": "4" * 32},
        active_names={"A", "B"},
    )
    assert delta == frozenset({"A"})


def test_new_token_is_strict_hex():
    token = new_token()
    assert len(token) == 32
    assert token == token.lower()
    assert all(ch in "0123456789abcdef" for ch in token)


def test_token_rejects_trailing_newline():
    """``$`` would accept a trailing newline; the validator must use fullmatch."""
    with pytest.raises(InvalidMcpLifecycle):
        parse_mcp_lifecycle({LIFECYCLE_KEY: {"version": 1, "servers": {"A": "a" * 32 + "\n"}}})
    assert parse_mcp_lifecycle({LIFECYCLE_KEY: {"version": 1, "servers": {"A": "a" * 32}}}) is not None
