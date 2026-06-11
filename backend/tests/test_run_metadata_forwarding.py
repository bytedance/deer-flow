"""Tests for request.state.run_metadata -> config["metadata"] forwarding."""

from unittest.mock import MagicMock

from app.gateway.services import inject_run_metadata


def _make_request(*, run_metadata=None, has_attr=True):
    """Build a mock Request with optional run_metadata on state."""
    request = MagicMock()
    if has_attr:
        request.state.run_metadata = run_metadata
    else:
        # Simulate attribute not existing
        request.state = MagicMock(spec=[])
    return request


def test_run_metadata_merged_into_config():
    """run_metadata dict values are merged into config["metadata"]."""
    request = _make_request(run_metadata={"token": "abc123", "project": "42"})
    config: dict = {}

    inject_run_metadata(config, request)

    assert config["metadata"] == {"token": "abc123", "project": "42"}


def test_missing_run_metadata_is_noop():
    """When request.state has no run_metadata, config is not modified."""
    request = _make_request(has_attr=False)
    config: dict = {}

    inject_run_metadata(config, request)

    assert "metadata" not in config


def test_none_run_metadata_is_noop():
    """When run_metadata is None, config is not modified."""
    request = _make_request(run_metadata=None)
    config: dict = {}

    inject_run_metadata(config, request)

    assert "metadata" not in config


def test_empty_dict_run_metadata_is_noop():
    """When run_metadata is an empty dict, config is not modified."""
    request = _make_request(run_metadata={})
    config: dict = {}

    inject_run_metadata(config, request)

    assert "metadata" not in config


def test_existing_metadata_preserved():
    """Existing config["metadata"] keys are preserved; run_metadata adds new ones."""
    request = _make_request(run_metadata={"new_key": "new_value"})
    config: dict = {"metadata": {"existing": "kept"}}

    inject_run_metadata(config, request)

    assert config["metadata"] == {"existing": "kept", "new_key": "new_value"}


def test_run_metadata_can_overwrite_same_key():
    """When run_metadata has a key that already exists in metadata, the new value wins."""
    request = _make_request(run_metadata={"key": "updated"})
    config: dict = {"metadata": {"key": "original"}}

    inject_run_metadata(config, request)

    assert config["metadata"]["key"] == "updated"


def test_non_dict_run_metadata_is_ignored():
    """Non-dict run_metadata (e.g. a list or string) is ignored via isinstance guard."""
    request = _make_request(run_metadata="not a dict")
    config: dict = {}

    inject_run_metadata(config, request)

    assert "metadata" not in config
