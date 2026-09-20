"""Contract tests for the optional Sandbox0 provider (no cloud credentials)."""

import sys
from dataclasses import make_dataclass
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from deerflow.community.sandbox0 import Sandbox0Provider
from deerflow.community.sandbox0.sandbox import Sandbox0Sandbox


def test_command_uses_fresh_bash_with_scoped_env():
    remote = Mock(id="remote")
    remote.cmd.return_value = SimpleNamespace(stdout="ok", stderr="", exit_code=0)
    sandbox = Sandbox0Sandbox("scope", remote, command_timeout=60)
    assert sandbox.execute_command("echo ok", env={"TOKEN": "secret"}) == "ok"
    options = remote.cmd.call_args.args[1]
    assert options.command == ["bash", "-lc", "echo ok"]
    assert options.env_vars == {"TOKEN": "secret"}
    assert options.ttl_sec == 60
    sandbox.execute_command("true")
    assert remote.cmd.call_args.args[1].env_vars is None


def test_nonzero_and_incomplete_execution_are_not_success():
    remote = Mock(id="remote")
    sandbox = Sandbox0Sandbox("scope", remote)
    remote.cmd.return_value = SimpleNamespace(stdout="partial", stderr="failed", exit_code=3)
    assert "Exit Code: 3" in sandbox.execute_command("false")
    remote.cmd.return_value.exit_code = None
    with pytest.raises(OSError, match="exit code"):
        sandbox.execute_command("sleep 30")


@pytest.mark.parametrize("path", ["/etc/passwd", "/mnt/user-data/../secret", "relative", "/mnt/user-data-other/file"])
def test_download_rejects_escape(path):
    sandbox = Sandbox0Sandbox("scope", Mock(id="remote"))
    with pytest.raises((PermissionError, ValueError)):
        sandbox.download_file(path)


def test_ranged_read_and_binary_write():
    remote = Mock(id="remote")
    remote.read_file.return_value = b"one\ntwo\nthree\n"
    sandbox = Sandbox0Sandbox("scope", remote)
    assert sandbox.read_file("/mnt/user-data/workspace/a", 2, 2) == "two"
    sandbox.update_file("/mnt/user-data/uploads/a.bin", b"\x00\xff")
    remote.write_file.assert_called_with("/mnt/user-data/uploads/a.bin", b"\x00\xff")


def test_release_waits_for_checkpoint_and_reacquire_resumes(provider):
    p, client = provider
    sid = p.acquire("thread", user_id="alice")
    p.release(sid)
    client.sandboxes.pause_and_wait.assert_called_once()
    assert p.get(sid) is None
    client.sandboxes.get.return_value = SimpleNamespace(status="paused", paused=True)
    assert p.acquire("thread", user_id="alice") == sid
    client.sandboxes.resume_and_wait.assert_called_once()
    assert client.sandboxes.claim.call_count == 1


def test_checkpoint_failure_keeps_client_for_retry(provider):
    p, client = provider
    sid = p.acquire("thread", user_id="alice")
    client.sandboxes.pause_and_wait.side_effect = TimeoutError("checkpoint")
    with pytest.raises(TimeoutError):
        p.release(sid)
    assert p.get(sid) is not None
    client.sandboxes.pause_and_wait.side_effect = None
    p.release(sid)
    assert p.get(sid) is None


def test_user_isolation(provider):
    p, client = provider
    assert p.acquire("thread", user_id="alice") != p.acquire("thread", user_id="bob")
    assert client.sandboxes.claim.call_count == 2


