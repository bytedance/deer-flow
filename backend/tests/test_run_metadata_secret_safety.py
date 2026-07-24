import pytest

from deerflow.runtime.secret_context import (
    LegacyRunMetadataSecretError,
    redact_metadata_secrets,
    validate_run_metadata_secrets,
)


@pytest.mark.parametrize("value", ["secret", "", None, {"nested": True}])
def test_validate_run_metadata_rejects_auth_token_key_by_presence(value):
    with pytest.raises(LegacyRunMetadataSecretError, match=r"config\.context\.secrets"):
        validate_run_metadata_secrets({"auth_token": value, "token_usage": 7})


@pytest.mark.parametrize(
    "metadata",
    [None, "not-a-mapping", {"token": "keep", "nested": {"auth_token": "keep"}}],
)
def test_validate_run_metadata_accepts_non_legacy_shapes(metadata):
    validate_run_metadata_secrets(metadata)


def test_redact_metadata_secrets_removes_exact_key_without_mutating_source():
    source = {
        "auth_token": "legacy-secret",
        "token_usage": 7,
        "nested": {"auth_token": "ordinary-nested-metadata"},
    }

    redacted = redact_metadata_secrets(source)

    assert redacted == {
        "token_usage": 7,
        "nested": {"auth_token": "ordinary-nested-metadata"},
    }
    assert source["auth_token"] == "legacy-secret"
    assert redacted is not source
