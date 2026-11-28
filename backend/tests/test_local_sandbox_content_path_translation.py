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
import errno
import os
import shutil
import threading
import tracemalloc
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


def test_download_file_reverse_resolves_paths_for_agent_written_script(tmp_path):
    """Issue #8259 — download_file must mirror read_file for agent-written scripts.

    ``write_file`` stores host paths on disk so the script runs; ``read_file``
    reverse-resolves them back to virtual paths. ``download_file`` returned the
    raw on-disk bytes, leaking the host absolute path (DEER_FLOW_HOME, username,
    thread id) and disagreeing with what the agent verified via ``read_file``.
    """
    sandbox = _sandbox(tmp_path)
    virtual = "/mnt/user-data/workspace/run.sh"
    content = "#!/bin/sh\ncat /mnt/user-data/outputs/data.csv\n"

    sandbox.write_file(virtual, content)

    stored = (tmp_path / "workspace" / "run.sh").read_text(encoding="utf-8")
    assert "/mnt/user-data" not in stored  # host paths live on disk
    assert sandbox.read_file(virtual) == content
    assert sandbox.download_file(virtual) == content.encode("utf-8")


def test_download_file_leaves_binary_bytes_identical(tmp_path):
    """Binary downloads stay byte-identical even for agent-written paths."""
    sandbox = _sandbox(tmp_path)
    virtual = "/mnt/user-data/workspace/model.bin"
    sandbox.write_file(virtual, "placeholder\n")
    raw = b"\x89PNG\r\n\x1a\n\x00\xff\xfe binary \x80\x81"
    (tmp_path / "workspace" / "model.bin").write_bytes(raw)

    assert sandbox.download_file(virtual) == raw


def test_download_file_does_not_reverse_resolve_non_agent_file(tmp_path):
    """Only agent-written files get reverse-resolved, mirroring read_file."""
    sandbox = _sandbox(tmp_path)
    host_path = str(tmp_path / "outputs" / "data.csv")
    content = f"see {host_path}\n"
    (tmp_path / "outputs" / "report.txt").write_text(content, encoding="utf-8")

    assert sandbox.download_file("/mnt/user-data/outputs/report.txt") == content.encode("utf-8")


def test_download_file_leaves_valid_utf8_binary_overwrite_identical(tmp_path):
    """PR #8260 (Codex P2 on #8259): a tracked path later overwritten with
    binary data must download byte-identical, even when the bytes validly
    decode as UTF-8 and contain a mapped host path.

    The old code used a successful UTF-8 decode as the text/binary test, so
    it reverse-resolved the host path inside the binary payload and the
    download no longer matched the file on disk.
    """
    sandbox = _sandbox(tmp_path)
    virtual = "/mnt/user-data/workspace/run.sh"
    sandbox.write_file(virtual, "#!/bin/sh\ncat /mnt/user-data/outputs/data.csv\n")

    host_path = os.path.realpath(tmp_path / "outputs" / "data.csv")
    raw = f"PK\x03\x04\x00binary blob {host_path} \x01\x02 tail\n".encode()
    raw.decode("utf-8")  # the payload is valid UTF-8 — that must not matter
    (tmp_path / "workspace" / "run.sh").write_bytes(raw)

    assert sandbox.download_file(virtual) == raw


def test_download_file_after_rewrite_without_translation_stays_identical(tmp_path):
    """Rewriting a translated script through write_file with content that
    translates nothing drops the translation record: the stored bytes are
    verbatim agent content, not a translated write, so the download must
    return them untouched even though they contain a host path.
    """
    sandbox = _sandbox(tmp_path)
    virtual = "/mnt/user-data/workspace/run.sh"
    sandbox.write_file(virtual, "#!/bin/sh\ncat /mnt/user-data/outputs/data.csv\n")

    host_path = os.path.realpath(tmp_path / "outputs" / "data.csv")
    rewritten = f"binary blob {host_path}\n"
    sandbox.write_file(virtual, rewritten)

    assert (tmp_path / "workspace" / "run.sh").read_text(encoding="utf-8") == rewritten
    assert sandbox.download_file(virtual) == rewritten.encode("utf-8")


def test_download_file_reverse_resolves_after_append_to_script(tmp_path):
    """An appending translating write extends the recorded digest, so a
    script built up over two write_file calls still reverse-resolves on
    download, matching read_file.
    """
    sandbox = _sandbox(tmp_path)
    virtual = "/mnt/user-data/workspace/run.sh"
    sandbox.write_file(virtual, "#!/bin/sh\n")
    sandbox.write_file(virtual, "cat /mnt/user-data/outputs/data.csv\n", append=True)

    expected = b"#!/bin/sh\ncat /mnt/user-data/outputs/data.csv\n"
    assert sandbox.read_file(virtual) == expected.decode("utf-8")
    assert sandbox.download_file(virtual) == expected


