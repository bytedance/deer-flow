"""Durable cursor allocation after JSONL run deletion and store reopening."""

import os
from pathlib import Path

import pytest

from deerflow.runtime.events.store.jsonl import JsonlRunEventStore


def event(run_id):
    return {"thread_id": "t1", "run_id": run_id, "event_type": "human_message", "category": "message", "content": run_id}


async def write(store, run_id, method):
    if method == "put_batch":
        return (await store.put_batch([event(run_id)]))[0]
    if method == "put_if_absent":
        return (await store.put_if_absent(**event(run_id)))[0]
    return await store.put(**event(run_id))


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["put", "put_batch", "put_if_absent"])
@pytest.mark.parametrize("reopen_before_delete", [False, True])
@pytest.mark.parametrize("delete_all", [False, True])
async def test_run_deletion_preserves_cursor_across_reopen(tmp_path, method, reopen_before_delete, delete_all):
    store = JsonlRunEventStore(tmp_path)
    await write(store, "r1", method)
    last = await write(store, "r2", method)
    assert last["seq"] == 2
    if reopen_before_delete:
        store = JsonlRunEventStore(tmp_path)
    assert await store.delete_by_run("t1", "r2") == 1
    if delete_all:
        assert await store.delete_by_run("t1", "r1") == 1
    reopened = JsonlRunEventStore(tmp_path)
    new = await write(reopened, "r3", method)
    assert new["seq"] == 3
    assert [row["seq"] for row in await reopened.list_messages("t1", after_seq=last["seq"])] == [3]


@pytest.mark.anyio
async def test_thread_deletion_resets_watermark_after_all_runs_deleted(tmp_path):
    store = JsonlRunEventStore(tmp_path)
    await store.put(**event("r1"))
    await store.delete_by_run("t1", "r1")
    assert await JsonlRunEventStore(tmp_path).delete_by_thread("t1") == 0
    recreated = await JsonlRunEventStore(tmp_path).put(**event("r2"))
    assert recreated["seq"] == 1


@pytest.mark.anyio
async def test_missing_run_deletion_does_not_create_storage(tmp_path):
    store = JsonlRunEventStore(tmp_path)
    assert await store.delete_by_run("t1", "missing") == 0
    assert not (tmp_path / "threads").exists()


@pytest.mark.anyio
async def test_legacy_directory_and_surviving_higher_seq(tmp_path):
    runs = tmp_path / "threads" / "t1" / "runs"
    runs.mkdir(parents=True)
    (runs / "legacy.jsonl").write_text('{"seq":9,"run_id":"legacy","category":"message"}\n', encoding="utf-8")
    store = JsonlRunEventStore(tmp_path)
    assert await store.delete_by_run("t1", "legacy") == 1
    assert (await store.put(**event("r1")))["seq"] == 10
    # The persisted floor is 9; recovery must also consider newer run records.
    assert (await JsonlRunEventStore(tmp_path).put(**event("r2")))["seq"] == 11


@pytest.mark.anyio
async def test_deleting_older_run_cannot_lower_watermark(tmp_path):
    store = JsonlRunEventStore(tmp_path)
    await store.put(**event("r1"))
    await store.put(**event("r2"))
    await store.delete_by_run("t1", "r2")
    await JsonlRunEventStore(tmp_path).delete_by_run("t1", "r1")
    assert (await JsonlRunEventStore(tmp_path).put(**event("r3")))["seq"] == 3


@pytest.mark.anyio
@pytest.mark.parametrize("invalid", ["garbage", "-1"])
async def test_invalid_watermark_fails_closed(tmp_path, invalid):
    runs = tmp_path / "threads" / "t1" / "runs"
    runs.mkdir(parents=True)
    (runs / ".seq-watermark").write_text(invalid, encoding="utf-8")
    with pytest.raises(ValueError):
        await JsonlRunEventStore(tmp_path).put(**event("r1"))
    assert not (runs / "r1.jsonl").exists()


