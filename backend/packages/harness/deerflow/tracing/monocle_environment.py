"""Fingerprint effective exporter inputs for the pinned Monocle 0.8.8 integration.

Only selected exporters contribute cloud/auth settings. Values and selected
credential-file contents are hashed in memory and never returned or logged.
This does not initialize SDK clients or contact credential/metadata services.
Ambient SDK credential discovery remains supported; an environment fingerprint
cannot prove that a metadata service or a credential plugin retains its identity.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deerflow.config.tracing_config import MonocleTracingConfig

_SUPPORTED = {"file", "console", "okahu", "s3", "blob", "gcs", "otlp"}


def _file_digest(value: str, cwd: str) -> str:
    path = Path(value)
    if not path.is_absolute():
        path = Path(cwd) / path
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        raise ValueError("A selected Monocle credential or certificate file is unavailable") from None


def _okahu_value(key: str, env: Mapping[str, str], cwd: str) -> str | None:
    # Same precedence and line parsing as monocle's get_monocle_env_value().
    if value := env.get(key):
        return value
    home = env.get("HOME") or os.path.expanduser("~")
    for path in (Path(cwd) / ".env.monocle", Path(home) / ".monocle" / ".env"):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if line.startswith(f"{key}="):
                value = line.split("=", 1)[1].strip()
                if value.startswith(('"', "'")):
                    value = value[1:-1].strip()
                if value:
                    return value
    return None


def _http_settings(env: Mapping[str, str], cwd: str) -> dict:
    # requests' transport may route through proxies and override the TLS trust.
    settings = {key: env.get(key) for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy")}
    trust = env.get("REQUESTS_CA_BUNDLE") or env.get("CURL_CA_BUNDLE")
    if trust:
        settings["trust"] = _file_digest(trust, cwd)
    return settings


def _s3_settings(env: Mapping[str, str], cwd: str) -> dict:
    monocle_credentials = env.get("MONOCLE_AWS_ACCESS_KEY_ID") and env.get("MONOCLE_AWS_SECRET_ACCESS_KEY")
    access_key = env.get("MONOCLE_AWS_ACCESS_KEY_ID" if monocle_credentials else "AWS_ACCESS_KEY_ID")
    secret_key = env.get("MONOCLE_AWS_SECRET_ACCESS_KEY" if monocle_credentials else "AWS_SECRET_ACCESS_KEY")
    settings = {
        "access_key": access_key,
        "secret_key": secret_key,
        "bucket": env.get("MONOCLE_S3_BUCKET_NAME", "default-bucket"),
        "prefix": env.get("MONOCLE_S3_FILE_PREFIX") or env.get("MONOCLE_S3_KEY_PREFIX") or "monocle_trace_",
        "current_prefix": env.get("MONOCLE_S3_KEY_PREFIX_CURRENT"),
        "sdk": {
            key: env.get(key)
            for key in ("AWS_DEFAULT_REGION", "AWS_REGION", "AWS_ENDPOINT_URL", "AWS_ENDPOINT_URL_S3", "AWS_IGNORE_CONFIGURED_ENDPOINT_URLS", "AWS_USE_FIPS_ENDPOINT", "AWS_USE_DUALSTACK_ENDPOINT", "AWS_STS_REGIONAL_ENDPOINTS")
        },
    }
    if not access_key or not secret_key:
        settings["session_token"] = env.get("AWS_SESSION_TOKEN")
        settings["credential_chain"] = {
            key: env.get(key)
            for key in (
                "AWS_ROLE_ARN",
                "AWS_ROLE_SESSION_NAME",
                "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
                "AWS_CONTAINER_CREDENTIALS_FULL_URI",
                "AWS_CONTAINER_AUTHORIZATION_TOKEN",
                "AWS_EC2_METADATA_DISABLED",
                "AWS_EC2_METADATA_SERVICE_ENDPOINT",
                "AWS_EC2_METADATA_SERVICE_ENDPOINT_MODE",
            )
        }
        for key in ("AWS_SHARED_CREDENTIALS_FILE", "AWS_WEB_IDENTITY_TOKEN_FILE", "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE"):
            if env.get(key):
                settings[key] = _file_digest(env[key], cwd)
    # Even with explicit credentials, botocore profiles can select endpoints,
    # regions and S3 addressing. Track the selected config, not other AWS env.
    config_file = env.get("AWS_CONFIG_FILE")
    if config_file:
        settings["config"] = _file_digest(config_file, cwd)
    # Botocore's ordered profile providers prefer AWS_DEFAULT_PROFILE, including
    # an explicitly present empty value, before consulting AWS_PROFILE.
    settings["profile"] = env.get("AWS_DEFAULT_PROFILE", env.get("AWS_PROFILE", "default"))
    if env.get("AWS_CA_BUNDLE"):
        settings["ca"] = _file_digest(env["AWS_CA_BUNDLE"], cwd)
    return settings


def _gcs_settings(env: Mapping[str, str], cwd: str) -> dict:
    credentials = env.get("GOOGLE_APPLICATION_CREDENTIALS")
    settings = {
        "bucket": env.get("MONOCLE_GCS_BUCKET_NAME"),
        "project": env.get("MONOCLE_GCS_PROJECT_ID") or env.get("GOOGLE_CLOUD_PROJECT") or env.get("GCLOUD_PROJECT"),
        "location": env.get("MONOCLE_GCS_LOCATION", "US"),
        "prefix": env.get("MONOCLE_GCS_KEY_PREFIX", "monocle_trace_"),
        "endpoint": env.get("STORAGE_EMULATOR_HOST"),
        "quota_project": env.get("GOOGLE_CLOUD_QUOTA_PROJECT"),
        "universe": env.get("GOOGLE_CLOUD_UNIVERSE_DOMAIN"),
        "credential_chain": {key: env.get(key) for key in ("CLOUDSDK_CONFIG", "GCE_METADATA_HOST", "GCE_METADATA_ROOT", "GCE_METADATA_IP", "GOOGLE_API_USE_MTLS_ENDPOINT", "GOOGLE_API_USE_CLIENT_CERTIFICATE")},
    }
    if credentials:
        settings["credentials"] = _file_digest(credentials, cwd)
    return settings


def _otlp_settings(env: Mapping[str, str], cwd: str) -> dict:
    # Pinned HTTP exporter resolves truthy traces-specific values before generic
    # ones. Metrics/logs variables never configure this exporter.
    def effective(suffix: str, default: str = "") -> str:
        return env.get(f"OTEL_EXPORTER_OTLP_TRACES_{suffix}") or env.get(f"OTEL_EXPORTER_OTLP_{suffix}") or default

    settings = {
        "endpoint": env.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or (env.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "http://localhost:4318").removesuffix("/") + "/v1/traces",
        "headers": effective("HEADERS"),
        "timeout": effective("TIMEOUT", "10"),
        "compression": effective("COMPRESSION", "none").lower().strip(),
        "credential_provider": env.get("OTEL_PYTHON_EXPORTER_OTLP_HTTP_CREDENTIAL_PROVIDER") or env.get("OTEL_PYTHON_EXPORTER_OTLP_HTTP_TRACES_CREDENTIAL_PROVIDER"),
    }
    for suffix in ("CERTIFICATE", "CLIENT_CERTIFICATE", "CLIENT_KEY"):
        value = effective(suffix)
        if value:
            settings[suffix] = _file_digest(value, cwd)
    return settings


def fingerprint_monocle_environment(config: MonocleTracingConfig, *, environment: Mapping[str, str] | None = None, working_directory: str | None = None) -> str:
    """Return a digest without initializing exporters or exposing secret values.

    SDK cloud discovery and credential plugins remain supported. Their external
    identity is outside this offline compatibility check; explicit selected
    credentials, files and provider selectors still contribute to the digest.
    """
    env = os.environ if environment is None else environment
    cwd = os.getcwd() if working_directory is None else working_directory
    selected = [value.strip() for value in config.exporters.split(",") if value.strip()]
    if not selected or any(value not in _SUPPORTED for value in selected):
        raise ValueError("The selected Monocle exporter cannot be fingerprinted")
    if env.get("MONOCLE_CONSOLE", "").lower() in ("1", "true", "yes") and "console" not in selected:
        selected.append("console")
    settings = {"enabled": config.enabled, "exporters": selected, "sdk_disabled": env.get("OTEL_SDK_DISABLED", "").lower() == "true"}
    for exporter in selected:
        if exporter == "file":
            output = env.get("MONOCLE_TRACE_OUTPUT_PATH", "./.monocle")
            settings[exporter] = {"output": os.path.normpath(output if os.path.isabs(output) else os.path.join(cwd, output)), "prefix": env.get("MONOCLE_FILE_PREFIX", "monocle_trace_")}
        elif exporter == "okahu":
            settings[exporter] = {"endpoint": _okahu_value("OKAHU_INGESTION_ENDPOINT", env, cwd) or "https://ingest.okahu.co/api/v1/trace/ingest", "api_key": _okahu_value("OKAHU_API_KEY", env, cwd)}
        elif exporter == "blob":
            settings[exporter] = {"connection": env.get("MONOCLE_BLOB_CONNECTION_STRING"), "container": env.get("MONOCLE_BLOB_CONTAINER_NAME", "default-container"), "prefix": env.get("MONOCLE_BLOB_FILE_PREFIX", "monocle_trace_")}
        elif exporter == "s3":
            settings[exporter] = _s3_settings(env, cwd)
        elif exporter == "gcs":
            settings[exporter] = _gcs_settings(env, cwd)
        elif exporter == "otlp":
            settings[exporter] = _otlp_settings(env, cwd)
        if exporter in {"okahu", "blob", "gcs", "otlp"}:
            settings[f"{exporter}_http"] = _http_settings(env, cwd)
    return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
