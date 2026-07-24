import pytest

from app.gateway.routers.thread_runs import _record_to_response
from app.gateway.routers.threads import HistoryEntry, ThreadResponse, ThreadStateResponse
from deerflow.runtime.runs.manager import RunRecord
from deerflow.runtime.runs.schemas import DisconnectMode, RunStatus
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


def test_run_response_hides_historical_auth_token_without_mutating_record():
    legacy_metadata = {"auth_token": "legacy-secret", "token_usage": 7}
    record = RunRecord(
        run_id="legacy-run",
        thread_id="legacy-thread",
        assistant_id="lead_agent",
        status=RunStatus.success,
        on_disconnect=DisconnectMode.cancel,
        metadata=legacy_metadata,
    )

    response = _record_to_response(record)

    assert response.metadata == {"token_usage": 7}
    assert record.metadata["auth_token"] == "legacy-secret"


@pytest.mark.parametrize(
    ("response_class", "required_fields"),
    [
        (ThreadResponse, {"thread_id": "legacy-thread"}),
        (ThreadStateResponse, {}),
        (HistoryEntry, {"checkpoint_id": "legacy-checkpoint"}),
    ],
)
def test_thread_metadata_response_models_hide_historical_auth_token(
    response_class,
    required_fields,
):
    source = {"auth_token": "legacy-secret", "token_usage": 7}

    response = response_class(**required_fields, metadata=source)

    assert response.metadata == {"token_usage": 7}
    assert source["auth_token"] == "legacy-secret"
