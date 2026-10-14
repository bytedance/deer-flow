"""Exclusive publication keeps complete bytes and coordinates processes."""

import multiprocessing
import os
from pathlib import Path

import pytest

from deerflow.utils.atomic_write import publish_bytes_atomically


def _competing_publisher(path, payload, barrier, results):
    link = os.link

    def link_together(source, destination):
        barrier.wait(timeout=15)
        return link(source, destination)

    os.link = link_together
    try:
        publish_bytes_atomically(Path(path), payload, overwrite=False)
    except FileExistsError:
        results.put(("occupied", payload))
    except BaseException as error:
        results.put(("error", repr(error)))
    else:
        results.put(("published", payload))
    finally:
        os.link = link


def test_exclusive_publication_preserves_existing_bytes_and_permissions(tmp_path):
    target = tmp_path / "shot.png"
    target.write_bytes(b"original")
    target.chmod(0o640)
    original_mode = target.stat().st_mode

    with pytest.raises(FileExistsError):
        publish_bytes_atomically(target, b"new capture", overwrite=False)

    assert target.read_bytes() == b"original"
    assert target.stat().st_mode == original_mode
    assert list(tmp_path.iterdir()) == [target]


def test_exclusive_publication_exposes_only_complete_bytes(tmp_path, monkeypatch):
    target = tmp_path / "shot.png"
    link = os.link

    def observe_link(source, destination):
        assert not target.exists()
        assert destination == target
        assert Path(source).read_bytes() == b"complete capture"
        link(source, destination)
        assert target.read_bytes() == b"complete capture"

    monkeypatch.setattr(os, "link", observe_link)
    publish_bytes_atomically(target, b"complete capture", overwrite=False)

    assert target.read_bytes() == b"complete capture"
    assert list(tmp_path.iterdir()) == [target]


def test_exclusive_link_failure_cleans_temporary_without_publishing(tmp_path, monkeypatch):
    target = tmp_path / "shot.png"
    error = PermissionError("hard links unavailable")

    def fail_link(*args):
        raise error

    monkeypatch.setattr(os, "link", fail_link)
    with pytest.raises(PermissionError) as raised:
        publish_bytes_atomically(target, b"new capture", overwrite=False)

    assert raised.value is error
    assert list(tmp_path.iterdir()) == []


def test_cleanup_failure_after_exclusive_publication_keeps_success(tmp_path, monkeypatch):
    target = tmp_path / "shot.png"
    unlink = Path.unlink

    def fail_temporary_unlink(path, *args, **kwargs):
        if path.name.startswith("."):
            raise PermissionError("temporary cleanup unavailable")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_temporary_unlink)
    publish_bytes_atomically(target, b"complete capture", overwrite=False)

    assert target.read_bytes() == b"complete capture"
    temporary = [path for path in tmp_path.iterdir() if path != target]
    assert len(temporary) == 1
    assert temporary[0].read_bytes() == b"complete capture"
    unlink(temporary[0])


def test_exclusive_publication_coordinates_spawned_processes(tmp_path):
    target = tmp_path / "shot.png"
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    payloads = [b"capture A", b"capture B"]
    workers = [context.Process(target=_competing_publisher, args=(str(target), payload, barrier, results)) for payload in payloads]
    try:
        for worker in workers:
            worker.start()
        outcomes = [results.get(timeout=25) for _ in workers]
        for worker in workers:
            worker.join(timeout=5)
            assert worker.exitcode == 0
        assert sorted(status for status, _ in outcomes) == ["occupied", "published"]
        winner = next(payload for status, payload in outcomes if status == "published")
        assert target.read_bytes() == winner
        assert list(tmp_path.iterdir()) == [target]
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
            if worker.pid is not None:
                worker.join(timeout=5)
        results.close()
        results.join_thread()
