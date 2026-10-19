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
from pathlib import Path

import pytest

from app.channels.message_bus import MessageBus
from app.channels.runtime_config_store import ChannelRuntimeConfigStore
from app.channels.store import JsonChannelStore
from app.channels.wechat import WechatChannel

CLEANUP_ERRNO = 28


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

    with caplog.at_level(logging.WARNING), pytest.raises(IsADirectoryError) as raised:
        store._save()

    assert raised.value.errno == 21
    assert "Failed to remove temporary channel store file" in caplog.text


def test_runtime_config_store_keeps_the_save_error(tmp_path, cleanup_fails, caplog):
    store = ChannelRuntimeConfigStore(tmp_path / "channels.json")
    _block_destination(store._path)

    with caplog.at_level(logging.WARNING), pytest.raises(IsADirectoryError) as raised:
        store._save({"feishu": {"app_id": "id"}})

    assert raised.value.errno == 21
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
    assert isinstance(records[0].exc_info[1], IsADirectoryError)
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

    with pytest.raises(IsADirectoryError):
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

        with caplog.at_level(logging.WARNING), pytest.raises(IsADirectoryError) as raised:
            store._save()

        assert raised.value.errno == 21
    finally:
        store_module.logger.removeHandler(handler)
