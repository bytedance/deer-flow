"""Staged-publication cleanup in the channel stores must keep the original error.

``JsonChannelStore``, ``ChannelRuntimeConfigStore`` and the WeChat auth-state file all
publish by writing a staged temporary file and renaming it over the destination. Their
cleanup path used to run ``close()`` and ``unlink()`` unguarded inside
``except BaseException: raise``, so a failing cleanup replaced the error that actually
made the save fail — and the staged file, which for the two credential stores holds an
``0600`` copy of IM tokens, stayed on disk with nothing reporting it.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from app.channels.message_bus import MessageBus
from app.channels.runtime_config_store import ChannelRuntimeConfigStore
from app.channels.store import JsonChannelStore
from app.channels.wechat import WechatChannel

CLEANUP_ERRNO = 28

# Replacing a file over a non-empty directory is EISDIR (errno 21) on POSIX and
# WinError 5 (errno 13, PermissionError) on Windows. The regression this file
# pins is "cleanup must not replace the save error", not the platform's errno,
# so accept the platform's blocked-rename error and assert it is not the
# cleanup error instead of hard-coding errno 21 (which failed on Windows dev
# hosts).
BLOCKED_RENAME_ERRORS: tuple[type[BaseException], ...] = (IsADirectoryError, PermissionError) if os.name == "nt" else (IsADirectoryError,)


def _assert_blocked_rename_error(exc: BaseException) -> None:
    """The save error must be the blocked rename, never the cleanup error."""
    if os.name == "nt":
        assert getattr(exc, "errno", None) != CLEANUP_ERRNO
    else:
        assert getattr(exc, "errno", None) == 21


def _block_destination(destination: Path) -> None:
    """Make the atomic rename fail with a deterministic errno-21 error.

    A non-empty directory in the destination's place cannot be replaced and cannot be
    absorbed by the rename (an empty directory would just swallow the staged file).
    """
    destination.mkdir()
    (destination / "occupant").write_text("x")


def _staged_files(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p.suffix == ".tmp")


@pytest.fixture
def cleanup_fails(monkeypatch):
    def exploding_unlink(self, *args, **kwargs):
        raise OSError(CLEANUP_ERRNO, "Simulated cleanup failure")

    monkeypatch.setattr(Path, "unlink", exploding_unlink)


class _CloseFails:
    """A staged file whose ``close()`` always fails, so cleanup has two broken steps."""

    def __init__(self, path: Path) -> None:
        self.name = str(path)
        self._path = path
        self._written: list[str] = []

    def write(self, text: str) -> None:
        self._written.append(text)

    def close(self) -> None:
        self._path.write_text("".join(self._written), encoding="utf-8")
        raise OSError(9, "Simulated close failure")


def test_json_channel_store_keeps_the_save_error(tmp_path, cleanup_fails, caplog):
    path = tmp_path / "store.json"
    _block_destination(path)
    store = JsonChannelStore(path)
    store._data = {"feishu:chat": {"thread_id": "t"}}

    with caplog.at_level(logging.WARNING), pytest.raises(BLOCKED_RENAME_ERRORS) as raised:
        store._save()

    _assert_blocked_rename_error(raised.value)
    assert "Failed to remove temporary channel store file" in caplog.text


def test_runtime_config_store_keeps_the_save_error(tmp_path, cleanup_fails, caplog):
    store = ChannelRuntimeConfigStore(tmp_path / "channels.json")
    _block_destination(store._path)

    with caplog.at_level(logging.WARNING), pytest.raises(BLOCKED_RENAME_ERRORS) as raised:
        store._save({"feishu": {"app_id": "id"}})

    _assert_blocked_rename_error(raised.value)
    assert "Failed to remove temporary channel runtime config file" in caplog.text


def test_wechat_auth_state_persist_failure_stays_attributable(tmp_path, cleanup_fails, caplog):
    state = tmp_path / "wechat"
    state.mkdir()
    channel = WechatChannel(bus=MessageBus(), config={"bot_token": "token", "state_dir": str(state)})
    _block_destination(channel._auth_path)

    # A persist failure is reported, not raised: the surviving signal is the log line,
    # so it has to carry the error that actually happened.
    with caplog.at_level(logging.WARNING):
        channel._save_auth_state(status="confirmed")

    records = [r for r in caplog.records if "failed to persist auth state" in r.getMessage()]
    assert len(records) == 1
    assert isinstance(records[0].exc_info[1], BLOCKED_RENAME_ERRORS)
    assert "Failed to remove temporary WeChat auth state file" in caplog.text


def test_runtime_config_store_keeps_the_close_error_and_still_unlinks(tmp_path, monkeypatch, caplog):
    path = tmp_path / "channels.json"
    store = ChannelRuntimeConfigStore(path)
    staged = path.parent / "staged.tmp"
    monkeypatch.setattr("tempfile.NamedTemporaryFile", lambda *args, **kwargs: _CloseFails(staged))

    with caplog.at_level(logging.WARNING), pytest.raises(OSError) as raised:
        store._save({"feishu": {"app_id": "id"}})

    assert raised.value.errno == 9
    assert "Failed to close temporary channel runtime config file" in caplog.text
    # The unlink is an independent step: it must still run after the close failed.
    assert not staged.exists()


def test_runtime_config_store_still_removes_the_staged_file(tmp_path):
    store = ChannelRuntimeConfigStore(tmp_path / "channels.json")
    _block_destination(store._path)

    with pytest.raises(BLOCKED_RENAME_ERRORS):
        store._save({"feishu": {"app_id": "id"}})

    assert _staged_files(tmp_path) == []


def test_a_raising_log_handler_does_not_replace_the_save_error(tmp_path, cleanup_fails, caplog):
    """Reporting the leaked file is itself best-effort.

    A handler can raise out of ``emit`` (a delayed ``FileHandler`` whose directory
    disappeared raises in the ``flush`` that ``StreamHandler.emit`` runs outside its
    own try/except), so the diagnostic call sits inside ``suppress``: a broken log
    must not become the error the caller sees, and must not skip remaining cleanup.
    """
    from app.channels import store as store_module

    class _RaisingHandler(logging.Handler):
        def emit(self, record):
            raise RuntimeError("Simulated logging failure")

    handler = _RaisingHandler(level=logging.WARNING)
    store_module.logger.addHandler(handler)
    try:
        path = tmp_path / "store.json"
        _block_destination(path)
        store = JsonChannelStore(path)
        store._data = {"feishu:chat": {"thread_id": "t"}}

        with caplog.at_level(logging.WARNING), pytest.raises(BLOCKED_RENAME_ERRORS) as raised:
            store._save()

        _assert_blocked_rename_error(raised.value)
    finally:
        store_module.logger.removeHandler(handler)


@pytest.mark.parametrize("failed_step", ["write", "close", "replace"])
@pytest.mark.parametrize("broken_handler", [False, True])
def test_buzz_failed_save_keeps_retryable_events_when_cleanup_and_logging_fail(tmp_path, monkeypatch, caplog, failed_step, broken_handler):
    from app.channels import buzz_seen_events as buzz_module

    path = tmp_path / "seen.json"
    store = buzz_module.BuzzSeenEventStore(path)
    store.record("chat", "existing")
    original_bytes = path.read_bytes()
    failure = OSError(5, f"primary {failed_step} failure")
    real_replace = Path.replace
    staged = tmp_path / "staged.tmp"
    attempted = []

    class CloseFails(_CloseFails):
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            self.close()

        def close(self):
            self._path.write_text("".join(self._written), encoding="utf-8")
            raise failure

    def fail_write(*args, **kwargs):
        raise failure

    def fail_replace(source, destination):
        if destination == path:
            raise failure
        return real_replace(source, destination)

    def fail_unlink(source, *args, **kwargs):
        attempted.append(source)
        raise PermissionError("temporary file is locked")

    handler = logging.FileHandler(tmp_path / "missing-log-directory" / "output.log", delay=True) if broken_handler else None
    if handler is not None:
        buzz_module.logger.addHandler(handler)
    try:
        with monkeypatch.context() as patch, caplog.at_level(logging.WARNING):
            if failed_step == "write":
                patch.setattr(buzz_module.json, "dump", fail_write)
            elif failed_step == "close":
                patch.setattr(buzz_module.tempfile, "NamedTemporaryFile", lambda *args, **kwargs: CloseFails(staged))
            else:
                patch.setattr(Path, "replace", fail_replace)
            patch.setattr(Path, "unlink", fail_unlink)
            store.record("chat", "pending")
    finally:
        if handler is not None:
            buzz_module.logger.removeHandler(handler)
            handler.close()

    assert attempted, "unlink must still run after a failing close or diagnostic"
    assert path.read_bytes() == original_bytes
    assert store.seen("chat", "pending")
    if not broken_handler:
        records = [record for record in caplog.records if "failed to persist seen-event store" in record.getMessage()]
        assert len(records) == 1
        assert records[0].exc_info[1] is failure
        assert any("temporary Buzz seen-event" in record.getMessage() for record in caplog.records)
    # The failed snapshot must remain dirty, including the event recorded before
    # the failure. A later flush retries without requiring a new incoming event.
    store.flush()
    assert buzz_module.BuzzSeenEventStore(path).seen("chat", "existing")
    assert buzz_module.BuzzSeenEventStore(path).seen("chat", "pending")


def test_buzz_write_and_close_failures_keep_the_original_persist_diagnostic(tmp_path, monkeypatch, caplog):
    from app.channels import buzz_seen_events as buzz_module

    primary = OSError("primary dump failure")
    staged = tmp_path / "staged.tmp"

    class CloseFails(_CloseFails):
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            self.close()

    def fail_dump(*args, **kwargs):
        raise primary

    with monkeypatch.context() as patch, caplog.at_level(logging.WARNING):
        patch.setattr(buzz_module.tempfile, "NamedTemporaryFile", lambda *args, **kwargs: CloseFails(staged))
        patch.setattr(buzz_module.json, "dump", fail_dump)
        assert buzz_module.BuzzSeenEventStore(tmp_path / "seen.json")._write_snapshot({"chat": ["pending"]}) is False

    records = [record for record in caplog.records if "failed to persist seen-event store" in record.getMessage()]
    assert len(records) == 1
    assert records[0].exc_info[1] is primary
    assert not staged.exists()


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
def test_buzz_interruption_cleans_staging_and_still_propagates(tmp_path, monkeypatch, interruption):
    from app.channels import buzz_seen_events as buzz_module

    primary = interruption("interrupted write")

    def interrupt(*args, **kwargs):
        raise primary

    with monkeypatch.context() as patch, pytest.raises(interruption) as raised:
        patch.setattr(buzz_module.json, "dump", interrupt)
        buzz_module.BuzzSeenEventStore(tmp_path / "seen.json")._write_snapshot({"chat": ["pending"]})

    assert raised.value is primary
    assert list(tmp_path.iterdir()) == []
