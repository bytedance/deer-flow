"""Optional live VM checks for DeerFlow's local and cloud Smol provider.

Run ``DEER_FLOW_RUN_LIVE_TESTS=1 uv run --extra smol pytest -m live
 tests/test_smol_sandbox_live.py``. Cloud additionally requires
``DEER_FLOW_SMOL_CLOUD_LIVE=1`` and an authenticated ``smol auth login`` session.
"""

from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import pytest

from deerflow.community.smol import provider as smol_provider
from deerflow.config.sandbox_config import SandboxConfig

pytestmark = pytest.mark.live


@pytest.mark.parametrize("target", ["local", "cloud"])
def test_smol_vm_lifecycle_and_tools(monkeypatch, target):
    if os.getenv("DEER_FLOW_RUN_LIVE_TESTS") != "1":
        pytest.skip("Set DEER_FLOW_RUN_LIVE_TESTS=1 to enable VM tests")
    if target == "cloud" and os.getenv("DEER_FLOW_SMOL_CLOUD_LIVE") != "1":
        pytest.skip("Set DEER_FLOW_SMOL_CLOUD_LIVE=1 to enable cloud VM tests")
    pytest.importorskip("smol")
    config = SandboxConfig(
        use="deerflow.community.smol:SmolSandboxProvider",
        target=target,
        image="python:3.12-slim",
        cpus=1,
        memory_mb=512,
        environment={"DEFAULT_FLAG": "yes"},
    )
    monkeypatch.setattr(smol_provider, "get_app_config", lambda: SimpleNamespace(sandbox=config))
    instance = smol_provider.SmolSandboxProvider()
    try:
        thread_id = uuid.uuid4().hex
        sid = instance.acquire(thread_id, user_id="live-test")
        box = instance.get_scoped(sid, thread_id=thread_id, user_id="live-test")
        assert box is not None
        assert "ok=yes secret=available" in box.execute_command(
            'printf "ok=%s secret=%s" "$DEFAULT_FLAG" "$PER_CALL"',
            env={"PER_CALL": "available"},
        )
        assert "available" not in box.execute_command('printf "secret=%s" "$PER_CALL"')
        timed_out = box.execute_command("sleep 4", timeout=0.1 if target == "local" else 1)
        assert "time" in timed_out.lower()
        assert box.execute_command("printf after") == "after"
        path = "/mnt/user-data/workspace/deer-flow-smol.txt"
        box.write_file(path, "first\n")
        box.write_file(path, "second\n", append=True)
        assert box.read_file(path) == "first\nsecond\n"
        assert path in box.list_dir("/mnt/user-data/workspace")
        assert box.glob("/mnt/user-data/workspace", "*.txt")[0] == [path]
        assert box.grep("/mnt/user-data/workspace", "second", literal=True)[0][0].line_number == 2
        box.update_file(path, b"\x00\xff\n")
        assert box.download_file(path) == b"\x00\xff\n"
        instance.release(sid)
        assert instance.acquire(thread_id, user_id="live-test") == sid
        assert instance.get(sid).download_file(path) == b"\x00\xff\n"
    finally:
        instance.shutdown()
