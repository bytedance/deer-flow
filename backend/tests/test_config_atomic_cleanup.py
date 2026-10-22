"""Cleanup failures in the secret-file and managed-model writers.

Both writers publish a temporary file and then discard it. On Windows a scanner,
a peer holding the handle, or a read-only mount can make that removal fail after
the value is already published, so the removal has to stay best-effort: it must
never replace the caller's outcome.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from deerflow.config.managed_models import ManagedModelStore
from deerflow.config.secret_file import read_or_create_secret_file


def _fail_unlink_where(predicate: Callable[[Path], bool], monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Make ``Path.unlink`` fail for matching paths and record the attempts."""
    real_unlink = Path.unlink
    attempts: list[Path] = []

    def unlink(self: Path, missing_ok: bool = False) -> None:
        if predicate(self):
            attempts.append(self)
            raise PermissionError(13, "The process cannot access the file", str(self))
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink)
    return attempts


def test_secret_creation_survives_a_failing_temporary_removal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / ".secret"
    attempts = _fail_unlink_where(lambda candidate: candidate.suffix == ".tmp", monkeypatch)

    value = read_or_create_secret_file(path, lambda: "generated-value")

    assert value == "generated-value"
    assert path.read_text(encoding="utf-8") == "generated-value"
    assert attempts, "the temporary file should have been handed to the cleanup helper"


def test_secret_creation_keeps_the_replace_error_when_cleanup_also_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / ".secret"
    path.write_text("", encoding="utf-8")  # an abandoned empty file takes the claim path

    def no_hard_links(*_args, **_kwargs):
        raise OSError(95, "Operation not supported")

    def failing_replace(*_args, **_kwargs):
        raise OSError(5, "publish failed")

    monkeypatch.setattr("deerflow.config.secret_file.os.link", no_hard_links)
    monkeypatch.setattr("deerflow.config.secret_file.os.replace", failing_replace)
    attempts = _fail_unlink_where(lambda candidate: candidate.suffix == ".replacing", monkeypatch)

    with pytest.raises(OSError) as raised:
        read_or_create_secret_file(path, lambda: "generated-value")

    assert "publish failed" in str(raised.value)
    assert attempts, "the unpublished claim should still have been cleaned up"


def test_managed_model_write_survives_a_failing_temporary_removal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "managed.json"
    attempts = _fail_unlink_where(lambda candidate: candidate.parent == tmp_path and candidate != target, monkeypatch)

    ManagedModelStore._write(target, b"payload")

    assert target.read_bytes() == b"payload"
    assert attempts


def test_managed_model_write_keeps_the_replace_error_when_cleanup_also_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "managed.json"

    def failing_replace(*_args, **_kwargs):
        raise OSError(5, "publish failed")

    monkeypatch.setattr("deerflow.config.managed_models.os.replace", failing_replace)
    attempts = _fail_unlink_where(lambda candidate: candidate.parent == tmp_path and candidate != target, monkeypatch)

    with pytest.raises(OSError) as raised:
        ManagedModelStore._write(target, b"payload")

    assert "publish failed" in str(raised.value)
    assert attempts
