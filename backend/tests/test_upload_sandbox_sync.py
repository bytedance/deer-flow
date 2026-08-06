import asyncio
import json
import os
import stat
from unittest.mock import patch

import pytest

from deerflow.sandbox.sandbox_provider import SandboxReconciliationResult
from deerflow.uploads.layout import conversion_path_for_upload, conversion_virtual_path, upload_virtual_path
from deerflow.uploads.manager import (
    RemoteDeletionCommitRequiredError,
    cleanup_stale_upload_staging_files,
    delete_file_safe,
    publish_upload_bytes,
)
from deerflow.uploads.sandbox_sync import (
    _deletion_hook_for_sandbox as _raw_deletion_hook_for_sandbox,
)
from deerflow.uploads.sandbox_sync import (
    _sandbox_provider_reconciliation_key,
    make_upload_paths_available,
    make_upload_paths_available_async,
    prepare_upload_deletion,
    prepare_upload_deletion_async,
    reconcile_pending_remote_deletions,
)


def _deletion_hook_for_sandbox(sandbox, **kwargs):
    if kwargs.get("sandbox_id") is not None:
        kwargs.setdefault("backend_namespace", "tests.backend")
        kwargs.setdefault("incarnation_id", "tests.incarnation")
    return _raw_deletion_hook_for_sandbox(sandbox, **kwargs)


class _ExactProviderMixin:
    def reconnect_sandbox_for_reconciliation(
        self,
        sandbox_id,
        *,
        thread_id,
        user_id,
        identity,
    ):
        del thread_id, user_id
        assert identity.backend_namespace == "tests.backend"
        assert identity.incarnation_id == "tests.incarnation"
        sandbox = self.get(sandbox_id)
        return SandboxReconciliationResult.found(sandbox) if sandbox is not None else SandboxReconciliationResult.unknown()


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

    class Provider(_ExactProviderMixin):
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
        provider_key=_sandbox_provider_reconciliation_key(Provider(sandbox)),
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


@pytest.mark.parametrize("unlink_first", [False, True], ids=["unlink", "directory-fsync"])
def test_remote_delete_finalize_failure_never_restores_deleted_host_generation(tmp_path, unlink_first):
    import deerflow.uploads.sandbox_sync as sandbox_sync_module

    primary_virtual = upload_virtual_path("report.pdf")
    conversion_virtual = conversion_virtual_path("report.pdf")

    class Sandbox:
        def __init__(self) -> None:
            self.files = {
                primary_virtual: b"pdf",
                conversion_virtual: b"generated",
            }

        def remove_file(self, path: str) -> None:
            self.files.pop(path, None)

    uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    primary = uploads / "report.pdf"
    primary.write_bytes(b"pdf")
    conversion = conversion_path_for_upload(primary)
    conversion.parent.mkdir()
    conversion.write_bytes(b"generated")
    sandbox = Sandbox()
    deletion_hook = _deletion_hook_for_sandbox(
        sandbox,
        sandbox_id="sandbox-1",
        thread_id="thread-1",
        user_id="alice",
        provider_key="tests.Provider",
    )
    real_unlink = sandbox_sync_module._unlink_journal_durably

    def fail_finalize(journal_path):
        if unlink_first:
            real_unlink(journal_path)
        raise OSError("remote deletion journal finalize failed")

    with patch.object(sandbox_sync_module, "_unlink_journal_durably", side_effect=fail_finalize):
        with pytest.raises(OSError, match="journal finalize failed"):
            delete_file_safe(uploads, primary.name, delete_remote_copy=deletion_hook)

    assert sandbox.files == {}
    assert not primary.exists()
    assert not conversion.exists()
    transactions = list(conversion.parent.glob(".upload-delete-*.part"))
    if unlink_first:
        assert transactions == []
    else:
        assert len(transactions) == 1
        assert (transactions[0] / ".remote-delete.json").is_file()
        assert (transactions[0] / "primary" / primary.name).read_bytes() == b"pdf"
        assert cleanup_stale_upload_staging_files(tmp_path) == 0