@pytest.fixture
def provider(monkeypatch, tmp_path):
    from deerflow.community.sandbox0 import provider as module
    from deerflow.config.sandbox_config import SandboxConfig

    config = SimpleNamespace(sandbox=SandboxConfig(use="deerflow.community.sandbox0:Sandbox0Provider", api_key="test", state_dir=str(tmp_path)), skills=SimpleNamespace(container_path="/mnt/skills"))
    monkeypatch.setattr(module, "get_app_config", lambda: config)
    client = Mock()
    client.sandbox.side_effect = lambda id: Mock(id=id)
    client.sandboxes.claim.side_effect = [Mock(id="remote-1"), Mock(id="remote-2")]
    client.sandboxes.get.return_value = SimpleNamespace(status="running", paused=False)
    monkeypatch.setattr(module, "_new_client", lambda **kwargs: client)
    monkeypatch.setattr(Sandbox0Provider, "_bootstrap", lambda *args: None)
    monkeypatch.setattr(Sandbox0Provider, "_sync_inputs", lambda *args: None)
    monkeypatch.setattr(Sandbox0Provider, "_sync_skills", lambda *args: None)
    monkeypatch.setattr(Sandbox0Provider, "_sync_artifacts", lambda *args: None)
    p = Sandbox0Provider()
    yield p, client
    client.sandboxes.pause_and_wait.side_effect = None
    p.shutdown()


@pytest.fixture(autouse=True)
def fake_optional_sdk(monkeypatch):
    module = ModuleType("sandbox0")
    module.CmdOptions = make_dataclass("CmdOptions", [("command", object), ("wait", bool), ("ttl_sec", int), ("env_vars", object)])
    monkeypatch.setitem(sys.modules, "sandbox0", module)
    config = ModuleType("sandbox0.apispec.models.sandbox_config")
    config.SandboxConfig = lambda **kwargs: SimpleNamespace(**kwargs)
    monkeypatch.setitem(sys.modules, "sandbox0.apispec.models.sandbox_config", config)


def test_provider_restart_preserves_binding(provider):
    p, client = provider
    sid = p.acquire("thread", user_id="alice")
    p.shutdown()
    client.sandboxes.get.return_value = SimpleNamespace(status="paused", paused=True)
    replacement = Sandbox0Provider()
    try:
        assert replacement.acquire("thread", user_id="alice") == sid
        assert client.sandboxes.claim.call_count == 1
        assert replacement.get(sid).remote_id == "remote-1"
    finally:
        replacement.shutdown()


def test_second_gateway_cannot_adopt_live_registry(provider):
    p, _ = provider
    p.acquire("thread", user_id="alice")
    other = Sandbox0Provider()
    try:
        with pytest.raises(RuntimeError, match="another Gateway"):
            other.acquire("thread", user_id="alice")
    finally:
        other.shutdown()


def test_missing_persistent_identity_is_not_silently_replaced(provider):
    p, client = provider
    sid = p.acquire("thread", user_id="alice")
    p.release(sid)
    client.sandboxes.get.side_effect = OSError("expired")
    with pytest.raises(OSError, match="expired"):
        p.acquire("thread", user_id="alice")
    assert client.sandboxes.claim.call_count == 1


def test_artifact_failure_still_checkpoints(provider, monkeypatch):
    p, client = provider
    sid = p.acquire("thread", user_id="alice")
    monkeypatch.setattr(p, "_sync_artifacts", Mock(side_effect=OSError("transfer limit")))
    with pytest.raises(OSError, match="transfer limit"):
        p.release(sid)
    client.sandboxes.pause_and_wait.assert_called_once()
    assert p.get(sid) is None


def test_destroy_deletes_only_owned_binding(provider):
    p, client = provider
    sid = p.acquire("thread", user_id="alice")
    p.release(sid)
    p.destroy(sid)
    client.sandboxes.delete.assert_called_once_with("remote-1")
    assert not p._binding_path(sid).exists()


def test_async_acquire_keeps_event_loop_responsive(provider, monkeypatch):
    import asyncio
    import threading

    p, _ = provider
    started, finish = threading.Event(), threading.Event()

    def slow(*args):
        started.set()
        assert finish.wait(3)

    monkeypatch.setattr(p, "_bootstrap", slow)

    async def run():
        task = asyncio.create_task(p.acquire_async("thread", user_id="alice"))
        while not started.is_set():
            await asyncio.sleep(0.001)
        finish.set()
        return await task

    assert asyncio.run(run())


