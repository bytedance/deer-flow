"""Issue #7461 — only executable content gets container paths translated.

``write_file`` rewrites container paths inside the bytes it stores so a script
the agent wrote can run under a host interpreter (PR #1935). Applying that to
documents put host paths into deliverables, and ``read_file`` masked the
rewrite for agent-written files, so the agent read back the virtual path and
reported content it had not stored. Documents, data, and configs are now
stored verbatim; code files keep the translation.
"""

from __future__ import annotations

import builtins
import os
import shutil
import threading
from pathlib import Path

import pytest

from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping


def _sandbox(tmp_path: Path) -> LocalSandbox:
    outputs = tmp_path / "outputs"
    workspace = tmp_path / "workspace"
    outputs.mkdir()
    workspace.mkdir()
    return LocalSandbox(
        id="test",
        path_mappings=[
            PathMapping(container_path="/mnt/user-data/outputs", local_path=str(outputs)),
            PathMapping(container_path="/mnt/user-data/workspace", local_path=str(workspace)),
        ],
    )


@pytest.mark.parametrize(
    "name,content",
    [
        ("README.md", "# Run notes\nThe results table is saved at /mnt/user-data/outputs/results.csv\n"),
        ("notes.txt", "see /mnt/user-data/outputs/results.csv and /mnt/user-data/workspace/plot.png\n"),
        ("data.csv", "label,path\nrows,/mnt/user-data/outputs/results.csv\n"),
        ("settings.json", '{"output": "/mnt/user-data/outputs/results.csv"}\n'),
        ("export.yaml", "output: /mnt/user-data/outputs/results.csv\n"),
    ],
    ids=["markdown", "text", "csv", "json", "yaml"],
)
def test_non_executable_content_is_stored_verbatim(tmp_path, name, content):
    """A dictation of exact bytes must survive the write and the read-back."""
    sandbox = _sandbox(tmp_path)
    virtual = f"/mnt/user-data/outputs/{name}"

    sandbox.write_file(virtual, content)

    stored = (tmp_path / "outputs" / name).read_bytes().decode("utf-8")
    assert stored == content
    # read_file returns the stored bytes, so the agent cannot claim a rewrite it did not see.
    assert sandbox.read_file(virtual) == content


def test_extensionless_document_without_shebang_is_stored_verbatim(tmp_path):
    """``README`` with no suffix is a document, not a program (the shared rule's negative case)."""
    sandbox = _sandbox(tmp_path)
    content = "Install notes: /mnt/user-data/workspace/setup.sh\n"

    sandbox.write_file("/mnt/user-data/outputs/README", content)

    assert (tmp_path / "outputs" / "README").read_text(encoding="utf-8") == content


def test_append_keeps_document_paths_virtual(tmp_path):
    sandbox = _sandbox(tmp_path)
    sandbox.write_file("/mnt/user-data/outputs/README.md", "# Run notes\n")
    sandbox.write_file("/mnt/user-data/outputs/README.md", "saved at /mnt/user-data/outputs/results.csv\n", append=True)

    assert (tmp_path / "outputs" / "README.md").read_text(encoding="utf-8") == ("# Run notes\nsaved at /mnt/user-data/outputs/results.csv\n")


def test_append_to_shebang_script_still_translates_paths(tmp_path):
    """An extensionless script's interpreter line stays at the top of the file."""
    sandbox = _sandbox(tmp_path)
    virtual = "/mnt/user-data/workspace/collect"
    sandbox.write_file(virtual, "#!/bin/bash\nset -eu\n")
    sandbox.write_file(virtual, "cat /mnt/user-data/outputs/results.csv\n", append=True)

    stored = (tmp_path / "workspace" / "collect").read_text(encoding="utf-8")
    assert stored.startswith("#!/bin/bash\n")
    assert "/mnt/user-data" not in stored


@pytest.mark.parametrize(
    "name,content",
    [
        ("plot.py", 'OUTPUT = "/mnt/user-data/outputs/results.csv"\n'),
        ("run.sh", 'export PATH="/mnt/user-data/workspace/bin:/mnt/user-data/outputs/bin"\n'),
        ("run", "#!/bin/bash\ncat /mnt/user-data/outputs/results.csv\n"),
    ],
    ids=["python", "shell", "shebang-without-suffix"],
)
def test_executable_content_still_translates_paths(tmp_path, name, content):
    """PR #1935: a script must see host paths, or ``bash``/``python`` cannot open them."""
    sandbox = _sandbox(tmp_path)
    virtual = f"/mnt/user-data/workspace/{name}"

    sandbox.write_file(virtual, content)

    stored = (tmp_path / "workspace" / name).read_text(encoding="utf-8")
    assert "/mnt/user-data" not in stored
    assert Path(os.path.realpath(tmp_path)).as_posix() in stored
    # The reverse translation keeps the agent's view consistent with what it wrote.
    assert sandbox.read_file(virtual) == content


