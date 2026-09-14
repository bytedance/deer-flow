"""Pin the shared symlink-planting helper's two contracts (TDD for test infra)."""

from __future__ import annotations

from pathlib import Path

import pytest
from _pytest.outcomes import Skipped
from support.symlinks import symlink_or_skip


def test_creates_real_symlink_when_the_host_allows_it(tmp_path: Path) -> None:
    target = tmp_path / "real.txt"
    target.write_text("payload", encoding="utf-8")
    link = tmp_path / "link.txt"

    symlink_or_skip(link, target)  # skips itself on hosts without the privilege

    assert link.is_symlink()
    assert link.read_text(encoding="utf-8") == "payload"


def test_skips_when_symlink_creation_is_denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _denied(self: Path, target: Path, *, target_is_directory: bool = False) -> None:
        raise OSError(1314, "privilege not held")

    monkeypatch.setattr(Path, "symlink_to", _denied)

    with pytest.raises(Skipped):
        symlink_or_skip(tmp_path / "link.txt", tmp_path / "real.txt")