def test_shutdown_rejects_queued_acquire(provider):
    import threading

    p, _ = provider
    p.acquire("thread", user_id="alice")
    queued = threading.Event()
    errors = []

    def acquire():
        queued.set()
        try:
            p.acquire("thread", user_id="alice")
        except RuntimeError as exc:
            errors.append(str(exc))

    with p._lifecycle:
        worker = threading.Thread(target=acquire, daemon=True)
        worker.start()
        assert queued.wait(1)
        p.shutdown()
    worker.join(2)
    assert not worker.is_alive()
    assert errors == ["Sandbox0 provider is shut down"]


def test_active_io_renews_soft_ttl_without_refreshing_every_operation(monkeypatch):
    from deerflow.community.sandbox0 import sandbox as module

    now = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    renew = Mock()
    remote = Mock(id="remote")
    remote.read_file.return_value = b"ok"
    sandbox = Sandbox0Sandbox("scope", remote, refresh=renew, refresh_interval=60)
    sandbox.read_file("/file")
    sandbox.read_file("/file")
    assert renew.call_count == 1
    now[0] += 61
    sandbox.update_file("/file", b"new")
    assert renew.call_count == 2


def test_destroy_waits_for_accepted_async_deletion(provider, monkeypatch):
    p, client = provider
    sid = p.acquire("thread", user_id="alice")
    accepted = RuntimeError("accepted")
    accepted.status_code = 202
    missing = RuntimeError("missing")
    missing.status_code = 404
    client.sandboxes.delete.side_effect = accepted
    client.sandboxes.get.side_effect = [SimpleNamespace(status="terminating"), missing]
    monkeypatch.setattr("deerflow.community.sandbox0.provider.time.sleep", lambda _: None)
    p.destroy(sid)
    assert client.sandboxes.get.call_count == 2
    assert not p._binding_path(sid).exists()


def test_accepted_pause_waits_for_committed_checkpoint(provider):
    p, client = provider
    sid = p.acquire("thread", user_id="alice")
    accepted = RuntimeError("accepted")
    accepted.status_code = 202
    client.sandboxes.pause_and_wait.side_effect = accepted
    p.release(sid)
    remote_id, predicate = client.sandboxes.wait_for_lifecycle.call_args.args
    assert remote_id == "remote-1"
    assert not predicate(SimpleNamespace(status="pausing", paused=False))
    assert predicate(SimpleNamespace(status="paused", paused=True))


def test_accepted_resume_requires_new_running_generation(provider):
    p, client = provider
    sid = p.acquire("thread", user_id="alice")
    p.release(sid)
    client.sandboxes.get.return_value = SimpleNamespace(status="paused", paused=True, runtime_generation=4)
    accepted = RuntimeError("accepted")
    accepted.status_code = 202
    client.sandboxes.resume_and_wait.side_effect = accepted
    assert p.acquire("thread", user_id="alice") == sid
    _, predicate = client.sandboxes.wait_for_lifecycle.call_args.args
    assert not predicate(SimpleNamespace(status="running", paused=False, runtime_generation=4))
    assert predicate(SimpleNamespace(status="running", paused=False, runtime_generation=5))


def test_delete_timeout_retains_binding_for_retry(provider, monkeypatch):
    p, client = provider
    sid = p.acquire("thread", user_id="alice")
    accepted = RuntimeError("accepted")
    accepted.status_code = 202
    client.sandboxes.delete.side_effect = accepted
    p._lifecycle_timeout = 1
    monkeypatch.setattr("deerflow.community.sandbox0.provider.time.monotonic", Mock(side_effect=[0, 2]))
    with pytest.raises(TimeoutError, match="binding retained"):
        p.destroy(sid)
    assert p._binding_path(sid).exists()
