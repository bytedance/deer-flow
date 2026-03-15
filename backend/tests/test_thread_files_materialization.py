from pathlib import Path

from src.storage import thread_files


class _Backend:
    def __init__(self):
        self.exists_calls = []
        self.materialize_calls = []

    def exists_virtual_file(self, thread_id: str, virtual_path: str) -> bool:
        self.exists_calls.append((thread_id, virtual_path))
        return True

    def materialize_virtual_file(self, thread_id: str, virtual_path: str, destination_path: str | Path) -> Path:
        self.materialize_calls.append((thread_id, virtual_path, str(destination_path)))
        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("from durable", encoding="utf-8")
        return destination


def test_materialize_upload_to_local_cache_downloads_when_missing(monkeypatch, tmp_path):
    backend = _Backend()
    monkeypatch.setattr(thread_files, "get_thread_file_backend", lambda feature: backend)
    monkeypatch.setattr(thread_files, "get_paths", lambda: type("P", (), {"sandbox_uploads_dir": lambda _self, _thread_id: tmp_path / "uploads"})())
    monkeypatch.setattr(thread_files, "evict_local_upload_cache", lambda thread_id, keep_filenames=None: None)

    result = thread_files.materialize_upload_to_local_cache("thread-1", "/mnt/user-data/uploads/data.csv")

    assert result.read_text(encoding="utf-8") == "from durable"
    assert backend.exists_calls == [("thread-1", "/mnt/user-data/uploads/data.csv")]
    assert backend.materialize_calls == [("thread-1", "/mnt/user-data/uploads/data.csv", str(tmp_path / "uploads" / "data.csv"))]


def test_materialize_upload_to_local_cache_uses_existing_file(monkeypatch, tmp_path):
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir(parents=True)
    existing = uploads_dir / "data.csv"
    existing.write_text("already local", encoding="utf-8")

    backend = _Backend()
    monkeypatch.setattr(thread_files, "get_thread_file_backend", lambda feature: backend)
    monkeypatch.setattr(thread_files, "get_paths", lambda: type("P", (), {"sandbox_uploads_dir": lambda _self, _thread_id: uploads_dir})())
    monkeypatch.setattr(thread_files, "evict_local_upload_cache", lambda thread_id, keep_filenames=None: None)

    result = thread_files.materialize_upload_to_local_cache("thread-1", "/mnt/user-data/uploads/data.csv")

    assert result.read_text(encoding="utf-8") == "already local"
    assert backend.exists_calls == []
    assert backend.materialize_calls == []


def test_evict_local_upload_cache_applies_ttl_and_size(monkeypatch, tmp_path):
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir(parents=True)

    stale = uploads_dir / "stale.txt"
    stale.write_bytes(b"x" * 40)
    keep = uploads_dir / "keep.txt"
    keep.write_bytes(b"x" * 30)
    recent = uploads_dir / "recent.txt"
    recent.write_bytes(b"x" * 50)

    now = 1_000_000
    stale_mtime = now - 120
    keep_mtime = now - 10
    recent_mtime = now - 20
    stale.touch()
    keep.touch()
    recent.touch()

    import os
    os.utime(stale, (stale_mtime, stale_mtime))
    os.utime(keep, (keep_mtime, keep_mtime))
    os.utime(recent, (recent_mtime, recent_mtime))

    monkeypatch.setattr(thread_files, "get_paths", lambda: type("P", (), {"sandbox_uploads_dir": lambda _self, _thread_id: uploads_dir})())
    monkeypatch.setattr(thread_files, "_safe_upload_cache_config", lambda: (60, 60))

    class _Now:
        @staticmethod
        def now():
            from datetime import datetime

            return datetime.fromtimestamp(now)

    monkeypatch.setattr(thread_files, "datetime", _Now)

    thread_files.evict_local_upload_cache("thread-1", keep_filenames={"keep.txt"})

    remaining = sorted(p.name for p in uploads_dir.iterdir() if p.is_file())
    assert remaining == ["keep.txt"]


def test_materialize_upload_rehydrates_after_local_cache_loss(monkeypatch, tmp_path):
    backend = _Backend()
    monkeypatch.setattr(thread_files, "get_thread_file_backend", lambda feature: backend)
    monkeypatch.setattr(thread_files, "get_paths", lambda: type("P", (), {"sandbox_uploads_dir": lambda _self, _thread_id: tmp_path / "uploads"})())
    monkeypatch.setattr(thread_files, "evict_local_upload_cache", lambda thread_id, keep_filenames=None: None)

    first = thread_files.materialize_upload_to_local_cache("thread-1", "/mnt/user-data/uploads/data.csv")
    assert first.read_text(encoding="utf-8") == "from durable"

    # Simulate pod restart/local ephemeral loss.
    first.unlink()

    second = thread_files.materialize_upload_to_local_cache("thread-1", "/mnt/user-data/uploads/data.csv")
    assert second.read_text(encoding="utf-8") == "from durable"
    assert len(backend.materialize_calls) == 2
