"""Regression tests for the config reload boundary registry.

Bytedance/deer-flow issue #3144: the hot-reload boundary is the contract
between gateway dependencies that resolve ``AppConfig`` every request and the
infrastructure that captures the snapshot once at startup. The registry in
``deerflow.config.reload_boundary`` is the machine-readable source of truth;
these tests pin the registry against the actual Pydantic schema so a future
field rename / addition / boundary change cannot silently drift.
"""

from __future__ import annotations

import pytest

from deerflow.config.app_config import AppConfig
from deerflow.config.reload_boundary import (
    STARTUP_ONLY_FIELDS,
    STARTUP_ONLY_PREFIX,
    format_field_description,
    is_startup_only_field,
    iter_startup_only_field_paths,
)


def test_registry_has_a_reason_for_every_field():
    """Every registry entry must explain *why* the field is restart-required.

    The reason text is what surfaces in IDE hover and in the AppConfig schema
    description, so an empty / placeholder value would defeat the purpose.
    """
    for field_path, reason in STARTUP_ONLY_FIELDS.items():
        assert reason.strip(), f"empty reason for {field_path}"
        assert len(reason) > 20, f"reason for {field_path} too short to be useful: {reason!r}"


def test_iter_startup_only_field_paths_matches_registry():
    """Iterator stays in sync with the registry mapping."""
    assert sorted(iter_startup_only_field_paths()) == sorted(STARTUP_ONLY_FIELDS)


def test_is_startup_only_field_recognises_registered_fields():
    """The membership helper accepts every registered field path."""
    for field_path in STARTUP_ONLY_FIELDS:
        assert is_startup_only_field(field_path)
    assert not is_startup_only_field("memory")  # hot-reloadable
    assert not is_startup_only_field("models")
    assert not is_startup_only_field("nonexistent_field")


def test_format_field_description_prefixes_with_marker():
    """The formatter produces a description that machine-readable tooling can
    pivot on (drift tests, future "needs-restart" scanners)."""
    for field_path in STARTUP_ONLY_FIELDS:
        text = format_field_description(field_path)
        assert text.startswith(STARTUP_ONLY_PREFIX), text
        # The reason is appended after the prefix; the formatter must not
        # silently drop it.
        assert STARTUP_ONLY_FIELDS[field_path] in text


def test_format_field_description_rejects_unknown_field():
    with pytest.raises(KeyError):
        format_field_description("not_in_registry")


def test_format_field_description_appends_optional_field_doc():
    """The formatter composes the startup-only marker with the field's own
    human-facing description when supplied.

    The original ``Field(description=)`` used to document allowed values
    (e.g. ``log_level`` listed ``debug/info/warning/error``); registry
    adoption must not drop that. The composed output keeps the marker as
    the leading token so machine-readable tooling still pivots on it,
    then appends the prose after a blank line.
    """
    text = format_field_description("log_level", field_doc="Logging level (debug/info/warning/error).")
    assert text.startswith(STARTUP_ONLY_PREFIX)
    assert STARTUP_ONLY_FIELDS["log_level"] in text
    assert "debug/info/warning/error" in text


def test_appconfig_descriptions_retain_original_field_documentation():
    """``AppConfig.model_fields[name].description`` for restart-required
    fields should still carry the original human-facing field doc so IDE
    hover documents what the field is *and* why a restart is needed."""
    descriptions = {
        "log_level": "debug/info/warning/error",
        "database": "memory, sqlite, or postgres",
        "sandbox": "Sandbox provider",
        "run_events": "memory for dev",
        "checkpointer": "state-persistence checkpointer",
        "stream_bridge": "Stream bridge",
        "channel_connections": "IM channel connection",
    }
    for field_name, expected_substring in descriptions.items():
        description = AppConfig.model_fields[field_name].description or ""
        assert description.startswith(STARTUP_ONLY_PREFIX), f"AppConfig.{field_name} missing startup-only marker"
        assert expected_substring in description, f"AppConfig.{field_name} description lost original field doc; got {description!r}"


def test_appconfig_schema_marks_registered_fields_with_prefix():
    """Every registry entry that corresponds to a top-level AppConfig field
    must carry the standardized ``startup-only:`` prefix in its Pydantic
    ``Field(description=...)``. This is the contract IDE hover relies on.
    """
    schema_fields = AppConfig.model_fields
    for field_path in STARTUP_ONLY_FIELDS:
        if field_path not in schema_fields:
            # Some entries (e.g. ``channels``) live outside the AppConfig
            # schema. The registry still owns them, but the schema-prefix
            # assertion does not apply.
            continue
        description = schema_fields[field_path].description or ""
        assert description.startswith(STARTUP_ONLY_PREFIX), f"AppConfig.{field_path} should have Field(description=) starting with {STARTUP_ONLY_PREFIX!r}, got {description!r}"


def test_no_appconfig_field_uses_prefix_without_registration():
    """Reverse drift check: if a future schema edit adds the
    ``startup-only:`` prefix to a new field, the registry must list it.

    This catches the silent-drift case where someone marks a field
    restart-required in the schema but forgets to update the registry
    that the operator-facing scanners and docs consume.
    """
    for name, info in AppConfig.model_fields.items():
        description = info.description or ""
        if not description.startswith(STARTUP_ONLY_PREFIX):
            continue
        assert name in STARTUP_ONLY_FIELDS, f"AppConfig.{name} schema description starts with {STARTUP_ONLY_PREFIX!r} but the field is not listed in reload_boundary.STARTUP_ONLY_FIELDS — update the registry."


def test_pydantic_field_descriptions_are_introspectable_at_runtime():
    """``AppConfig.model_fields[name].description`` is the IDE-hover source.

    If this read ever breaks (e.g. Pydantic deprecation, schema swap), the
    IDE-hover guarantee #3144 promises silently regresses. Pin it.
    """
    assert "database" in AppConfig.model_fields
    description = AppConfig.model_fields["database"].description
    assert description is not None
    assert description.startswith(STARTUP_ONLY_PREFIX)
