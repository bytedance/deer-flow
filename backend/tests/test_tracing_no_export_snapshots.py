"""An explicit no-export decision survives recovery without loading a credentials key."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, delete, event, select, update
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def snapshot_store(tmp_path, monkeypatch):
    import deerflow.persistence.models  # noqa: F401 -- register the complete SQL schema
    from deerflow.config.credentials_key import CredentialsCipher
    from deerflow.config.tracing_config import reset_tracing_config
    from deerflow.persistence.base import Base
    from deerflow.persistence.tracing_profiles.sql import SqlTracingProfileRepository

    for name in ("MONOCLE_TRACING", "LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING", "LANGFUSE_TRACING", "DEER_FLOW_CREDENTIALS_KEY"):
        monkeypatch.delenv(name, raising=False)
    reset_tracing_config()
    engine = create_engine(f"sqlite:///{tmp_path / 'snapshots.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    yield SqlTracingProfileRepository(sessions), sessions, CredentialsCipher.from_keys([Fernet.generate_key()])
    engine.dispose()
    reset_tracing_config()


def _service(repository, cipher=None, **kwargs):
    from deerflow.tracing.profiles import TracingProfileService

    return TracingProfileService(repository, cipher, identity_resolver=lambda *_args: "builtin:lead_agent", **kwargs)


class _ForbiddenCipher:
    def encrypt_text(self, _value):
        pytest.fail("a no-export snapshot must not encrypt or load a key")

    def decrypt_text(self, _value):
        pytest.fail("a no-export snapshot must not decrypt or load a key")


@pytest.mark.parametrize("mode", ["inherit", "disabled"])
def test_no_export_snapshot_persists_and_recovers_without_encryption(snapshot_store, mode):
    from deerflow.persistence.tracing_profiles.model import RunTracingSnapshotRow
    from deerflow.runtime.tracing_snapshot import snapshot_references

    repository, sessions, _ = snapshot_store
    service = _service(repository, _ForbiddenCipher())
    if mode == "disabled":
        service.set_binding(None, "alice", mode="disabled", profile_id=None, expected_revision=0)
    snapshot = service.resolve_snapshot(None, "alice")
    assert snapshot.providers == () and snapshot.monocle_enabled is False
    with sessions() as session:
        payload = session.scalar(select(RunTracingSnapshotRow.payload_ciphertext).where(RunTracingSnapshotRow.snapshot_id == snapshot.snapshot_id))
    assert payload.startswith("no-export:v1:")
    assert json.loads(payload.removeprefix("no-export:v1:"))["providers"] == []
    assert snapshot_references(snapshot) == {"deerflow_tracing_snapshot_id": snapshot.snapshot_id, "deerflow_tracing_agent_name": "lead_agent"}
    assert _service(repository, _ForbiddenCipher()).resolve_snapshot(None, "alice", snapshot_id=snapshot.snapshot_id) == snapshot


def test_cipher_factory_is_lazy_and_reused_for_actual_secret_operations(snapshot_store):
    from deerflow.tracing.profiles import ProviderConfig

    repository, _, cipher = snapshot_store
    loads = []

    def load():
        loads.append(True)
        return cipher

    service = _service(repository, cipher_factory=load)
    assert service.list_profiles("alice", is_admin=True) == []
    assert service.get_binding(None, "alice")["mode"] == "inherit"
    empty = service.resolve_snapshot(None, "alice")
    assert service.resolve_snapshot(None, "alice", snapshot_id=empty.snapshot_id) == empty
    assert loads == []
    service.save_profile(profile_id="private", name="Private", providers=(ProviderConfig(provider="langsmith", endpoint="https://collector.example", api_key="offline-test-key"),), allowed_user_ids=["alice"], expected_revision=0)
    service.set_binding(None, "alice", mode="configured", profile_id="private", expected_revision=0)
    exporting = service.resolve_snapshot(None, "alice")
    assert service.resolve_snapshot(None, "alice", snapshot_id=exporting.snapshot_id) == exporting
    assert loads == [True]


def test_lazy_cipher_failure_is_sanitized_and_never_falls_back(snapshot_store, monkeypatch):
    from deerflow.config.tracing_config import reset_tracing_config
    from deerflow.tracing.profiles import TracingUnavailableError

    repository, sessions, _ = snapshot_store

    def unavailable():
        raise OSError("private-key-material and private-file-path")

    service = _service(repository, cipher_factory=unavailable)
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "offline-test-key")
    reset_tracing_config()
    with pytest.raises(TracingUnavailableError) as error:
        service.resolve_snapshot(None, "alice")
    assert "private-key-material" not in str(error.value) and "private-file-path" not in str(error.value)
    from deerflow.persistence.tracing_profiles.model import RunTracingSnapshotRow

    with sessions() as session:
        assert session.scalars(select(RunTracingSnapshotRow)).all() == []


@pytest.mark.parametrize(
    "replacement",
    [
        "no-export:v2:{}",
        "no-export:v1:{",
        "no-export:v1:null",
        {"providers": [{"provider": "langsmith", "endpoint": "https://collector.example", "api_key": "offline-test-key"}]},
        {"mode": "configured"},
        {"monocle_enabled": True},
        {"monocle_enabled": "false"},
        {"monocle_fingerprint": "unexpected-fingerprint"},
        {"api_key": "unexpected-secret-field"},
        {"owner_user_id": "someone-else"},
        {"snapshot_id": "another-snapshot"},
    ],
)
def test_plaintext_marker_cannot_restore_exporters_or_malformed_identity(snapshot_store, replacement):
    from deerflow.persistence.tracing_profiles.model import RunTracingSnapshotRow
    from deerflow.tracing.profiles import TracingUnavailableError

    repository, sessions, cipher = snapshot_store
    service = _service(repository, cipher)
    snapshot = service.resolve_snapshot(None, "alice")
    payload = replacement if isinstance(replacement, str) else "no-export:v1:" + json.dumps({**snapshot.model_dump(), **replacement})
    with sessions.begin() as session:
        session.execute(update(RunTracingSnapshotRow).where(RunTracingSnapshotRow.snapshot_id == snapshot.snapshot_id).values(payload_ciphertext=payload))
    with pytest.raises(TracingUnavailableError):
        _service(repository, _ForbiddenCipher()).resolve_snapshot(None, "alice", snapshot_id=snapshot.snapshot_id)


@pytest.mark.parametrize("ciphertext_format", ["v2", "v1", "bare"])
def test_historical_encrypted_empty_snapshot_requires_its_original_key(snapshot_store, ciphertext_format):
    from deerflow.config.credentials_key import CredentialsCipher
    from deerflow.persistence.tracing_profiles.model import RunTracingSnapshotRow
    from deerflow.tracing.profiles import TracingUnavailableError

    repository, sessions, cipher = snapshot_store
    service = _service(repository, cipher)
    snapshot = service.resolve_snapshot(None, "alice")
    encrypted = cipher.encrypt_text(snapshot.model_dump_json())
    if ciphertext_format == "v1":
        encrypted = encrypted.replace("fernet:v2:", "fernet:v1:", 1)
    elif ciphertext_format == "bare":
        encrypted = encrypted.removeprefix("fernet:v2:")
    with sessions.begin() as session:
        session.execute(update(RunTracingSnapshotRow).where(RunTracingSnapshotRow.snapshot_id == snapshot.snapshot_id).values(payload_ciphertext=encrypted))
    assert service.resolve_snapshot(None, "alice", snapshot_id=snapshot.snapshot_id) == snapshot
    broken = _service(repository, CredentialsCipher.from_keys([Fernet.generate_key()]))
    with pytest.raises(TracingUnavailableError):
        broken.resolve_snapshot(None, "alice", snapshot_id=snapshot.snapshot_id)


@pytest.mark.parametrize("legacy_type", ["memory", "sqlite"])
def test_external_checkpointer_capture_never_becomes_gc_managed_after_config_change(snapshot_store, tmp_path, monkeypatch, legacy_type):
    from deerflow.config import credentials_key
    from deerflow.config.app_config import AppConfig
    from deerflow.persistence.tracing_profiles.model import RunTracingSnapshotRow
    from deerflow.tracing.profiles import resolve_run_snapshot

    _, sessions, _ = snapshot_store
    config = AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "database": {"backend": "sqlite", "sqlite_dir": str(tmp_path)},
            "checkpointer": {"type": legacy_type, "connection_string": str(tmp_path / "separate-checkpoints.db")},
        }
    )
    monkeypatch.setattr("deerflow.persistence.agents.sql.get_sync_sessionmaker", lambda _url: sessions)
    monkeypatch.setattr(credentials_key, "get_tracing_credentials_cipher", lambda _config: pytest.fail("no-export capture must not load the credentials key"))
    original = resolve_run_snapshot(None, "alice", managed_admission=True, app_config=config)
    config.checkpointer = None
    assert resolve_run_snapshot(None, "alice", snapshot_id=original.snapshot_id, managed_admission=True, app_config=config) == original
    fresh = resolve_run_snapshot(None, "alice", managed_admission=True, app_config=config)
    with sessions() as session:
        assert session.get(RunTracingSnapshotRow, original.snapshot_id).retention_state == "unmanaged"
        assert session.get(RunTracingSnapshotRow, fresh.snapshot_id).retention_state == "pending"


def _protection_config(tmp_path, sessions, monkeypatch):
    from deerflow.config import credentials_key
    from deerflow.config.app_config import AppConfig

    config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "database": {"backend": "sqlite", "sqlite_dir": str(tmp_path)}})
    monkeypatch.setattr("deerflow.persistence.agents.sql.get_sync_sessionmaker", lambda _url: sessions)
    monkeypatch.setattr(credentials_key, "get_tracing_credentials_cipher", lambda _config: pytest.fail("retention protection must not load the credentials key"))
    return config


@pytest.mark.parametrize("state", ["pending", "published", "unmanaged"])
@pytest.mark.parametrize("encrypted", [False, True], ids=["plaintext", "historical-ciphertext"])
def test_external_recovery_permanently_protects_existing_snapshot_without_a_key(snapshot_store, tmp_path, monkeypatch, state, encrypted):
    from deerflow.persistence.tracing_profiles.model import RunTracingSnapshotRow
    from deerflow.tracing.profiles import protect_run_snapshot

    repository, sessions, cipher = snapshot_store
    service = _service(repository, _ForbiddenCipher())
    snapshot = service.resolve_snapshot(None, "alice", managed_admission=True)
    with sessions.begin() as session:
        session.execute(update(RunTracingSnapshotRow).where(RunTracingSnapshotRow.snapshot_id == snapshot.snapshot_id).values(retention_state=state))
        if encrypted:
            session.execute(update(RunTracingSnapshotRow).where(RunTracingSnapshotRow.snapshot_id == snapshot.snapshot_id).values(payload_ciphertext=cipher.encrypt_text(snapshot.model_dump_json())))
        before = session.get(RunTracingSnapshotRow, snapshot.snapshot_id).payload_ciphertext
    config = _protection_config(tmp_path, sessions, monkeypatch)
    assert protect_run_snapshot(snapshot.snapshot_id, "alice", app_config=config) is True
    assert _service(repository, cipher if encrypted else _ForbiddenCipher()).resolve_snapshot(None, "alice", snapshot_id=snapshot.snapshot_id, managed_admission=True) == snapshot
    assert repository.release_snapshot(snapshot.snapshot_id, "alice") is False
    with sessions() as session:
        row = session.get(RunTracingSnapshotRow, snapshot.snapshot_id)
        assert row.retention_state == "unmanaged" and row.payload_ciphertext == before


def test_snapshot_protection_cannot_cross_owner_or_resurrect_missing_or_released_rows(snapshot_store, tmp_path, monkeypatch):
    from deerflow.persistence.tracing_profiles.model import RunTracingSnapshotRow
    from deerflow.tracing.profiles import TracingAuthorizationError, TracingUnavailableError, protect_run_snapshot

    repository, sessions, _ = snapshot_store
    snapshot = _service(repository, _ForbiddenCipher()).resolve_snapshot(None, "alice", managed_admission=True)
    config = _protection_config(tmp_path, sessions, monkeypatch)
    with pytest.raises(TracingAuthorizationError):
        protect_run_snapshot(snapshot.snapshot_id, "bob", app_config=config)
    with sessions() as session:
        assert session.get(RunTracingSnapshotRow, snapshot.snapshot_id).retention_state == "pending"
    assert repository.release_snapshot(snapshot.snapshot_id, "alice") is True
    with pytest.raises(TracingUnavailableError):
        protect_run_snapshot(snapshot.snapshot_id, "alice", app_config=config)
    with pytest.raises(TracingUnavailableError):
        protect_run_snapshot("f" * 32, "alice", app_config=config)
    with sessions() as session:
        assert [(row.snapshot_id, row.retention_state) for row in session.scalars(select(RunTracingSnapshotRow))] == [(snapshot.snapshot_id, "released")]


def test_snapshot_removed_by_a_winning_gc_cannot_be_recreated_by_recovery_protection(snapshot_store, tmp_path, monkeypatch):
    from deerflow.persistence.tracing_profiles.model import RunTracingSnapshotRow
    from deerflow.persistence.tracing_profiles.sql import _lock_admission_fence
    from deerflow.tracing.profiles import TracingUnavailableError, protect_run_snapshot

    repository, sessions, _ = snapshot_store
    snapshot = _service(repository, _ForbiddenCipher()).resolve_snapshot(None, "alice", managed_admission=True)
    config = _protection_config(tmp_path, sessions, monkeypatch)
    removed, finish_gc, protect_attempted = threading.Event(), threading.Event(), threading.Event()

    def collect():
        with sessions.begin() as session:
            _lock_admission_fence(session)
            session.execute(delete(RunTracingSnapshotRow).where(RunTracingSnapshotRow.snapshot_id == snapshot.snapshot_id))
            removed.set()
            assert finish_gc.wait(10)

    def observe(_conn, _cursor, statement, *_args):
        if statement.startswith("UPDATE tracing_admission_fence"):
            protect_attempted.set()

    engine = sessions.kw["bind"]
    with ThreadPoolExecutor(2) as workers:
        collecting = workers.submit(collect)
        try:
            assert removed.wait(10)
            event.listen(engine, "before_cursor_execute", observe)
            protecting = workers.submit(protect_run_snapshot, snapshot.snapshot_id, "alice", app_config=config)
            assert protect_attempted.wait(10)
            assert not protecting.done()
            finish_gc.set()
            collecting.result(timeout=10)
            with pytest.raises(TracingUnavailableError):
                protecting.result(timeout=10)
        finally:
            finish_gc.set()
            event.remove(engine, "before_cursor_execute", observe)
    with sessions() as session:
        assert session.get(RunTracingSnapshotRow, snapshot.snapshot_id) is None


def test_external_saver_startup_protects_all_existing_managed_history_without_rewriting_payloads(snapshot_store, tmp_path, monkeypatch):
    from deerflow.config.checkpointer_config import CheckpointerConfig
    from deerflow.persistence.tracing_profiles.model import RunTracingSnapshotRow
    from deerflow.tracing.profiles import protect_tracing_history

    repository, sessions, _ = snapshot_store
    service = _service(repository, _ForbiddenCipher())
    snapshots = {}
    for state, owner in (("pending", "alice"), ("published", "alice"), ("unmanaged", "alice"), ("released", "alice"), ("published", "bob")):
        snapshot = service.resolve_snapshot(None, owner)
        with sessions.begin() as session:
            session.execute(update(RunTracingSnapshotRow).where(RunTracingSnapshotRow.snapshot_id == snapshot.snapshot_id).values(retention_state=state))
        snapshots[snapshot.snapshot_id] = state
    config = _protection_config(tmp_path, sessions, monkeypatch)
    config.checkpointer = CheckpointerConfig(type="memory")
    with sessions() as session:
        payloads = dict(session.execute(select(RunTracingSnapshotRow.snapshot_id, RunTracingSnapshotRow.payload_ciphertext)).all())
    assert protect_tracing_history(config) == 3
    assert protect_tracing_history(config) == 0
    config.checkpointer = None
    with sessions() as session:
        for row in session.scalars(select(RunTracingSnapshotRow)):
            assert row.retention_state == ("released" if snapshots[row.snapshot_id] == "released" else "unmanaged")
            assert row.payload_ciphertext == payloads[row.snapshot_id]


def test_memory_retention_protection_has_no_database_or_key_side_effects(monkeypatch):
    from deerflow.config.app_config import AppConfig
    from deerflow.tracing import profiles

    config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}})
    monkeypatch.setattr(profiles, "get_profile_service", lambda **_kwargs: pytest.fail("memory protection must not initialize SQL or encryption"))
    assert profiles.protect_run_snapshot("f" * 32, "alice", app_config=config) is False
    assert profiles.protect_tracing_history(config) == 0
