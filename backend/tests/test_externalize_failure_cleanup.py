"""A failed externalization must not leave a half-written output behind."""

import pathlib

from deerflow.agents.middlewares import tool_output_budget_middleware as mw


class _FailsAfterHalfTheWrite:
    """File object that fails part-way through the write, like a full disk."""

    def __init__(self, handle):
        self._handle = handle

    def write(self, data):
        self._handle.write(data[: len(data) // 2])
        self._handle.flush()
        raise OSError(28, "No space left on device")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._handle.close()
        return False


def test_failed_write_leaves_no_file_behind(tmp_path, monkeypatch):
    real_open = open

    def failing_open(path, mode="r", *args, **kwargs):
        handle = real_open(path, mode, *args, **kwargs)
        return _FailsAfterHalfTheWrite(handle) if "w" in mode else handle

    # open is a builtin, so it is not in the module dict to begin with.
    monkeypatch.setitem(mw.__dict__, "open", failing_open)

    result = mw._externalize(
        "X" * 100,
        tool_name="bash",
        tool_call_id="call_1",
        outputs_path=str(tmp_path),
        storage_subdir="sub",
    )

    assert result is None
    assert [p for p in pathlib.Path(tmp_path).rglob("*") if p.is_file()] == []


def test_successful_write_publishes_the_whole_content(tmp_path):
    result = mw._externalize(
        "Y" * 100,
        tool_name="bash",
        tool_call_id="call_2",
        outputs_path=str(tmp_path),
        storage_subdir="sub",
    )

    assert result is not None
    written = [p for p in pathlib.Path(tmp_path).rglob("*") if p.is_file()]
    assert len(written) == 1
    assert written[0].read_text(encoding="utf-8") == "Y" * 100
