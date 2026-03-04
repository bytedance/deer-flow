"""Shared test fixtures for the test suite."""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture()
def tmp_store_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Provide a temporary directory for file-based stores.

    Patches all store modules to use the temporary directory instead of
    the real .think-tank directory. Also forces file-based mode by
    disabling the database path (in case DATABASE_URL is set via .env).
    This ensures tests are fully isolated.
    """
    store_dir = tmp_path / ".think-tank"
    store_dir.mkdir()

    # Save and remove DATABASE_URL so is_db_enabled() returns False
    saved_db_url = os.environ.pop("DATABASE_URL", None)
    # Save and remove ENCRYPTION_KEY so tests use file-based key generation
    saved_enc_key = os.environ.pop("ENCRYPTION_KEY", None)

    patches = [
        # Force file-based mode regardless of environment
        patch("src.db.engine.is_db_enabled", return_value=False),
        patch("src.gateway.auth.user_store._STORE_DIR", store_dir),
        patch("src.gateway.auth.user_store._DATA_FILE", store_dir / "users.json"),
        patch("src.gateway.auth.thread_store._STORE_DIR", store_dir),
        patch("src.gateway.auth.thread_store._DATA_FILE", store_dir / "thread-ownership.json"),
        patch("src.gateway.auth.jwt._STORE_DIR", store_dir),
        patch("src.gateway.auth.jwt._SECRET_FILE", store_dir / "jwt-secret.key"),
        patch("src.security.api_key_store._STORE_DIR", store_dir),
        patch("src.security.api_key_store._KEY_FILE", store_dir / "api-keys.key"),
        patch("src.security.api_key_store._DATA_FILE", store_dir / "api-keys.json"),
        patch("src.security.model_preference_store._STORE_DIR", store_dir),
        patch("src.security.model_preference_store._DATA_FILE", store_dir / "model-preferences.json"),
    ]

    for p in patches:
        p.start()

    yield store_dir

    for p in patches:
        p.stop()

    # Restore DATABASE_URL if it was previously set
    if saved_db_url is not None:
        os.environ["DATABASE_URL"] = saved_db_url
    # Restore ENCRYPTION_KEY if it was previously set
    if saved_enc_key is not None:
        os.environ["ENCRYPTION_KEY"] = saved_enc_key


@pytest.fixture()
def jwt_secret(tmp_store_dir: Path) -> str:
    """Set a deterministic JWT secret for testing."""
    secret = "test-jwt-secret-key-for-unit-tests-only"
    os.environ["JWT_SECRET_KEY"] = secret
    yield secret
    os.environ.pop("JWT_SECRET_KEY", None)


@pytest.fixture()
def sample_user_data() -> dict[str, str]:
    """Provide sample user registration data."""
    return {
        "email": "test@example.com",
        "password": "SecurePass1",
        "display_name": "Test User",
    }


# ---------------------------------------------------------------------------
# Database test fixtures (SQLite in-memory for fast, isolated testing)
# ---------------------------------------------------------------------------
@pytest.fixture()
def db_engine():
    """Create a SQLite in-memory engine for testing.

    Creates all tables from ORM models and yields the engine.
    """
    # Import models to register them with Base
    import src.db.models  # noqa: F401
    from src.db.engine import Base

    engine = create_engine("sqlite:///:memory:", echo=False)

    # Enable foreign key support in SQLite
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def db_session(db_engine) -> Generator[Session, None, None]:
    """Provide a database session for testing.

    Each test gets a clean session. Rolls back after each test.
    """
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    session = factory()
    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def db_enabled(db_engine) -> Generator[None, None, None]:
    """Enable database mode for tests by patching the engine module.

    This patches:
    - is_db_enabled() to return True
    - get_engine() to return the test SQLite engine
    - get_session_factory() to return a session factory bound to the test engine
    """
    import src.db.engine as engine_module

    factory = sessionmaker(bind=db_engine, expire_on_commit=False)

    patches = [
        patch.object(engine_module, "_engine", db_engine),
        patch.object(engine_module, "_session_factory", factory),
        patch("src.db.engine.is_db_enabled", return_value=True),
    ]

    # Also set a fake DATABASE_URL so is_db_enabled checks pass in stores
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"

    for p in patches:
        p.start()

    yield

    for p in patches:
        p.stop()

    os.environ.pop("DATABASE_URL", None)


# ---------------------------------------------------------------------------
# Sandbox & Runtime test fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def mock_sandbox_provider(tmp_path: Path):
    """Provide a mock SandboxProvider backed by a LocalSandbox on tmp_path.

    Patches `get_sandbox_provider()` so sandbox tool tests never touch
    the real filesystem outside of the test temp directory.
    """
    from unittest.mock import MagicMock

    from src.sandbox.local.local_sandbox import LocalSandbox

    sandbox = LocalSandbox(id="local", path_mappings={})
    provider = MagicMock()
    provider.acquire.return_value = "local"
    provider.get.return_value = sandbox

    with patch("src.sandbox.sandbox_provider.get_sandbox_provider", return_value=provider):
        with patch("src.sandbox.tools.get_sandbox_provider", return_value=provider):
            yield provider


@pytest.fixture()
def mock_runtime(tmp_path: Path):
    """Build a fake ToolRuntime with populated state and context.

    The runtime has:
    - state.sandbox = {"sandbox_id": "local"}
    - state.thread_data with workspace/uploads/outputs paths under tmp_path
    - context.thread_id = "test-thread-123"
    - context.user_id = "test-user-456"
    """
    from unittest.mock import MagicMock

    workspace = tmp_path / "workspace"
    uploads = tmp_path / "uploads"
    outputs = tmp_path / "outputs"
    workspace.mkdir()
    uploads.mkdir()
    outputs.mkdir()

    state = {
        "sandbox": {"sandbox_id": "local"},
        "thread_data": {
            "workspace_path": str(workspace),
            "uploads_path": str(uploads),
            "outputs_path": str(outputs),
        },
        "thread_directories_created": False,
    }

    context = {
        "thread_id": "test-thread-123",
        "user_id": "test-user-456",
    }

    runtime = MagicMock()
    runtime.state = state
    runtime.context = context

    # Make state behave like a dict (support .get() and [] access)
    runtime.state.__getitem__ = state.__getitem__
    runtime.state.__setitem__ = state.__setitem__
    runtime.state.__contains__ = state.__contains__
    runtime.state.get = state.get

    runtime.context.__getitem__ = context.__getitem__
    runtime.context.get = context.get

    yield runtime
