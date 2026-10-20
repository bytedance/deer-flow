"""Authoritative tracing configuration, optimistic writes and immutable run snapshots."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def control(tmp_path, monkeypatch):
    from deerflow.config.credentials_key import CredentialsCipher
    from deerflow.config.tracing_config import reset_tracing_config
    from deerflow.persistence.base import Base
    from deerflow.persistence.tracing_profiles.sql import SqlTracingProfileRepository
    from deerflow.tracing.profiles import TracingProfileService

    for name in ("MONOCLE_TRACING", "LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGFUSE_TRACING"):
        monkeypatch.delenv(name, raising=False)
    reset_tracing_config()
    engine = create_engine(f"sqlite:///{tmp_path / 'tracing.db'}", connect_args={"check_same_thread": False, "timeout": 30})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    key = Fernet.generate_key()
    monkeypatch.setenv("DEER_FLOW_CREDENTIALS_KEY", key.decode())
    cipher = CredentialsCipher.from_keys([key])
    service = TracingProfileService(SqlTracingProfileRepository(factory), cipher, identity_resolver=lambda name, owner: f"test:{owner}:{name}")
    yield service, factory, cipher, tmp_path
    engine.dispose()
    reset_tracing_config()


def _provider(**values):
    from deerflow.tracing.profiles import ProviderConfig

    return ProviderConfig(provider="arize", endpoint="https://otlp.arize.com", project="project-a", space_id="space-a", api_key="private-test-key", **values)


def _save(service, **values):
    return service.save_profile(profile_id="profile-a", name="Operations", providers=(_provider(),), allowed_user_ids=["alice"], expected_revision=0, **values)


def test_committed_profile_is_visible_to_a_fresh_replica_and_preserves_omitted_secret(control):
    from deerflow.persistence.tracing_profiles.sql import SqlTracingProfileRepository
    from deerflow.tracing.profiles import TracingProfileService

    service, factory, cipher, _ = control
    peer = TracingProfileService(SqlTracingProfileRepository(factory), cipher, identity_resolver=service.identity_resolver)
    assert peer.list_profiles("alice", is_admin=False) == []
    first = _save(service)
    public = peer.list_profiles("alice", is_admin=False)[0]
    assert public["providers"][0]["has_api_key"] is True
    assert "private-test-key" not in str(public)
    provider = _provider().model_copy(update={"api_key": None})
    peer.save_profile(profile_id="profile-a", name="Changed", providers=(provider,), allowed_user_ids=["alice"], expected_revision=first["revision"])
    service.set_binding("worker", "alice", mode="configured", profile_id="profile-a", expected_revision=0)
    snapshot = service.resolve_snapshot("worker", "alice")
    assert snapshot.providers[0].api_key.get_secret_value() == "private-test-key"
    assert "private-test-key" not in repr(snapshot)


def test_concurrent_profile_cas_allows_one_winner_and_keeps_version_history(control):
    from deerflow.tracing.profiles import TracingConflictError

    service, factory, _, _ = control
    _save(service)
    barrier = Barrier(2)

    def save(name):
        barrier.wait()
        try:
            service.save_profile(profile_id="profile-a", name=name, providers=(_provider(),), allowed_user_ids=["alice"], expected_revision=1)
            return "saved"
        except TracingConflictError:
            return "conflict"

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(save, ("first", "second"))) == ["conflict", "saved"]
    with factory() as session:
        assert session.scalar(text("select count(*) from tracing_profile_versions")) == 2


def test_binding_cas_and_owner_isolation(control):
    from deerflow.tracing.profiles import TracingAuthorizationError, TracingConflictError

    service, _, _, _ = control
    _save(service)
    service.set_binding("worker", "alice", mode="configured", profile_id="profile-a", expected_revision=0)
    with pytest.raises(TracingConflictError):
        service.set_binding("worker", "alice", mode="disabled", profile_id=None, expected_revision=0)
    with pytest.raises(TracingAuthorizationError):
        service.set_binding("worker", "bob", mode="configured", profile_id="profile-a", expected_revision=0)
    assert service.get_binding("worker", "bob")["mode"] == "inherit"
    assert service.list_profiles("bob", is_admin=False) == []


def test_snapshots_freeze_edits_credentials_and_authorization_but_new_runs_refresh(control):
    from deerflow.tracing.profiles import TracingAuthorizationError

    service, factory, cipher, _ = control
    _save(service)
    service.set_binding("worker", "alice", mode="configured", profile_id="profile-a", expected_revision=0)
    old = service.resolve_snapshot("worker", "alice")
    service.save_profile(profile_id="profile-a", name="Changed", providers=(_provider().model_copy(update={"project": "project-b"}),), allowed_user_ids=["alice"], expected_revision=1)
    new = service.resolve_snapshot("worker", "alice")
    assert old.providers[0].project == "project-a"
    assert new.providers[0].project == "project-b"
    assert old.revision != new.revision
    service.save_profile(profile_id="profile-a", name="Revoked", providers=(_provider(),), allowed_user_ids=[], expected_revision=2)
    with pytest.raises(TracingAuthorizationError):
        service.resolve_snapshot("worker", "alice")
    from deerflow.persistence.tracing_profiles.sql import SqlTracingProfileRepository
    from deerflow.tracing.profiles import TracingProfileService

    restarted = TracingProfileService(SqlTracingProfileRepository(factory), cipher, identity_resolver=service.identity_resolver)
    assert restarted.resolve_snapshot("worker", "alice", snapshot_id=old.snapshot_id) == old
    with pytest.raises(TracingAuthorizationError):
        restarted.resolve_snapshot("worker", "bob", snapshot_id=old.snapshot_id)
    with pytest.raises(TracingAuthorizationError):
        restarted.resolve_snapshot("other-agent", "alice", snapshot_id=old.snapshot_id)


def test_inherited_snapshot_freezes_environment_and_disabled_snapshot_has_no_destinations(control, monkeypatch):
    from deerflow.config.tracing_config import reset_tracing_config

    service, _, _, _ = control
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "global-secret")
    monkeypatch.setenv("LANGSMITH_PROJECT", "initial")
    reset_tracing_config()
    old = service.resolve_snapshot(None, "alice")
    monkeypatch.setenv("LANGSMITH_PROJECT", "changed")
    reset_tracing_config()
    assert service.resolve_snapshot(None, "alice").providers[0].project == "changed"
    assert service.resolve_snapshot(None, "alice", snapshot_id=old.snapshot_id).providers[0].project == "initial"
    service.set_binding("worker", "alice", mode="disabled", profile_id=None, expected_revision=0)
    disabled = service.resolve_snapshot("worker", "alice")
    assert disabled.mode == "disabled" and disabled.providers == ()


def test_langsmith_workspace_is_frozen_and_private_profiles_suppress_ambient_workspace(control, monkeypatch):
    from deerflow.config.tracing_config import reset_tracing_config
    from deerflow.tracing.profiles import ProviderConfig

    service, _, _, _ = control
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "global-key")
    monkeypatch.setenv("LANGSMITH_WORKSPACE_ID", "workspace-a")
    reset_tracing_config()
    snapshot = service.resolve_snapshot(None, "alice")
    monkeypatch.setenv("LANGSMITH_WORKSPACE_ID", "workspace-b")
    assert service.resolve_snapshot(None, "alice").providers[0].workspace_id == "workspace-b"
    assert service.resolve_snapshot(None, "alice", snapshot_id=snapshot.snapshot_id).providers[0].workspace_id == "workspace-a"
    private = ProviderConfig(provider="langsmith", endpoint="https://api.smith.langchain.com", api_key="private-key")
    service.save_profile(profile_id="private", name="Private", providers=(private,), allowed_user_ids=["alice"], expected_revision=0)
    service.set_binding("worker", "alice", mode="configured", profile_id="private", expected_revision=0)
    assert service.resolve_snapshot("worker", "alice").providers[0].workspace_id == ""


def test_profile_and_snapshot_store_no_plaintext_and_bad_key_never_falls_back(control):
    from deerflow.config.credentials_key import CredentialsCipher
    from deerflow.persistence.tracing_profiles.sql import SqlTracingProfileRepository
    from deerflow.tracing.profiles import TracingProfileService, TracingUnavailableError

    service, factory, _, path = control
    _save(service)
    service.set_binding("worker", "alice", mode="configured", profile_id="profile-a", expected_revision=0)
    snapshot = service.resolve_snapshot("worker", "alice")
    assert b"private-test-key" not in (path / "tracing.db").read_bytes()
    broken = TracingProfileService(SqlTracingProfileRepository(factory), CredentialsCipher.from_keys([Fernet.generate_key()]), identity_resolver=service.identity_resolver)
    with pytest.raises(TracingUnavailableError):
        broken.resolve_snapshot("worker", "alice")
    with pytest.raises(TracingUnavailableError):
        broken.resolve_snapshot("worker", "alice", snapshot_id=snapshot.snapshot_id)


def test_endpoint_change_cannot_reuse_old_credentials(control):
    from deerflow.tracing.profiles import TracingInputError

    service, _, _, _ = control
    _save(service)
    with pytest.raises(TracingInputError):
        service.save_profile(profile_id="profile-a", name="Changed", providers=(_provider().model_copy(update={"endpoint": "https://other.example", "api_key": None}),), allowed_user_ids=["alice"], expected_revision=1)


def test_langfuse_public_key_change_requires_a_new_matching_secret(control):
    from deerflow.tracing.profiles import ProviderConfig, TracingInputError

    service, _, _, _ = control
    original = ProviderConfig(provider="langfuse", endpoint="https://cloud.langfuse.com", public_key="project-key-a", secret_key="secret-a")
    service.save_profile(profile_id="langfuse", name="Langfuse", providers=(original,), allowed_user_ids=["alice"], expected_revision=0)
    with pytest.raises(TracingInputError):
        service.save_profile(profile_id="langfuse", name="Langfuse", providers=(original.model_copy(update={"public_key": "project-key-b", "secret_key": None}),), allowed_user_ids=["alice"], expected_revision=1)


def test_synthetic_authenticated_admin_can_run_an_admin_only_profile(control):
    from types import SimpleNamespace

    from deerflow.runtime.user_context import reset_current_user, set_current_user

    service, _, _, _ = control
    service.save_profile(profile_id="admin-only", name="Admin only", providers=(_provider(),), allowed_user_ids=[], expected_revision=0)
    service.set_binding("worker", "synthetic-admin", mode="configured", profile_id="admin-only", expected_revision=0, is_admin=True)
    token = set_current_user(SimpleNamespace(id="synthetic-admin", system_role="admin"))
    try:
        assert service.resolve_snapshot("worker", "synthetic-admin").mode == "configured"
    finally:
        reset_current_user(token)


def test_malformed_inherited_destination_fails_without_echoing_secret(control, monkeypatch):
    from deerflow.config.tracing_config import reset_tracing_config
    from deerflow.tracing.profiles import TracingUnavailableError

    service, _, _, _ = control
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "never-echo-secret")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://provider.example/?key=never-echo-secret")
    reset_tracing_config()
    with pytest.raises(TracingUnavailableError) as error:
        service.resolve_snapshot("worker", "alice")
    assert "never-echo-secret" not in str(error.value)


def test_monocle_operator_lock_rejects_overrides(control, monkeypatch):
    from deerflow.config.tracing_config import reset_tracing_config
    from deerflow.tracing.profiles import TracingOperatorLockError

    service, _, _, _ = control
    monkeypatch.setattr("deerflow.tracing.scoped.is_global_tracing_guard_installed", lambda: False, raising=False)
    monkeypatch.setenv("MONOCLE_TRACING", "true")
    reset_tracing_config()
    with pytest.raises(TracingOperatorLockError):
        service.set_binding("worker", "alice", mode="disabled", profile_id=None, expected_revision=0)
    assert service.resolve_snapshot("worker", "alice").monocle_enabled is True


def test_monocle_guard_allows_safe_agent_overrides(control, monkeypatch):
    from deerflow.config.tracing_config import reset_tracing_config

    service, _, _, _ = control
    monkeypatch.setenv("MONOCLE_TRACING", "true")
    monkeypatch.setattr("deerflow.tracing.scoped.is_global_tracing_guard_installed", lambda: True, raising=False)
    reset_tracing_config()
    result = service.set_binding("worker", "alice", mode="disabled", profile_id=None, expected_revision=0)
    assert result["status"] == "active" and result["can_select"]
    assert service.resolve_snapshot("worker", "alice").monocle_enabled is False


def test_old_monocle_snapshot_cannot_redirect_after_exporter_environment_changes(control, monkeypatch):
    from deerflow.config.tracing_config import reset_tracing_config
    from deerflow.tracing.profiles import TracingUnavailableError

    service, _, _, _ = control
    monkeypatch.setenv("MONOCLE_TRACING", "true")
    monkeypatch.setenv("MONOCLE_EXPORTERS", "file")
    reset_tracing_config()
    snapshot = service.resolve_snapshot("worker", "alice")
    assert service.resolve_snapshot("worker", "alice", snapshot_id=snapshot.snapshot_id) == snapshot
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://different-export-destination.example")
    with pytest.raises(TracingUnavailableError):
        service.resolve_snapshot("worker", "alice", snapshot_id=snapshot.snapshot_id)


def test_old_disabled_snapshot_requires_a_working_guard_on_the_restoring_replica(control, monkeypatch):
    from deerflow.config.tracing_config import reset_tracing_config
    from deerflow.tracing.profiles import TracingOperatorLockError

    service, _, _, _ = control
    service.set_binding("worker", "alice", mode="disabled", profile_id=None, expected_revision=0)
    snapshot = service.resolve_snapshot("worker", "alice")
    monkeypatch.setenv("MONOCLE_TRACING", "true")
    monkeypatch.setattr("deerflow.tracing.scoped.is_global_tracing_guard_installed", lambda: False)
    reset_tracing_config()
    with pytest.raises(TracingOperatorLockError):
        service.resolve_snapshot("worker", "alice", snapshot_id=snapshot.snapshot_id)


def test_independent_process_reads_committed_authority_and_recovers_encrypted_snapshot(control):
    service, _, _, path = control
    _save(service)
    service.set_binding("worker", "alice", mode="configured", profile_id="profile-a", expected_revision=0)
    old = service.resolve_snapshot("worker", "alice")
    service.save_profile(profile_id="profile-a", name="Changed", providers=(_provider().model_copy(update={"project": "new-project"}),), allowed_user_ids=["alice"], expected_revision=1)
    script = """