def test_directory_fsync_failure_restores_journal_and_reserves_old_basename(tmp_path):
    import deerflow.uploads.manager as upload_manager_module
    import deerflow.uploads.sandbox_sync as sandbox_sync_module

    primary_virtual = upload_virtual_path("report.pdf")
    conversion_virtual = conversion_virtual_path("report.pdf")

    class Sandbox:
        def __init__(self) -> None:
            self.files = {
                primary_virtual: b"old primary",
                conversion_virtual: b"old conversion",
            }

        def remove_file(self, path: str) -> None:
            self.files.pop(path, None)

    class Provider(_ExactProviderMixin):
        def __init__(self, sandbox) -> None:
            self.sandbox = sandbox

        def get(self, sandbox_id: str):
            assert sandbox_id == "sandbox-1"
            return self.sandbox

    uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    primary = uploads / "report.pdf"
    primary.write_bytes(b"old primary")
    conversion = conversion_path_for_upload(primary)
    conversion.parent.mkdir()
    conversion.write_bytes(b"old conversion")
    identity = upload_manager_module.UploadIdentity.from_path(primary)
    staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
        uploads,
        primary,
        identity,
        recover_on_crash=True,
        conversion_path=conversion,
    )
    sandbox = Sandbox()
    provider = Provider(sandbox)
    hook = _deletion_hook_for_sandbox(
        sandbox,
        sandbox_id="sandbox-1",
        thread_id="thread-1",
        user_id="alice",
        provider_key=_sandbox_provider_reconciliation_key(provider),
    )
    hook.prepare(
        primary.name,
        staged_path,
        upload_manager_module._staged_conversion_path(staged_path),
    )
    upload_manager_module._mark_staged_deletion_committed(staged_path)
    stage_lease.release()
    journal_path = next(conversion.parent.glob(".upload-delete-*.part/.remote-delete.json"))
    journal_payload = journal_path.read_bytes()
    real_fsync = sandbox_sync_module.os.fsync
    fsync_calls = 0

    def fail_first_directory_fsync(descriptor):
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 1:
            raise OSError("directory fsync failed")
        return real_fsync(descriptor)

    with patch.object(sandbox_sync_module.os, "fsync", side_effect=fail_first_directory_fsync):
        with pytest.raises(OSError, match="directory fsync failed"):
            sandbox_sync_module._unlink_journal_durably(journal_path)

    assert journal_path.read_bytes() == journal_payload
    replacement = publish_upload_bytes(uploads, "report.pdf", b"new primary")
    assert replacement.name == "report_1.pdf"

    assert (
        reconcile_pending_remote_deletions(
            sandbox_provider_factory=lambda: provider,
            base_dir=tmp_path,
        )
        == 1
    )
    assert sandbox.files == {}
    assert replacement.read_bytes() == b"new primary"
    assert cleanup_stale_upload_staging_files(tmp_path) == 1


def test_failed_journal_restore_keeps_in_memory_name_reservation(tmp_path):
    import deerflow.uploads.manager as upload_manager_module
    import deerflow.uploads.sandbox_sync as sandbox_sync_module

    uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    primary = uploads / "report.pdf"
    primary.write_bytes(b"old primary")
    conversion = conversion_path_for_upload(primary)
    conversion.parent.mkdir()
    conversion.write_bytes(b"old conversion")
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
        provider_key="tests.Provider",
    )
    hook.prepare(
        primary.name,
        staged_path,
        upload_manager_module._staged_conversion_path(staged_path),
    )
    upload_manager_module._mark_staged_deletion_committed(staged_path)
    stage_lease.release()
    journal_path = next(conversion.parent.glob(".upload-delete-*.part/.remote-delete.json"))
    real_open = sandbox_sync_module.os.open
    real_fsync = sandbox_sync_module.os.fsync
    fsync_calls = 0

    def fail_directory_fsync(descriptor):
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 1:
            raise OSError("directory fsync failed")
        return real_fsync(descriptor)

    def fail_journal_recreation(path, flags, mode=0o777):
        if os.path.abspath(path) == os.path.abspath(journal_path) and flags & os.O_CREAT:
            raise OSError("journal recreation failed")
        return real_open(path, flags, mode)

    try:
        with (
            patch.object(sandbox_sync_module.os, "fsync", side_effect=fail_directory_fsync),
            patch.object(sandbox_sync_module.os, "open", side_effect=fail_journal_recreation),
        ):
            with pytest.raises(OSError, match="directory fsync failed"):
                sandbox_sync_module._unlink_journal_durably(journal_path)

        assert not journal_path.exists()
        sandbox_sync_module._unlink_journal_durably(journal_path)
        assert cleanup_stale_upload_staging_files(tmp_path) == 0
        replacement = publish_upload_bytes(uploads, "report.pdf", b"new primary")
        assert replacement.name == "report_1.pdf"
    finally:
        upload_manager_module._release_uncertain_remote_journal_reservation(journal_path)

    assert cleanup_stale_upload_staging_files(tmp_path) == 1


