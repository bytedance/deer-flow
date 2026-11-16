"""Skill projection manifests preserve publication errors through failed cleanup."""

from __future__ import annotations

import json
import logging
import os
import stat
from contextlib import suppress
from pathlib import Path
from unittest.mock import Mock

import pytest


class _Records(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.mark.parametrize("phase", ["fdopen", "fdopen_close", "write", "replace"])
@pytest.mark.parametrize("primary_type", [RuntimeError, KeyboardInterrupt])
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("unlink_fails", [False, True])
@pytest.mark.parametrize("logging_fails", [False, True])
def test_manifest_preserves_primary_error_and_independent_cleanup(tmp_path, monkeypatch, phase, primary_type, existing, unlink_fails, logging_fails):
    from deerflow.skills import projection
    from deerflow.utils import atomic_write

    scope = tmp_path / "scope"
    scope.mkdir()
    target = scope / ".projection-manifest.json"
    if existing:
        target.write_bytes(b"previous manifest")
    primary = primary_type("manifest publication failed")
    allocated = []
    unlinks = []
    closes = []
    real_allocate = projection.tempfile.mkstemp
    real_fdopen = os.fdopen
    real_close = os.close
    real_fstat = os.fstat
    real_unlink = Path.unlink
    real_replace = Path.replace

    def allocate(*args, **kwargs):
        fd, name = real_allocate(*args, **kwargs)
        allocated.append((fd, Path(name)))
        return fd, name

    def fdopen(fd, *args, **kwargs):
        if allocated and fd == allocated[0][0] and phase.startswith("fdopen"):
            raise primary
        return real_fdopen(fd, *args, **kwargs)

    def close(fd):
        if allocated and fd == allocated[0][0]:
            closes.append(fd)
            real_close(fd)
            if phase == "fdopen_close":
                raise OSError("descriptor cleanup failed")
        else:
            real_close(fd)

    def dump(payload, stream, **kwargs):
        stream.write('{"partial":')
        raise primary

    def replace(path, destination):
        if allocated and path == allocated[0][1]:
            raise primary
        return real_replace(path, destination)

    def unlink(path, *args, **kwargs):
        if allocated and path == allocated[0][1]:
            unlinks.append(path)
            if unlink_fails:
                raise PermissionError("temporary unlink failed")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(projection.tempfile, "mkstemp", allocate)
    monkeypatch.setattr(os, "fdopen", fdopen)
    monkeypatch.setattr(os, "close", close)
    monkeypatch.setattr(Path, "unlink", unlink)
    if phase == "write":
        monkeypatch.setattr(projection.json, "dump", dump)
    if phase == "replace":
        monkeypatch.setattr(Path, "replace", replace)

    records = _Records()
    # A real stdlib handler: opening this delayed destination raises from emit.
    broken = logging.FileHandler(tmp_path / "missing-logs" / "gateway.log", delay=True)
    broken.emit = Mock(wraps=broken.emit)
    monkeypatch.setattr(atomic_write.logger, "handlers", [records, broken] if logging_fails else [records])
    monkeypatch.setattr(atomic_write.logger, "propagate", False)
    monkeypatch.setattr(atomic_write.logger, "level", logging.WARNING)
    try:
        with pytest.raises(primary_type) as raised:
            projection._write_manifest(scope, "source", "view")
        assert raised.value is primary
        assert len(allocated) == 1
        fd, temporary = allocated[0]
        assert unlinks == [temporary]
        assert closes == ([fd] if phase.startswith("fdopen") else [])
        with pytest.raises(OSError):
            real_fstat(fd)
        assert temporary.exists() == unlink_fails
        if existing:
            assert target.read_bytes() == b"previous manifest"
        else:
            assert not target.exists()
        expected_warnings = int(phase == "fdopen_close") + int(unlink_fails)
        assert len(records.records) == expected_warnings
        assert all(record.exc_info and str(temporary) in record.getMessage() for record in records.records)
        assert broken.emit.call_count == (expected_warnings if logging_fails else 0)
    finally:
        broken.close()
        records.close()
        for fd, temporary in allocated:
            with suppress(OSError):
                real_close(fd)
            real_unlink(temporary, missing_ok=True)


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("view_signature", [None, "view-签名"])
def test_manifest_success_keeps_format_and_private_permissions(tmp_path, existing, view_signature):
    from deerflow.skills import projection

    scope = tmp_path / "scope"
    scope.mkdir()
    target = scope / ".projection-manifest.json"
    if existing:
        target.write_bytes(b"old")
        target.chmod(0o644)
    projection._write_manifest(scope, "source-签名", view_signature)
    expected = {"version": projection._MANIFEST_VERSION, "source_signature": "source-签名"}
    if view_signature is not None:
        expected["view_signature"] = view_signature
    assert target.read_text(encoding="utf-8") == json.dumps(expected, sort_keys=True)
    if os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert list(scope.iterdir()) == [target]
