import asyncio
import stat

from deerflow.uploads.sandbox_sync import (
    make_upload_paths_available,
    make_upload_paths_available_async,
    prepare_upload_deletion,
    prepare_upload_deletion_async,
)


class _ProviderThatBecomesMounted:
    def __init__(self) -> None:
        self.uses_thread_data_mounts = False
        self.get_calls = 0

    def refresh_thread_data_mount_capabilities(self) -> bool:
        return False

    def acquire(self, _thread_id: str, *, user_id: str | None = None) -> str:
        self.uses_thread_data_mounts = True
        return "mounted-sandbox"

    async def acquire_async(self, _thread_id: str, *, user_id: str | None = None) -> str:
        self.uses_thread_data_mounts = True
        return "mounted-sandbox"

    def get(self, _sandbox_id: str):
        self.get_calls += 1
        raise AssertionError("mounted mode must not explicitly synchronize files")


def test_prepare_deletion_rechecks_mount_mode_after_acquire():
    provider = _ProviderThatBecomesMounted()

    assert prepare_upload_deletion(provider, "thread-1", user_id="alice") is None
    assert provider.get_calls == 0


def test_prepare_deletion_async_rechecks_mount_mode_after_acquire():
    provider = _ProviderThatBecomesMounted()

    assert asyncio.run(prepare_upload_deletion_async(provider, "thread-1", user_id="alice")) is None
    assert provider.get_calls == 0


def test_make_paths_available_rechecks_mount_mode_after_acquire(tmp_path):
    provider = _ProviderThatBecomesMounted()
    path = tmp_path / "notes.txt"
    path.write_text("notes", encoding="utf-8")
    path.chmod(0o600)

    receipt = make_upload_paths_available(
        provider,
        "thread-1",
        user_id="alice",
        paths=[(path, "/mnt/user-data/uploads/notes.txt")],
    )

    assert receipt.sandbox is None
    assert stat.S_IMODE(path.stat().st_mode) == 0o644
    assert provider.get_calls == 0


def test_make_paths_available_async_rechecks_mount_mode_after_acquire(tmp_path):
    provider = _ProviderThatBecomesMounted()
    path = tmp_path / "notes.txt"
    path.write_text("notes", encoding="utf-8")
    path.chmod(0o600)

    receipt = asyncio.run(
        make_upload_paths_available_async(
            provider,
            "thread-1",
            user_id="alice",
            paths=[(path, "/mnt/user-data/uploads/notes.txt")],
        )
    )

    assert receipt.sandbox is None
    assert stat.S_IMODE(path.stat().st_mode) == 0o644
    assert provider.get_calls == 0
