"""Tests for the typed MCP lifecycle model and the pure lifecycle rules."""

from __future__ import annotations

import pytest

from deerflow.config.mcp_lifecycle import (
    McpLifecycle,
    McpLifecycleError,
    parse_mcp_lifecycle,
)
from deerflow.mcp.lifecycle_rules import compute_next_lifecycle


def test_valid_block_round_trips_with_camel_case_aliases() -> None:
    lifecycle = parse_mcp_lifecycle(
        {
            "schemaVersion": 1,
            "configRevision": 3,
            "globalGeneration": 2,
            "serverGenerations": {"A": 4, "B": 0},
        }
    )

    assert lifecycle is not None
    assert lifecycle.schema_version == 1
    assert lifecycle.config_revision == 3
    assert lifecycle.global_generation == 2
    assert lifecycle.server_generations == {"A": 4, "B": 0}
    assert lifecycle.model_dump(by_alias=True, exclude_none=False) == {
        "schemaVersion": 1,
        "configRevision": 3,
        "globalGeneration": 2,
        "serverGenerations": {"A": 4, "B": 0},
    }


def test_empty_block_uses_defaults() -> None:
    lifecycle = parse_mcp_lifecycle({})

    assert lifecycle is not None
    assert lifecycle.schema_version == 1
    assert lifecycle.config_revision == 0
    assert lifecycle.global_generation == 0
    assert lifecycle.server_generations == {}


def test_absent_block_is_the_legacy_case() -> None:
    assert parse_mcp_lifecycle(None) is None


@pytest.mark.parametrize("raw", [[], "x", 5, True, ["mcpLifecycle"]])
def test_non_mapping_value_is_rejected(raw: object) -> None:
    with pytest.raises(McpLifecycleError):
        parse_mcp_lifecycle(raw)


@pytest.mark.parametrize("schema_version", [2, 0, -1])
def test_unknown_schema_version_is_rejected(schema_version: int) -> None:
    with pytest.raises(McpLifecycleError):
        parse_mcp_lifecycle({"schemaVersion": schema_version})


@pytest.mark.parametrize("value", [True, False, 1.5, "1"])
def test_boolean_or_non_integer_schema_version_is_rejected(value: object) -> None:
    with pytest.raises(McpLifecycleError):
        parse_mcp_lifecycle({"schemaVersion": value})


@pytest.mark.parametrize("field", ["configRevision", "globalGeneration"])
@pytest.mark.parametrize("value", [-1, True, False, 1.5, "1"])
def test_invalid_counters_are_rejected(field: str, value: object) -> None:
    with pytest.raises(McpLifecycleError):
        parse_mcp_lifecycle({field: value})


@pytest.mark.parametrize("generation", [-1, True, False, 1.5, "1"])
def test_invalid_server_generation_values_are_rejected(generation: object) -> None:
    with pytest.raises(McpLifecycleError):
        parse_mcp_lifecycle({"serverGenerations": {"A": generation}})


@pytest.mark.parametrize("name", [1, None, True, 2.0])
def test_non_string_server_keys_are_rejected(name: object) -> None:
    with pytest.raises(McpLifecycleError):
        parse_mcp_lifecycle({"serverGenerations": {name: 0}})


@pytest.mark.parametrize("server_generations", [[], 5, "A", True])
def test_non_mapping_server_generations_is_rejected(server_generations: object) -> None:
    with pytest.raises(McpLifecycleError):
        parse_mcp_lifecycle({"serverGenerations": server_generations})


def test_extra_key_is_rejected() -> None:
    with pytest.raises(McpLifecycleError):
        parse_mcp_lifecycle({"schemaVersion": 1, "unexpected": 3})


def test_model_accepts_python_field_names() -> None:
    lifecycle = McpLifecycle(
        schema_version=1,
        config_revision=5,
        global_generation=1,
        server_generations={"A": 2},
    )

    assert lifecycle.model_dump(by_alias=True) == {
        "schemaVersion": 1,
        "configRevision": 5,
        "globalGeneration": 1,
        "serverGenerations": {"A": 2},
    }


