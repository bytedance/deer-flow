"""A failed discard must not replace the outcome of an agent file publish.

``_publish_text`` writes an agent's ``SOUL.md``/config through a same-directory
temporary. On Windows a scanner or a peer holding the handle can make the
removal fail after a successful ``os.replace`` — or while another error is
already propagating — and the cleanup error used to win.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def real_unlink():
    return Path.unlink


def _fail_unlink_on(monkeypatch, predicate, real_unlink):
    def unlink(self, *args, **kwargs):
        if predicate(self):
            raise PermissionError("temporary unlink failed")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)


def test_publish_text_keeps_the_replace_error_when_cleanup_fails(tmp_path, monkeypatch, real_unlink):
    from deerflow.tools.builtins import setup_agent_tool as module

    target = tmp_path / "SOUL.md"
    target.write_text("original", encoding="utf-8")

    def _failing_replace(self, *args, **kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", _failing_replace)
    _fail_unlink_on(monkeypatch, lambda path: path.suffix == ".tmp", real_unlink)

    with pytest.raises(OSError, match="replace failed"):
        module._publish_text(target, "replacement")

    assert target.read_text(encoding="utf-8") == "original"


def test_publish_text_still_succeeds_and_leaves_no_temporary(tmp_path, caplog):
    from deerflow.tools.builtins import setup_agent_tool as module

    target = tmp_path / "SOUL.md"
    target.write_text("original", encoding="utf-8")
    caplog.clear()

    with caplog.at_level("WARNING", logger="deerflow.utils.atomic_write"):
        module._publish_text(target, "replacement")

    assert target.read_text(encoding="utf-8") == "replacement"
    # The staged name comes from ``NamedTemporaryFile`` (``tmpXXXXXXXX.tmp``), so
    # assert the whole directory: nothing leaked and nothing else was created.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["SOUL.md"]
    assert caplog.text == ""


def test_publish_text_survives_a_discard_that_fails_after_publishing(tmp_path, monkeypatch, caplog, real_unlink):
    """Removal can fail after a successful replace; the publish must still stand."""
    from deerflow.tools.builtins import setup_agent_tool as module

    target = tmp_path / "SOUL.md"
    target.write_text("original", encoding="utf-8")
    caplog.clear()
    _fail_unlink_on(monkeypatch, lambda path: path.suffix == ".tmp", real_unlink)

    with caplog.at_level("WARNING", logger="deerflow.utils.atomic_write"):
        module._publish_text(target, "replacement")

    assert target.read_text(encoding="utf-8") == "replacement"
    assert "Failed to remove temporary output file" in caplog.text
