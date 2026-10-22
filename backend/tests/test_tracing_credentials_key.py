"""Tracing loads encryption authority only when an operation needs credentials."""

from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from app.gateway.app import _load_credentials_cipher
from app.gateway.deps import _enforce_credentials_key, credentials_key_consumers
from deerflow.config import credentials_key
from deerflow.config.credentials_key import CREDENTIALS_KEY_ENV_VAR, CREDENTIALS_KEY_FILENAME, CredentialsKeyError, reset_credentials_cipher
from deerflow.config.deployment_config import MULTI_INSTANCE_ENV_VAR
from deerflow.config.paths import Paths


@pytest.fixture(autouse=True)
def isolated_authority(monkeypatch, tmp_path):
    monkeypatch.delenv(CREDENTIALS_KEY_ENV_VAR, raising=False)
    monkeypatch.delenv(MULTI_INSTANCE_ENV_VAR, raising=False)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path / "home"))
    reset_credentials_cipher()
    yield
    reset_credentials_cipher()


def config(*, backend="postgres", multi_instance=False, scheduler_multi_instance=False):
    return SimpleNamespace(
        database=SimpleNamespace(backend=backend),
        deployment=SimpleNamespace(multi_instance=multi_instance),
        scheduler=SimpleNamespace(multi_instance=scheduler_multi_instance),
        channel_connections=SimpleNamespace(enabled=False),
        extensions=None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("backend,multi_instance", [("sqlite", False), ("postgres", False), ("postgres", True)])
async def test_empty_sql_deployment_does_not_load_or_create_a_credentials_key(tmp_path, backend, multi_instance):
    deployment = config(backend=backend, multi_instance=multi_instance)
    _enforce_credentials_key(deployment)
    assert credentials_key_consumers(deployment) == []
    assert await _load_credentials_cipher(deployment) is None
    assert not (tmp_path / "home" / CREDENTIALS_KEY_FILENAME).exists()


@pytest.mark.parametrize("topology", ["deployment", "environment", "scheduler"])
def test_first_tracing_secret_operation_rejects_missing_shared_key_before_local_generation(monkeypatch, tmp_path, topology):
    deployment = config(multi_instance=topology == "deployment", scheduler_multi_instance=topology == "scheduler")
    if topology == "environment":
        monkeypatch.setenv(MULTI_INSTANCE_ENV_VAR, "1")
    with pytest.raises(CredentialsKeyError, match=CREDENTIALS_KEY_ENV_VAR):
        credentials_key.get_tracing_credentials_cipher(deployment)
    assert not (tmp_path / "home" / CREDENTIALS_KEY_FILENAME).exists()


def test_shared_key_gate_runs_even_after_a_single_instance_cipher_is_cached(tmp_path):
    credentials_key.get_credentials_cipher()
    assert (tmp_path / "home" / CREDENTIALS_KEY_FILENAME).exists()
    with pytest.raises(CredentialsKeyError, match=CREDENTIALS_KEY_ENV_VAR):
        credentials_key.get_tracing_credentials_cipher(config(multi_instance=True))


@pytest.mark.parametrize("topology", ["deployment", "environment", "scheduler"])
def test_tracing_secret_operations_accept_the_explicit_shared_key(monkeypatch, topology):
    monkeypatch.setenv(CREDENTIALS_KEY_ENV_VAR, Fernet.generate_key().decode("ascii"))
    if topology == "environment":
        monkeypatch.setenv(MULTI_INSTANCE_ENV_VAR, "1")
    cipher = credentials_key.get_tracing_credentials_cipher(config(multi_instance=topology == "deployment", scheduler_multi_instance=topology == "scheduler"))
    token = cipher.encrypt_text("test-only-provider-token")
    reset_credentials_cipher()
    reloaded = credentials_key.get_tracing_credentials_cipher(config(multi_instance=topology == "deployment", scheduler_multi_instance=topology == "scheduler"))
    assert reloaded.decrypt_text(token) == "test-only-provider-token"


def test_single_instance_tracing_uses_the_existing_local_key_on_reload(tmp_path):
    cipher = credentials_key.get_tracing_credentials_cipher(config(backend="sqlite"))
    token = cipher.encrypt_text("test-only-provider-token")
    assert (tmp_path / "home" / CREDENTIALS_KEY_FILENAME).exists()
    reset_credentials_cipher()
    assert credentials_key.get_tracing_credentials_cipher(config(backend="sqlite")).decrypt_text(token) == "test-only-provider-token"


def test_cached_cipher_does_not_bypass_malformed_explicit_key_validation(monkeypatch):
    monkeypatch.setenv(CREDENTIALS_KEY_ENV_VAR, Fernet.generate_key().decode("ascii"))
    credentials_key.get_credentials_cipher()
    monkeypatch.setenv(CREDENTIALS_KEY_ENV_VAR, "invalid-test-shared-key")
    with pytest.raises(CredentialsKeyError) as error:
        credentials_key.get_tracing_credentials_cipher(config(multi_instance=True))
    assert "invalid-test-shared-key" not in str(error.value)
