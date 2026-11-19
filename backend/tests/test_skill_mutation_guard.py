"""The same owner lock protects exports, old writers and new publication."""

import os
import subprocess
import sys
import threading

import pytest

from deerflow.skills.projection import _projection_lock, skill_projection_read_lock
from deerflow.skills.storage.local_skill_storage import LocalSkillStorage


def test_read_guard_is_reentrant_inside_existing_writer(tmp_path):
    storage = LocalSkillStorage(host_path=str(tmp_path))
    with _projection_lock(tmp_path / "custom"):
        with skill_projection_read_lock(storage, timeout=0.05):
            pass


def test_guard_wait_is_bounded_across_threads(tmp_path):
    storage = LocalSkillStorage(host_path=str(tmp_path))
    held, release = threading.Event(), threading.Event()

    def holder():
        with _projection_lock(tmp_path / "custom"):
            held.set()
            release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    try:
        assert held.wait(2)
        with pytest.raises(TimeoutError):
            with skill_projection_read_lock(storage, timeout=0.05):
                pytest.fail("Concurrent writer lock was bypassed")
    finally:
        release.set()
        thread.join(2)


@pytest.mark.skipif(os.name != "posix", reason="POSIX publication locks")
def test_another_process_cannot_bypass_owner_guard_and_kill_releases_it(tmp_path):
    script = """
import sys
from pathlib import Path
from deerflow.skills.projection import _projection_lock
with _projection_lock(Path(sys.argv[1]) / 'custom'):
    print('locked', flush=True)
    sys.stdin.read()
"""
    child = subprocess.Popen([sys.executable, "-c", script, str(tmp_path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "locked"
        storage = LocalSkillStorage(host_path=str(tmp_path))
        with pytest.raises(TimeoutError):
            with skill_projection_read_lock(storage, timeout=0.05):
                pytest.fail("process bypassed owner lock")
        child.kill()
        child.wait(timeout=5)
        with skill_projection_read_lock(storage, timeout=0.5):
            pass
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=5)
