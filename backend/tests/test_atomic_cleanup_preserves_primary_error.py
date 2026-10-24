# SPDX-License-Identifier: MIT
"""Failed publications report their own error, not the cleanup's.

Three writers publish through a same-directory temporary and then clean it up
inside the handler for a failure they are already reporting. Left unguarded,
two distinct defects appear:

* a failing ``unlink`` replaces the error the caller sees — the real cause
  survives only as ``__context__``, which the surrounding
  ``logger.warning("...: %s", exc)`` formats never print;
* a ``with os.fdopen(fd, ...)`` that never binds leaks ``fd``, because the
  ``with`` cannot close a descriptor it never received.

``uploads/companions.py`` is the strongest case: after a successful
``os.replace`` the staged name was already gone, so the unguarded ``finally``
only ever ran on the failure path, where its own error replaced the
``json.dump``/``os.replace`` one the caller needed.

Sites are pinned separately because they own different parts of the pipeline.
The channel publishers (#7106), project staging (#7141), the extension manager
and the Gateway skill-archive copy (#7164) are deliberately not repeated here.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest


class _PrimaryError(Exception):
    """Stand-in for the failure a publisher is already reporting."""


class _Records(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def _fail_unlink_on(monkeypatch, predicate, real_unlink):
    """Make ``Path.unlink`` (and ``os.unlink``) raise for the paths we own."""

    def unlink(self, *args, **kwargs):
        if predicate(self):
            raise PermissionError("temporary unlink failed")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)


def _capture_atomic_write_warnings(monkeypatch):
    """Point ``deerflow.utils.atomic_write`` diagnostics at a recording handler."""
    from deerflow.utils import atomic_write

    records = _Records()
    monkeypatch.setattr(atomic_write.logger, "handlers", [records])
    monkeypatch.setattr(atomic_write.logger, "propagate", False)
    monkeypatch.setattr(atomic_write.logger, "level", logging.WARNING)
    return records


@pytest.fixture
def real_unlink():
    return Path.unlink


def _is_temporary_of(target):
    """Match the ``.{name}.<random>.tmp`` sibling these helpers allocate."""

    def predicate(path: Path) -> bool:
        return path.parent == target.parent and path.name.startswith(f".{target.name}.") and path.suffix == ".tmp"

    return predicate


# --------------------------------------------------------------------------
# integrations/lark_cli.py::_publish_bytes_atomically
# --------------------------------------------------------------------------


def _publish_lark(target, content):
    from deerflow.integrations import lark_cli

    lark_cli._publish_bytes_atomically(target, content)


def test_lark_cli_publish_preserves_primary_error_when_unlink_fails(tmp_path, monkeypatch, real_unlink):
    target = tmp_path / "lark-cli"
    target.write_bytes(b"previous runtime")
    primary = _PrimaryError("publication failed")

    def replace(source, path):
        raise primary

    monkeypatch.setattr(os, "replace", replace)
    _fail_unlink_on(monkeypatch, _is_temporary_of(target), real_unlink)
    records = _capture_atomic_write_warnings(monkeypatch)

    with pytest.raises(_PrimaryError) as raised:
        _publish_lark(target, b"new runtime")

    assert raised.value is primary
    assert raised.value.__context__ is None
    assert target.read_bytes() == b"previous runtime"
    # The leftover temporary is named in the diagnostic instead of silently
    # becoming the reported failure.
    assert len(records.records) == 1
    assert records.records[0].exc_info is not None
    assert any(_is_temporary_of(target)(path) for path in tmp_path.iterdir())


def test_lark_cli_publish_closes_the_descriptor_when_fdopen_fails(tmp_path, monkeypatch):
    target = tmp_path / "lark-cli"
    primary = _PrimaryError("fdopen failed")
    allocated: list[int] = []

    def fdopen(fd, *args, **kwargs):
        allocated.append(fd)
        raise primary

    monkeypatch.setattr(os, "fdopen", fdopen)
    records = _capture_atomic_write_warnings(monkeypatch)

    with pytest.raises(_PrimaryError) as raised:
        _publish_lark(target, b"new runtime")

    assert raised.value is primary
    assert len(allocated) == 1
    # A leaked descriptor is still open, so fstat would succeed.
    with pytest.raises(OSError):
        os.fstat(allocated[0])
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []
    assert records.records == []


def test_lark_cli_publish_success_is_unchanged(tmp_path):
    target = tmp_path / "lark-cli"

    _publish_lark(target, b"#!/bin/sh\n")

    assert target.read_bytes() == b"#!/bin/sh\n"
    assert list(tmp_path.iterdir()) == [target]


# --------------------------------------------------------------------------
# integrations/lark_broker.py::_write_text_atomically
# --------------------------------------------------------------------------


def _write_broker_launcher(path, content):
    from deerflow.integrations import lark_broker

    lark_broker._write_text_atomically(str(path), content, mode=0o755)


def test_lark_broker_launcher_closes_the_descriptor_when_fdopen_fails(tmp_path, monkeypatch):
    target = tmp_path / "bin" / "lark-cli"
    target.parent.mkdir()
    primary = _PrimaryError("fdopen failed")
    allocated: list[int] = []

    def fdopen(fd, *args, **kwargs):
        allocated.append(fd)
        raise primary

    monkeypatch.setattr(os, "fdopen", fdopen)
    records = _capture_atomic_write_warnings(monkeypatch)

    with pytest.raises(_PrimaryError) as raised:
        _write_broker_launcher(target, "#!/bin/sh\n")

    assert raised.value is primary
    assert len(allocated) == 1
    with pytest.raises(OSError):
        os.fstat(allocated[0])
    assert list(target.parent.iterdir()) == []
    assert records.records == []


def test_lark_broker_launcher_preserves_primary_error_when_unlink_fails(tmp_path, monkeypatch, real_unlink):
    target = tmp_path / "bin" / "lark-cli"
    target.parent.mkdir()
    target.write_text("old launcher", encoding="utf-8")
    primary = _PrimaryError("chmod failed")

    def chmod(path, mode, *args, **kwargs):
        raise primary

    monkeypatch.setattr(os, "chmod", chmod)
    _fail_unlink_on(monkeypatch, _is_temporary_of(target), real_unlink)
    records = _capture_atomic_write_warnings(monkeypatch)

    with pytest.raises(_PrimaryError) as raised:
        _write_broker_launcher(target, "new launcher")

    assert raised.value is primary
    assert raised.value.__context__ is None
    assert target.read_text(encoding="utf-8") == "old launcher"
    # Previously this cleanup failure was swallowed by `except OSError: pass`,
    # leaving an unobservable leftover; now it is reported.
    assert len(records.records) == 1
    assert any(_is_temporary_of(target)(path) for path in target.parent.iterdir())


def test_lark_broker_launcher_success_is_unchanged(tmp_path):
    target = tmp_path / "bin" / "lark-cli"
    target.parent.mkdir()

    _write_broker_launcher(target, "#!/bin/sh\nexec lark-cli\n")

    assert target.read_text(encoding="utf-8") == "#!/bin/sh\nexec lark-cli\n"
    assert list(target.parent.iterdir()) == [target]


# --------------------------------------------------------------------------
# uploads/companions.py::register_companion
# --------------------------------------------------------------------------


def _prepare_companion(tmp_path):
    uploads = tmp_path / "thread" / "uploads"
    uploads.mkdir(parents=True)
    original = uploads / "report.pdf"
    original.write_bytes(b"source")
    markdown = uploads / "report.md"
    markdown.write_text("# converted", encoding="utf-8")
    return original, markdown


def _staged_predicate(uploads_dir):
    """The staged record lives in ``<thread>/upload-companions/.companion-*``."""

    def predicate(path: Path) -> bool:
        return path.name.startswith(".companion-") and path.parent.name == "upload-companions"

    return predicate


def test_companion_registration_preserves_error_when_staged_unlink_fails(tmp_path, monkeypatch, real_unlink):
    from deerflow.uploads import companions

    original, markdown = _prepare_companion(tmp_path)
    primary = _PrimaryError("json dump failed")

    def dump(payload, stream, **kwargs):
        stream.write("{")
        raise primary

    monkeypatch.setattr(companions.json, "dump", dump)
    _fail_unlink_on(monkeypatch, _staged_predicate(original.parent), real_unlink)
    records = _capture_atomic_write_warnings(monkeypatch)

    with pytest.raises(_PrimaryError) as raised:
        companions.register_companion(original, markdown)

    assert raised.value is primary
    assert raised.value.__context__ is None
    assert len(records.records) == 1
    leftovers = [p for p in (tmp_path / "thread" / "upload-companions").iterdir() if p.name.startswith(".companion-")]
    assert leftovers, "the failed staged record is left behind but reported"


def test_companion_registration_success_is_unchanged(tmp_path):
    from deerflow.uploads import companions

    original, markdown = _prepare_companion(tmp_path)

    companions.register_companion(original, markdown)

    records_dir = tmp_path / "thread" / "upload-companions"
    assert [p.name for p in records_dir.iterdir() if p.name.endswith(".json")] or list(records_dir.glob("*.json"))
    assert not list(records_dir.glob(".companion-*"))
    assert companions.resolve_companion(original) == markdown


def test_companion_registration_still_succeeds_when_publish_cleanup_would_fail(tmp_path, monkeypatch, real_unlink):
    """The success path must stay silent: nothing to clean up after a good replace."""
    from deerflow.uploads import companions

    original, markdown = _prepare_companion(tmp_path)
    records = _capture_atomic_write_warnings(monkeypatch)

    companions.register_companion(original, markdown)

    assert companions.resolve_companion(original) == markdown
    assert records.records == []


class _ArchiveResponse:
    """A download response that trips the archive size guard."""

    def __init__(self, chunk: bytes) -> None:
        self._chunk = chunk

    def __enter__(self) -> _ArchiveResponse:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def read(self, _size: int) -> bytes:
        return self._chunk


def _staged_archive_in(tmp_path):
    """Keep the download's temporary archive inside the test's own directory."""
    import tempfile as tempfile_module

    # Bind the real allocator first: ``lark_cli.tempfile`` is this same module,
    # so a late lookup would call the patched attribute and recurse forever.
    real_mkstemp = tempfile_module.mkstemp

    def mkstemp(*_args, **_kwargs):
        return real_mkstemp(dir=tmp_path, prefix="lark-cli-skills-", suffix=".zip")

    return mkstemp


def test_lark_archive_too_large_keeps_its_error_when_cleanup_fails(tmp_path, monkeypatch, real_unlink):
    """The size guard's ValueError must survive a failing download cleanup."""
    from deerflow.integrations import lark_cli

    oversized = b"x" * (lark_cli.LARK_CLI_MAX_ARCHIVE_BYTES + 1)
    monkeypatch.setattr(
        lark_cli.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _ArchiveResponse(oversized),
    )
    monkeypatch.setattr(lark_cli.tempfile, "mkstemp", _staged_archive_in(tmp_path))
    _fail_unlink_on(monkeypatch, lambda path: path.suffix == ".zip", real_unlink)

    with pytest.raises(ValueError, match="too large"):
        lark_cli._download_lark_archive("v1.2.3")


def test_lark_archive_download_error_keeps_its_message_when_cleanup_fails(tmp_path, monkeypatch, real_unlink):
    """The network boundary's ValueError must survive a failing download cleanup."""

    def _offline(*_args, **_kwargs):
        raise OSError("network down")

    from deerflow.integrations import lark_cli

    monkeypatch.setattr(lark_cli.urllib.request, "urlopen", _offline)
    monkeypatch.setattr(lark_cli.tempfile, "mkstemp", _staged_archive_in(tmp_path))
    _fail_unlink_on(monkeypatch, lambda path: path.suffix == ".zip", real_unlink)

    with pytest.raises(ValueError, match="Could not download the Lark skill pack"):
        lark_cli._download_lark_archive("v1.2.3")
