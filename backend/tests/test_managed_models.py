"""Managed models: persistence, snapshot resolution and administrator boundaries."""

import asyncio
import logging
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from deerflow.config.app_config import AppConfig
from deerflow.config.managed_models import ManagedModel, ManagedModelStore, merge_managed_models


def profile(**kwargs):
    return ManagedModel(name="managed-test", model="test-model", base_url="https://example.com/v1", api_key="test-secret", **kwargs)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    return ManagedModelStore()


def test_persist_encrypt_preserve_secret_and_revision(store):
    with pytest.raises(FileNotFoundError):
        store.save(profile(), expected_revision="missing")
    first = store.save(profile(), expected_revision=None)
    assert b"test-secret" not in store.path.read_bytes()
    assert ManagedModelStore().list()[0].api_key.get_secret_value() == "test-secret"
    updated = store.save(profile(enabled=False).model_copy(update={"api_key": None}), expected_revision=first.revision)
    assert updated.api_key.get_secret_value() == "test-secret"
    assert updated.revision != first.revision
    with pytest.raises(FileExistsError):
        store.save(profile(), expected_revision=first.revision)
    with pytest.raises(FileExistsError):
        store.save(profile(), expected_revision=None)


def test_snapshot_merge_yaml_precedence_and_disable(store):
    base = AppConfig.model_validate({"sandbox": {"use": "test"}, "models": [{"name": "yaml", "model": "yaml", "use": "test"}]})
    first = store.save(profile(), expected_revision=None)
    merged = merge_managed_models(base)
    assert [m.name for m in merged.models] == ["yaml", "managed-test"]
    assert merged.get_model_config("managed-test").api_key == "test-secret"
    assert base.get_model_config("managed-test") is None
    store.save(profile(enabled=False), expected_revision=first.revision)
    assert merge_managed_models(base).get_model_config("managed-test") is None
    assert merged.get_model_config("managed-test") is not None
    store.save(profile().model_copy(update={"name": "yaml"}), expected_revision=None)
    assert merge_managed_models(base).get_model_config("yaml").use == "test"


def test_missing_encryption_key_never_replaced(store):
    store.save(profile(), expected_revision=None)
    store.key_path.unlink()
    with pytest.raises(ValueError, match="key"):
        store.list()
    assert not store.key_path.exists()


def test_first_save_keeps_a_key_a_peer_created_concurrently(store, monkeypatch):
    """A peer that publishes the key file first must win; replacing it would orphan the peer's catalog."""
    from cryptography.fernet import Fernet

    peer_key = Fernet.generate_key()
    original_generate = Fernet.generate_key

    def peer_wins_the_race():
        store.key_path.parent.mkdir(parents=True, exist_ok=True)
        store.key_path.write_bytes(peer_key)
        return original_generate()

    monkeypatch.setattr(Fernet, "generate_key", staticmethod(peer_wins_the_race))
    store.save(profile(), expected_revision=None)

    assert store.key_path.read_bytes() == peer_key
    assert Fernet(peer_key).decrypt(store.path.read_bytes())


def test_first_save_recovers_an_empty_key_left_by_an_interrupted_creation(store):
    """An empty key file with no catalog encrypted no data, so the next save must replace it, not 503 forever."""
    from cryptography.fernet import Fernet

    store.key_path.parent.mkdir(parents=True, exist_ok=True)
    store.key_path.write_bytes(b"")

    store.save(profile(), expected_revision=None)

    key = store.key_path.read_bytes()
    assert key.strip()
    assert Fernet(key).decrypt(store.path.read_bytes())
    assert ManagedModelStore().list()[0].api_key.get_secret_value() == "test-secret"