@pytest.mark.parametrize("unlink_first", [False, True], ids=["unlink", "directory-fsync"])
def test_compensated_remote_delete_restores_host_even_when_journal_abort_fails(tmp_path, unlink_first):
    import deerflow.uploads.sandbox_sync as sandbox_sync_module

    primary_virtual = upload_virtual_path("report.pdf")
    conversion_virtual = conversion_virtual_path("report.pdf")

    class Sandbox:
        def __init__(self) -> None:
            self.files = {
                primary_virtual: b"pdf",
                conversion_virtual: b"generated",
            }
            self.failed = False

        def remove_file(self, path: str) -> None:
            self.files.pop(path, None)
            if path == conversion_virtual and not self.failed:
                self.failed = True
                raise OSError("conversion deletion failed")

        def update_file(self, path: str, content: bytes) -> None:
            self.files[path] = content

    uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    primary = uploads / "report.pdf"
    primary.write_bytes(b"pdf")
    conversion = conversion_path_for_upload(primary)
    conversion.parent.mkdir()
    conversion.write_bytes(b"generated")
    sandbox = Sandbox()
    deletion_hook = _deletion_hook_for_sandbox(
        sandbox,
        sandbox_id="sandbox-1",
        thread_id="thread-1",
        user_id="alice",
        provider_key="tests.Provider",
    )
    real_unlink = sandbox_sync_module._unlink_journal_durably

    def fail_abort(journal_path):
        if unlink_first:
            real_unlink(journal_path)
        raise OSError("remote deletion journal abort failed")

    with patch.object(sandbox_sync_module, "_unlink_journal_durably", side_effect=fail_abort):
        with pytest.raises(OSError, match="journal abort failed"):
            delete_file_safe(uploads, primary.name, delete_remote_copy=deletion_hook)

    assert sandbox.files == {
        primary_virtual: b"pdf",
        conversion_virtual: b"generated",
    }
    assert primary.read_bytes() == b"pdf"
    assert conversion.read_bytes() == b"generated"


def test_pending_remote_deletion_reserves_name_until_exact_remote_generation_is_gone(tmp_path):
    old_primary_virtual = upload_virtual_path("report.pdf")
    old_conversion_virtual = conversion_virtual_path("report.pdf")

    class RestartableSandbox:
        def __init__(self) -> None:
            self.files = {
                old_primary_virtual: b"old pdf",
                old_conversion_virtual: b"old generated",
            }
            self.unavailable = True

        def remove_file(self, path: str) -> None:
            self.files.pop(path, None)
            if self.unavailable and path == old_conversion_virtual:
                raise OSError("old conversion deletion unconfirmed")

        def update_file(self, _path: str, _content: bytes) -> None:
            raise OSError("compensation unavailable")

    class Provider(_ExactProviderMixin):
        uses_thread_data_mounts = False

        def __init__(self, sandbox) -> None:
            self.sandbox = sandbox

        def get(self, sandbox_id: str):
            assert sandbox_id == "sandbox-1"
            return self.sandbox

    uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    primary = uploads / "report.pdf"
    primary.write_bytes(b"old pdf")
    conversion = conversion_path_for_upload(primary)
    conversion.parent.mkdir()
    conversion.write_bytes(b"old generated")
    sandbox = RestartableSandbox()
    deletion_hook = _deletion_hook_for_sandbox(
        sandbox,
        sandbox_id="sandbox-1",
        thread_id="thread-1",
        user_id="alice",
        provider_key=_sandbox_provider_reconciliation_key(Provider(sandbox)),
    )

    with pytest.raises(RemoteDeletionCommitRequiredError):
        delete_file_safe(uploads, primary.name, delete_remote_copy=deletion_hook)

    replacement = publish_upload_bytes(uploads, "report.pdf", b"new pdf")
    assert replacement.name == "report_1.pdf"
    new_primary_virtual = upload_virtual_path(replacement.name)
    new_conversion_virtual = conversion_virtual_path(replacement.name)
    sandbox.files[new_primary_virtual] = b"new pdf"
    sandbox.files[new_conversion_virtual] = b"new generated"

    sandbox.unavailable = False
    assert (
        reconcile_pending_remote_deletions(
            sandbox_provider_factory=lambda: Provider(sandbox),
            base_dir=tmp_path,
        )
        == 1
    )
    assert sandbox.files == {
        new_primary_virtual: b"new pdf",
        new_conversion_virtual: b"new generated",
    }
    assert cleanup_stale_upload_staging_files(tmp_path) == 1
    assert not list(conversion.parent.glob(".upload-delete-*.part"))


