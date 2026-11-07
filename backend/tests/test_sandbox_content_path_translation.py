"""Issue #7466 — write_file stores document bytes verbatim.

Path translation inside content exists so an agent-written script can run
under a host interpreter (PR #1935). A document whose dictated text names a
virtual path (e.g. README.md mentioning /mnt/user-data/outputs/results.csv)
must keep that exact virtual path in the stored bytes: the pre-#7461
behavior rewrote deliverables to host paths while read_file masked the
change back, so the agent confirmed content the store never held.

The sandbox maps `/mnt/user-data`, which covers the path named in CONTENT:
with blanket translation the stored bytes differ, so these tests pin the
behavior instead of passing vacuously.
"""

from __future__ import annotations

import pytest

from deerflow.sandbox.local.local_sandbox import (
    LocalSandbox,
    PathMapping,
    _content_path_translation_applies,
)


def _make_sandbox(tmp_path):
    data = tmp_path / "user-data"
    skills = tmp_path / "skills"
    data.mkdir()
    skills.mkdir()
    return LocalSandbox(
        id="test",
        path_mappings=[
            PathMapping(container_path="/mnt/user-data", local_path=str(data)),
            PathMapping(container_path="/mnt/skills", local_path=str(skills), read_only=True),
        ],
    )


CONTENT = "The results table is saved at /mnt/user-data/outputs/results.csv\n"


@pytest.mark.parametrize(
    "name",
    ["README.md", "results.csv", "config.yaml", "notes.txt", "report.pdf", "data.json"],
)
def test_document_suffixes_are_stored_verbatim(tmp_path, name):
    sb = _make_sandbox(tmp_path)
    sb.write_file(f"/mnt/user-data/outputs/{name}", CONTENT)
    stored = (tmp_path / "user-data" / "outputs" / name).read_text(encoding="utf-8")
    assert stored == CONTENT, f"{name} bytes were rewritten with host paths"


def test_document_read_back_matches_stored_bytes(tmp_path):
    sb = _make_sandbox(tmp_path)
    sb.write_file("/mnt/user-data/outputs/README.md", CONTENT)
    assert sb.read_file("/mnt/user-data/outputs/README.md") == CONTENT


def test_script_content_is_still_translated(tmp_path):
    """Executable content keeps the PR #1935 behavior: host-resolvable paths."""
    sb = _make_sandbox(tmp_path)
    script = "OUT=/mnt/user-data/outputs/results.csv\n"
    sb.write_file("/mnt/user-data/outputs/run.sh", script)
    outputs_local = str((tmp_path / "user-data" / "outputs").resolve()).replace("\\", "/")
    stored = (tmp_path / "user-data" / "outputs" / "run.sh").read_text(encoding="utf-8")
    assert stored == f"OUT={outputs_local}/results.csv\n"
    # read_file reverse-resolves agent-written scripts back to virtual paths
    assert sb.read_file("/mnt/user-data/outputs/run.sh") == script


def test_classifier_by_suffix_and_shebang(tmp_path):
    resolved = str(tmp_path / "user-data" / "outputs" / "x")
    assert _content_path_translation_applies("/mnt/user-data/outputs/run.py", CONTENT, append=False, resolved_path=resolved)
    assert _content_path_translation_applies("/mnt/user-data/outputs/run.sh", CONTENT, append=False, resolved_path=resolved)
    for doc in ("README.md", "results.csv", "config.yaml", "notes.txt"):
        assert not _content_path_translation_applies(f"/mnt/user-data/outputs/{doc}", CONTENT, append=False, resolved_path=resolved), doc
    # An extensionless file with a shebang is a script; without one it is not.
    assert _content_path_translation_applies("/mnt/user-data/outputs/run", "#!/bin/sh\n", append=False, resolved_path=resolved)
    assert not _content_path_translation_applies("/mnt/user-data/outputs/run", CONTENT, append=False, resolved_path=resolved)


def test_append_to_document_does_not_translate(tmp_path):
    sb = _make_sandbox(tmp_path)
    sb.write_file("/mnt/user-data/outputs/README.md", CONTENT)
    sb.write_file(
        "/mnt/user-data/outputs/README.md",
        "Appendix: see /mnt/user-data/outputs/extra.csv\n",
        append=True,
    )
    stored = (tmp_path / "user-data" / "outputs" / "README.md").read_text(encoding="utf-8")
    assert stored == CONTENT + "Appendix: see /mnt/user-data/outputs/extra.csv\n"
