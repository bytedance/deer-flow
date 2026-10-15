"""Browserless capture names must be claimed atomically, not merely checked.

``_dedupe_output_name`` promises that "an explicit filename never silently
overwrites an earlier capture", but on main name selection (``Path.exists()``)
and publication (``os.replace`` inside ``publish_bytes_atomically``) are two
separate operations. Two ``web_capture`` calls in the same thread outputs
directory can therefore both choose ``report.png`` before either publishes, and
the second publication replaces the first capture while both tools report
success for the same artifact path. ``web_capture_tool`` runs its writer through
``asyncio.to_thread``, so parallel captures are the normal shape rather than a
corner case. Same-second default names collide the same way, because the
generated stem's timestamp has second resolution.
"""

import importlib
import logging
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

tools = importlib.import_module("deerflow.community.browserless.tools")


@pytest.fixture()
def outputs(tmp_path):
    directory = tmp_path / "outputs"
    directory.mkdir()
    return directory


def test_concurrent_captures_do_not_claim_the_same_name(outputs, monkeypatch):
    """Two writers that pick names before either publishes still get distinct files.

    The barrier sits after name selection, which is exactly the interleaving the
    check-then-publish split allows: both writers have committed to a name and
    only then write bytes.
    """
    barrier = threading.Barrier(2, timeout=5)
    real_dedupe = tools._dedupe_output_name

    def choose_then_meet(outputs_path: object, output_name: str) -> str:
        chosen = real_dedupe(outputs_path, output_name)
        barrier.wait()
        return chosen

    monkeypatch.setattr(tools, "_dedupe_output_name", choose_then_meet)
    claimed: dict[str, str] = {}

    def capture(tag: str, content: bytes) -> None:
        claimed[tag] = tools._write_capture_output(outputs, "report.png", content)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(capture, "A", b"first"), pool.submit(capture, "B", b"second")]
        for future in futures:
            future.result()

    assert claimed["A"] != claimed["B"], f"both captures claimed {claimed}"
    assert (outputs / claimed["A"]).read_bytes() == b"first"
    assert (outputs / claimed["B"]).read_bytes() == b"second"


def test_reserved_names_keep_new_file_permissions(outputs):
    """Claiming a name must not change the mode the capture would already have had.

    ``publish_bytes_atomically`` preserves an existing file's mode, so a
    placeholder opened with the wrong default mode would make every capture
    executable rather than ``0o666 & ~umask``.
    """
    reference = outputs / "reference.bin"
    reference.write_bytes(b"x")
    expected = stat.S_IMODE(reference.stat().st_mode)

    claimed = tools._write_capture_output(outputs, "report.png", b"payload")

    assert stat.S_IMODE((outputs / claimed).stat().st_mode) == expected


def test_reservation_closes_the_descriptor_it_opened(outputs, monkeypatch):
    """The claim is an ``os.open``, so its descriptor has to be released too."""
    real_close = tools.os.close
    closed: list[int] = []

    def spy_close(fd: int) -> None:
        closed.append(fd)
        real_close(fd)

    monkeypatch.setattr(tools.os, "close", spy_close)

    tools._write_capture_output(outputs, "report.png", b"payload")

    assert closed, "the reserved name leaked its file descriptor"


def test_single_writer_still_uses_the_documented_suffix(outputs):
    (outputs / "report.png").write_bytes(b"existing")

    assert tools._write_capture_output(outputs, "report.png", b"new") == "report-1.png"
    assert (outputs / "report.png").read_bytes() == b"existing"
    assert (outputs / "report-1.png").read_bytes() == b"new"


def test_publication_failure_does_not_leave_the_reserved_name(outputs, monkeypatch, caplog):
    def failing_publish(path: object, content: bytes) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(tools, "_publish_bytes_atomically", failing_publish)

    with pytest.raises(OSError, match="disk full"):
        tools._write_capture_output(outputs, "report.png", b"payload")

    assert not (outputs / "report.png").exists()
    assert not any(record.name == tools.__name__ and record.levelno >= logging.WARNING for record in caplog.records)


@pytest.mark.parametrize("publication_error", [OSError("disk full"), KeyboardInterrupt("interrupted")], ids=["publication-error", "interruption"])
def test_unlink_failure_warns_without_masking_the_publication_error(outputs, monkeypatch, caplog, publication_error):
    def failing_publish(path: object, content: bytes) -> None:
        raise publication_error

    def failing_unlink(*args: object, **kwargs: object) -> None:
        raise OSError("busy")

    monkeypatch.setattr(tools, "_publish_bytes_atomically", failing_publish)
    monkeypatch.setattr(tools.os, "unlink", failing_unlink)

    with caplog.at_level(logging.WARNING, logger=tools.__name__), pytest.raises(type(publication_error)) as raised:
        tools._write_capture_output(outputs, "report.png", b"payload")
    assert raised.value is publication_error
    destination = outputs / "report.png"
    assert destination.is_file() and destination.stat().st_size == 0
    warnings = [record for record in caplog.records if record.name == tools.__name__ and record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert str(destination) in warnings[0].getMessage()
    assert isinstance(warnings[0].exc_info[1], OSError)
    assert str(warnings[0].exc_info[1]) == "busy"


def test_interruption_propagates_and_frees_the_name(outputs, monkeypatch):
    def interrupting_publish(path: object, content: bytes) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(tools, "_publish_bytes_atomically", interrupting_publish)

    with pytest.raises(KeyboardInterrupt):
        tools._write_capture_output(outputs, "report.png", b"payload")

    assert not (outputs / "report.png").exists()


def test_probe_bound_is_inclusive(outputs, monkeypatch):
    """The last probe index is reachable, so a directory full of ``-1``/``-2`` still gets ``-3``."""
    monkeypatch.setattr(tools, "_MAX_FILENAME_COLLISION_PROBES", 3)
    for name in ("report.png", "report-1.png", "report-2.png"):
        (outputs / name).write_bytes(b"earlier")

    assert tools._write_capture_output(outputs, "report.png", b"new") == "report-3.png"


def test_saturated_probe_range_still_reserves_a_fresh_name(outputs, monkeypatch):
    monkeypatch.setattr(tools, "_MAX_FILENAME_COLLISION_PROBES", 2)
    taken = ["report.png", "report-1.png", "report-2.png", "report-3.png"]
    for name in taken:
        (outputs / name).write_bytes(b"earlier")

    claimed = tools._write_capture_output(outputs, "report.png", b"new")

    assert claimed not in taken
    assert claimed.startswith("report-")
    assert (outputs / claimed).read_bytes() == b"new"
    assert all((outputs / name).read_bytes() == b"earlier" for name in taken)


def test_exhausted_timestamp_claims_refuse_to_overwrite(outputs, monkeypatch):
    """When even the fallback name is held, fail loudly rather than returning it.

    A returned name here would be published onto an existing capture, which is
    the exact silent overwrite the reservation replaces.
    """

    class _FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 14, 12, 0, 0, 123456, tzinfo=UTC)

    monkeypatch.setattr(tools, "_MAX_FILENAME_COLLISION_PROBES", 1)
    monkeypatch.setattr(tools, "datetime", _FrozenClock)
    held = ["report.png", "report-1.png", "report-20261014-120000-123456.png"]
    for name in held:
        (outputs / name).write_bytes(b"earlier")

    with pytest.raises(RuntimeError, match="could not reserve an output filename"):
        tools._dedupe_output_name(outputs, "report.png")

    assert all((outputs / name).read_bytes() == b"earlier" for name in held)
