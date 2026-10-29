# SPDX-License-Identifier: MIT
"""Skill archive upload copies keep the original error when temporary cleanup fails."""

from __future__ import annotations

import logging
import tempfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

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


class _Form:
    def __init__(self, *, close_error: BaseException | None = None) -> None:
        self.archive = skills_router.UploadFile(BytesIO(b"unused"), filename="demo.skill")
        self.close_error = close_error
        self.closed = False

    async def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error
        await self.archive.close()

    def get(self, _key: str) -> skills_router.UploadFile:
        return self.archive


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "install_error"])
@pytest.mark.parametrize("failure", ["none", "unlink", "logging"])
async def test_upload_finally_preserves_install_outcome(tmp_path, monkeypatch, caplog, outcome, failure):
    archive = tmp_path / "uploaded.skill"
    archive.write_bytes(b"archive-bytes")
    response = skills_router.SkillInstallResponse(success=True, skill_name="demo", message="installed")
    install_error = RuntimeError("install failed")

    async def _admin(*_args, **_kwargs):
        return None

    async def _parse(_request):
        return _Form()

    def _copy(_source):
        return archive

    async def _install(path, _config):
        assert path.read_bytes() == b"archive-bytes"
        if outcome == "install_error":
            raise install_error
        return response

    monkeypatch.setattr(skills_router, "require_admin_user", _admin)
    monkeypatch.setattr(skills_router, "_parse_skill_archive_form", _parse)
    monkeypatch.setattr(skills_router, "_copy_uploaded_skill_archive", _copy)
    monkeypatch.setattr(skills_router, "_install_skill_archive", _install)

    real_unlink = Path.unlink
    if failure in {"unlink", "logging"}:

        def unlink(path, *args, **kwargs):
            if path == archive:
                raise OSError("temporary unlink failed")
            return real_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", unlink)
    if failure == "logging":

        def boom_log(*args, **kwargs):
            raise RuntimeError("log handler failed")

        monkeypatch.setattr("deerflow.utils.atomic_write.logger.warning", boom_log)

    try:
        with caplog.at_level(logging.WARNING, logger="deerflow.utils.atomic_write"):
            if outcome == "success":
                result = await skills_router.upload_and_install_skill(SimpleNamespace(), SimpleNamespace())
                assert result == response
            else:
                with pytest.raises(RuntimeError) as raised:
                    await skills_router.upload_and_install_skill(SimpleNamespace(), SimpleNamespace())
                assert raised.value is install_error
        if failure == "none":
            assert not archive.exists()
            assert "Failed to remove temporary output file" not in caplog.text
        else:
            assert archive.exists()
            if failure == "unlink":
                assert "Failed to remove temporary output file" in caplog.text
                assert str(archive) in caplog.text
                assert "temporary unlink failed" in caplog.text
    finally:
        real_unlink(archive, missing_ok=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "install_error"])
@pytest.mark.parametrize("failure", ["none", "unlink"])
async def test_upload_finally_close_failure_still_discards_and_preserves_outcome(tmp_path, monkeypatch, caplog, outcome, failure):
    archive = tmp_path / "uploaded.skill"
    archive.write_bytes(b"archive-bytes")
    response = skills_router.SkillInstallResponse(success=True, skill_name="demo", message="installed")
    install_error = RuntimeError("install failed")
    close_error = RuntimeError("form close failed")
    form = _Form(close_error=close_error)

    async def _admin(*_args, **_kwargs):
        return None

    async def _parse(_request):
        return form

    def _copy(_source):
        return archive

    async def _install(path, _config):
        assert path.read_bytes() == b"archive-bytes"
        if outcome == "install_error":
            raise install_error
        return response

    monkeypatch.setattr(skills_router, "require_admin_user", _admin)
    monkeypatch.setattr(skills_router, "_parse_skill_archive_form", _parse)
    monkeypatch.setattr(skills_router, "_copy_uploaded_skill_archive", _copy)
    monkeypatch.setattr(skills_router, "_install_skill_archive", _install)

    real_unlink = Path.unlink
    if failure == "unlink":

        def unlink(path, *args, **kwargs):
            if path == archive:
                raise OSError("temporary unlink failed")
            return real_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", unlink)

    try:
        with caplog.at_level(logging.WARNING, logger="deerflow.utils.atomic_write"):
            if outcome == "success":
                result = await skills_router.upload_and_install_skill(SimpleNamespace(), SimpleNamespace())
                assert result == response
            else:
                with pytest.raises(RuntimeError) as raised:
                    await skills_router.upload_and_install_skill(SimpleNamespace(), SimpleNamespace())
                assert raised.value is install_error
        assert form.closed
        assert "form close failed" not in caplog.text
        if failure == "none":
            assert not archive.exists()
        else:
            assert archive.exists()
            assert "Failed to remove temporary output file" in caplog.text
            assert "temporary unlink failed" in caplog.text
    finally:
        real_unlink(archive, missing_ok=True)
