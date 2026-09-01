from __future__ import annotations

import asyncio
import io
import os
import threading
import zipfile
from pathlib import Path
from uuid import UUID

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway import artifact_archive
from app.gateway.auth.models import User
from app.gateway.routers import thread_runs
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.store.memory import MemoryRunStore

THREAD_ID = "thread-archive"
RUN_ID = "run-archive"
USER_ID = UUID("00000000-0000-0000-0000-000000000123")
ARCHIVE_URL = f"/api/threads/{THREAD_ID}/runs/{RUN_ID}/artifacts/archive"


class _FakePaths:
    def __init__(self, outputs_dir: Path) -> None:
        self._outputs_dir = outputs_dir

    def sandbox_outputs_dir(self, _thread_id: str, *, user_id: str | None = None) -> Path:
        return self._outputs_dir

    def sandbox_user_data_dir(self, _thread_id: str, *, user_id: str | None = None) -> Path:
        return self._outputs_dir.parent


def _user() -> User:
    return User(
        id=USER_ID,
        email="archive-test@example.com",
        password_hash="x",
        system_role="user",
    )


def _archive_app(
    monkeypatch: pytest.MonkeyPatch,
    outputs_dir: Path,
    *,
    paths: list[str] | None = None,
    run_thread_id: str = THREAD_ID,
    run_status: str = "success",
    with_receipt: bool = True,
) -> tuple[TestClient, MemoryRunStore, MemoryRunEventStore]:
    run_store = MemoryRunStore()
    event_store = MemoryRunEventStore()
    run_manager = RunManager(store=run_store)

    asyncio.run(
        run_store.put(
            RUN_ID,
            thread_id=run_thread_id,
            user_id=None,
            status=run_status,
        )
    )
    if with_receipt:
        presented = paths or []
        asyncio.run(
            event_store.put(
                thread_id=THREAD_ID,
                run_id=RUN_ID,
                event_type="run.delivery",
                category="outputs",
                content={
                    "presented": len(presented),
                    "paths": presented,
                    "by_tool": {"present_files": presented},
                },
            )
        )

    monkeypatch.setattr(
        thread_runs,
        "get_paths",
        lambda: _FakePaths(outputs_dir),
        raising=False,
    )

    app = make_authed_test_app(user_factory=_user)
    app.state.run_store = run_store
    app.state.run_event_store = event_store
    app.state.run_manager = run_manager
    app.include_router(thread_runs.router)
    return TestClient(app), run_store, event_store


