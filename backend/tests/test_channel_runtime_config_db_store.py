"""Shared, encrypted IM channel runtime configuration (``channel_runtime_configs``).

``SqlChannelRuntimeConfigStore`` replaces ``{base_dir}/channels/runtime-config.json``
for a sqlite/postgres database: every Gateway instance reads the same rows, the
UI-entered credentials are stored as ``DEER_FLOW_CREDENTIALS_KEY`` ciphertext,
a disconnect is a plaintext tombstone with no secrets, and every save bumps the
provider's ``version`` so a peer notices it. The old JSON file is imported once
and then deleted, because a plaintext copy left on disk is the leak the table
closes.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.channels.runtime_config_store import (
    RUNTIME_CHANNEL_DISABLED_FLAG,
    ChannelRuntimeConfigEncryptionUnavailable,
    ChannelRuntimeConfigStore,
    SqlChannelRuntimeConfigStore,
    resolve_runtime_config_store,
)
from deerflow.config.app_config import AppConfig
from deerflow.config.credentials_key import CredentialsCipher
from deerflow.persistence.base import Base
from deerflow.persistence.channel_runtime_configs import ChannelRuntimeConfigRow, SqlChannelRuntimeConfigRepository
from deerflow.persistence.postgres_schema import dsn_with_search_path

SLACK = {"enabled": True, "bot_token": "xoxb-secret-token", "app_token": "xapp-secret-token"}
TOMBSTONE = {"enabled": False, RUNTIME_CHANNEL_DISABLED_FLAG: True}


@pytest.fixture(params=["sqlite", "postgres"])
def session_factory(request, tmp_path) -> sessionmaker[Session]:
    """The synchronous session factory the Gateway builds from ``app_sync_sqlalchemy_url``, on each dialect."""
    schema = None
    if request.param == "sqlite":
        engine = sa.create_engine(f"sqlite:///{(tmp_path / 'runtime.db').as_posix()}")
    else:
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI (real Postgres channel_runtime_configs)")
        schema = f"channel_runtime_configs_{uuid.uuid4().hex}"
        admin = sa.create_engine(make_url(uri).set(drivername="postgresql+psycopg"))
        with admin.begin() as conn:
            conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        admin.dispose()
        engine = sa.create_engine(make_url(dsn_with_search_path(uri, schema)).set(drivername="postgresql+psycopg"))
    Base.metadata.create_all(engine, tables=[ChannelRuntimeConfigRow.__table__])
    yield sessionmaker(engine, expire_on_commit=False)
    if schema is not None:
        with engine.begin() as conn:
            conn.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
    engine.dispose()


def _cipher(*keys: bytes) -> CredentialsCipher:
    return CredentialsCipher.from_keys(list(keys) or [Fernet.generate_key()])


def _store(session_factory, *, cipher: CredentialsCipher | None = None, legacy_path: Path | None = None) -> SqlChannelRuntimeConfigStore:
    return SqlChannelRuntimeConfigStore(SqlChannelRuntimeConfigRepository(session_factory), cipher=cipher, legacy_path=legacy_path)


def _row(session_factory, provider: str) -> ChannelRuntimeConfigRow | None:
    with session_factory() as session:
        return session.get(ChannelRuntimeConfigRow, provider)


def _write_legacy(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# -- storage ---------------------------------------------------------------


def test_saved_config_round_trips_and_is_encrypted_at_rest(session_factory):
    store = _store(session_factory, cipher=_cipher())

    store.set_provider_config("slack", SLACK)

    assert store.get_provider_config("slack") == SLACK
    assert store.load_all() == {"slack": SLACK}
    row = _row(session_factory, "slack")
    assert row.disconnected is False
    assert row.config_ciphertext.startswith("fernet:v2:")
    assert "xoxb-secret-token" not in row.config_ciphertext


def test_every_save_bumps_the_provider_version(session_factory):
    store = _store(session_factory, cipher=_cipher())
    assert store.versions() == {}

    store.set_provider_config("slack", SLACK)
    store.set_provider_config("telegram", {"enabled": True, "bot_token": "t"})
    store.set_provider_config("slack", {**SLACK, "bot_token": "xoxb-rotated"})
    store.set_provider_disconnected("slack")

    assert store.versions() == {"slack": 3, "telegram": 1}


def test_concurrent_saves_from_two_instances_each_get_their_own_version(session_factory):
    from concurrent.futures import ThreadPoolExecutor

    repo = SqlChannelRuntimeConfigRepository(session_factory)

    def save_many(instance: str) -> list[int]:
        return [repo.save("slack", config_ciphertext=f"{instance}-{n}", disconnected=False, now=float(n)) for n in range(10)]

    with ThreadPoolExecutor(max_workers=2) as pool:
        versions = [version for batch in pool.map(save_many, ["a", "b"]) for version in batch]

    # The upsert serializes on the row: no save is lost and no version is handed out twice.
    assert sorted(versions) == list(range(1, 21))
    assert repo.versions() == {"slack": 20}


def test_disconnect_is_a_plaintext_tombstone_without_secrets(session_factory):
    cipher = _cipher()
    _store(session_factory, cipher=cipher).set_provider_config("feishu", {"enabled": True, "app_id": "a", "app_secret": "s"})

    _store(session_factory, cipher=cipher).set_provider_disconnected("feishu")

    row = _row(session_factory, "feishu")
    assert (row.disconnected, row.config_ciphertext) == (True, None)
    # The tombstone needs no key: it still suppresses a config.yaml block when the key is unavailable.
    assert _store(session_factory, cipher=None).load_all() == {"feishu": TOMBSTONE}


def test_a_peer_store_reads_a_save_without_restarting(session_factory):
    cipher = _cipher()
    replica_a, replica_b = _store(session_factory, cipher=cipher), _store(session_factory, cipher=cipher)
    assert replica_b.load_all() == {}

    replica_a.set_provider_config("slack", SLACK)

    assert replica_b.get_provider_config("slack") == SLACK
    replica_b.set_provider_disconnected("slack")
    assert replica_a.load_all() == {"slack": TOMBSTONE}


def test_a_row_the_configured_key_cannot_decrypt_reads_as_not_configured(session_factory, caplog):
    _store(session_factory, cipher=_cipher()).set_provider_config("slack", SLACK)
    _store(session_factory, cipher=_cipher()).set_provider_disconnected("discord")

    with caplog.at_level(logging.ERROR, logger="app.channels.runtime_config_store"):
        configs = _store(session_factory, cipher=_cipher()).load_all()

    assert configs == {"discord": TOMBSTONE}
    assert "slack" in caplog.text and "DEER_FLOW_CREDENTIALS_KEY" in caplog.text
    assert "xoxb" not in caplog.text


def test_a_rotated_key_list_still_reads_rows_written_with_the_old_key(session_factory):
    old, new = Fernet.generate_key(), Fernet.generate_key()
    _store(session_factory, cipher=_cipher(old)).set_provider_config("slack", SLACK)

    assert _store(session_factory, cipher=_cipher(new, old)).load_all() == {"slack": SLACK}


def test_without_a_cipher_credentials_are_refused_not_stored_in_plaintext(session_factory):
    store = _store(session_factory, cipher=None)
    assert store.can_store_credentials is False

    with pytest.raises(ChannelRuntimeConfigEncryptionUnavailable):
        store.set_provider_config("slack", SLACK)

    assert _row(session_factory, "slack") is None
    assert _store(session_factory, cipher=_cipher()).can_store_credentials is True


# -- one-time import of runtime-config.json --------------------------------


def test_import_moves_the_plaintext_file_into_the_table_and_deletes_it(session_factory, tmp_path):
    legacy = tmp_path / "channels" / "runtime-config.json"
    _write_legacy(legacy, {"slack": SLACK, "feishu": TOMBSTONE})
    store = _store(session_factory, cipher=_cipher(), legacy_path=legacy)

    assert store.import_legacy_json() == 2

    assert not legacy.exists()
    assert store.load_all() == {"slack": SLACK, "feishu": TOMBSTONE}
    assert "xoxb-secret-token" not in _row(session_factory, "slack").config_ciphertext
    assert _row(session_factory, "feishu").disconnected is True


def test_import_keeps_rows_already_in_the_table(session_factory, tmp_path):
    cipher = _cipher()
    _store(session_factory, cipher=cipher).set_provider_config("slack", SLACK)
    legacy = tmp_path / "runtime-config.json"
    _write_legacy(legacy, {"slack": {"enabled": True, "bot_token": "stale", "app_token": "stale"}, "telegram": {"enabled": True, "bot_token": "t"}})
    store = _store(session_factory, cipher=cipher, legacy_path=legacy)

    assert store.import_legacy_json() == 1

    # The table is newer than the file for every provider it already has; the rest is imported.
    assert store.load_all() == {"slack": SLACK, "telegram": {"enabled": True, "bot_token": "t"}}
    assert store.versions() == {"slack": 1, "telegram": 1}
    assert not legacy.exists()


def test_replicas_importing_the_same_file_neither_duplicate_nor_fail(session_factory, tmp_path):
    cipher = _cipher()
    legacy = tmp_path / "runtime-config.json"
    _write_legacy(legacy, {"slack": SLACK})

    assert _store(session_factory, cipher=cipher, legacy_path=legacy).import_legacy_json() == 1
    # The peer finds the file gone (and would find the row present).
    assert _store(session_factory, cipher=cipher, legacy_path=legacy).import_legacy_json() == 0
    _write_legacy(legacy, {"slack": SLACK})
    assert _store(session_factory, cipher=cipher, legacy_path=legacy).import_legacy_json() == 0

    assert _store(session_factory, cipher=cipher).versions() == {"slack": 1}


def test_a_corrupt_legacy_file_is_kept(session_factory, tmp_path):
    legacy = tmp_path / "runtime-config.json"
    legacy.write_text("{not json", encoding="utf-8")

    assert _store(session_factory, cipher=_cipher(), legacy_path=legacy).import_legacy_json() == 0

    assert legacy.read_text(encoding="utf-8") == "{not json"


def test_without_a_cipher_the_import_keeps_the_file(session_factory, tmp_path):
    legacy = tmp_path / "runtime-config.json"
    _write_legacy(legacy, {"slack": SLACK})

    assert _store(session_factory, cipher=None, legacy_path=legacy).import_legacy_json() == 0

    assert legacy.exists()
    assert _row(session_factory, "slack") is None


def test_import_skips_malformed_entries(session_factory, tmp_path):
    legacy = tmp_path / "runtime-config.json"
    _write_legacy(legacy, {"slack": SLACK, "discord": "not an object", "x" * 65: {"enabled": True}})
    store = _store(session_factory, cipher=_cipher(), legacy_path=legacy)

    assert store.import_legacy_json() == 1

    assert store.load_all() == {"slack": SLACK}


def test_no_legacy_file_is_a_no_op(session_factory, tmp_path):
    assert _store(session_factory, cipher=_cipher(), legacy_path=tmp_path / "missing.json").import_legacy_json() == 0
    assert _store(session_factory, cipher=_cipher()).import_legacy_json() == 0


# -- selection -------------------------------------------------------------


def _app_config(tmp_path, backend: str) -> AppConfig:
    database = {"backend": backend, "sqlite_dir": str(tmp_path)} if backend != "memory" else {"backend": "memory"}
    return AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "database": database})


def test_a_memory_database_keeps_the_json_file(tmp_path):
    store = resolve_runtime_config_store(_app_config(tmp_path, "memory"), cipher=_cipher(), path=tmp_path / "runtime-config.json")

    assert isinstance(store, ChannelRuntimeConfigStore)


def test_a_sql_database_uses_the_shared_table(tmp_path, monkeypatch):
    import deerflow.persistence.engine as engine_module

    monkeypatch.setattr(engine_module, "get_session_factory", lambda: object())
    legacy = tmp_path / "runtime-config.json"

    store = resolve_runtime_config_store(_app_config(tmp_path, "sqlite"), cipher=_cipher(), path=legacy)

    assert isinstance(store, SqlChannelRuntimeConfigStore)
    assert store.legacy_path == legacy


def test_a_sql_database_without_an_initialised_engine_falls_back_to_the_file(tmp_path, monkeypatch, caplog):
    import deerflow.persistence.engine as engine_module

    monkeypatch.setattr(engine_module, "get_session_factory", lambda: None)

    with caplog.at_level(logging.WARNING, logger="app.channels.runtime_config_store"):
        store = resolve_runtime_config_store(_app_config(tmp_path, "sqlite"), cipher=_cipher(), path=tmp_path / "runtime-config.json")

    assert isinstance(store, ChannelRuntimeConfigStore)
    assert "runtime-config.json" in caplog.text
