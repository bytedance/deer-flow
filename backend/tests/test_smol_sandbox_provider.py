"""Smol VM provider lifecycle and sandbox contract without optional native assets."""

from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace

import pytest

from deerflow.community.smol import provider as smol_provider
from deerflow.community.smol.sandbox import SmolSandbox


class _Machine:
    instances: list[_Machine] = []
    fail_bootstrap = False

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.deleted = False
        self.calls: list[tuple[list[str], object]] = []
        type(self).instances.append(self)

    @classmethod
    def create(cls, config, conn):
        return cls()

    def exec(self, command: list[str], opts=None):
        self.calls.append((command, opts))
        if self.fail_bootstrap and command[0] == "mkdir":
            return SimpleNamespace(exit_code=1, stdout="", stderr="cannot mkdir")
        return SimpleNamespace(exit_code=0, stdout="ok", stderr="")

    def read_file(self, path: str) -> bytes:
        if path not in self.files:
            raise SimpleNamespaceError("NOT_FOUND")
        return self.files[path]

    def write_file(self, path: str, content: bytes) -> None:
        self.files[path] = content

    def delete(self) -> None:
        self.deleted = True


class SimpleNamespaceError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@pytest.fixture
def provider(monkeypatch):
    _Machine.instances.clear()
    _Machine.fail_bootstrap = False
    sandbox = SimpleNamespace(
        target="local",
        api_key=None,
        image="python:3.12-slim",
        cpus=None,
        memory_mb=None,
        replicas=2,
        idle_timeout=60,
        ttl_seconds=None,
        bash_command_timeout=4.5,
        environment={"CONFIG_ENV": "configured"},
        network=SimpleNamespace(mode="open"),
    )
    monkeypatch.setattr(smol_provider, "get_app_config", lambda: SimpleNamespace(sandbox=sandbox))
    monkeypatch.setattr(
        smol_provider,
        "_import_smol",
        lambda: (SimpleNamespace, _Machine, SimpleNamespace, SimpleNamespace),
    )
    fake = ModuleType("smol")
    fake.ExecOptions = SimpleNamespace
    monkeypatch.setitem(sys.modules, "smol", fake)
    instance = smol_provider.SmolSandboxProvider()
    yield instance, sandbox
    instance.shutdown()


def test_scope_warm_reclaim_and_binary_file_roundtrip(provider):
    p, _ = provider
    sid = p.acquire("thread-a", user_id="alice")
    sandbox = p.get_scoped(sid, thread_id="thread-a", user_id="alice")
    assert isinstance(sandbox, SmolSandbox)
    assert p.get_scoped(sid, thread_id="thread-a", user_id="bob") is None
    assert p.get_scoped(sid, thread_id="thread-b", user_id="alice") is None
    assert p.acquire("thread-a", user_id="alice") == sid
    assert len(_Machine.instances) == 1

    path = "/mnt/user-data/workspace/output.bin"
    sandbox.update_file(path, b"\x00\xff\n")
    assert sandbox.download_file(path) == b"\x00\xff\n"
    sandbox.write_file(path, "append", append=True)
    assert sandbox.download_file(path) == b"\x00\xff\nappend"
    assert sandbox.execute_command("echo ok", env={"PER_CALL": "secret"}) == "ok"
    _, options = _Machine.instances[0].calls[-1]
    assert options.env == {"CONFIG_ENV": "configured", "PER_CALL": "secret"}
    assert options.timeout == 4.5
    sandbox.execute_command("echo ok")
    assert "PER_CALL" not in _Machine.instances[0].calls[-1][1].env
    with pytest.raises(ValueError):
        sandbox.execute_command("echo ok", env={"BAD-ENV": "oops"})
    with pytest.raises(PermissionError):
        sandbox.download_file("/mnt/user-data/../etc/passwd")
    with pytest.raises(PermissionError):
        sandbox.download_file("/etc/passwd")

    p.release(sid)
    assert p.get_scoped(sid, thread_id="thread-a", user_id="alice") is None
    assert p.acquire("thread-a", user_id="alice") == sid
    assert len(_Machine.instances) == 1
    assert p.get(sid).download_file(path) == b"\x00\xff\nappend"
    p.shutdown()
    assert _Machine.instances[0].deleted


def test_cloud_file_paths_are_rejected_before_guest_mutation(provider):
    p, _ = provider
    p._config["target"] = "cloud"
    sid = p.acquire("unsafe-filenames", user_id="alice")
    sandbox = p.get(sid)
    machine = _Machine.instances[-1]
    calls_after_bootstrap = len(machine.calls)
    for suffix in ("#draft", "?v=2", "%20draft", "\nname", "\x00name"):
        path = f"/mnt/user-data/workspace/report{suffix}.txt"
        with pytest.raises(ValueError, match="Smol Cloud file path"):
            sandbox.write_file(path, "write")
        with pytest.raises(ValueError, match="Smol Cloud file path"):
            sandbox.write_file(path, "append", append=True)
        with pytest.raises(ValueError, match="Smol Cloud file path"):
            sandbox.update_file(path, b"binary")
        with pytest.raises(ValueError, match="Smol Cloud file path"):
            sandbox.read_file(path)
        with pytest.raises(ValueError, match="Smol Cloud file path"):
            sandbox.download_file(path)
    assert machine.files == {}
    assert len(machine.calls) == calls_after_bootstrap


def test_local_file_paths_keep_url_delimiters(provider):
    p, _ = provider
    sid = p.acquire("local-filenames", user_id="alice")
    sandbox = p.get(sid)
    path = "/mnt/user-data/workspace/report#draft%20.txt"
    sandbox.write_file(path, "first")
    sandbox.write_file(path, "+second", append=True)
    assert sandbox.download_file(path) == b"first+second"
    assert sandbox.read_file(path) == "first+second"


def test_failed_bootstrap_deletes_vm(provider):
    p, _ = provider
    _Machine.fail_bootstrap = True
    with pytest.raises(OSError, match="bootstrap failed"):
        p.acquire("broken", user_id="alice")
    assert _Machine.instances[0].deleted
    assert p.get(p._sandbox_id("broken", "alice")) is None


def test_unenforced_network_policy_rejected(monkeypatch):
    sandbox = SimpleNamespace(network=SimpleNamespace(mode="allowlist"))
    monkeypatch.setattr(smol_provider, "get_app_config", lambda: SimpleNamespace(sandbox=sandbox))
    with pytest.raises(ValueError, match="network.mode"):
        smol_provider.SmolSandboxProvider()


def test_async_acquire_uses_same_scope(provider):
    p, _ = provider

    async def scenario():
        first, second = await asyncio.gather(
            p.acquire_async("same", user_id="alice"),
            p.acquire_async("same", user_id="alice"),
        )
        assert first == second
        assert len(_Machine.instances) == 1

    asyncio.run(scenario())