def test_reconciliation_never_redirects_old_journal_to_new_sandbox(tmp_path):
    primary_virtual = upload_virtual_path("report.pdf")
    conversion_virtual = conversion_virtual_path("report.pdf")

    class OldSandbox:
        def remove_file(self, path: str) -> None:
            if path == conversion_virtual:
                raise OSError("old sandbox unavailable")

        def update_file(self, _path: str, _content: bytes) -> None:
            raise OSError("old sandbox compensation unavailable")

    class NewSandbox:
        def __init__(self) -> None:
            self.files = {
                primary_virtual: b"new primary",
                conversion_virtual: b"new conversion",
            }

        def remove_file(self, path: str) -> None:
            self.files.pop(path, None)

    class RollingProvider(_ExactProviderMixin):
        uses_thread_data_mounts = False

        def __init__(self, new_sandbox) -> None:
            self.new_sandbox = new_sandbox

        def get(self, sandbox_id: str):
            if sandbox_id == "sandbox-old":
                return None
            assert sandbox_id == "sandbox-new"
            return self.new_sandbox

        def acquire(self, thread_id: str, *, user_id: str | None = None) -> str:
            assert thread_id == "thread-1"
            assert user_id == "alice"
            return "sandbox-new"

    uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    primary = uploads / "report.pdf"
    primary.write_bytes(b"old primary")
    conversion = conversion_path_for_upload(primary)
    conversion.parent.mkdir()
    conversion.write_bytes(b"old conversion")
    provider = RollingProvider(new_sandbox=None)
    deletion_hook = _deletion_hook_for_sandbox(
        OldSandbox(),
        sandbox_id="sandbox-old",
        thread_id="thread-1",
        user_id="alice",
        provider_key=_sandbox_provider_reconciliation_key(provider),
    )
    with pytest.raises(RemoteDeletionCommitRequiredError):
        delete_file_safe(uploads, primary.name, delete_remote_copy=deletion_hook)

    new_sandbox = NewSandbox()
    provider.new_sandbox = new_sandbox
    assert (
        reconcile_pending_remote_deletions(
            sandbox_provider_factory=lambda: provider,
            base_dir=tmp_path,
        )
        == 0
    )
    assert new_sandbox.files == {
        primary_virtual: b"new primary",
        conversion_virtual: b"new conversion",
    }
    assert len(list(conversion.parent.glob(".upload-delete-*.part/.remote-delete.json"))) == 1
    assert cleanup_stale_upload_staging_files(tmp_path) == 0


