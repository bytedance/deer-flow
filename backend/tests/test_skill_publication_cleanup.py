"""A failed discard must not replace the outcome of a skill publication.

``replace_main`` publishes ``SKILL.md`` through a ``.host-mutation-*`` sibling and
discards it on exit. That discard only tolerated ``FileNotFoundError``, so any
other ``OSError`` replaced the publish error — or turned a decided outcome into a
cleanup failure. A leftover from a failed publication is swept later by
``cleanup_temporary`` when ``resolve_prepared`` classifies the outcome, so
reporting is enough here; ``assert_temporary_absent`` never sees it, because its
only caller checks a freshly minted operation id.
"""

from __future__ import annotations

import os

import pytest

# ``replace_main`` walks directory descriptors with ``O_DIRECTORY``/``O_NOFOLLOW``.
pytestmark = pytest.mark.skipif(os.name != "posix", reason="host skill mutation tests require POSIX filesystem primitives")


def _make_skill_dir(tmp_path):
    root = tmp_path / "skills" / "example"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text("original\n", encoding="utf-8")
    return root


def test_replace_main_keeps_the_publish_error_when_cleanup_fails(tmp_path, monkeypatch, caplog):
    from deerflow.skills.mutations import publication

    root = _make_skill_dir(tmp_path)
    real_unlink = publication.os.unlink

    def failing_fsync(_fd):
        raise OSError("disk error")

    def failing_unlink(path, *args, **kwargs):
        if str(path).startswith(".host-mutation-"):
            raise PermissionError("temporary is still open")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(publication.os, "fsync", failing_fsync)
    monkeypatch.setattr(publication.os, "unlink", failing_unlink)

    with caplog.at_level("WARNING", logger="deerflow.skills.mutations.publication"):
        with pytest.raises(OSError, match="disk error"):
            publication.replace_main(root, b"replacement\n", operation_id="cleanup")

    assert (root / "SKILL.md").read_text(encoding="utf-8") == "original\n"
    assert "Failed to remove skill mutation temporary" in caplog.text


def test_replace_main_still_publishes_and_removes_the_temporary(tmp_path):
    from deerflow.skills.mutations import publication

    root = _make_skill_dir(tmp_path)

    publication.replace_main(root, b"replacement\n", operation_id="clean")

    assert (root / "SKILL.md").read_text(encoding="utf-8") == "replacement\n"
    assert [p.name for p in root.parent.iterdir() if p.name.startswith(".host-mutation-")] == []


def test_replace_main_survives_a_discard_that_fails_after_publishing(tmp_path, monkeypatch, caplog):
    """A discard can fail after a successful replace; the publish must still stand."""
    from deerflow.skills.mutations import publication

    root = _make_skill_dir(tmp_path)
    real_unlink = publication.os.unlink

    def failing_unlink(path, *args, **kwargs):
        if str(path).startswith(".host-mutation-"):
            raise PermissionError("temporary is still open")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(publication.os, "unlink", failing_unlink)

    with caplog.at_level("WARNING", logger="deerflow.skills.mutations.publication"):
        publication.replace_main(root, b"replacement\n", operation_id="late-discard")

    assert (root / "SKILL.md").read_text(encoding="utf-8") == "replacement\n"
    assert "Failed to remove skill mutation temporary" in caplog.text