def test_archive_download_contains_only_presented_files(tmp_path, monkeypatch) -> None:
    outputs = tmp_path / "outputs"
    (outputs / "reports").mkdir(parents=True)
    (outputs / "reports" / "summary.txt").write_text("summary", encoding="utf-8")
    (outputs / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (outputs / "not-presented.txt").write_text("secret", encoding="utf-8")
    paths = [
        "/mnt/user-data/outputs/reports/summary.txt",
        "/mnt/user-data/outputs/data.csv",
        "/mnt/user-data/outputs/data.csv",
    ]
    client, _, _ = _archive_app(monkeypatch, outputs, paths=paths)

    with client:
        response = client.post(
            ARCHIVE_URL,
            json={"paths": ["/mnt/user-data/outputs/not-presented.txt"]},
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ["reports/summary.txt", "data.csv"]
        assert archive.read("reports/summary.txt") == b"summary"
        assert archive.read("data.csv") == b"a,b\n1,2\n"
        assert "not-presented.txt" not in archive.namelist()


def test_archive_manifest_counts_only_verified_delivery_paths(tmp_path, monkeypatch) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    client, _, _ = _archive_app(
        monkeypatch,
        outputs,
        paths=[
            "/mnt/user-data/outputs/report.txt",
            "/mnt/user-data/outputs/data.csv",
            "/mnt/user-data/outputs/data.csv",
        ],
    )

    with client:
        response = client.get(ARCHIVE_URL)

    assert response.status_code == 200
    assert response.json() == {"file_count": 2}


@pytest.mark.parametrize(
    "presented_path",
    [
        "/mnt/user-data/uploads/private.txt",
        "/mnt/user-data/outputs/../uploads/private.txt",
        "/mnt/user-data/outputs/.tool-results/raw.txt",
        "/mnt/user-data/outputs/.browser-frames/frame.png",
    ],
)
def test_archive_rejects_paths_outside_public_outputs(
    tmp_path,
    monkeypatch,
    presented_path: str,
) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    client, _, _ = _archive_app(monkeypatch, outputs, paths=[presented_path])

    with client:
        response = client.post(ARCHIVE_URL)

    assert response.status_code == 409
    assert response.json()["detail"] == "The files listed by this response are not available for archive download"


def test_archive_rejects_a_directory_without_recursing(tmp_path, monkeypatch) -> None:
    outputs = tmp_path / "outputs"
    folder = outputs / "site"
    folder.mkdir(parents=True)
    (folder / "index.html").write_text("hidden descendant", encoding="utf-8")
    client, _, _ = _archive_app(
        monkeypatch,
        outputs,
        paths=["/mnt/user-data/outputs/site"],
    )

    with client:
        response = client.post(ARCHIVE_URL)

    assert response.status_code == 409


def test_archive_rejects_a_symlink(tmp_path, monkeypatch) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = outputs / "linked.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")
    client, _, _ = _archive_app(
        monkeypatch,
        outputs,
        paths=["/mnt/user-data/outputs/linked.txt"],
    )

    with client:
        response = client.post(ARCHIVE_URL)

    assert response.status_code == 409


def test_archive_rejects_a_symlinked_outputs_root(tmp_path, monkeypatch) -> None:
    user_data = tmp_path / "user-data"
    user_data.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside", encoding="utf-8")
    outputs = user_data / "outputs"
    try:
        outputs.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")
    client, _, _ = _archive_app(
        monkeypatch,
        outputs,
        paths=["/mnt/user-data/outputs/secret.txt"],
    )

    with client:
        response = client.post(ARCHIVE_URL)

    assert response.status_code == 409


def test_archive_rejects_a_hard_linked_member(tmp_path, monkeypatch) -> None:
    outputs = tmp_path / "outputs"
    internal = outputs / ".tool-results"
    internal.mkdir(parents=True)
    secret = internal / "raw-secret.txt"
    secret.write_text("internal", encoding="utf-8")
    public_alias = outputs / "report.txt"
    try:
        public_alias.hardlink_to(secret)
    except OSError:
        pytest.skip("hard links are unavailable on this platform")
    client, _, _ = _archive_app(
        monkeypatch,
        outputs,
        paths=["/mnt/user-data/outputs/report.txt"],
    )

    with client:
        response = client.post(ARCHIVE_URL)

    assert response.status_code == 409


@pytest.mark.parametrize("junction_relative", [Path(), Path("site")])
def test_archive_rejects_junction_like_roots_and_components(
    tmp_path,
    monkeypatch,
    junction_relative: Path,
) -> None:
    outputs = tmp_path / "outputs"
    target = outputs / "site" / "report.txt"
    target.parent.mkdir(parents=True)
    target.write_text("report", encoding="utf-8")
    junction = outputs / junction_relative
    monkeypatch.setattr(Path, "is_junction", lambda self: self == junction)

    with pytest.raises(artifact_archive.ArtifactArchiveError):
        artifact_archive.build_artifact_archive(
            outputs,
            ["/mnt/user-data/outputs/site/report.txt"],
            user_data_dir=outputs.parent,
        )


def test_archive_rejects_missing_or_nonterminal_delivery(tmp_path, monkeypatch) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    client, _, _ = _archive_app(
        monkeypatch,
        outputs,
        run_status="running",
        with_receipt=False,
    )

    with client:
        response = client.post(ARCHIVE_URL)

    assert response.status_code == 409


@pytest.mark.parametrize("method", ["get", "post"])
def test_archive_hides_a_run_from_another_thread(tmp_path, monkeypatch, method: str) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    client, _, _ = _archive_app(
        monkeypatch,
        outputs,
        run_thread_id="another-thread",
        paths=["/mnt/user-data/outputs/report.txt"],
    )

    with client:
        response = getattr(client, method)(ARCHIVE_URL)

    assert response.status_code == 404


def test_archive_conflicts_with_an_active_run(tmp_path, monkeypatch) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "report.txt").write_text("report", encoding="utf-8")
    client, run_store, _ = _archive_app(
        monkeypatch,
        outputs,
        paths=["/mnt/user-data/outputs/report.txt"],
    )
    asyncio.run(
        run_store.put(
            "active-run",
            thread_id=THREAD_ID,
            user_id=None,
            status="running",
        )
    )

    with client:
        response = client.post(ARCHIVE_URL)

    assert response.status_code == 409


