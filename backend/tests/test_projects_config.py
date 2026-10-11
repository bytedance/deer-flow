"""Tests for ProjectsConfig (spec §6.4).

Defaults when the ``projects:`` section is absent, invalid values fall back to
defaults with a warning (the ``_get_upload_limit`` idiom), and the documented
bounds are enforced.
"""

import logging

import pytest

from deerflow.config.app_config import AppConfig
from deerflow.config.projects_config import ProjectsConfig

_MINIMAL_APP_CONFIG = {"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}


def test_defaults_when_section_absent():
    config = AppConfig.model_validate(_MINIMAL_APP_CONFIG)

    assert config.projects == ProjectsConfig()
    assert config.projects.instructions_max_bytes == 8192
    assert config.projects.shelf_index_max_entries == 50
    assert config.projects.shelf_index_max_bytes == 4096
    assert config.projects.trash_retention_days == 30
    assert config.projects.summaries_enabled is False
    assert config.projects.summary_max_bytes == 256
    assert config.projects.summary_model_name is None
    assert config.projects.summary_concurrency == 2
    assert config.projects.summary_queue_size == 32
    assert config.projects.summary_timeout_seconds == 60


def test_null_section_falls_back_to_defaults():
    config = AppConfig.model_validate({**_MINIMAL_APP_CONFIG, "projects": None})
    assert config.projects == ProjectsConfig()


def test_explicit_values_are_honored():
    config = AppConfig.model_validate(
        {
            **_MINIMAL_APP_CONFIG,
            "projects": {
                "instructions_max_bytes": 1024,
                "shelf_index_max_entries": 10,
                "shelf_index_max_bytes": 2048,
                "trash_retention_days": 7,
            },
        }
    )
    assert config.projects.instructions_max_bytes == 1024
    assert config.projects.shelf_index_max_entries == 10
    assert config.projects.shelf_index_max_bytes == 2048
    assert config.projects.trash_retention_days == 7


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("instructions_max_bytes", "not-a-number"),
        ("instructions_max_bytes", 255),  # below ge=256
        ("instructions_max_bytes", 262145),  # above le=262144
        ("shelf_index_max_entries", 0),
        ("shelf_index_max_entries", 501),
        ("shelf_index_max_bytes", 511),
        ("shelf_index_max_bytes", 65537),
        ("trash_retention_days", 0),
        ("trash_retention_days", 3651),
        ("trash_retention_days", True),
        # Fractional floats must fall back too: accepting int(512.5) would let
        # the ORIGINAL fractional value reach Pydantic and fail the whole config.
        ("instructions_max_bytes", 512.5),
        ("shelf_index_max_bytes", 1024.5),
        ("trash_retention_days", 30.5),
        # Non-finite floats escape int() (OverflowError/ValueError) entirely.
        ("instructions_max_bytes", float("inf")),
        ("instructions_max_bytes", float("-inf")),
        ("instructions_max_bytes", float("nan")),
        ("shelf_index_max_entries", float("inf")),
        # Absurdly large ints exceed the bounds even though Python holds them.
        ("instructions_max_bytes", 10**400),
    ],
)
def test_invalid_values_fall_back_with_warning(key, value, caplog):
    with caplog.at_level(logging.WARNING):
        config = AppConfig.model_validate({**_MINIMAL_APP_CONFIG, "projects": {key: value}})

    assert getattr(config.projects, key) == getattr(ProjectsConfig(), key)
    assert f"projects.{key}" in caplog.text


def test_int_valued_float_is_accepted_and_coerced():
    """``8192.0`` mirrors the ``_get_upload_limit`` idiom: an int-valued finite
    float is accepted and normalized to a plain int."""
    config = AppConfig.model_validate({**_MINIMAL_APP_CONFIG, "projects": {"instructions_max_bytes": 8192.0}})
    assert config.projects.instructions_max_bytes == 8192
    assert isinstance(config.projects.instructions_max_bytes, int)


def test_summary_bool_field_rejects_non_bool():
    config = AppConfig.model_validate({**_MINIMAL_APP_CONFIG, "projects": {"summaries_enabled": "yes"}})
    assert config.projects.summaries_enabled is False


def test_summary_model_name_rejects_non_str():
    config = AppConfig.model_validate({**_MINIMAL_APP_CONFIG, "projects": {"summary_model_name": 42}})
    assert config.projects.summary_model_name is None
    config = AppConfig.model_validate({**_MINIMAL_APP_CONFIG, "projects": {"summary_model_name": "gpt-x"}})
    assert config.projects.summary_model_name == "gpt-x"


def test_summary_int_bounds_fall_back():
    config = AppConfig.model_validate({**_MINIMAL_APP_CONFIG, "projects": {"summary_concurrency": 99, "summary_queue_size": 0, "summary_timeout_seconds": 1}})
    assert config.projects.summary_concurrency == 2
    assert config.projects.summary_queue_size == 32
    assert config.projects.summary_timeout_seconds == 60


def test_summary_fields_are_registered_startup_only():
    """The generator captures every summary knob at lifespan startup, so the
    fields must be registered restart-required and carry the standard prefix
    (config/AGENTS.md "Config Hot-Reload Boundary")."""
    from deerflow.config.reload_boundary import STARTUP_ONLY_PREFIX, is_startup_only_field

    for name in ("summaries_enabled", "summary_max_bytes", "summary_model_name", "summary_concurrency", "summary_queue_size", "summary_timeout_seconds"):
        assert is_startup_only_field(f"projects.{name}")
        description = ProjectsConfig.model_fields[name].description
        assert description is not None and description.startswith(STARTUP_ONLY_PREFIX)


def test_valid_sibling_values_survive_an_invalid_value():
    config = AppConfig.model_validate({**_MINIMAL_APP_CONFIG, "projects": {"instructions_max_bytes": "junk", "trash_retention_days": 90}})
    assert config.projects.instructions_max_bytes == 8192
    assert config.projects.trash_retention_days == 90


def test_out_of_bounds_values_never_take_effect_on_any_path(caplog):
    """Bounds are enforced everywhere: an out-of-bounds value can never land in
    the model — it falls back to the default with a warning (the
    ``_get_upload_limit`` idiom), on config load and direct construction alike.
    """
    with caplog.at_level(logging.WARNING):
        config = ProjectsConfig(instructions_max_bytes=262145)
    assert config.instructions_max_bytes == 8192
    assert "projects.instructions_max_bytes" in caplog.text


def test_bounds_are_declared_on_the_model():
    """The Field(ge/le) constraints pin the documented §6.4 bounds."""
    from annotated_types import Ge, Le

    expected = {
        "instructions_max_bytes": (256, 262144),
        "shelf_index_max_entries": (1, 500),
        "shelf_index_max_bytes": (512, 65536),
        "trash_retention_days": (1, 3650),
    }
    for name, (lower, upper) in expected.items():
        metadata = ProjectsConfig.model_fields[name].metadata
        assert lower in [m.ge for m in metadata if isinstance(m, Ge)]
        assert upper in [m.le for m in metadata if isinstance(m, Le)]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("instructions_max_bytes", 256),
        ("instructions_max_bytes", 262144),
        ("shelf_index_max_entries", 1),
        ("shelf_index_max_entries", 500),
        ("shelf_index_max_bytes", 512),
        ("shelf_index_max_bytes", 65536),
        ("trash_retention_days", 1),
        ("trash_retention_days", 3650),
    ],
)
def test_boundary_values_accepted(key, value):
    assert getattr(ProjectsConfig(**{key: value}), key) == value
