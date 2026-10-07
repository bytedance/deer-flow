"""Quarantine follows a container generation across provider restarts."""

import pytest

from deerflow.community.aio_sandbox.quarantine import SandboxQuarantine
from deerflow.community.aio_sandbox.sandbox_info import SandboxInfo


def test_quarantine_survives_restart_and_does_not_taint_replacement(tmp_path):
    old = SandboxInfo("thread-sandbox", "http://sandbox", container_id="old-generation")
    replacement = SandboxInfo("thread-sandbox", "http://sandbox", container_id="new-generation")
    SandboxQuarantine(tmp_path, "provisioner-a").mark(old)

    restarted = SandboxQuarantine(tmp_path, "provisioner-a")
    assert restarted.contains(old)
    assert not restarted.contains(replacement)
    assert not SandboxQuarantine(tmp_path, "provisioner-b").contains(old)


def test_discovery_without_generation_cannot_bypass_quarantine(tmp_path):
    store = SandboxQuarantine(tmp_path, "provisioner")
    store.mark(SandboxInfo("thread-sandbox", "http://sandbox", container_id="old-generation"))

    assert store.contains(SandboxInfo("thread-sandbox", "http://sandbox"))
    assert not store.contains(SandboxInfo("another-thread", "http://sandbox"))


def test_quarantine_storage_failure_is_not_treated_as_safe(tmp_path, monkeypatch):
    store = SandboxQuarantine(tmp_path, "provisioner")

    def unavailable(*_args, **_kwargs):
        raise PermissionError("quarantine storage unavailable")

    monkeypatch.setattr(type(tmp_path), "stat", unavailable)
    with pytest.raises(PermissionError):
        store.contains(SandboxInfo("thread-sandbox", "http://sandbox", container_id="generation"))


def test_crash_residue_between_directory_and_record_still_fences(tmp_path):
    # mark() mkdirs the per-sandbox directory before writing the generation
    # record; a process dying in between must not silently drop the fence.
    store = SandboxQuarantine(tmp_path, "provisioner")
    directory = tmp_path / store._key("provisioner") / store._key("thread-sandbox")
    directory.mkdir(parents=True)

    assert store.contains(SandboxInfo("thread-sandbox", "http://sandbox"))
    assert store.contains(SandboxInfo("thread-sandbox", "http://sandbox", container_id="crashed-generation"))


def test_retired_quarantine_allows_replacements_without_generation(tmp_path):
    store = SandboxQuarantine(tmp_path, "provisioner")
    old = SandboxInfo("thread-sandbox", "http://sandbox")
    store.mark(old)
    store.mark(SandboxInfo(old.sandbox_id, old.sandbox_url, container_id="old-generation"))
    other = SandboxInfo("another-thread", "http://sandbox")
    store.mark(other)

    store.retire(old)

    restarted = SandboxQuarantine(tmp_path, "provisioner")
    assert not restarted.contains(old)
    assert not restarted.contains(SandboxInfo(old.sandbox_id, old.sandbox_url, container_id="new-generation"))
    assert restarted.contains(other)
