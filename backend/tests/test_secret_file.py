"""Exclusive-create helper for small secret files shared by concurrent processes.

Gateway replicas that share a runtime home (a Helm ``ReadWriteMany`` volume, a
compose bind mount, or several uvicorn workers of one host) cold-start at the
same time and each find no secret file yet. A read-then-``O_TRUNC`` write lets
every one of them keep a different value -- for ``.jwt_secret`` that is two
replicas signing sessions with different keys, for ``.credentials_key`` it is
credentials one replica cannot decrypt. ``read_or_create_secret_file`` creates
with ``O_EXCL`` and reads the winner's value back instead.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import pytest

from deerflow.config.secret_file import InvalidSecretFileError, read_or_create_secret_file


def test_creates_a_missing_file_with_owner_only_permissions(tmp_path: Path) -> None:
    path = tmp_path / "nested" / ".secret"

    value = read_or_create_secret_file(path, lambda: "generated-value")

    assert value == "generated-value"
    assert path.read_text(encoding="utf-8") == "generated-value"
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


def test_reuses_an_existing_value_without_generating(tmp_path: Path) -> None:
    path = tmp_path / ".secret"
    path.write_text("existing-value\n", encoding="utf-8")

    def generate() -> str:
        raise AssertionError("an existing secret must never be regenerated")

    assert read_or_create_secret_file(path, generate) == "existing-value"
    assert path.read_text(encoding="utf-8") == "existing-value\n"


def test_a_peer_that_publishes_first_wins(tmp_path: Path) -> None:
    """Deterministic race: the peer creates the file between our existence check and our create.

    A read-then-truncating write would overwrite the peer's value and return
    our own, leaving the two processes on different secrets.
    """
    path = tmp_path / ".secret"

    def generate() -> str:
        path.write_text("peer-value", encoding="utf-8")
        return "our-value"

    assert read_or_create_secret_file(path, generate) == "peer-value"
    assert path.read_text(encoding="utf-8") == "peer-value"


def test_concurrent_creators_converge_on_one_value(tmp_path: Path) -> None:
    path = tmp_path / ".secret"
    workers = 16
    barrier = threading.Barrier(workers)
    results: list[str] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def run(index: int) -> None:
        try:
            barrier.wait(timeout=10)
            value = read_or_create_secret_file(path, lambda: f"value-{index}")
            with lock:
                results.append(value)
        except BaseException as exc:  # noqa: BLE001 - surface every worker failure
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=run, args=(index,)) for index in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors
    assert len(results) == workers
    assert len(set(results)) == 1, f"creators diverged: {sorted(set(results))}"
    assert path.read_text(encoding="utf-8") == results[0]


def test_waits_for_a_peer_that_has_created_but_not_yet_written(tmp_path: Path) -> None:
    """Older releases published the name before its content: an empty file may be one of them mid-write."""
    path = tmp_path / ".secret"
    path.touch()
    writer = threading.Timer(0.1, lambda: path.write_text("late-value", encoding="utf-8"))
    writer.start()
    try:
        value = read_or_create_secret_file(path, lambda: "our-value", settle_seconds=5)
    finally:
        writer.join()

    assert value == "late-value"
    assert path.read_text(encoding="utf-8") == "late-value"


def test_retries_a_partially_written_value_that_fails_validation(tmp_path: Path) -> None:
    path = tmp_path / ".secret"
    path.write_text("0123", encoding="utf-8")

    def validate(value: str) -> None:
        if len(value) != 10:
            raise ValueError("incomplete")

    writer = threading.Timer(0.1, lambda: path.write_text("0123456789", encoding="utf-8"))
    writer.start()
    try:
        value = read_or_create_secret_file(path, lambda: "abcdefghij", validate=validate, settle_seconds=5)
    finally:
        writer.join()

    assert value == "0123456789"


def test_an_abandoned_empty_file_is_replaced(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """A crash between create and write (or an older release's truncating write) leaves an empty file.

    Nothing can have been signed or encrypted with an empty secret, so once the
    settle window passes it is replaced instead of failing startup forever.
    """
    path = tmp_path / ".secret"
    path.touch()

    with caplog.at_level(logging.WARNING, logger="deerflow.config.secret_file"):
        value = read_or_create_secret_file(path, lambda: "fresh-value", settle_seconds=0.05)

    assert value == "fresh-value"
    assert path.read_text(encoding="utf-8") == "fresh-value"
    assert any(str(path) in record.getMessage() for record in caplog.records)
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


def test_concurrent_replacers_of_an_abandoned_empty_file_converge(tmp_path: Path) -> None:
    """Replicas restarting together after a crash all find the same abandoned empty file.

    The replacement is a last-writer-wins rename, so a replacer must not trust
    its own value until peers that decided to replace in the same window have
    written theirs.
    """
    path = tmp_path / ".secret"
    path.touch()
    workers = 8
    barrier = threading.Barrier(workers)
    results: list[str] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def run(index: int) -> None:
        def generate() -> str:
            # Stagger the replacements so an early replacer would otherwise
            # read back its own value before a later one overwrites it.
            threading.Event().wait(0.01 * index)
            return f"value-{index}"

        try:
            barrier.wait(timeout=10)
            value = read_or_create_secret_file(path, generate, settle_seconds=0.2)
            with lock:
                results.append(value)
        except BaseException as exc:  # noqa: BLE001 - surface every worker failure
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=run, args=(index,)) for index in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors
    assert len(results) == workers
    assert len(set(results)) == 1, f"replacers diverged: {sorted(set(results))}"
    assert path.read_text(encoding="utf-8") == results[0]


def test_waits_for_a_peer_that_holds_the_replacement_claim(tmp_path: Path) -> None:
    path = tmp_path / ".secret"
    path.touch()
    claim = tmp_path / ".secret.replacing"
    claim.write_text("peer-value", encoding="utf-8")
    publisher = threading.Timer(0.3, lambda: os.replace(claim, path))
    publisher.start()
    try:
        value = read_or_create_secret_file(path, lambda: "our-value", settle_seconds=0.05)
    finally:
        publisher.join()

    assert value == "peer-value"
    assert not claim.exists()


def test_a_claim_left_by_a_crashed_replacer_is_refused_after_a_bounded_wait(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("deerflow.config.secret_file._CLAIM_WAIT_SECONDS", 0.2)
    path = tmp_path / ".secret"
    path.touch()
    claim = tmp_path / ".secret.replacing"
    claim.touch()

    with pytest.raises(InvalidSecretFileError, match="interrupted creation"):
        read_or_create_secret_file(path, lambda: "our-value", settle_seconds=0.05)

    assert path.read_text(encoding="utf-8") == ""


def test_a_late_replacer_does_not_overwrite_a_published_replacement(tmp_path: Path) -> None:
    """A process that saw the empty file before a peer's replacement landed must back off."""
    path = tmp_path / ".secret"
    path.write_text("peer-value", encoding="utf-8")
    from deerflow.config.secret_file import _publish_under_claim

    assert _publish_under_claim(path, lambda: "late-value", replace_empty=True) is True
    assert path.read_text(encoding="utf-8") == "peer-value"
    assert not (tmp_path / ".secret.replacing").exists()


def test_a_persistently_invalid_file_is_refused_without_echoing_it(tmp_path: Path) -> None:
    """A non-empty value may be the only copy of a key that encrypted data: never overwrite it."""
    path = tmp_path / ".secret"
    path.write_text("operator-typo-in-the-key", encoding="utf-8")

    def validate(value: str) -> None:
        raise ValueError(f"bad value {value}")

    with pytest.raises(InvalidSecretFileError) as exc_info:
        read_or_create_secret_file(path, lambda: "replacement", validate=validate, settle_seconds=0.05)

    assert str(path) in str(exc_info.value)
    assert "operator-typo-in-the-key" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None, "the validator's message may quote the value"
    assert path.read_text(encoding="utf-8") == "operator-typo-in-the-key"


def test_a_failed_write_leaves_no_empty_file_for_peers_to_wait_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / ".secret"

    def broken_write(_fd: int, _data: bytes) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("deerflow.config.secret_file._write_all", broken_write)

    with pytest.raises(OSError, match="disk full"):
        read_or_create_secret_file(path, lambda: "value")

    assert not path.exists()


def _pause_one_creator(monkeypatch: pytest.MonkeyPatch, thread_name: str, *, fail: bool = False) -> tuple[threading.Event, threading.Event]:
    """Hold ``thread_name`` inside its secret write until released; the other threads write normally."""
    import deerflow.config.secret_file as secret_file

    entered = threading.Event()
    release = threading.Event()
    original_write_all = secret_file._write_all

    def write_all(fd: int, data: bytes) -> None:
        if threading.current_thread().name == thread_name:
            entered.set()
            assert release.wait(timeout=10)
            if fail:
                raise OSError("disk full")
        original_write_all(fd, data)

    monkeypatch.setattr(secret_file, "_write_all", write_all)
    return entered, release


@pytest.mark.parametrize("fail", [False, True], ids=["paused-then-writes", "paused-then-fails"])
def test_a_paused_creator_never_exposes_a_file_a_peer_could_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail: bool) -> None:
    """A creator stalled mid-write must not leave a visible empty file behind.

    Otherwise a peer treats it as abandoned after the settle window and
    publishes its own value; the resumed creator then returns a value nobody
    persisted, or (when its write fails) deletes the peer's valid file.
    """
    path = tmp_path / ".secret"
    entered, release = _pause_one_creator(monkeypatch, "first", fail=fail)
    results: dict[str, str | BaseException] = {}

    def run(name: str) -> None:
        try:
            results[name] = read_or_create_secret_file(path, lambda: f"{name}-value", settle_seconds=0.05)
        except BaseException as exc:  # noqa: BLE001 - asserted below
            results[name] = exc

    first = threading.Thread(target=run, args=("first",), name="first")
    first.start()
    assert entered.wait(timeout=10)
    peer = threading.Thread(target=run, args=("peer",), name="peer")
    peer.start()
    peer.join(timeout=10)
    release.set()
    first.join(timeout=10)

    assert results["peer"] == "peer-value"
    assert path.read_text(encoding="utf-8") == "peer-value", "the peer's published value must survive"
    if fail:
        assert isinstance(results["first"], OSError)
    else:
        assert results["first"] == "peer-value", "the resumed creator must adopt the persisted value"


def test_creation_without_hard_links_still_converges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Filesystems without hard links (SMB shares) publish through the replacement claim instead."""
    import errno

    def no_hard_links(*_args, **_kwargs):
        raise OSError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(os, "link", no_hard_links)
    path = tmp_path / ".secret"
    workers = 8
    barrier = threading.Barrier(workers)
    results: list[str] = []
    lock = threading.Lock()

    def run(index: int) -> None:
        barrier.wait(timeout=10)
        value = read_or_create_secret_file(path, lambda: f"value-{index}", settle_seconds=0.05)
        with lock:
            results.append(value)

    threads = [threading.Thread(target=run, args=(index,)) for index in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(results) == workers
    assert len(set(results)) == 1, f"creators diverged: {sorted(set(results))}"
    assert path.read_text(encoding="utf-8") == results[0]
    assert not (tmp_path / ".secret.replacing").exists()
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


def test_no_temporary_files_are_left_behind(tmp_path: Path) -> None:
    path = tmp_path / ".secret"
    read_or_create_secret_file(path, lambda: "value")

    assert sorted(entry.name for entry in tmp_path.iterdir()) == [".secret"]