# --- Lifecycle computation rules ---------------------------------------------

_A1 = "stdio:server-a:A1"
_A2 = "stdio:server-a:A2"
_B1 = "stdio:server-b:B1"


def _previous(config_revision: int, global_generation: int, server_generations: dict[str, int]) -> McpLifecycle:
    return McpLifecycle(
        schema_version=1,
        config_revision=config_revision,
        global_generation=global_generation,
        server_generations=server_generations,
    )


_AB_PREVIOUS = _previous(4, 1, {"A": 1, "B": 1})


@pytest.mark.parametrize(
    "previous,old_servers,new_servers,interceptors_changed,expected_revision,expected_global,expected_generations",
    [
        pytest.param(
            _AB_PREVIOUS,
            {"A": _A1, "B": _B1},
            {"B": _B1},
            False,
            5,
            1,
            {"A": 2, "B": 1},
            id="delete",
        ),
        pytest.param(
            _previous(4, 1, {"A": 1}),
            {"A": _A1},
            {},
            False,
            5,
            1,
            {"A": 2},
            id="disable",
        ),
        pytest.param(
            _previous(7, 2, {"A": 3}),
            {},
            {"A": _A1},
            False,
            8,
            2,
            {"A": 4},
            id="re-enable",
        ),
        pytest.param(
            _previous(4, 1, {"B": 1}),
            {"B": _B1},
            {"A": _A1, "B": _B1},
            False,
            5,
            1,
            {"A": 1, "B": 1},
            id="add",
        ),
        pytest.param(
            _previous(4, 1, {"A": 1}),
            {"A": _A1},
            {"A": _A2},
            False,
            5,
            1,
            {"A": 2},
            id="connection-change",
        ),
        pytest.param(
            _AB_PREVIOUS,
            {"A": _A1, "B": _B1},
            {"A": _A1, "B": _B1},
            False,
            5,
            1,
            {"A": 1, "B": 1},
            id="metadata-only",
        ),
        pytest.param(
            _AB_PREVIOUS,
            {"A": _A1, "B": _B1},
            {"B": _B1, "A": _A1},
            False,
            5,
            1,
            {"A": 1, "B": 1},
            id="declaration-order",
        ),
        pytest.param(
            _AB_PREVIOUS,
            {"A": _A1, "B": _B1},
            {"A": _A1, "B": _B1},
            True,
            5,
            2,
            {"A": 1, "B": 1},
            id="interceptor-change",
        ),
        pytest.param(
            _previous(4, 1, {"A": 1, "B": 1, "removed": 2}),
            {"A": _A1, "B": _B1},
            {"B": _B1},
            False,
            5,
            1,
            {"A": 2, "B": 1, "removed": 2},
            id="removed-name-keeps-counter",
        ),
        pytest.param(
            None,
            {},
            {"A": _A1},
            False,
            1,
            0,
            {"A": 1},
            id="first-adoption",
        ),
    ],
)
def test_compute_next_lifecycle(
    previous: McpLifecycle | None,
    old_servers: dict[str, str],
    new_servers: dict[str, str],
    interceptors_changed: bool,
    expected_revision: int,
    expected_global: int,
    expected_generations: dict[str, int],
) -> None:
    result = compute_next_lifecycle(
        previous,
        old_servers,
        new_servers,
        interceptors_changed=interceptors_changed,
    )

    assert result.schema_version == 1
    assert result.config_revision == expected_revision
    assert result.global_generation == expected_global
    assert result.server_generations == expected_generations


def test_connection_returning_to_original_fingerprint_advances_twice() -> None:
    first = compute_next_lifecycle(
        _previous(4, 1, {"A": 1}),
        {"A": _A1},
        {"A": _A2},
        interceptors_changed=False,
    )
    second = compute_next_lifecycle(
        first,
        {"A": _A2},
        {"A": _A1},
        interceptors_changed=False,
    )

    assert first.server_generations == {"A": 2}
    assert second.server_generations == {"A": 3}
    assert second.config_revision == 6
    assert second.global_generation == 1
