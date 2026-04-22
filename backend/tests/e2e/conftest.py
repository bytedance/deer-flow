"""Shared fixtures for end-to-end API tests."""

import pytest
from fastapi.testclient import TestClient

from app.plugins.auth.api.schemas import _login_attempts
from app.plugins.auth.domain.config import AuthConfig
from app.plugins.auth.runtime.config_state import reset_auth_config, set_auth_config
from store.config.app_config import AppConfig, reset_app_config, set_app_config
from store.config.storage_config import StorageConfig

_TEST_SECRET = "test-secret-key-e2e-auth-minimum-32"


@pytest.fixture()
def client(tmp_path):
    """Create a full app client backed by an isolated SQLite directory."""
    from app.gateway.app import create_app

    _login_attempts.clear()
    reset_auth_config()
    reset_app_config()
    set_auth_config(AuthConfig(jwt_secret=_TEST_SECRET))
    set_app_config(AppConfig(storage=StorageConfig(driver="sqlite", sqlite_dir=str(tmp_path))))

    app = create_app()

    with TestClient(app) as test_client:
        yield test_client

    _login_attempts.clear()
    reset_auth_config()
    reset_app_config()
