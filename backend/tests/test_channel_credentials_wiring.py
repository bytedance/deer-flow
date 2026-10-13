"""Per-connection channel credentials use the deployment credentials key.

Before ``DEER_FLOW_CREDENTIALS_KEY`` no production construction site passed a
cipher to ``ChannelConnectionRepository``: ``store_credentials`` refused
(``RuntimeError``) and ``get_credentials`` always answered ``None``, so Slack
replies always fell back to the deployment bot token. The Gateway now loads
the cipher once at startup (off the event loop) for the features that need it
and hands it to the channel service, the scheduled-task notification outbox
and the channel-connections router.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet

from app.channels.message_bus import MessageBus, OutboundMessage
from deerflow.config.credentials_key import (
    CIPHERTEXT_PREFIX,
    CREDENTIALS_KEY_ENV_VAR,
    CREDENTIALS_KEY_FILENAME,
    CredentialsCipher,
    load_credentials_cipher,
    reset_credentials_cipher,
)
from deerflow.config.paths import Paths

KEY_OLD = Fernet.generate_key().decode("ascii")
KEY_NEW = Fernet.generate_key().decode("ascii")


@pytest.fixture(autouse=True)
def _isolated_cipher(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delenv(CREDENTIALS_KEY_ENV_VAR, raising=False)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path / "home"))
    reset_credentials_cipher()
    yield
    reset_credentials_cipher()


def _startup_config(*, channel_connections: bool) -> SimpleNamespace:
    return SimpleNamespace(channel_connections=SimpleNamespace(enabled=channel_connections))


@pytest.fixture
async def session_factory(tmp_path: Path):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'channels.db'}", sqlite_dir=str(tmp_path))
    try:
        yield get_session_factory()
    finally:
        await close_engine()


async def _connection(repo) -> str:
    connection = await repo.upsert_connection(owner_user_id="alice", provider="slack", external_account_id="U-alice", workspace_id="T1")
    return connection["id"]


# ---------------------------------------------------------------------------
# Startup loading
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_no_key_is_loaded_or_generated_when_no_feature_needs_it(tmp_path: Path) -> None:
    from app.gateway.app import _load_credentials_cipher

    assert await _load_credentials_cipher(_startup_config(channel_connections=False)) is None
    assert not (tmp_path / "home" / CREDENTIALS_KEY_FILENAME).exists()


@pytest.mark.anyio
async def test_channel_connections_load_the_generated_key_file(tmp_path: Path) -> None:
    from app.gateway.app import _load_credentials_cipher

    cipher = await _load_credentials_cipher(_startup_config(channel_connections=True))

    assert isinstance(cipher, CredentialsCipher)
    key_file = tmp_path / "home" / CREDENTIALS_KEY_FILENAME
    assert key_file.exists()
    assert CredentialsCipher.from_keys([key_file.read_text(encoding="utf-8").strip()]).decrypt_text(cipher.encrypt_text("x")) == "x"


@pytest.mark.anyio
async def test_channel_connections_prefer_the_environment_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.gateway.app import _load_credentials_cipher

    monkeypatch.setenv(CREDENTIALS_KEY_ENV_VAR, KEY_NEW)

    cipher = await _load_credentials_cipher(_startup_config(channel_connections=True))

    assert CredentialsCipher.from_keys([KEY_NEW]).decrypt_text(cipher.encrypt_text("x")) == "x"
    assert not (tmp_path / "home" / CREDENTIALS_KEY_FILENAME).exists()


@pytest.mark.anyio
async def test_an_unloadable_key_degrades_to_no_stored_credentials(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """A broken key file must not take the Gateway down: credentials stay unavailable, as before the key existed."""
    from app.gateway import app as gateway_app

    def broken_loader():
        raise OSError("read-only file system")

    monkeypatch.setattr("deerflow.config.credentials_key.get_credentials_cipher", broken_loader)
    with caplog.at_level(logging.ERROR, logger=gateway_app.logger.name):
        assert await gateway_app._load_credentials_cipher(_startup_config(channel_connections=True)) is None
    assert any("credentials" in record.getMessage().lower() for record in caplog.records)


# ---------------------------------------------------------------------------
# Construction sites
# ---------------------------------------------------------------------------


def test_the_channel_service_repository_gets_the_cipher(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.channels.service import _make_connection_repo

    sentinel_factory = MagicMock(name="session_factory")
    monkeypatch.setattr("deerflow.persistence.engine.get_session_factory", lambda: sentinel_factory)
    cipher = CredentialsCipher.from_keys([KEY_NEW])

    repo = _make_connection_repo(SimpleNamespace(enabled=True), credentials_cipher=cipher)

    assert repo is not None
    assert repo.session_factory is sentinel_factory
    assert repo._cipher is cipher
    assert _make_connection_repo(SimpleNamespace(enabled=True))._cipher is None, "callers that pass no cipher keep the old behaviour"


def test_the_notification_outbox_repository_gets_the_cipher(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.gateway.app import _scheduled_task_notification_repos

    monkeypatch.setattr("deerflow.persistence.engine.get_session_factory", lambda: MagicMock(name="session_factory"))
    cipher = CredentialsCipher.from_keys([KEY_NEW])

    connection_repo, notification_repo = _scheduled_task_notification_repos(_startup_config(channel_connections=True), cipher)

    assert connection_repo._cipher is cipher
    assert notification_repo is not None


def test_the_router_repository_gets_the_cipher_from_app_state(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.gateway.routers import channel_connections

    monkeypatch.setattr(channel_connections, "get_session_factory", lambda: MagicMock(name="session_factory"))
    cipher = CredentialsCipher.from_keys([KEY_NEW])
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(credentials_cipher=cipher)))

    repo = channel_connections._get_repository(request, MagicMock())

    assert repo._cipher is cipher
    assert request.app.state.channel_connection_repo is repo


def test_start_channel_service_threads_the_cipher_through(monkeypatch: pytest.MonkeyPatch) -> None:
    import anyio

    import app.channels.service as service_module

    captured: dict[str, object] = {}

    class _FakeService:
        async def start(self):
            return None

    def fake_from_app_config(app_config=None, *, get_stream_bridge=None, credentials_cipher=None):
        captured["credentials_cipher"] = credentials_cipher
        return _FakeService()

    cipher = CredentialsCipher.from_keys([KEY_NEW])
    monkeypatch.setattr(service_module.ChannelService, "from_app_config", staticmethod(fake_from_app_config))
    monkeypatch.setattr(service_module, "_channel_service", None)

    anyio.run(lambda: service_module.start_channel_service(credentials_cipher=cipher))

    assert captured["credentials_cipher"] is cipher


# ---------------------------------------------------------------------------
# Repository behaviour under the deployment key
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_credentials_round_trip_under_the_deployment_key(session_factory, tmp_path: Path) -> None:
    from sqlalchemy import select

    from deerflow.persistence.channel_connections import ChannelConnectionRepository, ChannelCredentialRow

    repo = ChannelConnectionRepository(session_factory, cipher=load_credentials_cipher(base_dir=tmp_path))
    connection_id = await _connection(repo)

    await repo.store_credentials(connection_id, access_token="xoxb-connection-token", extra={"bot_user_id": "B1"})

    async with session_factory() as session:
        row = (await session.execute(select(ChannelCredentialRow))).scalar_one()
    assert row.encrypted_access_token.startswith(CIPHERTEXT_PREFIX)
    assert "xoxb-connection-token" not in row.encrypted_access_token

    restarted = ChannelConnectionRepository(session_factory, cipher=load_credentials_cipher(base_dir=tmp_path))
    credentials = await restarted.get_credentials(connection_id)
    assert credentials is not None
    assert credentials["access_token"] == "xoxb-connection-token"
    assert credentials["extra"] == {"bot_user_id": "B1"}


@pytest.mark.anyio
async def test_rotation_keeps_rows_written_under_the_previous_key_readable(session_factory) -> None:
    from deerflow.persistence.channel_connections import ChannelConnectionRepository

    before = ChannelConnectionRepository(session_factory, cipher=CredentialsCipher.from_keys([KEY_OLD]))
    connection_id = await _connection(before)
    await before.store_credentials(connection_id, access_token="written-before-rotation")

    after = ChannelConnectionRepository(session_factory, cipher=CredentialsCipher.from_keys([KEY_NEW, KEY_OLD]))

    assert (await after.get_credentials(connection_id))["access_token"] == "written-before-rotation"


@pytest.mark.anyio
async def test_a_changed_key_treats_stored_credentials_as_missing(session_factory, caplog: pytest.LogCaptureFixture) -> None:
    from deerflow.persistence.channel_connections import ChannelConnectionRepository

    before = ChannelConnectionRepository(session_factory, cipher=CredentialsCipher.from_keys([KEY_OLD]))
    connection_id = await _connection(before)
    await before.store_credentials(connection_id, access_token="unreadable-after-key-loss")

    after = ChannelConnectionRepository(session_factory, cipher=CredentialsCipher.from_keys([KEY_NEW]))
    with caplog.at_level(logging.WARNING, logger="deerflow.persistence.channel_connections.sql"):
        assert await after.get_credentials(connection_id) is None
    assert any("Unable to decrypt channel connection credentials" in record.getMessage() for record in caplog.records)
    assert not any("unreadable-after-key-loss" in record.getMessage() for record in caplog.records)


@pytest.mark.anyio
async def test_slack_falls_back_to_the_deployment_token_without_stored_credentials(session_factory) -> None:
    from app.channels.slack import SlackChannel
    from deerflow.persistence.channel_connections import ChannelConnectionRepository

    repo = ChannelConnectionRepository(session_factory, cipher=CredentialsCipher.from_keys([KEY_NEW]))
    connection_id = await _connection(repo)
    operator_client = MagicMock(name="operator_client")
    factory = MagicMock(name="web_client_factory")
    channel = SlackChannel(bus=MessageBus(), config={"connection_repo": repo, "web_client_factory": factory})
    channel._web_client = operator_client
    message = OutboundMessage(channel_name="slack", chat_id="C1", thread_id="t1", text="hi", connection_id=connection_id)

    assert await channel._get_web_client_for_message(message) is operator_client
    factory.assert_not_called()

    await repo.store_credentials(connection_id, access_token="xoxb-connection-token")
    connection_client = await channel._get_web_client_for_message(message)
    factory.assert_called_once_with(token="xoxb-connection-token")
    assert connection_client is factory.return_value
