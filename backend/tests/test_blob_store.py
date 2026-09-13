"""Tests for the content-addressed blob store contract and the local_fs backend.

Scope: the seam only. No producer is migrated yet, so these tests never touch
``viewed_images`` or ``ToolOutputBudgetMiddleware`` -- that is the follow-up
wiring PR for issue #4189 item 2.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pytest
from pydantic import ValidationError

from deerflow.config import blob_storage_config as bsc
from deerflow.storage import (
    BlobNotConfiguredError,
    BlobNotFoundError,
    BlobReadError,
    BlobRef,
    BlobStore,
    BlobStoreError,
    BlobWriteError,
    get_blob_store,
    get_blob_store_if_enabled,
    is_valid_blob_kind,
    reset_blob_store,
    validate_blob_kind,
)
from deerflow.storage import contract as contract_module
from deerflow.storage.backends.local_fs import LocalFsBlobStore


@pytest.fixture(autouse=True)
def _isolated_config(monkeypatch):
    """Give every test a pristine config + a fresh singleton."""
    bsc.set_blob_storage_config(bsc.BlobStorageConfig())
    reset_blob_store()
    yield
    bsc.set_blob_storage_config(bsc.BlobStorageConfig())
    reset_blob_store()


@pytest.fixture
def store(tmp_path: Path) -> LocalFsBlobStore:
    return LocalFsBlobStore.from_config({"root": str(tmp_path / "blobs")})


# ---------------------------------------------------------------------------
# BlobRef
# ---------------------------------------------------------------------------


def test_blob_ref_validates_digest_shape():
    with pytest.raises(ValidationError):
        BlobRef(sha256="not-a-digest", size=1, kind="tool-output")
    with pytest.raises(ValidationError):
        BlobRef(sha256="z" * 64, size=1, kind="tool-output")  # right length, not hex
    with pytest.raises(ValidationError):
        BlobRef(sha256="a" * 63, size=1, kind="tool-output")  # too short
    ref = BlobRef(sha256=hashlib.sha256(b"x").hexdigest(), size=1, kind="tool-output")
    assert ref.sha256 == hashlib.sha256(b"x").hexdigest()


def test_blob_ref_kind_is_path_safe():
    for bad in ("../etc", "a/b", "Aupper", "", "-lead", "trailing-", "has space", "x" * 65):
        with pytest.raises(ValidationError):
            BlobRef(sha256=hashlib.sha256(b"x").hexdigest(), size=1, kind=bad)
    for good in ("viewed-image", "tool-output", "a", "0", "a" * 64):
        assert is_valid_blob_kind(good)


def test_blob_ref_matches_detects_corruption():
    data = b"payload"
    ref = BlobRef(sha256=hashlib.sha256(data).hexdigest(), size=len(data), kind="tool-output")
    assert ref.matches(data)
    assert not ref.matches(b"payload!")
    assert not ref.matches(b"")


# ---------------------------------------------------------------------------
# local_fs backend semantics
# ---------------------------------------------------------------------------


def test_put_then_get_roundtrip(store: LocalFsBlobStore):
    data = "外部化内容 🚀".encode()
    ref = store.put_bytes(data, kind="tool-output", content_type="text/plain", thread_id="t-1")
    assert ref.size == len(data)
    assert ref.sha256 == hashlib.sha256(data).hexdigest()
    assert ref.content_type == "text/plain"
    assert store.get_bytes(ref) == data


def test_put_is_idempotent_and_deduplicates(store: LocalFsBlobStore, tmp_path: Path):
    data = b"same bytes"
    first = store.put_bytes(data, kind="tool-output")
    before = sorted(p.name for p in (tmp_path / "blobs").rglob("*") if p.is_file())
    second = store.put_bytes(data, kind="tool-output", thread_id="t-9")
    after = sorted(p.name for p in (tmp_path / "blobs").rglob("*") if p.is_file())

    assert first == second
    assert before == after, "a re-put must not create new files"


def test_dedup_records_only_the_first_writer_as_advisory_provenance(store: LocalFsBlobStore):
    """Identical content is *shared*, so the sidecar cannot be a reference count.

    The GC contract in docs/blob-storage.md says a blob may only be unlinked
    after liveness is confirmed from the durable references; this test pins the
    sidecar semantics that make that rule necessary, so nobody later "fixes"
    dedup by trusting writer_thread_id.
    """
    data = b"the same uploaded image"
    first = store.put_bytes(data, kind="viewed-image", thread_id="thread-a")
    second = store.put_bytes(data, kind="viewed-image", thread_id="thread-b")

    assert first == second, "one address for one content"
    data_path = next((store._root / "viewed-image").rglob(first.sha256))
    sidecar = next((store._root / "viewed-image").rglob(f"{first.sha256}.json"))
    assert data_path.is_file()
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["writer_thread_id"] == "thread-a"
    assert "thread-b" not in json.dumps(payload), "dedup keeps the first writer only — never a refcount"


def test_kind_rejection_quotes_the_enforced_grammar():
    """One validator, one message: the pattern a producer is shown must be the
    pattern that is enforced (it was not, before this was centralised)."""
    assert validate_blob_kind("tool-output") == "tool-output"
    for bad in ("trailing-", "a--", "-lead", "Aupper", "a/b", "", "x" * 65):
        with pytest.raises(ValueError) as caught:
            validate_blob_kind(bad)
        message = str(caught.value)
        assert "^[a-z0-9]([a-z0-9-]*[a-z0-9])?$" in message, message
        assert "1-64 chars" in message, message
        assert "no leading or trailing hyphen" in message, message
    assert validate_blob_kind is contract_module.validate_blob_kind


def test_same_content_different_kind_lands_separately(store: LocalFsBlobStore):
    ref_a = store.put_bytes(b"shared", kind="tool-output")
    ref_b = store.put_bytes(b"shared", kind="viewed-image")
    assert ref_a.sha256 == ref_b.sha256
    assert ref_a != ref_b
    assert store.exists(ref_a) and store.exists(ref_b)


def test_get_missing_blob_raises_not_found(store: LocalFsBlobStore):
    ref = BlobRef(sha256=hashlib.sha256(b"absent").hexdigest(), size=6, kind="tool-output")
    with pytest.raises(BlobNotFoundError):
        store.get_bytes(ref)
    assert store.exists(ref) is False


def test_get_detects_content_mismatch(store: LocalFsBlobStore):
    data = b"intact"
    ref = store.put_bytes(data, kind="tool-output")
    # Corrupt the stored bytes behind the store's back.
    data_path = next((store._root / "tool-output").rglob(ref.sha256))
    data_path.write_bytes(b"tampered")
    with pytest.raises(BlobReadError):
        store.get_bytes(ref)


def test_delete_is_idempotent(store: LocalFsBlobStore):
    ref = store.put_bytes(b"doomed", kind="tool-output")
    store.delete(ref)
    assert store.exists(ref) is False
    store.delete(ref)  # absent blob: not an error
    with pytest.raises(BlobNotFoundError):
        store.get_bytes(ref)


def test_delete_failure_raises_the_neutral_base_error(store: LocalFsBlobStore, monkeypatch: pytest.MonkeyPatch):
    """A failed unlink is not a read failure.

    The exception family is public API from the first release, so callers that
    match on BlobReadError must not receive delete failures they cannot
    interpret.
    """
    ref = store.put_bytes(b"cannot unlink", kind="tool-output")

    def _boom(self, *args, **kwargs):
        raise OSError("device busy")

    monkeypatch.setattr(Path, "unlink", _boom)
    with pytest.raises(BlobStoreError) as caught:
        store.delete(ref)
    assert not isinstance(caught.value, BlobReadError)
    assert "Failed to delete blob" in str(caught.value)


def test_delete_unsupported_on_contract_default(tmp_path: Path):
    class Minimal(BlobStore):
        def from_config(cls, backend_config):
            raise NotImplementedError

        def put_bytes(self, data, *, kind, content_type=None, thread_id=None):
            raise NotImplementedError

        def get_bytes(self, ref):
            raise BlobNotFoundError("nope")

    assert Minimal().exists(BlobRef(sha256="0" * 64, size=0, kind="tool-output")) is False
    with pytest.raises(NotImplementedError):
        Minimal().delete(BlobRef(sha256="0" * 64, size=0, kind="tool-output"))


def test_invalid_kind_is_rejected_before_touching_disk(store: LocalFsBlobStore, tmp_path: Path):
    with pytest.raises(ValueError):
        store.put_bytes(b"x", kind="../escape")
    assert not any(tmp_path.rglob("escape"))


def test_oversized_put_is_refused(store: LocalFsBlobStore, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("deerflow.storage.backends.local_fs.local_fs_store._MAX_BLOB_BYTES", 4)
    with pytest.raises(BlobWriteError):
        store.put_bytes(b"12345", kind="tool-output")


def test_concurrent_puts_of_same_content(tmp_path: Path):
    """Two instances racing the same blob must not corrupt or duplicate it."""
    store = LocalFsBlobStore.from_config({"root": str(tmp_path / "blobs")})
    data = b"raced content" * 100
    results: list[BlobRef] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def worker() -> None:
        try:
            barrier.wait(timeout=5)
            results.append(store.put_bytes(data, kind="tool-output"))
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, errors
    assert len({r.sha256 for r in results}) == 1
    assert store.get_bytes(results[0]) == data
    assert len(list((tmp_path / "blobs" / "tool-output").rglob(f"{results[0].sha256}"))) == 1


def test_put_survives_a_lost_sidecar(store: LocalFsBlobStore):
    """The sidecar is GC metadata, not a read dependency."""
    data = b"payload-with-sidecar"
    ref = store.put_bytes(data, kind="tool-output")
    meta = next((store._root / "tool-output").rglob(f"{ref.sha256}.json"))
    meta.unlink()
    assert store.get_bytes(ref) == data


# ---------------------------------------------------------------------------
# Factory + config wiring
# ---------------------------------------------------------------------------


def test_package_exports_the_whole_error_family():
    """Callers use `from deerflow.storage import ...`, so the error they must
    catch has to be reachable there — and be the same class the contract
    raises, not a re-exported copy."""
    assert BlobNotConfiguredError is contract_module.BlobNotConfiguredError
    assert BlobStoreError is contract_module.BlobStoreError
    for name in ("BlobNotConfiguredError", "BlobStoreError", "BlobNotFoundError", "validate_blob_kind"):
        assert name in __import__("deerflow.storage", fromlist=["__all__"]).__all__

    bsc.set_blob_storage_config(bsc.BlobStorageConfig())
    reset_blob_store()
    with pytest.raises(BlobStoreError):
        get_blob_store()


def test_disabled_by_default():
    bsc.set_blob_storage_config(bsc.BlobStorageConfig())
    reset_blob_store()
    assert get_blob_store_if_enabled() is None
    with pytest.raises(BlobNotConfiguredError):
        get_blob_store()


def test_enabled_factory_resolves_folder_backend(tmp_path: Path):
    bsc.set_blob_storage_config(bsc.BlobStorageConfig(enabled=True, backend="local_fs", backend_config={"root": str(tmp_path / "b")}))
    reset_blob_store()
    store = get_blob_store_if_enabled()
    assert isinstance(store, LocalFsBlobStore)
    # Singleton: a second call returns the same instance.
    assert get_blob_store() is store


def test_unknown_backend_fails_fast(tmp_path: Path):
    bsc.set_blob_storage_config(bsc.BlobStorageConfig(enabled=True, backend="does_not_exist", backend_config={"root": str(tmp_path)}))
    reset_blob_store()
    with pytest.raises(ValueError, match="Unknown blob store backend"):
        get_blob_store()


def test_dotted_import_path_backend(tmp_path: Path):
    bsc.set_blob_storage_config(
        bsc.BlobStorageConfig(
            enabled=True,
            backend="deerflow.storage.backends.local_fs:LocalFsBlobStore",
            backend_config={"root": str(tmp_path / "d")},
        )
    )
    reset_blob_store()
    assert isinstance(get_blob_store(), LocalFsBlobStore)


def test_relative_root_is_resolved_against_runtime_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import deerflow.storage.manager as mgr

    monkeypatch.setattr(mgr, "_default_backend_config", lambda: {"root": str(tmp_path / "state")})
    bsc.set_blob_storage_config(bsc.BlobStorageConfig(enabled=True, backend="local_fs", backend_config={"root": "relative"}))
    reset_blob_store()
    store = get_blob_store()
    assert Path(str(store._root)).is_absolute()