def test_reconciliation_never_crosses_provider_boundary_when_raw_id_matches(tmp_path):
    primary_virtual = upload_virtual_path("report.pdf")
    conversion_virtual = conversion_virtual_path("report.pdf")

    class OldProvider:
        pass

    class OldSandbox:
        def remove_file(self, path: str) -> None:
            if path == conversion_virtual:
                raise OSError("old provider unavailable")

        def update_file(self, _path: str, _content: bytes) -> None:
            raise OSError("old provider compensation unavailable")

    class NewSandbox:
        def __init__(self) -> None:
            self.files = {
                primary_virtual: b"new primary",
                conversion_virtual: b"new conversion",
            }

        def remove_file(self, path: str) -> None:
            self.files.pop(path, None)

    class NewProvider:
        uses_thread_data_mounts = False

        def __init__(self, sandbox) -> None:
            self.sandbox = sandbox

        def get(self, sandbox_id: str):
            assert sandbox_id == "same-id"
            return None

        def acquire(self, thread_id: str, *, user_id: str | None = None) -> str:
            assert (thread_id, user_id) == ("thread-1", "alice")
            return "same-id"

    uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    primary = uploads / "report.pdf"
    primary.write_bytes(b"old primary")
    conversion = conversion_path_for_upload(primary)
    conversion.parent.mkdir()
    conversion.write_bytes(b"old conversion")
    deletion_hook = _deletion_hook_for_sandbox(
        OldSandbox(),
        sandbox_id="same-id",
        thread_id="thread-1",
        user_id="alice",
        provider_key=_sandbox_provider_reconciliation_key(OldProvider()),
    )
    with pytest.raises(RemoteDeletionCommitRequiredError):
        delete_file_safe(uploads, primary.name, delete_remote_copy=deletion_hook)

    new_sandbox = NewSandbox()
    assert (
        reconcile_pending_remote_deletions(
            sandbox_provider_factory=lambda: NewProvider(new_sandbox),
            base_dir=tmp_path,
        )
        == 0
    )
    assert new_sandbox.files == {
        primary_virtual: b"new primary",
        conversion_virtual: b"new conversion",
    }
    assert len(list(conversion.parent.glob(".upload-delete-*.part/.remote-delete.json"))) == 1


def test_reconciliation_finalizes_when_provider_confirms_exact_sandbox_absent(tmp_path):
    conversion_virtual = conversion_virtual_path("report.pdf")

    class Provider(_ExactProviderMixin):
        def reconnect_sandbox_for_reconciliation(
            self,
            sandbox_id: str,
            *,
            thread_id: str,
            user_id: str | None,
            identity,
        ):
            assert identity.backend_namespace == "tests.backend"
            assert identity.incarnation_id == "tests.incarnation"
            assert (sandbox_id, thread_id, user_id) == ("sandbox-old", "thread-1", "alice")
            from deerflow.sandbox.sandbox_provider import SandboxReconciliationResult

            return SandboxReconciliationResult.absent()

    class OldSandbox:
        def remove_file(self, path: str) -> None:
            if path == conversion_virtual:
                raise OSError("old sandbox unavailable")

        def update_file(self, _path: str, _content: bytes) -> None:
            raise OSError("old sandbox compensation unavailable")

    provider = Provider()
    uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    primary = uploads / "report.pdf"
    primary.write_bytes(b"old primary")
    conversion = conversion_path_for_upload(primary)
    conversion.parent.mkdir()
    conversion.write_bytes(b"old conversion")
    deletion_hook = _deletion_hook_for_sandbox(
        OldSandbox(),
        sandbox_id="sandbox-old",
        thread_id="thread-1",
        user_id="alice",
        provider_key=_sandbox_provider_reconciliation_key(provider),
    )
    with pytest.raises(RemoteDeletionCommitRequiredError):
        delete_file_safe(uploads, primary.name, delete_remote_copy=deletion_hook)

    assert (
        reconcile_pending_remote_deletions(
            sandbox_provider_factory=lambda: provider,
            base_dir=tmp_path,
        )
        == 1
    )
    assert cleanup_stale_upload_staging_files(tmp_path) == 1
    assert not list(conversion.parent.glob(".upload-delete-*.part"))