def test_an_empty_key_next_to_an_existing_catalog_is_never_replaced(store):
    """The catalog was encrypted with the lost key; a new key would silently orphan it."""
    store.save(profile(), expected_revision=None)
    catalog = store.path.read_bytes()
    store.key_path.write_bytes(b"")

    with pytest.raises(ValueError):
        store.save(profile(), expected_revision=None)
    with pytest.raises(ValueError, match="restore it from backup"):
        store._cipher(create=True)

    assert store.key_path.read_bytes() == b""
    assert store.path.read_bytes() == catalog


@pytest.mark.parametrize("url", ["file:///tmp/test", "https://user:pass@example.com/v1", "https://example.com/v1?key=abc", "https://example.com/#fragment"])
def test_endpoint_validation(url):
    with pytest.raises(ValidationError):
        ManagedModel(name="test", model="test", base_url=url)


@pytest.mark.asyncio
async def test_save_model_drains_started_persistence_across_cancellation(monkeypatch):
    from app.gateway.routers import managed_models as router

    started = threading.Event()
    release = threading.Event()

    def save(_body):
        started.set()
        assert release.wait(timeout=2)
        return {"name": "managed-test", "has_api_key": True}

    monkeypatch.setattr(router, "_save", save)
    request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="admin")))
    body = router.SaveModelRequest(config=profile())

    task = asyncio.create_task(router.save_model(request, body))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.sleep(0.05)
        assert not task.done()

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [OSError, RuntimeError])
async def test_save_model_logs_failed_drained_persistence_after_cancellation(store, monkeypatch, caplog, failure):
    from app.gateway.routers import managed_models as router

    started = threading.Event()
    release = threading.Event()

    def fail_save(self, *_args, **_kwargs):
        started.set()
        assert release.wait(timeout=5)
        raise failure("test-secret must not appear in logs")

    monkeypatch.setattr(router, "get_app_config", lambda: AppConfig.model_validate({"sandbox": {"use": "test"}}))
    monkeypatch.setattr(ManagedModelStore, "save", fail_save)
    request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="admin")))
    body = router.SaveModelRequest(config=profile())

    with caplog.at_level(logging.ERROR, logger=router.__name__):
        task = asyncio.create_task(router.save_model(request, body))
        try:
            assert await asyncio.to_thread(started.wait, 5)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()

            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    save_errors = [record for record in caplog.records if record.name == router.__name__ and "Managed model save failed" in record.message]
    assert len(save_errors) == 1
    expected_detail = "503" if failure is OSError else "RuntimeError"
    assert expected_detail in save_errors[0].message
    assert "test-secret" not in caplog.text


@pytest.mark.asyncio
async def test_admin_gate_and_response_redaction(store, monkeypatch):
    from app.gateway.routers import managed_models as router

    config = AppConfig.model_validate({"sandbox": {"use": "test"}})
    monkeypatch.setattr(router, "get_app_config", lambda: config)
    admin = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="admin")))
    member = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="user")))
    body = router.SaveModelRequest(config=profile())
    with pytest.raises(HTTPException) as exc:
        await router.save_model(member, body)
    assert exc.value.status_code == 403
    result = await router.save_model(admin, body)
    assert result["has_api_key"] is True
    assert "api_key" not in result
    assert "test-secret" not in str(await router.list_managed_models(admin))
    with pytest.raises(HTTPException) as exc:
        await router.list_managed_models(member)
    assert exc.value.status_code == 403


def test_config_loader_sees_changes_without_yaml_write(store, tmp_path, monkeypatch):
    from deerflow.config.app_config import get_app_config, reset_app_config

    path = tmp_path / "config.yaml"
    original = "sandbox:\n  use: test\nmodels: []\n"
    path.write_text(original, encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(path))
    monkeypatch.delenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", raising=False)
    reset_app_config()
    try:
        assert not get_app_config().models
        saved = store.save(profile(), expected_revision=None)
        snapshot = get_app_config()
        assert snapshot.get_model_config("managed-test").model == "test-model"
        assert get_app_config() is snapshot
        store.save(profile(enabled=False), expected_revision=saved.revision)
        assert not get_app_config().models
        assert snapshot.get_model_config("managed-test") is not None
        assert path.read_text(encoding="utf-8") == original
    finally:
        reset_app_config()