@pytest.mark.parametrize("name", ["report.awk", "cleanup.sed", "plugin.lua", "plot.r", "run.tcl", "REPORT.AWK"])
def test_interpreter_script_suffixes_translate_container_paths(tmp_path, name):
    """``awk -f`` and friends open the script itself, so its container paths need host paths."""
    sandbox = _sandbox(tmp_path)
    content = 'BEGIN { while ((getline line < "/mnt/user-data/outputs/data.txt") > 0) print line }\n'
    virtual = f"/mnt/user-data/workspace/{name}"

    sandbox.write_file(virtual, content)

    stored = (tmp_path / "workspace" / name).read_text(encoding="utf-8")
    assert "/mnt/user-data" not in stored
    assert Path(os.path.realpath(tmp_path)).as_posix() in stored
    assert sandbox.read_file(virtual) == content


@pytest.mark.skipif(shutil.which("awk") is None, reason="awk is not installed")
def test_awk_script_written_through_the_sandbox_still_runs(tmp_path):
    """An AWK program that opens a container path must run through ``execute_command``."""
    sandbox = _sandbox(tmp_path)
    (tmp_path / "outputs" / "data.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    sandbox.write_file(
        "/mnt/user-data/workspace/report.awk",
        'BEGIN { while ((getline line < "/mnt/user-data/outputs/data.txt") > 0) print line }\n',
    )

    output = sandbox.execute_command("awk -f /mnt/user-data/workspace/report.awk /dev/null", timeout=20)

    assert "alpha" in output
    assert "beta" in output


def test_append_does_not_read_the_destination_before_classifying(tmp_path, monkeypatch):
    """A ``.py`` suffix already settles it, so the append must not open the file for reading."""
    sandbox = _sandbox(tmp_path)
    virtual = "/mnt/user-data/outputs/events.py"
    sandbox.write_file(virtual, "print('ready')\n")
    destination = os.path.realpath(tmp_path / "outputs" / "events.py")
    real_open = builtins.open

    def guard_reads(file, mode="r", *args, **kwargs):
        reads_only = not set(mode) & set("wa+")
        if isinstance(file, str) and reads_only and os.path.realpath(file) == destination:
            raise AssertionError("append opened the destination for reading")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guard_reads)

    sandbox.write_file(virtual, "print('appended')\n", append=True)

    assert (tmp_path / "outputs" / "events.py").read_text(encoding="utf-8") == "print('ready')\nprint('appended')\n"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes are a POSIX primitive")
@pytest.mark.parametrize("name", ["events.py", "events"], ids=["suffix-settles-the-answer", "extensionless-shebang-sniff"])
def test_append_to_a_named_pipe_does_not_block_while_classifying(tmp_path, name):
    """Classification must not wait on the destination, whichever shape settles it.

    A ``.py`` suffix settles the answer with no I/O; an extensionless name
    reaches the shebang sniff, which has to open the destination without
    waiting and reject the non-regular handle before reading. Reading a FIFO
    waits for the other end and for data; the append used to complete as soon
    as a reader was connected.
    """
    sandbox = _sandbox(tmp_path)
    fifo = tmp_path / "outputs" / name
    os.mkfifo(fifo)
    virtual = f"/mnt/user-data/outputs/{name}"
    received: list[str] = []

    def read_pipe() -> None:
        with open(fifo, encoding="utf-8") as reader:
            received.append(reader.read())

    reader_thread = threading.Thread(target=read_pipe, daemon=True)
    reader_thread.start()

    errors: list[BaseException] = []

    def append_pipe() -> None:
        try:
            sandbox.write_file(virtual, "ready\n", append=True)
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(exc)

    writer_thread = threading.Thread(target=append_pipe, daemon=True)
    writer_thread.start()
    writer_thread.join(5)

    assert not writer_thread.is_alive(), "append blocked while classifying the destination"
    assert errors == []
    reader_thread.join(5)
    assert received == ["ready\n"]
