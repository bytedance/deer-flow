"""Size-guard tests for write_file_tool (issue #3189, PR #3195).

These tests verify that write_file_tool rejects oversized single-shot payloads
with an actionable message, while leaving append-mode and env-override paths
untouched. They run purely against the tool's internal guard — no real sandbox
or filesystem is exercised, so they're fast and hermetic.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from deerflow.sandbox import tools as tools_module
from deerflow.sandbox.tools import write_file_tool


def _call_write_file(*, content: str, append: bool = False) -> str:
    """Invoke write_file_tool via its underlying callable.

    We patch the sandbox initialisation chain to a no-op MagicMock so the test
    focuses purely on the size guard. The guard runs BEFORE any sandbox call,
    so when the guard rejects we never enter the patched path; when the guard
    passes, the patched sandbox.write_file returns silently and the tool
    returns "OK".
    """
    fn = getattr(write_file_tool, "func", write_file_tool)
    runtime = MagicMock()

    with (
        patch.object(tools_module, "ensure_sandbox_initialized") as mock_ensure,
        patch.object(tools_module, "ensure_thread_directories_exist"),
        patch.object(tools_module, "is_local_sandbox", return_value=False),
        patch.object(tools_module, "get_file_operation_lock") as mock_lock,
    ):
        sandbox = MagicMock()
        sandbox.write_file = MagicMock()
        mock_ensure.return_value = sandbox
        mock_lock.return_value.__enter__ = MagicMock(return_value=None)
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)

        return fn(
            runtime=runtime,
            description="test write",
            path="/tmp/test.txt",
            content=content,
            append=append,
        )


def test_below_cap_succeeds():
    """A 79 KB payload sits comfortably under the 80 KB default and must pass
    straight through to the sandbox layer.
    """
    payload = "a" * (79 * 1024)
    result = _call_write_file(content=payload)
    assert result == "OK"


def test_above_cap_returns_actionable_error():
    """An 81 KB payload trips the guard. The error message must name the
    cap, the actual size, and steer the LLM toward str_replace / append=True
    — these are the exact handles Reviewer A/B asked for in PR #3195.
    """
    payload = "a" * (81 * 1024)
    result = _call_write_file(content=payload)

    assert result.startswith("Error: write_file content")
    assert "81920 bytes" in result or "82944 bytes" in result, "Error must report the actual content size so the LLM/operator can judge how much to trim or chunk."
    assert "str_replace" in result, "Error must point to str_replace as the preferred incremental-edit path."
    assert "append=True" in result, "Error must also surface the append-in-chunks alternative."


def test_above_cap_with_append_true_bypasses_guard():
    """append=True is the *correct* way to write a large document in chunks,
    so the guard must not block it. The 80 KB cap intentionally applies only
    to single-shot overwrite calls.
    """
    payload = "a" * (200 * 1024)  # 200 KB
    result = _call_write_file(content=payload, append=True)
    assert result == "OK", f"append=True must bypass the size guard, got: {result!r}"


def test_env_override_raises_cap(monkeypatch: pytest.MonkeyPatch):
    """Setting DEERFLOW_WRITE_FILE_MAX_BYTES lets deployments accept larger
    payloads when the underlying LLM/network can demonstrably handle them.
    """
    monkeypatch.setenv("DEERFLOW_WRITE_FILE_MAX_BYTES", str(300 * 1024))
    payload = "a" * (150 * 1024)  # 150 KB — would normally trip the 80 KB cap
    result = _call_write_file(content=payload)
    assert result == "OK"


def test_env_override_zero_disables_guard(monkeypatch: pytest.MonkeyPatch):
    """Setting the env var to 0 is the documented escape hatch for operators
    who want to opt out of the guard entirely (e.g. when running models with
    very large stream_chunk_timeout values).
    """
    monkeypatch.setenv("DEERFLOW_WRITE_FILE_MAX_BYTES", "0")
    payload = "a" * (500 * 1024)  # 500 KB
    result = _call_write_file(content=payload)
    assert result == "OK"


def test_env_override_malformed_falls_back_to_default(monkeypatch: pytest.MonkeyPatch):
    """A typo in the env var (e.g. 'lots') must not crash the tool — fall
    back silently to the safe 80 KB default. Crashing on every write because
    of a misconfigured env var would be far worse than ignoring it.
    """
    monkeypatch.setenv("DEERFLOW_WRITE_FILE_MAX_BYTES", "lots")
    # 100 KB should still be rejected because the malformed value falls back
    # to the 80 KB default.
    payload = "a" * (100 * 1024)
    result = _call_write_file(content=payload)
    assert result.startswith("Error: write_file content")