def test_parallel_writes_preserve_all_models(store):
    from concurrent.futures import ThreadPoolExecutor

    def save(index):
        store.save(profile().model_copy(update={"name": f"model-{index}"}), expected_revision=None)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(save, range(16)))
    assert len(store.list()) == 16


def test_clear_key_and_corrupt_catalog_fail_closed(store):
    from pydantic import SecretStr

    previous = store.save(profile(), expected_revision=None)
    saved = store.save(profile().model_copy(update={"api_key": SecretStr("")}), expected_revision=previous.revision)
    assert saved.public()["has_api_key"] is False
    assert store.list()[0].runtime_config().api_key == "not-required"
    store.path.write_bytes(b"broken")
    with pytest.raises(ValueError):
        store.save(profile(), expected_revision=None)
    assert store.path.read_bytes() == b"broken"


@pytest.mark.asyncio
async def test_yaml_name_reserved_and_pat_denied(store, monkeypatch):
    from app.gateway.auth_disabled import AUTH_SOURCE_PAT
    from app.gateway.routers import managed_models as router

    config = AppConfig.model_validate({"sandbox": {"use": "test"}, "models": [{"name": "managed-test", "model": "yaml", "use": "test"}]})
    monkeypatch.setattr(router, "get_app_config", lambda: config)
    request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="admin")))
    body = router.SaveModelRequest(config=profile())
    with pytest.raises(HTTPException) as exc:
        await router.save_model(request, body)
    assert exc.value.status_code == 409
    request.state.auth_source = AUTH_SOURCE_PAT
    for operation in (router.save_model, router.test_model):
        with pytest.raises(HTTPException) as exc:
            await operation(request, body)
        assert exc.value.status_code == 403
    assert not store.path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,expected", [("tool", "success"), ("text", "tool_call_missing"), ("error", "connection_failed")])
async def test_connection_probe_is_bounded_redacted_and_does_not_save(store, monkeypatch, mode, expected):
    import langchain_openai
    from langchain_core.messages import AIMessageChunk

    from app.gateway.routers import managed_models as router

    captured = {}

    class FakeModel:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def bind_tools(self, tools, **kwargs):
            assert kwargs["tool_choice"] == "connection_check"
            return self

        async def astream(self, *args, **kwargs):
            if mode == "error":
                raise RuntimeError("test-secret should never be returned")
            yield AIMessageChunk(content="", tool_call_chunks=[{"name": "connection_check", "args": "{}", "id": "call-1", "index": 0}] if mode == "tool" else [])

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", FakeModel)
    request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="admin")))
    result = await router.test_model(request, router.SaveModelRequest(config=profile()))
    assert result["message"] == expected
    assert "test-secret" not in str(result)
    assert captured["max_retries"] == 0
    assert captured["timeout"] == 15
    assert not store.path.exists()


def test_separate_process_writers_share_catalog_lock(store):
    import os
    import subprocess
    import sys

    script = """
import sys
from deerflow.config.managed_models import ManagedModelStore, ManagedModel
store = ManagedModelStore()
for index in range(5):
    store.save(ManagedModel(name=f'{sys.argv[1]}-{index}', model='test', base_url='https://example.com/v1', api_key='secret'), expected_revision=None)
"""
    processes = [subprocess.Popen([sys.executable, "-c", script, str(index)], env=os.environ.copy(), stdout=subprocess.PIPE, stderr=subprocess.PIPE) for index in range(3)]
    try:
        for process in processes:
            output, errors = process.communicate(timeout=30)
            assert process.returncode == 0, (output, errors)
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()
    assert len(store.list()) == 15
    if os.name == "posix":
        assert store.path.stat().st_mode & 0o777 == 0o600
        assert store.key_path.stat().st_mode & 0o777 == 0o600