def test_reconciliation_rejects_journal_that_does_not_match_retained_generation(tmp_path):
    report_virtual = upload_virtual_path("report.pdf")
    report_conversion_virtual = conversion_virtual_path("report.pdf")
    other_virtual = upload_virtual_path("other.pdf")
    other_conversion_virtual = conversion_virtual_path("other.pdf")

    class Sandbox:
        def __init__(self) -> None:
            self.files = {
                report_virtual: b"report",
                report_conversion_virtual: b"report conversion",
                other_virtual: b"other",
                other_conversion_virtual: b"other conversion",
            }
            self.unavailable = True

        def remove_file(self, path: str) -> None:
            if self.unavailable and path == report_conversion_virtual:
                raise OSError("report conversion deletion unconfirmed")
            self.files.pop(path, None)

        def update_file(self, _path: str, _content: bytes) -> None:
            raise OSError("compensation unavailable")

    class Provider(_ExactProviderMixin):
        uses_thread_data_mounts = False

        def __init__(self, sandbox) -> None:
            self.sandbox = sandbox

        def get(self, sandbox_id: str):
            assert sandbox_id == "sandbox-1"
            return self.sandbox

    uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    primary = uploads / "report.pdf"
    primary.write_bytes(b"report")
    conversion = conversion_path_for_upload(primary)
    conversion.parent.mkdir()
    conversion.write_bytes(b"report conversion")
    sandbox = Sandbox()
    deletion_hook = _deletion_hook_for_sandbox(
        sandbox,
        sandbox_id="sandbox-1",
        thread_id="thread-1",
        user_id="alice",
        provider_key=_sandbox_provider_reconciliation_key(Provider(sandbox)),
    )
    with pytest.raises(RemoteDeletionCommitRequiredError):
        delete_file_safe(uploads, primary.name, delete_remote_copy=deletion_hook)

    journal_path = next(conversion.parent.glob(".upload-delete-*.part/.remote-delete.json"))
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal["filename"] = "other.pdf"
    journal["virtual_paths"] = [other_virtual, other_conversion_virtual]
    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    sandbox.unavailable = False

    assert (
        reconcile_pending_remote_deletions(
            sandbox_provider_factory=lambda: Provider(sandbox),
            base_dir=tmp_path,
        )
        == 0
    )
    assert sandbox.files[other_virtual] == b"other"
    assert sandbox.files[other_conversion_virtual] == b"other conversion"
    assert journal_path.is_file()


@pytest.mark.skipif(os.name == "nt", reason="POSIX legacy filenames are not representable on Windows")
@pytest.mark.parametrize("filename", ["CON", "report?.pdf", "trailing ", r"report\draft.pdf"])
def test_reconciliation_accepts_exact_legacy_posix_filename(tmp_path, filename):
    primary_virtual = upload_virtual_path(filename)
    conversion_virtual = conversion_virtual_path(filename)

    class RestartableSandbox:
        def __init__(self) -> None:
            self.files = {
                primary_virtual: b"legacy primary",
                conversion_virtual: b"legacy conversion",
            }
            self.unavailable = True

        def remove_file(self, path: str) -> None:
            self.files.pop(path, None)
            if self.unavailable and path == conversion_virtual:
                raise OSError("legacy conversion deletion unconfirmed")

        def update_file(self, _path: str, _content: bytes) -> None:
            raise OSError("legacy compensation unavailable")

    class Provider(_ExactProviderMixin):
        uses_thread_data_mounts = False

        def __init__(self, sandbox) -> None:
            self.sandbox = sandbox

        def get(self, sandbox_id: str):
            assert sandbox_id == "sandbox-1"
            return self.sandbox

    uploads = tmp_path / "users" / "alice" / "threads" / "thread-1" / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    primary = uploads / filename
    primary.write_bytes(b"legacy primary")
    conversion = conversion_path_for_upload(primary)
    conversion.parent.mkdir()
    conversion.write_bytes(b"legacy conversion")
    sandbox = RestartableSandbox()
    deletion_hook = _deletion_hook_for_sandbox(
        sandbox,
        sandbox_id="sandbox-1",
        thread_id="thread-1",
        user_id="alice",
        provider_key=_sandbox_provider_reconciliation_key(Provider(sandbox)),
    )

    with pytest.raises(RemoteDeletionCommitRequiredError):
        delete_file_safe(uploads, filename, delete_remote_copy=deletion_hook)

    sandbox.unavailable = False
    assert (
        reconcile_pending_remote_deletions(
            sandbox_provider_factory=lambda: Provider(sandbox),
            base_dir=tmp_path,
        )
        == 1
    )
    assert sandbox.files == {}
    assert cleanup_stale_upload_staging_files(tmp_path) == 1


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
        provider_key="tests.Provider",
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