def test_download_file_enforces_limit_on_restored_bytes(tmp_path):
    """The size ceiling applies to the bytes download_file returns, not
    only to the bytes on disk: reverse resolution can expand the payload
    when a short host path stands in for a longer virtual one, so a file
    that fits the limit on disk can still exceed it once restored.
    """
    outputs = tmp_path / "o"
    outputs.mkdir()
    # A virtual prefix far longer than any host temp path, so restoring it
    # measurably expands the payload over what is stored on disk.
    prefix = "/mnt/user-data/" + "/".join(["segment"] * 16) + "/outputs"
    sandbox = LocalSandbox(
        id="test",
        path_mappings=[PathMapping(container_path=prefix, local_path=str(outputs))],
    )
    virtual = f"{prefix}/run.sh"
    content = f"#!/bin/sh\ncat {prefix}/data.csv\n"
    sandbox.write_file(virtual, content)

    stored_size = (outputs / "run.sh").stat().st_size
    restored = content.encode()
    assert stored_size < len(restored)  # the fixture must really expand on restore

    assert sandbox.download_file(virtual, max_bytes=len(restored)) == restored
    with pytest.raises(OSError) as excinfo:
        sandbox.download_file(virtual, max_bytes=stored_size)
    assert excinfo.value.errno == errno.EFBIG


def test_download_file_applies_limit_to_fully_restored_output(tmp_path):
    """willem-bd P2 on #8260 (2026-11-17): the download limit applies to
    the fully restored output, not to each mapping pass. With two custom
    mounts, the first pass (longest local root first) expands paths and
    the second contracts them, so a limit equal to the stored size must
    still return the restored bytes when they fit — the old per-pass cap
    raised EFBIG on the intermediate expansion instead.
    """
    expanding_host = tmp_path / ("a" * 80)
    expanding_host.mkdir()
    contracting_host = tmp_path / ("b" * 40)
    contracting_host.mkdir()
    # The expanding mount's virtual root is far longer than its host root;
    # the contracting mount's virtual root is a single short segment.
    expanding_virtual = "/mnt/user-data/" + "/".join(["segment"] * 48) + "/outputs"
    contracting_virtual = "/m"
    sandbox = LocalSandbox(
        id="test",
        path_mappings=[
            PathMapping(container_path=expanding_virtual, local_path=str(expanding_host)),
            PathMapping(container_path=contracting_virtual, local_path=str(contracting_host)),
        ],
    )
    virtual = f"{expanding_virtual}/run.sh"
    expand_line = f"cat {expanding_virtual}/data.csv\n"
    contract_line = f"cat {contracting_virtual}/data.csv\n"
    # Size the fixture from the resolved host paths, so the net contraction
    # holds whatever the temporary directory is called: one expanding line
    # and enough contracting lines that the restored bytes fit the stored
    # size, while the first pass alone still expands past it.
    expand_growth = len(expand_line) - len(f"cat {os.path.realpath(expanding_host)}/data.csv\n")
    contract_shrink = len(f"cat {os.path.realpath(contracting_host)}/data.csv\n") - len(contract_line)
    assert expand_growth > 0  # the first pass really expands
    assert contract_shrink > 0  # the second pass really contracts
    n_contract = (expand_growth + 50) // contract_shrink + 1
    content = "#!/bin/sh\n" + expand_line + contract_line * n_contract
    sandbox.write_file(virtual, content)

    stored = (expanding_host / "run.sh").read_bytes()
    restored = content.encode("utf-8")
    assert b"/mnt/user-data" not in stored  # host paths live on disk
    assert len(restored) < len(stored)  # net contraction: the limit fits

    assert sandbox.download_file(virtual, max_bytes=len(stored)) == restored


def test_download_file_bounds_restored_bytes_while_substituting(tmp_path):
    """The size ceiling must bound the substitution itself, not only the
    result: with a virtual root far longer than the host root, repeated
    translated paths expand the payload far beyond the limit, and building
    the whole expanded string before checking would materialize the very
    bytes the ceiling exists to refuse (Codex P2 on #8260).
    """
    outputs = tmp_path / "o"
    outputs.mkdir()
    # A virtual prefix far longer than any host temp path, so restoring it
    # expands the payload an order of magnitude over what is stored.
    prefix = "/mnt/user-data/" + "/".join(["segment"] * 128) + "/outputs"
    sandbox = LocalSandbox(
        id="test",
        path_mappings=[PathMapping(container_path=prefix, local_path=str(outputs))],
    )
    virtual = f"{prefix}/run.sh"
    line = f"cat {prefix}/data.csv\n"
    content = "#!/bin/sh\n" + line * 50
    sandbox.write_file(virtual, content)

    stored_size = (outputs / "run.sh").stat().st_size
    restored = content.encode()
    assert stored_size < len(restored)  # the fixture must really expand on restore

    tracemalloc.start()
    try:
        with pytest.raises(OSError) as excinfo:
            sandbox.download_file(virtual, max_bytes=stored_size)
    finally:
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    assert excinfo.value.errno == errno.EFBIG
    # The refused payload is never materialized: peak memory stays well
    # below the size of the expanded string the old code built first.
    # The traced allocation includes reading and decoding the stored file,
    # whose size grows with the host temporary directory name on every
    # repeated path — so the bound is sized by the stored bytes, not by a
    # fixed fraction of the restored size, or a longer pytest root fails
    # it (willem-bd P3 on #8260: 27,094 bytes against 26,505 under the
    # default macOS pytest directory). The stored file is read, decoded,
    # and substituted under the budget, so peak stays near three stored
    # sizes plus one replacement piece and tracing overhead.
    assert peak < 4 * stored_size + 8192
    assert peak < len(restored)
