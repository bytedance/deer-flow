"""Issue #7461 — only executable content gets container paths translated.

``write_file`` rewrites container paths inside the bytes it stores so a script
the agent wrote can run under a host interpreter (PR #1935). Applying that to
documents put host paths into deliverables, and ``read_file`` masked the
rewrite for agent-written files, so the agent read back the virtual path and
reported content it had not stored. Documents, data, and configs are now
stored verbatim; code files keep the translation.
"""

from __future__ import annotations

import os
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
