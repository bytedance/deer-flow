"""Restored tool outputs retain the mounted sandbox's file access contract."""

import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from deerflow.agents.middlewares import tool_output_budget_middleware as mw


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are not available on Windows")
@pytest.mark.parametrize("mask", [0o022, 0o002, 0o077], ids=["other-readable", "group-writable", "private"])
@pytest.mark.parametrize("hook", ["sync", "async"])
def test_blob_restore_respects_gateway_umask(tmp_path, mask, hook):
    # umask is process-global: isolate changes from middleware worker threads.
    script = """
import asyncio
import json
import os
from pathlib import Path
import stat
import sys
from types import SimpleNamespace

from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import ToolMessage
from deerflow.agents.middlewares import tool_output_budget_middleware as mw
from deerflow.config.tool_output_config import ToolOutputConfig
from deerflow.storage.backends.local_fs import LocalFsBlobStore

root = Path(sys.argv[1])
os.umask(int(sys.argv[2]))
store = LocalFsBlobStore(root / "blobs")
mw.get_blob_store_if_enabled = lambda: store
content = "complete tool output\\n" * 2000
producer_outputs = root / "gateway-a" / "outputs"
runtime = SimpleNamespace(state={"thread_data": {"outputs_path": str(producer_outputs)}}, context={"thread_id": "thread-1"}, config={})
tool_request = SimpleNamespace(tool_call={"name": "remote_executor", "id": "call-1"}, runtime=runtime)
middleware = mw.ToolOutputBudgetMiddleware(config=ToolOutputConfig(max_chars=1000, externalize_min_chars=1000))
message = middleware.wrap_tool_call(tool_request, lambda request: ToolMessage(content=content, name="remote_executor", tool_call_id="call-1"))
assert mw.TOOL_OUTPUT_BLOB_KEY in message.additional_kwargs
payload = message.additional_kwargs[mw.TOOL_OUTPUT_BLOB_KEY]
relative = Path(payload["storage_subdir"]) / payload["virtual_path"].rsplit("/", 1)[1]
original = producer_outputs / relative
assert original.read_bytes() == content.encode()
modes = [stat.S_IMODE(original.stat().st_mode)]
# Recover only the checkpointed message and a shared real blob store.
restored_message = ToolMessage.model_validate_json(message.model_dump_json())
for scenario in ("missing", "mismatched"):
    outputs = root / scenario / "outputs"
    destination = outputs / relative
    if scenario == "mismatched":
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"stale output")
    request = ModelRequest(model=None, messages=[restored_message], tools=[], state={"thread_data": {"outputs_path": str(outputs)}})
    def handler(prepared):
        assert destination.read_bytes() == content.encode()
        modes.append(stat.S_IMODE(destination.stat().st_mode))
        return []
    if sys.argv[3] == "async":
        async def async_handler(prepared):
            return handler(prepared)
        asyncio.run(middleware.awrap_model_call(request, async_handler))
    else:
        middleware.wrap_model_call(request, handler)
    assert list(destination.parent.iterdir()) == [destination]
print(json.dumps({"modes": modes}))
"""
    completed = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(mask), hook], capture_output=True, text=True, timeout=30, check=True)
    assert json.loads(completed.stdout)["modes"] == [0o666 & ~mask] * 3


def test_restore_creation_collision_preserves_other_writers_temp(tmp_path, monkeypatch):
    destination = tmp_path / "output.txt"
    destination.write_bytes(b"previous complete output")
    other_temp = tmp_path / ".tool-output-collision.tmp"
    other_temp.write_bytes(b"another writer's pending output")
    monkeypatch.setattr(mw, "uuid", SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="collision")))

    assert mw._write_restored_output(str(destination), b"replacement") is False

    assert destination.read_bytes() == b"previous complete output"
    assert other_temp.read_bytes() == b"another writer's pending output"
    assert set(tmp_path.iterdir()) == {destination, other_temp}


@pytest.mark.parametrize("operation", ["fsync", "replace"])
def test_restore_failure_preserves_published_output_and_cleans_owned_temp(tmp_path, monkeypatch, operation):
    destination = tmp_path / "output.txt"
    destination.write_bytes(b"previous complete output")

    def fail(*args):
        raise OSError("storage unavailable")

    monkeypatch.setattr(mw.os, operation, fail)

    assert mw._write_restored_output(str(destination), b"replacement") is False

    assert destination.read_bytes() == b"previous complete output"
    assert list(tmp_path.iterdir()) == [destination]
