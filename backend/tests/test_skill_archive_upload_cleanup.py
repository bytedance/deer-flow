# SPDX-License-Identifier: MIT
"""Skill archive upload copies keep the original error when temporary cleanup fails."""

from __future__ import annotations

import logging
import tempfile
from io import BytesIO
from pathlib import Path

import pytest

from app.gateway.routers import skills as skills_router


class _FailingRead:
    def __init__(self, error: BaseException):
        self._error = error

    def read(self, _size: int) -> bytes:
        raise self._error


@pytest.mark.parametrize("kind", ["read", "limit"])
@pytest.mark.parametrize("failure", ["none", "unlink", "logging"])
def test_copy_preserves_original_error_when_cleanup_fails(monkeypatch, caplog, kind, failure):
    created: list[Path] = []
    real_named = tempfile.NamedTemporaryFile
    real_unlink = Path.unlink
    primary = OSError("read failed")

    def tracking(*args, **kwargs):
        handle = real_named(*args, **kwargs)
        created.append(Path(handle.name))
        return handle

    monkeypatch.setattr(skills_router.tempfile, "NamedTemporaryFile", tracking)
    if kind == "limit":
        monkeypatch.setattr(skills_router, "_MAX_SKILL_ARCHIVE_UPLOAD_BYTES", 4)
        source = BytesIO(b"12345")
        expected_type = skills_router._SkillArchiveUploadTooLargeError
    else:
        source = _FailingRead(primary)
        expected_type = OSError
    if failure in {"unlink", "logging"}:

        def unlink(path, *args, **kwargs):
            if created and path == created[0]:
                raise OSError("temporary unlink failed")
            return real_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", unlink)
    if failure == "logging":

        def boom_log(*args, **kwargs):
            raise RuntimeError("log handler failed")

        monkeypatch.setattr("deerflow.utils.atomic_write.logger.warning", boom_log)

    try:
        with caplog.at_level(logging.WARNING, logger="deerflow.utils.atomic_write"):
            with pytest.raises(expected_type) as raised:
                skills_router._copy_uploaded_skill_archive(source)
        if kind == "read":
            assert raised.value is primary
        else:
            assert "upload limit" in str(raised.value)
        assert "temporary unlink failed" not in str(raised.value)
        assert len(created) == 1
        if failure == "none":
            assert not created[0].exists()
            assert "Failed to remove temporary output file" not in caplog.text
        else:
            assert created[0].exists()
            if failure == "unlink":
                assert "Failed to remove temporary output file" in caplog.text
                assert str(created[0]) in caplog.text
                assert "temporary unlink failed" in caplog.text
    finally:
        for path in created:
            real_unlink(path, missing_ok=True)


def test_copy_success_returns_the_uploaded_bytes():
    payload = b"PK\x03\x04exact-skill-bytes"
    destination = skills_router._copy_uploaded_skill_archive(BytesIO(payload))
    try:
        assert destination.read_bytes() == payload
        assert destination.name.startswith("deerflow-skill-")
        assert destination.suffix == ".skill"
    finally:
        destination.unlink(missing_ok=True)