def test_reconciliation_finishes_crash_after_first_remote_delete(tmp_path):
    import deerflow.uploads.manager as upload_manager_module

    primary_virtual = upload_virtual_path("report.pdf")
    conversion_virtual = conversion_virtual_path("report.pdf")

    class Sandbox:
        def __init__(self) -> None:
            self.files = {
                primary_virtual: b"pdf",
                conversion_virtual: b"generated",
            }

        def remove_file(self, path: str) -> None:
            self.files.pop(path, None)

    class Provider(_ExactProviderMixin):
        uses_thread_data_mounts = False

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
    identity = upload_manager_module.UploadIdentity.from_path(primary)
    staged_path, stage_lease = upload_manager_module._stage_primary_deletion(
        uploads,
        primary,
        identity,
        recover_on_crash=True,
        conversion_path=conversion,
    )
    sandbox = Sandbox()
    hook = _deletion_hook_for_sandbox(
        sandbox,
        sandbox_id="sandbox-1",
        thread_id="thread-1",
        user_id="alice",
        provider_key=_sandbox_provider_reconciliation_key(Provider(sandbox)),
    )
    hook.prepare(
        primary.name,
        staged_path,
        upload_manager_module._staged_conversion_path(staged_path),
    )
    upload_manager_module._mark_staged_deletion_committed(staged_path)
    sandbox.remove_file(primary_virtual)
    stage_lease.release()

    assert cleanup_stale_upload_staging_files(tmp_path) == 0
    assert (
        reconcile_pending_remote_deletions(
            sandbox_provider_factory=lambda: Provider(sandbox),
            base_dir=tmp_path,
        )
        == 1
    )
    assert sandbox.files == {}
    assert cleanup_stale_upload_staging_files(tmp_path) == 1
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


def test_prepare_deletion_fails_before_mutation_without_restart_safe_identity():
    class Sandbox:
        def __init__(self) -> None:
            self.remove_calls: list[str] = []
            self.update_calls: list[str] = []

        def remove_file(self, path: str) -> None:
            self.remove_calls.append(path)

        def update_file(self, path: str, _content: bytes) -> None:
            self.update_calls.append(path)

    class Provider:
        uses_thread_data_mounts = False

        def __init__(self) -> None:
            self.sandbox = Sandbox()

        def refresh_thread_data_mount_capabilities(self) -> bool:
            return False

        def acquire(self, thread_id: str, *, user_id: str | None = None) -> str:
            assert (thread_id, user_id) == ("thread-1", "alice")
            return "sandbox-1"

        def get(self, sandbox_id: str):
            assert sandbox_id == "sandbox-1"
            return self.sandbox

    provider = Provider()

    with pytest.raises(RuntimeError, match="restart-safe backend and incarnation identity"):
        prepare_upload_deletion(provider, "thread-1", user_id="alice")

    assert provider.sandbox.remove_calls == []
    assert provider.sandbox.update_calls == []


def test_prepare_deletion_reconciles_and_cleans_before_mount_decision():
    import deerflow.uploads.sandbox_sync as sandbox_sync_module

    provider = _ProviderThatBecomesMounted()
    provider.uses_thread_data_mounts = True
    events: list[str] = []

    with (
        patch.object(
            sandbox_sync_module,
            "reconcile_pending_remote_deletions",
            side_effect=lambda **_kwargs: events.append("reconcile") or 1,
        ),
        patch.object(
            sandbox_sync_module,
            "cleanup_stale_upload_staging_files",
            side_effect=lambda: events.append("cleanup") or 1,
        ),
    ):
        assert prepare_upload_deletion(provider, "thread-1", user_id="alice") is None

    assert events == ["reconcile", "cleanup"]


def test_prepare_deletion_async_rechecks_mount_mode_after_acquire():
    provider = _ProviderThatBecomesMounted()

    assert asyncio.run(prepare_upload_deletion_async(provider, "thread-1", user_id="alice")) is None
    assert provider.get_calls == 0


def test_prepare_deletion_async_reconciles_and_cleans_before_mount_decision():
    import deerflow.uploads.sandbox_sync as sandbox_sync_module

    provider = _ProviderThatBecomesMounted()
    provider.uses_thread_data_mounts = True
    events: list[str] = []

    with (
        patch.object(
            sandbox_sync_module,
            "reconcile_pending_remote_deletions",
            side_effect=lambda **_kwargs: events.append("reconcile") or 1,
        ),
        patch.object(
            sandbox_sync_module,
            "cleanup_stale_upload_staging_files",
            side_effect=lambda: events.append("cleanup") or 1,
        ),
    ):
        assert asyncio.run(prepare_upload_deletion_async(provider, "thread-1", user_id="alice")) is None

    assert events == ["reconcile", "cleanup"]


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
