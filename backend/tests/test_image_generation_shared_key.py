"""The image profile and server probe catalogs must share one stable key."""

import multiprocessing
import os
from pathlib import Path

import pytest

from deerflow.config.image_generation import (
    ImageGenerationProfile,
    ManagedImageGenerationProfile,
    ManagedImageGenerationProfileStore,
    ServerImageProbeStore,
)


def _save_first_image_profile(home: str, key_write_started, release_key_write) -> None:
    os.environ["DEER_FLOW_HOME"] = home
    os.environ["DEER_FLOW_MANAGED_IMAGE_PROFILES_ENABLED"] = "true"
    store = ManagedImageGenerationProfileStore()
    write_bytes = store._catalog.write_bytes

    def pause_key_write(path: Path, content: bytes) -> None:
        if path == store.key_path:
            key_write_started.set()
            if not release_key_write.wait(timeout=10):
                raise TimeoutError("The first key write was not released")
        write_bytes(path, content)

    store._catalog.write_bytes = pause_key_write
    store.save(
        ManagedImageGenerationProfile(name="web", provider="openai", model="test-image", base_url="https://images.example/v1", api_key="synthetic-web-key"),
        expected_revision=None,
    )


def _record_first_server_probe(home: str, cipher_started, probe_written) -> None:
    os.environ["DEER_FLOW_HOME"] = home
    os.environ["DEER_FLOW_MANAGED_IMAGE_PROFILES_ENABLED"] = "true"
    store = ServerImageProbeStore()
    cipher = store._catalog._cipher

    def mark_cipher(*, create: bool = False):
        cipher_started.set()
        return cipher(create=create)

    store._catalog._cipher = mark_cipher
    store.record(ImageGenerationProfile(provider="openai", model="server-image", base_url="https://server.example/v1", api_key="synthetic-server-key"), "generation", "success")
    probe_written.set()


@pytest.mark.skipif("fork" not in multiprocessing.get_all_start_methods(), reason="requires POSIX fork and advisory file locks")
def test_first_image_catalog_and_server_probe_share_key_across_processes(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setenv("DEER_FLOW_MANAGED_IMAGE_PROFILES_ENABLED", "true")
    context = multiprocessing.get_context("fork")
    key_write_started = context.Event()
    release_key_write = context.Event()
    cipher_started = context.Event()
    probe_written = context.Event()
    first = context.Process(target=_save_first_image_profile, args=(str(tmp_path), key_write_started, release_key_write))
    second = context.Process(target=_record_first_server_probe, args=(str(tmp_path), cipher_started, probe_written))

    first.start()
    try:
        assert key_write_started.wait(timeout=5)
        second.start()
        assert cipher_started.wait(timeout=5)
        wrote_before_key_creation = probe_written.wait(timeout=1)
    finally:
        release_key_write.set()
        first.join(timeout=5)
        if second.pid is not None:
            second.join(timeout=5)
        for process in (first, second):
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)

    assert first.exitcode == 0
    assert second.exitcode == 0
    assert not wrote_before_key_creation
    assert ManagedImageGenerationProfileStore().list()[0].model == "test-image"
    server = ImageGenerationProfile(provider="openai", model="server-image", base_url="https://server.example/v1", api_key="synthetic-server-key")
    assert ServerImageProbeStore().results(server) == {"generation": "success"}