@pytest.mark.anyio
async def test_failed_watermark_publish_keeps_previous_floor_and_run(tmp_path, monkeypatch):
    store = JsonlRunEventStore(tmp_path)
    await store.put(**event("r1"))
    await store.delete_by_run("t1", "r1")
    await store.put(**event("r2"))
    replace = Path.replace

    def fail_publish(path, target):
        if Path(target).name == ".seq-watermark":
            raise OSError("synthetic watermark publication failure")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_publish)
    with pytest.raises(OSError, match="publication failure"):
        await store.delete_by_run("t1", "r2")
    assert len(await store.list_events("t1", "r2")) == 1
    runs = tmp_path / "threads" / "t1" / "runs"
    assert (runs / ".seq-watermark").read_text(encoding="utf-8") == "1"
    assert not list(runs.glob(".seq-*.tmp"))
    assert (await JsonlRunEventStore(tmp_path).put(**event("r3")))["seq"] == 3


@pytest.mark.anyio
@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are not supported on Windows")
@pytest.mark.parametrize("run_mode", [0o600, 0o640, 0o644])
@pytest.mark.parametrize("replace_existing", [False, True])
async def test_watermark_matches_run_permissions_before_publication(tmp_path, monkeypatch, run_mode, replace_existing):
    store = JsonlRunEventStore(tmp_path)
    if replace_existing:
        await store.put(**event("r0"))
        await store.delete_by_run("t1", "r0")
    last = await store.put(**event("r1"))
    runs = tmp_path / "threads" / "t1" / "runs"
    (runs / "r1.jsonl").chmod(run_mode)
    replace = Path.replace

    def check_permissions(path, target):
        if Path(target).name == ".seq-watermark":
            assert path.stat().st_mode & 0o777 == run_mode
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", check_permissions)
    assert await store.delete_by_run("t1", "r1") == 1
    watermark = runs / ".seq-watermark"
    assert watermark.stat().st_mode & 0o777 == run_mode
    assert watermark.read_text(encoding="utf-8") == str(last["seq"])
    assert not (runs / "r1.jsonl").exists()
    assert (await JsonlRunEventStore(tmp_path).put(**event("r2")))["seq"] == last["seq"] + 1


@pytest.mark.anyio
@pytest.mark.parametrize("replace_existing", [False, True])
async def test_failed_watermark_permissions_keep_previous_floor_and_run(tmp_path, monkeypatch, replace_existing):
    store = JsonlRunEventStore(tmp_path)
    if replace_existing:
        await store.put(**event("r1"))
        await store.delete_by_run("t1", "r1")
    last = await store.put(**event("r2"))
    chmod = Path.chmod

    def fail_permissions(path, mode, **kwargs):
        if path.name.startswith(".seq-") and path.suffix == ".tmp":
            raise OSError("synthetic watermark permission failure")
        return chmod(path, mode, **kwargs)

    monkeypatch.setattr(Path, "chmod", fail_permissions)
    with pytest.raises(OSError, match="permission failure"):
        await store.delete_by_run("t1", "r2")
    assert len(await store.list_events("t1", "r2")) == 1
    runs = tmp_path / "threads" / "t1" / "runs"
    watermark = runs / ".seq-watermark"
    if replace_existing:
        assert watermark.read_text(encoding="utf-8") == "1"
    else:
        assert not watermark.exists()
    assert not list(runs.glob(".seq-*.tmp"))
    assert (await JsonlRunEventStore(tmp_path).put(**event("r3")))["seq"] == last["seq"] + 1


@pytest.mark.anyio
async def test_failed_run_unlink_keeps_safe_allocation_floor(tmp_path, monkeypatch):
    store = JsonlRunEventStore(tmp_path)
    await store.put(**event("r1"))

    def fail_delete(*args):
        raise OSError("synthetic unlink failure")

    monkeypatch.setattr(store, "_delete_run_file", fail_delete)
    with pytest.raises(OSError, match="unlink failure"):
        await store.delete_by_run("t1", "r1")
    assert len(await store.list_messages("t1")) == 1
    assert (await JsonlRunEventStore(tmp_path).put(**event("r2")))["seq"] == 2
