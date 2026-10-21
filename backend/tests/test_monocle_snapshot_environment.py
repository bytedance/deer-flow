"""Frozen Monocle snapshots follow their selected exporter's effective settings."""

from types import SimpleNamespace

import pytest

from deerflow.config.tracing_config import MonocleTracingConfig
from deerflow.tracing import profiles


@pytest.fixture
def fingerprint(monkeypatch):
    def calculate(exporters, environment=None, cwd="/worker"):
        config = MonocleTracingConfig(enabled=True, exporters=exporters, okahu_api_key=None)
        with monkeypatch.context() as patch:
            patch.setattr(profiles, "get_tracing_config", lambda: SimpleNamespace(monocle=config))
            patch.setattr(profiles.os, "environ", {"HOME": "/nonexistent-monocle-test-home", **(environment or {})})
            patch.setattr(profiles.os, "getcwd", lambda: cwd)
            return profiles.current_monocle_fingerprint()

    return calculate


@pytest.mark.parametrize("exporter", ["file", "console"])
@pytest.mark.parametrize(
    "name", ["AWS_SESSION_TOKEN", "AWS_LAMBDA_RUNTIME_API", "AZURE_CLIENT_SECRET", "GOOGLE_CLOUD_PROJECT", "OTEL_EXPORTER_OTLP_TRACES_HEADERS", "OTEL_RESOURCE_ATTRIBUTES", "OTEL_BSP_MAX_QUEUE_SIZE", "OTEL_TRACES_SAMPLER"]
)
def test_local_exporters_ignore_other_exporter_credentials(fingerprint, exporter, name):
    assert fingerprint(exporter, {name: "fake-first"}) == fingerprint(exporter, {name: "fake-second"})


def test_console_ignores_working_directory(fingerprint):
    assert fingerprint("console", cwd="/worker-a") == fingerprint("console", cwd="/worker-b")


def test_file_only_depends_on_cwd_for_relative_output(fingerprint):
    assert fingerprint("file", cwd="/worker-a") != fingerprint("file", cwd="/worker-b")
    environment = {"MONOCLE_TRACE_OUTPUT_PATH": "/var/traces"}
    assert fingerprint("file", environment, cwd="/worker-a") == fingerprint("file", environment, cwd="/worker-b")


@pytest.mark.parametrize("name", ["MONOCLE_TRACE_OUTPUT_PATH", "MONOCLE_FILE_PREFIX"])
def test_file_destination_changes_are_incompatible(fingerprint, name):
    assert fingerprint("file", {name: "first"}) != fingerprint("file", {name: "second"})


def test_selected_s3_rejects_session_token_changes(fingerprint):
    environment = {"MONOCLE_S3_BUCKET_NAME": "example-traces"}
    assert fingerprint("s3", {**environment, "AWS_SESSION_TOKEN": "fake-first"}) != fingerprint("s3", {**environment, "AWS_SESSION_TOKEN": "fake-second"})


@pytest.mark.parametrize("prefix", ["AWS", "MONOCLE_AWS"])
def test_s3_explicit_key_pair_does_not_forward_ambient_session_token(fingerprint, prefix):
    environment = {f"{prefix}_ACCESS_KEY_ID": "fake-access", f"{prefix}_SECRET_ACCESS_KEY": "fake-secret"}
    assert fingerprint("s3", {**environment, "AWS_SESSION_TOKEN": "first"}) == fingerprint("s3", {**environment, "AWS_SESSION_TOKEN": "second"})


def test_s3_ignores_other_cloud_and_otel_destinations(fingerprint):
    environment = {"AWS_ACCESS_KEY_ID": "fake-access", "AWS_SECRET_ACCESS_KEY": "fake-secret", "MONOCLE_S3_BUCKET_NAME": "example-traces"}
    assert fingerprint("s3", {**environment, "AZURE_CLIENT_SECRET": "first"}, cwd="/a") == fingerprint("s3", {**environment, "AZURE_CLIENT_SECRET": "second"}, cwd="/b")


