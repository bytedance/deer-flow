import asyncio
import stat

import pytest

from deerflow.uploads.layout import conversion_path_for_upload
from deerflow.uploads.manager import RemoteDeletionCommitRequiredError, cleanup_stale_upload_staging_files, delete_file_safe
from deerflow.uploads.sandbox_sync import (
    _deletion_hook_for_sandbox,
    make_upload_paths_available,
    make_upload_paths_available_async,
    prepare_upload_deletion,
    prepare_upload_deletion_async,
    reconcile_pending_remote_deletions,
)


def test_failed_compensation_deletes_paths_that_were_already_republished(tmp_path):
    primary_virtual = "/mnt/user-data/uploads/report.pdf"
    conversion_virtual = "/mnt/user-data/.upload-conversions/report.pdf.md"

    class PartialFailureSandbox:
        def __init__(self) -> None:
            self.files = {
                primary_virtual: b"pdf",
                conversion_virtual: b"generated",
            }
            self.remove_calls: list[str] = []
            self.conversion_failure_injected = False

        def remove_file(self, path: str) -> None:
            self.remove_calls.append(path)
            self.files.pop(path, None)
            if path == conversion_virtual and not self.conversion_failure_injected:
                self.conversion_failure_injected = True
                raise OSError("conversion response lost")

        def update_file(self, path: str, content: bytes) -> None:
            if path == primary_virtual:
                raise OSError("primary compensation unavailable")
            self.files[path] = content

    primary = tmp_path / "report.pdf"
    primary.write_bytes(b"pdf")
    conversion = tmp_path / "report.pdf.md"
    conversion.write_bytes(b"generated")
    sandbox = PartialFailureSandbox()

    with pytest.raises(RemoteDeletionCommitRequiredError):
        _deletion_hook_for_sandbox(sandbox)("report.pdf", primary, conversion)

    assert sandbox.files == {}
    assert sandbox.remove_calls == [
        primary_virtual,
        conversion_virtual,
        primary_virtual,
        conversion_virtual,
    ]


def test_unconfirmed_remote_delete_is_persisted_and_retried_after_restart(tmp_path):
    primary_virtual = "/mnt/user-data/uploads/report.pdf"
    conversion_virtual = "/mnt/user-data/.upload-conversions/report.pdf.md"

    class RestartableSandbox:
        def __init__(self) -> None:
            self.files = {
                primary_virtual: b"pdf",
                conversion_virtual: b"generated",
            }
            self.unavailable = True

        def remove_file(self, path: str) -> None:
            if path == primary_virtual:
                self.files.pop(path, None)
                return
            if self.unavailable:
                self.files.pop(path, None)
                raise OSError("conversion deletion unconfirmed")
            self.files.pop(path, None)

        def update_file(self, _path: str, _content: bytes) -> None:
            raise OSError("compensation unavailable")

    class Provider:
        def __init__(self, sandbox) -> None:
            self.sandbox = sandbox

        def get(self, sandbox_id: str):
            assert sandbox_id == "sandbox-1"
            return self.sandbox

    uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    primary = uploads / "report.pdf"
    primary.write_bytes(b"pdf")
    conversion = conversion_path_for_upload(primary)
    conversion.parent.mkdir()
    conversion.write_bytes(b"generated")
    sandbox = RestartableSandbox()
    deletion_hook = _deletion_hook_for_sandbox(
        sandbox,
        sandbox_id="sandbox-1",
        thread_id="thread-1",
        user_id="alice",
    )

    with pytest.raises(RemoteDeletionCommitRequiredError):
        delete_file_safe(uploads, primary.name, delete_remote_copy=deletion_hook)

    assert not primary.exists()
    assert not conversion.exists()
    journals = list(conversion.parent.glob(".upload-delete-*.part/.remote-delete.json"))
    assert len(journals) == 1
    assert cleanup_stale_upload_staging_files(tmp_path) == 0

    sandbox.unavailable = False
    provider = Provider(sandbox)
    assert (
        reconcile_pending_remote_deletions(
            sandbox_provider_factory=lambda: provider,
            base_dir=tmp_path,
        )
        == 1
    )
    assert sandbox.files == {}
    assert cleanup_stale_upload_staging_files(tmp_path) == 1
    assert not list(conversion.parent.glob(".upload-delete-*.part"))


def test_prepared_remote_journal_without_commit_marker_restores_host(tmp_path):
    import deerflow.uploads.manager as upload_manager_module

    uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    primary = uploads / "report.pdf"
    primary.write_bytes(b"pdf")
    conversion = conversion_path_for_upload(primary)
    conversion.parent.mkdir()
    conversion.write_bytes(b"generated")
    identity = upload_manager_module.UploadIdentity.from_path(primary)
    staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
        uploads,
        primary,
        identity,
        recover_on_crash=True,
        conversion_path=conversion,
    )
    hook = _deletion_hook_for_sandbox(
        object(),
        sandbox_id="sandbox-1",
        thread_id="thread-1",
        user_id="alice",
    )
    hook.prepare(primary.name, staged_path, upload_manager_module._staged_conversion_path(staged_path))

    assert (
        reconcile_pending_remote_deletions(
            sandbox_provider_factory=lambda: (_ for _ in ()).throw(AssertionError("live journal must be skipped")),
            base_dir=tmp_path,
        )
        == 0
    )
    stage_lease.release()
    assert (
        reconcile_pending_remote_deletions(
            sandbox_provider_factory=lambda: (_ for _ in ()).throw(AssertionError("uncommitted journal must be skipped")),
            base_dir=tmp_path,
        )
        == 0
    )

    assert cleanup_stale_upload_staging_files(tmp_path) == 1
    assert primary.read_bytes() == b"pdf"
    assert conversion.read_bytes() == b"generated"
    assert not list(conversion.parent.glob(".upload-delete-*.part"))


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
