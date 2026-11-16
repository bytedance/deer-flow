"""Runtime channel config saves must merge with peer Gateway workers' saves.

Every Gateway worker builds its own ``ChannelRuntimeConfigStore`` over the same
``runtime-config.json``. Two store instances on one path stand in for two
workers here; the advisory file lock is per open file, so it also excludes the
two instances inside one test process.
"""

from __future__ import annotations

import os
import threading

import pytest

from app.channels.runtime_config_store import ChannelRuntimeConfigStore

TELEGRAM = {"enabled": True, "bot_token": "tg-token"}
SLACK = {"enabled": True, "bot_token": "xoxb-ui", "app_token": "xapp-ui"}


def _path(tmp_path):
    return tmp_path / "channels" / "runtime-config.json"


def test_save_keeps_a_provider_a_peer_saved_after_this_store_loaded(tmp_path):
    worker_a = ChannelRuntimeConfigStore(_path(tmp_path))
    worker_b = ChannelRuntimeConfigStore(_path(tmp_path))

    worker_a.set_provider_config("telegram", TELEGRAM)
    worker_b.set_provider_config("slack", SLACK)

    assert ChannelRuntimeConfigStore(_path(tmp_path)).load_all() == {"telegram": TELEGRAM, "slack": SLACK}
    # The saving worker's own snapshot also picks up the peer's provider.
    assert worker_b.get_provider_config("telegram") == TELEGRAM


def test_disconnect_survives_a_later_peer_save(tmp_path):
    ChannelRuntimeConfigStore(_path(tmp_path)).set_provider_config("slack", SLACK)
    worker_a = ChannelRuntimeConfigStore(_path(tmp_path))
    worker_b = ChannelRuntimeConfigStore(_path(tmp_path))

    worker_a.set_provider_disconnected("slack")
    worker_b.set_provider_config("telegram", TELEGRAM)

    assert ChannelRuntimeConfigStore(_path(tmp_path)).load_all() == {
        "slack": {"enabled": False, "_runtime_disabled": True},
        "telegram": TELEGRAM,
    }


def test_remove_sees_a_provider_a_peer_saved_after_this_store_loaded(tmp_path):
    worker_a = ChannelRuntimeConfigStore(_path(tmp_path))
    worker_b = ChannelRuntimeConfigStore(_path(tmp_path))
    worker_b.set_provider_config("slack", SLACK)

    assert worker_a.remove_provider_config("slack") is True
    assert ChannelRuntimeConfigStore(_path(tmp_path)).load_all() == {}


def test_save_over_a_corrupt_file_keeps_this_process_copy(tmp_path):
    store = ChannelRuntimeConfigStore(_path(tmp_path))
    store.set_provider_config("telegram", TELEGRAM)
    _path(tmp_path).write_text("{not json", encoding="utf-8")

    store.set_provider_config("slack", SLACK)

    assert ChannelRuntimeConfigStore(_path(tmp_path)).load_all() == {"telegram": TELEGRAM, "slack": SLACK}


def test_failed_save_leaves_the_served_snapshot_and_file_unchanged(tmp_path, monkeypatch):
    store = ChannelRuntimeConfigStore(_path(tmp_path))
    store.set_provider_config("telegram", TELEGRAM)

    def failing_save(*_args):
        raise OSError("disk full")

    monkeypatch.setattr(store, "_save", failing_save)
    with pytest.raises(OSError, match="disk full"):
        store.set_provider_config("slack", SLACK)

    assert store.load_all() == {"telegram": TELEGRAM}
    assert ChannelRuntimeConfigStore(_path(tmp_path)).load_all() == {"telegram": TELEGRAM}


def test_peer_mutation_waits_for_the_file_lock_before_reading(tmp_path):
    """The reload must sit inside the cross-process lock, not just before the write.

    Worker A stalls between reading and saving. Worker B's mutation must not
    read the file until A has saved; reading earlier would let A's save
    overwrite B's provider, or B's overwrite A's.
    """
    worker_a = ChannelRuntimeConfigStore(_path(tmp_path))
    worker_b = ChannelRuntimeConfigStore(_path(tmp_path))
    a_saving = threading.Event()
    release_a = threading.Event()
    b_loaded = threading.Event()

    real_save_a = worker_a._save

    def stalled_save(data):
        a_saving.set()
        assert release_a.wait(timeout=5)
        real_save_a(data)

    real_load_b = worker_b._load

    def observed_load(*args, **kwargs):
        b_loaded.set()
        return real_load_b(*args, **kwargs)

    worker_a._save = stalled_save
    worker_b._load = observed_load

    thread_a = threading.Thread(target=worker_a.set_provider_config, args=("telegram", TELEGRAM))
    thread_b = threading.Thread(target=worker_b.set_provider_config, args=("slack", SLACK))
    thread_a.start()
    try:
        assert a_saving.wait(timeout=5)
        thread_b.start()
        assert not b_loaded.wait(timeout=0.5)
    finally:
        release_a.set()
        thread_a.join(timeout=5)
        if thread_b.ident is not None:
            thread_b.join(timeout=5)

    assert b_loaded.is_set()
    assert ChannelRuntimeConfigStore(_path(tmp_path)).load_all() == {"telegram": TELEGRAM, "slack": SLACK}


@pytest.mark.skipif(os.name == "nt", reason="creating symlinks needs extra privileges on Windows")
def test_symlinked_store_path_shares_the_lock_of_its_target(tmp_path):
    """A worker configured with a symlinked spelling of the file must still exclude peers."""
    target = _path(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_text("{}", encoding="utf-8")
    link = target.parent / "runtime-config-link.json"
    link.symlink_to(target)
    via_link = ChannelRuntimeConfigStore(link)
    via_target = ChannelRuntimeConfigStore(target)
    link_saving = threading.Event()
    release_link = threading.Event()
    target_loaded = threading.Event()

    real_save = via_link._save

    def stalled_save(data):
        link_saving.set()
        assert release_link.wait(timeout=5)
        real_save(data)

    real_load = via_target._load

    def observed_load(*args, **kwargs):
        target_loaded.set()
        return real_load(*args, **kwargs)

    via_link._save = stalled_save
    via_target._load = observed_load

    thread_link = threading.Thread(target=via_link.set_provider_config, args=("telegram", TELEGRAM))
    thread_target = threading.Thread(target=via_target.set_provider_config, args=("slack", SLACK))
    thread_link.start()
    try:
        assert link_saving.wait(timeout=5)
        thread_target.start()
        assert not target_loaded.wait(timeout=0.5)
    finally:
        release_link.set()
        thread_link.join(timeout=5)
        if thread_target.ident is not None:
            thread_target.join(timeout=5)

    assert target_loaded.is_set()