def test_otlp_ignores_metrics_endpoint_and_unrelated_cloud_credentials(fingerprint):
    environment = {"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "https://example.com/v1/traces"}
    assert fingerprint("otlp", {**environment, "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": "https://one.example.com", "AWS_SESSION_TOKEN": "first"}, cwd="/a") == fingerprint(
        "otlp", {**environment, "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": "https://two.example.com", "AWS_SESSION_TOKEN": "second"}, cwd="/b"
    )


@pytest.mark.parametrize("name", ["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_HEADERS"])
def test_selected_otlp_destination_and_auth_changes_are_incompatible(fingerprint, name):
    assert fingerprint("otlp", {name: "first"}) != fingerprint("otlp", {name: "second"})


def test_otlp_trace_specific_environment_overrides_generic_values(fingerprint):
    environment = {"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "https://example.com/v1/traces", "OTEL_EXPORTER_OTLP_TRACES_HEADERS": "authorization=fake-trace"}
    assert fingerprint("otlp", {**environment, "OTEL_EXPORTER_OTLP_ENDPOINT": "https://one.example.com", "OTEL_EXPORTER_OTLP_HEADERS": "authorization=first"}) == fingerprint(
        "otlp", {**environment, "OTEL_EXPORTER_OTLP_ENDPOINT": "https://two.example.com", "OTEL_EXPORTER_OTLP_HEADERS": "authorization=second"}
    )


@pytest.mark.parametrize("exporter, name", [("s3", "AWS_WEB_IDENTITY_TOKEN_FILE"), ("gcs", "GOOGLE_APPLICATION_CREDENTIALS"), ("otlp", "OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE")])
def test_selected_credential_and_certificate_file_contents_are_frozen(fingerprint, tmp_path, exporter, name):
    path = tmp_path / "fake-credential"
    path.write_text("fake-first", encoding="utf-8")
    environment = {name: str(path)}
    initial = fingerprint(exporter, environment)
    path.write_text("fake-second", encoding="utf-8")
    assert initial != fingerprint(exporter, environment)


def test_otlp_generic_certificate_is_ignored_when_trace_certificate_selected(fingerprint, tmp_path):
    path = tmp_path / "fake-certificate"
    path.write_text("fake-trust", encoding="utf-8")
    environment = {"OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE": str(path)}
    assert fingerprint("otlp", {**environment, "OTEL_EXPORTER_OTLP_CERTIFICATE": "/missing-first"}) == fingerprint("otlp", {**environment, "OTEL_EXPORTER_OTLP_CERTIFICATE": "/missing-second"})


@pytest.mark.parametrize("exporter", ["s3", "gcs", "blob"])
def test_ambient_cloud_credential_discovery_remains_supported(fingerprint, exporter):
    assert fingerprint(exporter)


def test_s3_explicit_monocle_credentials_override_other_aws_credentials(fingerprint):
    environment = {"MONOCLE_AWS_ACCESS_KEY_ID": "fake-access", "MONOCLE_AWS_SECRET_ACCESS_KEY": "fake-secret"}
    assert fingerprint("s3", {**environment, "AWS_SECRET_ACCESS_KEY": "first"}) == fingerprint("s3", {**environment, "AWS_SECRET_ACCESS_KEY": "second"})


def test_s3_default_profile_overrides_profile_for_endpoint_selection(fingerprint, tmp_path):
    config = tmp_path / "aws-config"
    config.write_text("[profile first]\nregion = us-east-1\nendpoint_url = https://first.example.com\n[profile second]\nregion = us-west-2\nendpoint_url = https://second.example.com\n", encoding="utf-8")
    environment = {"AWS_ACCESS_KEY_ID": "fake-access", "AWS_SECRET_ACCESS_KEY": "fake-secret", "AWS_CONFIG_FILE": str(config), "AWS_PROFILE": "first"}
    assert fingerprint("s3", {**environment, "AWS_DEFAULT_PROFILE": "first"}) != fingerprint("s3", {**environment, "AWS_DEFAULT_PROFILE": "second"})


def test_s3_shadowed_profile_does_not_change_selected_destination(fingerprint):
    environment = {"AWS_ACCESS_KEY_ID": "fake-access", "AWS_SECRET_ACCESS_KEY": "fake-secret", "AWS_DEFAULT_PROFILE": "selected"}
    assert fingerprint("s3", {**environment, "AWS_PROFILE": "first"}) == fingerprint("s3", {**environment, "AWS_PROFILE": "second"})


@pytest.mark.parametrize("name", ["MONOCLE_BLOB_CONNECTION_STRING", "MONOCLE_BLOB_CONTAINER_NAME", "MONOCLE_BLOB_FILE_PREFIX"])
def test_blob_tracks_selected_destination_and_auth(fingerprint, name):
    assert fingerprint("blob", {name: "fake-first"}) != fingerprint("blob", {name: "fake-second"})


def test_blob_ignores_unselected_azure_identity(fingerprint):
    assert fingerprint("blob", {"AZURE_CLIENT_SECRET": "first"}) == fingerprint("blob", {"AZURE_CLIENT_SECRET": "second"})


def test_okahu_uses_environment_before_sdk_env_files(fingerprint, tmp_path):
    path = tmp_path / ".env.monocle"
    path.write_text("OKAHU_API_KEY=fake-file-first\n", encoding="utf-8")
    initial = fingerprint("okahu", cwd=str(tmp_path))
    path.write_text("OKAHU_API_KEY=fake-file-second\n", encoding="utf-8")
    assert initial != fingerprint("okahu", cwd=str(tmp_path))
    environment = {"OKAHU_API_KEY": "fake-env"}
    explicit = fingerprint("okahu", environment, cwd=str(tmp_path))
    path.write_text("OKAHU_API_KEY=fake-file-third\n", encoding="utf-8")
    assert explicit == fingerprint("okahu", environment, cwd=str(tmp_path))


def test_unknown_exporter_fails_closed(fingerprint):
    with pytest.raises(ValueError, match="cannot be fingerprinted"):
        fingerprint("unknown")


def test_selected_missing_certificate_fails_without_exposing_path(fingerprint):
    with pytest.raises(ValueError, match="file is unavailable") as error:
        fingerprint("otlp", {"OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE": "/missing-private-test-file"})
    assert "private-test-file" not in str(error.value)


def test_snapshot_restore_accepts_unrelated_environment_and_rejects_selected_changes(monkeypatch, tmp_path):
    config = MonocleTracingConfig(enabled=True, exporters="file", okahu_api_key=None)
    monkeypatch.setattr(profiles, "get_tracing_config", lambda: SimpleNamespace(monocle=config))
    monkeypatch.setenv("MONOCLE_TRACE_OUTPUT_PATH", str(tmp_path))
    snapshot = profiles.RunTracingSnapshot(snapshot_id="fake", owner_user_id="alice", agent_name="lead_agent", mode="inherit", revision="1", providers=(), monocle_enabled=True, monocle_fingerprint=profiles.current_monocle_fingerprint())
    monkeypatch.setenv("AWS_SESSION_TOKEN", "fake-rotated")
    profiles.validate_snapshot_environment(snapshot)
    monkeypatch.setenv("MONOCLE_FILE_PREFIX", "changed_")
    with pytest.raises(profiles.TracingUnavailableError, match="differs"):
        profiles.validate_snapshot_environment(snapshot)
