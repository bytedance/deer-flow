"""Tests for deerflow.utils.daily_log."""

from __future__ import annotations

import gzip
from datetime import date
from pathlib import Path
from unittest import mock

import pytest

from deerflow.utils import daily_log as daily_log_mod


def test_parse_rotated_date_plain_and_gz() -> None:
    assert daily_log_mod._parse_rotated_date("gateway.log.2026-04-15") == date(2026, 4, 15)
    assert daily_log_mod._parse_rotated_date("gateway.log.2026-04-15.gz") == date(2026, 4, 15)
    assert daily_log_mod._parse_rotated_date("gateway.log") is None
    assert daily_log_mod._parse_rotated_date("other.txt") is None


def test_compress_rotated_plain_files_creates_gz(tmp_path: Path) -> None:
    plain = tmp_path / "gateway.log.2020-06-01"
    plain.write_text("hello log", encoding="utf-8")
    daily_log_mod._compress_rotated_plain_files(tmp_path, "gateway", compress=True)
    gz = tmp_path / "gateway.log.2020-06-01.gz"
    assert gz.is_file()
    assert not plain.exists()
    with gzip.open(gz, "rt", encoding="utf-8") as f:
        assert f.read() == "hello log"


def test_compress_skips_when_gz_exists(tmp_path: Path) -> None:
    plain = tmp_path / "gateway.log.2020-06-02"
    plain.write_text("x", encoding="utf-8")
    gz = tmp_path / "gateway.log.2020-06-02.gz"
    gz.write_bytes(b"already")
    daily_log_mod._compress_rotated_plain_files(tmp_path, "gateway", compress=True)
    assert not plain.exists()
    assert gz.read_bytes() == b"already"


def test_compress_noop_when_disabled(tmp_path: Path) -> None:
    plain = tmp_path / "gateway.log.2020-06-03"
    plain.write_text("keep", encoding="utf-8")
    daily_log_mod._compress_rotated_plain_files(tmp_path, "gateway", compress=False)
    assert plain.is_file()
    assert not (tmp_path / "gateway.log.2020-06-03.gz").exists()


def test_purge_by_retention_deletes_old_files(tmp_path: Path) -> None:
    old_plain = tmp_path / "gateway.log.2000-01-01"
    old_plain.write_text("old", encoding="utf-8")
    old_gz = tmp_path / "gateway.log.2000-01-02.gz"
    old_gz.write_bytes(b"x")
    recent = tmp_path / "gateway.log.2099-01-01"
    recent.write_text("recent", encoding="utf-8")
    current = tmp_path / "gateway.log"
    current.write_text("current", encoding="utf-8")

    fixed_today = date(2026, 6, 15)

    class _DateShim:
        @staticmethod
        def today() -> date:
            return fixed_today

        fromisoformat = staticmethod(date.fromisoformat)

    with mock.patch("deerflow.utils.daily_log.date", _DateShim):
        daily_log_mod._purge_by_retention(tmp_path, "gateway", retention_days=30)

    assert not old_plain.exists()
    assert not old_gz.exists()
    assert recent.is_file()
    assert current.is_file()


def test_purge_retention_zero_skips_delete(tmp_path: Path) -> None:
    old = tmp_path / "gateway.log.2000-01-01"
    old.write_text("x", encoding="utf-8")
    daily_log_mod._purge_by_retention(tmp_path, "gateway", retention_days=0)
    assert old.is_file()


def test_attach_daily_file_logging_idempotent(tmp_path: Path) -> None:
    import logging

    log_dir = str(tmp_path / "logs")
    with mock.patch.dict(
        "os.environ",
        {
            "DEER_FLOW_GATEWAY_LOG_RETENTION_DAYS": "7",
            "DEER_FLOW_GATEWAY_LOG_COMPRESS": "false",
        },
        clear=False,
    ):
        root = logging.getLogger()
        before = len(root.handlers)
        daily_log_mod.attach_daily_file_logging(log_dir, "gateway")
        mid = len(root.handlers)
        daily_log_mod.attach_daily_file_logging(log_dir, "gateway")
        after = len(root.handlers)
        to_remove = [h for h in root.handlers if getattr(h, daily_log_mod._ATTACHED_MARKER, None)]
        for h in to_remove:
            root.removeHandler(h)
            h.close()
    assert mid == before + 1
    assert after == mid


@pytest.mark.parametrize(
    ("compress_arg", "retention_arg"),
    [(True, 14), (False, 7)],
)
def test_gateway_daily_rotating_handler_init(tmp_path: Path, compress_arg: bool, retention_arg: int) -> None:
    fp = tmp_path / "gateway.log"
    fp.parent.mkdir(parents=True, exist_ok=True)
    h = daily_log_mod.GatewayDailyRotatingFileHandler(
        str(fp),
        retention_days=retention_arg,
        compress=compress_arg,
    )
    assert h._compress is compress_arg
    assert h._retention_days == retention_arg
    h.close()