def test_archive_rejects_when_the_worker_is_at_capacity(tmp_path, monkeypatch) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "report.txt").write_text("report", encoding="utf-8")
    client, _, _ = _archive_app(
        monkeypatch,
        outputs,
        paths=["/mnt/user-data/outputs/report.txt"],
    )
    slots = asyncio.Semaphore(1)
    asyncio.run(slots.acquire())
    monkeypatch.setattr(thread_runs, "_artifact_archive_slots", slots, raising=False)

    with client:
        response = client.post(ARCHIVE_URL)

    assert response.status_code == 429


def test_archive_rejects_casefolded_entry_collisions(tmp_path, monkeypatch) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    upper = outputs / "Report.txt"
    lower = outputs / "report.txt"
    upper.write_text("upper", encoding="utf-8")
    lower.write_text("lower", encoding="utf-8")
    if upper.samefile(lower):
        pytest.skip("case-sensitive filenames are unavailable on this filesystem")
    client, _, _ = _archive_app(
        monkeypatch,
        outputs,
        paths=[
            "/mnt/user-data/outputs/Report.txt",
            "/mnt/user-data/outputs/report.txt",
        ],
    )

    with client:
        response = client.post(ARCHIVE_URL)

    assert response.status_code == 409


def test_archive_rechecks_size_after_open(tmp_path, monkeypatch) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    artifact = outputs / "report.txt"
    artifact.write_bytes(b"x")
    original_member = artifact_archive._member

    def grow_after_validation(*args, **kwargs):
        member = original_member(*args, **kwargs)
        artifact.write_bytes(b"12345")
        return member

    monkeypatch.setattr(artifact_archive, "MAX_FILE_BYTES", 4)
    monkeypatch.setattr(artifact_archive, "MAX_TOTAL_BYTES", 8)
    monkeypatch.setattr(artifact_archive, "_member", grow_after_validation)

    with pytest.raises(artifact_archive.ArtifactArchiveError) as exc_info:
        artifact_archive.build_artifact_archive(
            outputs,
            ["/mnt/user-data/outputs/report.txt"],
            user_data_dir=outputs.parent,
        )

    assert exc_info.value.status_code == 413


def test_archive_enforces_file_count_and_total_size_limits(tmp_path, monkeypatch) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    paths = []
    for name in ("one.txt", "two.txt"):
        (outputs / name).write_bytes(b"x")
        paths.append(f"/mnt/user-data/outputs/{name}")

    monkeypatch.setattr(artifact_archive, "MAX_FILES", 1)
    with pytest.raises(artifact_archive.ArtifactArchiveError) as count_error:
        artifact_archive.build_artifact_archive(outputs, paths, user_data_dir=outputs.parent)
    assert count_error.value.status_code == 413

    monkeypatch.setattr(artifact_archive, "MAX_FILES", 2)
    monkeypatch.setattr(artifact_archive, "MAX_TOTAL_BYTES", 1)
    with pytest.raises(artifact_archive.ArtifactArchiveError) as size_error:
        artifact_archive.build_artifact_archive(outputs, paths, user_data_dir=outputs.parent)
    assert size_error.value.status_code == 413


@pytest.mark.parametrize(
    ("relative_path", "reserved"),
    [
        (".ARTIFACT-EDIT-draft", set()),
        ("private-cache/result.txt", {"private-cache"}),
    ],
)
def test_archive_rejects_internal_output_names(
    tmp_path,
    relative_path: str,
    reserved: set[str],
) -> None:
    outputs = tmp_path / "outputs"
    target = outputs / relative_path
    target.parent.mkdir(parents=True)
    target.write_text("internal", encoding="utf-8")

    with pytest.raises(artifact_archive.ArtifactArchiveError):
        artifact_archive.build_artifact_archive(
            outputs,
            [f"/mnt/user-data/outputs/{relative_path}"],
            user_data_dir=outputs.parent,
            extra_reserved_dir_names=reserved,
        )


def test_archive_rejects_a_path_replaced_during_read(tmp_path, monkeypatch) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    artifact = outputs / "report.txt"
    artifact.write_bytes(b"old-content")
    replacement = outputs / "replacement.txt"
    replacement.write_bytes(b"new-content")
    original_read = artifact_archive.os.read
    replaced = False

    def replace_after_read(descriptor: int, count: int) -> bytes:
        nonlocal replaced
        data = original_read(descriptor, count)
        if not replaced:
            replaced = True
            replacement.replace(artifact)
        return data

    monkeypatch.setattr(artifact_archive.os, "read", replace_after_read)

    with pytest.raises(artifact_archive.ArtifactArchiveError):
        artifact_archive.build_artifact_archive(
            outputs,
            ["/mnt/user-data/outputs/report.txt"],
            user_data_dir=outputs.parent,
        )


