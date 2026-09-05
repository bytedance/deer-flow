"""Admission runs before acquisition, on every acquisition path."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deerflow.sandbox import tools as sandbox_tools
from deerflow.sandbox.exceptions import SandboxAdmissionRefused
from deerflow.sandbox.lease import SandboxLeaseManager
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import SandboxProvider


class _Provider(SandboxProvider):
    def __init__(self) -> None:
        self.admitted: list[tuple[str | None, str | None]] = []
        self.acquired: list[str | None] = []

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        del user_id
        self.acquired.append(thread_id)
        return "sandbox"

    async def acquire_async(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        return self.acquire(thread_id, user_id=user_id)

    def get(self, sandbox_id: str) -> Sandbox | None:
        return None

    def release(self, sandbox_id: str) -> None:
        return None


class _Refusing(_Provider):
    def admit(self, thread_id: str | None = None, *, user_id: str | None = None) -> None:
        self.admitted.append((thread_id, user_id))
        raise SandboxAdmissionRefused("per-user sandbox quota exhausted", reason="user_quota_exhausted")


def test_the_default_admits_everything() -> None:
    provider = _Provider()
    manager = SandboxLeaseManager(provider)

    assert manager.acquire("owner", "thread", user_id="user") == "sandbox"
    assert provider.acquired == ["thread"]


def test_the_lease_manager_admits_before_the_provider_acquires() -> None:
    provider = _Refusing()
    manager = SandboxLeaseManager(provider)

    with pytest.raises(SandboxAdmissionRefused) as refused:
        manager.acquire("owner", "thread", user_id="user")

    assert refused.value.reason == "user_quota_exhausted"
    assert provider.admitted == [("thread", "user")]
    assert provider.acquired == []
    assert manager.binding_for("owner") is None


@pytest.mark.asyncio
async def test_async_acquisition_admits_through_the_sync_rule_by_default() -> None:
    provider = _Refusing()
    manager = SandboxLeaseManager(provider)

    with pytest.raises(SandboxAdmissionRefused):
        await manager.acquire_async("owner", "thread", user_id="user")

    assert provider.admitted == [("thread", "user")]
    assert provider.acquired == []


def _runtime() -> SimpleNamespace:
    return SimpleNamespace(state={"sandbox": None}, context={"thread_id": "thread", "user_id": "user"}, config=None)


def test_direct_tool_acquisition_admits_too(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _Refusing()
    monkeypatch.setattr(sandbox_tools, "get_sandbox_provider", lambda: provider)

    with pytest.raises(SandboxAdmissionRefused):
        sandbox_tools.ensure_sandbox_initialized(_runtime())

    assert provider.acquired == []


@pytest.mark.asyncio
async def test_direct_async_tool_acquisition_admits_too(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _Refusing()
    monkeypatch.setattr(sandbox_tools, "get_sandbox_provider", lambda: provider)

    with pytest.raises(SandboxAdmissionRefused):
        await sandbox_tools.ensure_sandbox_initialized_async(_runtime())

    assert provider.acquired == []
