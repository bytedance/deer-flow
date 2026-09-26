"""Tests for the typed MCP lifecycle model and the pure lifecycle rules."""

from __future__ import annotations

import pytest

from deerflow.config.mcp_lifecycle import (
    SUPPORTED_SCHEMA_VERSION,
    McpLifecycle,
    McpLifecycleError,
    lifecycle_covers_servers,
    new_lifecycle_id,
    parse_mcp_lifecycle,
)
from deerflow.mcp.lifecycle_rules import compute_next_lifecycle

_FULL_BLOCK = {
    "schemaVersion": 2,
    "lifecycleId": "lineage-1",
    "configRevision": 3,
    "globalGeneration": 2,
    "serverGenerations": {"A": 4, "B": 0},
}


def test_valid_block_round_trips_with_camel_case_aliases() -> None:
    lifecycle = parse_mcp_lifecycle(dict(_FULL_BLOCK))

    assert lifecycle is not None
    assert lifecycle.schema_version == 2
    assert lifecycle.lifecycle_id == "lineage-1"
    assert lifecycle.config_revision == 3
    assert lifecycle.global_generation == 2
    assert lifecycle.server_generations == {"A": 4, "B": 0}
    assert lifecycle.model_dump(by_alias=True, exclude_none=False) == _FULL_BLOCK


@pytest.mark.parametrize(
    "partial",
    [
        {},
        {"schemaVersion": 2},
        {"lifecycleId": "lineage-1"},
        {"schemaVersion": 2, "lifecycleId": "lineage-1", "configRevision": 3},
        {"schemaVersion": 2, "lifecycleId": "lineage-1", "globalGeneration": 1, "serverGenerations": {}},
    ],
)
def test_partial_persisted_block_is_rejected(partial: dict) -> None:
    """A truncated block must never be completed with defaults into a version."""
    with pytest.raises(McpLifecycleError):
        parse_mcp_lifecycle(partial)


def test_absent_block_is_the_legacy_case() -> None:
    assert parse_mcp_lifecycle(None) is None


@pytest.mark.parametrize("raw", [[], "x", 5, True, ["mcpLifecycle"]])
def test_non_mapping_value_is_rejected(raw: object) -> None:
    with pytest.raises(McpLifecycleError):
        parse_mcp_lifecycle(raw)


@pytest.mark.parametrize("schema_version", [1, 3, 0, -1])
def test_unknown_schema_version_is_rejected(schema_version: int) -> None:
    with pytest.raises(McpLifecycleError):
        parse_mcp_lifecycle({**_FULL_BLOCK, "schemaVersion": schema_version})


@pytest.mark.parametrize("value", [True, False, 1.5, "2"])
def test_boolean_or_non_integer_schema_version_is_rejected(value: object) -> None:
    with pytest.raises(McpLifecycleError):
        parse_mcp_lifecycle({**_FULL_BLOCK, "schemaVersion": value})


@pytest.mark.parametrize("value", ["", 5, None, True])
def test_non_string_lifecycle_id_is_rejected(value: object) -> None:
    with pytest.raises(McpLifecycleError):
        parse_mcp_lifecycle({**_FULL_BLOCK, "lifecycleId": value})


@pytest.mark.parametrize("field", ["configRevision", "globalGeneration"])
@pytest.mark.parametrize("value", [-1, True, False, 1.5, "1"])
def test_invalid_counters_are_rejected(field: str, value: object) -> None:
    with pytest.raises(McpLifecycleError):
        parse_mcp_lifecycle({**_FULL_BLOCK, field: value})


@pytest.mark.parametrize("generation", [-1, True, False, 1.5, "1"])
def test_invalid_server_generation_values_are_rejected(generation: object) -> None:
    with pytest.raises(McpLifecycleError):
        parse_mcp_lifecycle({**_FULL_BLOCK, "serverGenerations": {"A": generation}})


@pytest.mark.parametrize("name", [1, None, True, 2.0])
def test_non_string_server_keys_are_rejected(name: object) -> None:
    with pytest.raises(McpLifecycleError):
        parse_mcp_lifecycle({**_FULL_BLOCK, "serverGenerations": {name: 0}})


@pytest.mark.parametrize("server_generations", [[], 5, "A", True])
def test_non_mapping_server_generations_is_rejected(server_generations: object) -> None:
    with pytest.raises(McpLifecycleError):
        parse_mcp_lifecycle({**_FULL_BLOCK, "serverGenerations": server_generations})


def test_extra_key_is_rejected() -> None:
    with pytest.raises(McpLifecycleError):
        parse_mcp_lifecycle({**_FULL_BLOCK, "unexpected": 3})


def test_validation_error_message_never_echoes_the_input_value() -> None:
    """The block is operator-editable, so failures must not echo its values."""
    with pytest.raises(McpLifecycleError) as excinfo:
        parse_mcp_lifecycle({**_FULL_BLOCK, "configRevision": "secret-value-xyz"})

    assert "secret-value-xyz" not in str(excinfo.value)


def test_model_accepts_python_field_names_and_mints_an_id() -> None:
    lifecycle = McpLifecycle(
        config_revision=5,
        global_generation=1,
        server_generations={"A": 2},
    )

    assert lifecycle.schema_version == SUPPORTED_SCHEMA_VERSION
    assert lifecycle.lifecycle_id
    assert lifecycle.model_dump(by_alias=True) == {
        "schemaVersion": 2,
        "lifecycleId": lifecycle.lifecycle_id,
        "configRevision": 5,
        "globalGeneration": 1,
        "serverGenerations": {"A": 2},
    }


def test_new_lifecycle_id_is_unique() -> None:
    assert new_lifecycle_id() != new_lifecycle_id()


def test_lifecycle_covers_servers() -> None:
    lifecycle = McpLifecycle(server_generations={"A": 1})
    assert lifecycle_covers_servers(lifecycle, ["A"])
    assert lifecycle_covers_servers(lifecycle, [])
    assert not lifecycle_covers_servers(lifecycle, ["A", "B"])


# --- Lifecycle computation rules ---------------------------------------------

_A1 = "stdio:server-a:A1"
_A2 = "stdio:server-a:A2"
_B1 = "stdio:server-b:B1"


def _previous(config_revision: int, global_generation: int, server_generations: dict[str, int]) -> McpLifecycle:
    return McpLifecycle(
        lifecycle_id="lineage-1",
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

    assert result.schema_version == 2
    assert result.config_revision == expected_revision
    assert result.global_generation == expected_global
    assert result.server_generations == expected_generations
    if previous is None:
        assert result.lifecycle_id
    else:
        assert result.lifecycle_id == previous.lifecycle_id


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


def test_fresh_baseline_mints_a_new_lineage_id_even_when_counters_match() -> None:
    """A re-based counter set must never be mistaken for the one it replaced."""
    first = compute_next_lifecycle(None, {}, {"A": _A1}, interceptors_changed=True)
    second = compute_next_lifecycle(None, {}, {"A": _A1}, interceptors_changed=True)

    assert (first.global_generation, first.server_generations) == (second.global_generation, second.server_generations)
    assert first.lifecycle_id != second.lifecycle_id