def test_archive_rejects_same_size_content_change_with_restored_mtime(tmp_path, monkeypatch) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    artifact = outputs / "report.bin"
    chunk_size = artifact_archive._CHUNK_BYTES
    artifact.write_bytes(b"A" * (chunk_size * 2))
    original_mtime_ns = artifact.stat().st_mtime_ns
    original_read = artifact_archive.os.read
    reads = 0

    def change_middle_chunk_then_restore(descriptor: int, count: int) -> bytes:
        nonlocal reads
        data = original_read(descriptor, count)
        reads += 1
        if reads == 1:
            with artifact.open("r+b") as stream:
                stream.seek(chunk_size)
                stream.write(b"B" * chunk_size)
            os.utime(artifact, ns=(artifact.stat().st_atime_ns, original_mtime_ns))
        elif reads == 2:
            with artifact.open("r+b") as stream:
                stream.seek(chunk_size)
                stream.write(b"A" * chunk_size)
            os.utime(artifact, ns=(artifact.stat().st_atime_ns, original_mtime_ns))
        return data

    monkeypatch.setattr(artifact_archive.os, "read", change_middle_chunk_then_restore)

    with pytest.raises(artifact_archive.ArtifactArchiveError):
        artifact_archive.build_artifact_archive(
            outputs,
            ["/mnt/user-data/outputs/report.bin"],
            user_data_dir=outputs.parent,
        )


def test_archive_deadline_applies_to_empty_files(tmp_path, monkeypatch) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "empty.txt").touch()
    monkeypatch.setattr(artifact_archive, "BUILD_TIMEOUT_SECONDS", -1)

    with pytest.raises(artifact_archive.ArtifactArchiveError) as exc_info:
        artifact_archive.build_artifact_archive(
            outputs,
            ["/mnt/user-data/outputs/empty.txt"],
            user_data_dir=outputs.parent,
        )

    assert exc_info.value.status_code == 503


@pytest.mark.parametrize(
    "filename",
    [
        "report.txt.",
        "C:report.txt",
        "CON.txt",
        "report<draft>.txt",
        'report"draft.txt',
        "report|draft.txt",
        "report?.txt",
        "report*.txt",
    ],
)
def test_archive_rejects_nonportable_zip_names(tmp_path, filename: str) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    target = outputs / filename
    try:
        target.write_text("report", encoding="utf-8")
    except OSError:
        pytest.skip("the platform cannot create this nonportable filename")

    with pytest.raises(artifact_archive.ArtifactArchiveError):
        artifact_archive.build_artifact_archive(
            outputs,
            [f"/mnt/user-data/outputs/{filename}"],
            user_data_dir=outputs.parent,
        )


def test_archive_allows_emoji_joiner_sequences(tmp_path) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    filename = "report-🧑‍💻.txt"
    (outputs / filename).write_text("report", encoding="utf-8")

    result = artifact_archive.build_artifact_archive(
        outputs,
        [f"/mnt/user-data/outputs/{filename}"],
        user_data_dir=outputs.parent,
    )

    with result.file, zipfile.ZipFile(result.file) as archive:
        assert archive.namelist() == [filename]


@pytest.mark.asyncio
async def test_repeated_cancellation_keeps_the_archive_slot_until_worker_exit(monkeypatch) -> None:
    started = threading.Event()
    release = threading.Event()

    def blocking_build(*_args, **_kwargs):
        started.set()
        release.wait(timeout=5)
        return artifact_archive.ArtifactArchiveResult(io.BytesIO(), 0, 0, 0)

    slots = asyncio.Semaphore(1)
    monkeypatch.setattr(thread_runs, "_artifact_archive_slots", slots)
    monkeypatch.setattr(thread_runs, "build_artifact_archive", blocking_build)
    task = asyncio.create_task(
        thread_runs._build_archive_without_abandoning_worker(
            Path("unused"),
            Path("unused-parent"),
            [],
            extra_reserved_dir_names=set(),
        )
    )
    assert await asyncio.to_thread(started.wait, 1)

    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    done, _ = await asyncio.wait({task}, timeout=0.1)

    try:
        assert not done
        assert slots.locked()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