import json, sys
from deerflow.persistence.agents.sql import get_sync_sessionmaker
from deerflow.persistence.tracing_profiles.sql import SqlTracingProfileRepository
from deerflow.config.credentials_key import get_credentials_cipher
from deerflow.tracing.profiles import TracingProfileService
service = TracingProfileService(SqlTracingProfileRepository(get_sync_sessionmaker(sys.argv[1])), get_credentials_cipher(), identity_resolver=lambda name, owner: f'test:{owner}:{name}')
new = service.resolve_snapshot('worker', 'alice')
old = service.resolve_snapshot('worker', 'alice', snapshot_id=sys.argv[2])
print(json.dumps([new.providers[0].project, old.providers[0].project]))
"""
    child = subprocess.run([sys.executable, "-c", script, f"sqlite:///{path / 'tracing.db'}", old.snapshot_id], capture_output=True, text=True, check=True, timeout=30, env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)})
    assert child.stdout.strip() == '["new-project", "project-a"]'


def test_memory_backend_refuses_control_plane_and_preserves_legacy_resolution(monkeypatch):
    from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
    from deerflow.tracing.profiles import TracingUnavailableError, get_profile_service, resolve_run_snapshot

    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))
    try:
        assert resolve_run_snapshot("worker", "alice") is None
        with pytest.raises(TracingUnavailableError):
            get_profile_service()
    finally:
        reset_app_config()


def test_explicit_embedded_config_does_not_load_an_unrelated_global_config(monkeypatch):
    from deerflow.config.app_config import AppConfig
    from deerflow.tracing.profiles import resolve_run_snapshot

    config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}})
    monkeypatch.setattr("deerflow.config.app_config.get_app_config", lambda: pytest.fail("must use the explicit embedded config"))
    assert resolve_run_snapshot("worker", "alice", app_config=config) is None


def test_real_postgres_repositories_apply_the_same_atomic_profile_and_binding_contract(monkeypatch):
    from uuid import uuid4

    from deerflow.config.credentials_key import CredentialsCipher
    from deerflow.config.database_config import DatabaseConfig
    from deerflow.persistence.base import Base
    from deerflow.persistence.tracing_profiles.model import AgentTracingBindingRow, RunTracingSnapshotRow, TracingAdmissionFenceRow, TracingProfileRow, TracingProfileVersionRow
    from deerflow.persistence.tracing_profiles.sql import SqlTracingProfileRepository
    from deerflow.tracing.profiles import TracingConflictError, TracingProfileService

    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires TEST_POSTGRES_URI for real PostgreSQL compare-and-swap coverage")
    schema = f"tracing_{uuid4().hex}"
    config = DatabaseConfig(backend="postgres", postgres_url=uri, postgres_schema=schema)
    engine = create_engine(config.app_sync_sqlalchemy_url)
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            Base.metadata.create_all(connection, tables=[row.__table__ for row in (AgentTracingBindingRow, RunTracingSnapshotRow, TracingProfileRow, TracingProfileVersionRow, TracingAdmissionFenceRow)])
        factory = sessionmaker(engine, expire_on_commit=False)
        cipher = CredentialsCipher.from_keys([Fernet.generate_key()])
        service = TracingProfileService(SqlTracingProfileRepository(factory), cipher, identity_resolver=lambda name, owner: f"test:{owner}:{name}")
        _save(service)
        barrier = Barrier(2)

        def save(name):
            barrier.wait()
            try:
                service.save_profile(profile_id="profile-a", name=name, providers=(_provider(),), allowed_user_ids=["alice"], expected_revision=1)
                return "saved"
            except TracingConflictError:
                return "conflict"

        with ThreadPoolExecutor(2) as pool:
            assert sorted(pool.map(save, ("first", "second"))) == ["conflict", "saved"]
        service.set_binding("worker", "alice", mode="configured", profile_id="profile-a", expected_revision=0)
        snapshot = service.resolve_snapshot("worker", "alice")
        peer = TracingProfileService(SqlTracingProfileRepository(factory), cipher, identity_resolver=service.identity_resolver)
        assert peer.resolve_snapshot("worker", "alice", snapshot_id=snapshot.snapshot_id) == snapshot
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
