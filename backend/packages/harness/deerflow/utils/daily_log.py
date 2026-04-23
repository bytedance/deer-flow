"""Daily-rotating file logging with optional gzip and retention for Gateway (and similar)."""

from __future__ import annotations

import gzip
import logging
import os
import re
import shutil
from datetime import date, timedelta
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Final

_DATE_SUFFIX: Final = re.compile(r"^(.+\.log)\.(\d{4}-\d{2}-\d{2})$")
_ROTATED_GZ: Final = re.compile(r"^(.+\.log)\.(\d{4}-\d{2}-\d{2})\.gz$")


def _parse_rotated_date(filename: str) -> date | None:
    """Return calendar date encoded in a rotated log filename, or None."""
    m = _DATE_SUFFIX.match(filename)
    if m:
        try:
            return date.fromisoformat(m.group(2))
        except ValueError:
            return None
    m = _ROTATED_GZ.match(filename)
    if m:
        try:
            return date.fromisoformat(m.group(2))
        except ValueError:
            return None
    return None


def _compress_rotated_plain_files(log_dir: Path, base_name: str, *, compress: bool) -> None:
    """Gzip uncompressed ``{base}.log.YYYY-MM-DD`` files (idempotent)."""
    if not compress:
        return
    prefix = f"{base_name}.log."
    for p in sorted(log_dir.iterdir()):
        if not p.is_file() or p.name == f"{base_name}.log":
            continue
        if not p.name.startswith(prefix) or p.name.endswith(".gz"):
            continue
        if not _DATE_SUFFIX.match(p.name):
            continue
        gz_path = p.parent / f"{p.name}.gz"
        if gz_path.exists():
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
            continue
        try:
            with open(p, "rb") as f_in:
                with gzip.open(gz_path, "wb", compresslevel=6) as f_out:
                    shutil.copyfileobj(f_in, f_out)
            p.unlink(missing_ok=False)
        except OSError:
            continue


def _purge_by_retention(log_dir: Path, base_name: str, retention_days: int) -> None:
    """Remove rotated logs (plain or gz) strictly older than *retention_days* from today."""
    if retention_days <= 0:
        return
    cutoff = date.today() - timedelta(days=retention_days)
    current = f"{base_name}.log"
    for p in list(log_dir.iterdir()):
        if not p.is_file() or p.name == current:
            continue
        if not p.name.startswith(f"{base_name}.log"):
            continue
        d = _parse_rotated_date(p.name)
        if d is None:
            continue
        if d < cutoff:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass


class GatewayDailyRotatingFileHandler(TimedRotatingFileHandler):
    """Rotate at local midnight; optional gzip of dated files; retention by calendar day."""

    def __init__(
        self,
        filename: str,
        *,
        retention_days: int = 30,
        compress: bool = True,
    ) -> None:
        super().__init__(
            filename,
            when="midnight",
            interval=1,
            backupCount=0,
            encoding="utf-8",
            delay=False,
            utc=False,
        )
        self._retention_days = max(0, int(retention_days))
        self._compress = bool(compress)
        self._log_dir = Path(filename).parent
        self._base_name = Path(filename).stem

    def doRollover(self) -> None:
        super().doRollover()
        self._maintenance()

    def _maintenance(self) -> None:
        _compress_rotated_plain_files(self._log_dir, self._base_name, compress=self._compress)
        _purge_by_retention(self._log_dir, self._base_name, self._retention_days)


_ATTACHED_MARKER = "_deerflow_gateway_daily_handler"


def attach_daily_file_logging(log_dir: str, basename: str = "gateway") -> None:
    """Append daily-rotating file logs under *log_dir* / ``{basename}.log``.

    Environment (optional):

    - ``DEER_FLOW_GATEWAY_LOG_RETENTION_DAYS`` — delete rotated files older than this many
      whole calendar days from today (default ``30``). ``0`` disables age-based deletion.
    - ``DEER_FLOW_GATEWAY_LOG_COMPRESS`` — if ``true``/``1``/``yes`` (default), gzip rotated
      ``*.log.YYYY-MM-DD`` files after rollover.

    Idempotent: avoids attaching duplicate handlers for the same file path.
    """
    root = logging.getLogger()
    path = Path(log_dir).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    file_path = path / f"{basename}.log"

    retention_raw = os.environ.get("DEER_FLOW_GATEWAY_LOG_RETENTION_DAYS", "30").strip()
    try:
        retention_days = int(retention_raw)
    except ValueError:
        retention_days = 30

    compress_raw = os.environ.get("DEER_FLOW_GATEWAY_LOG_COMPRESS", "true").strip().lower()
    compress = compress_raw in ("1", "true", "yes", "on")

    for h in root.handlers:
        if getattr(h, _ATTACHED_MARKER, None) == str(file_path):
            return

    handler = GatewayDailyRotatingFileHandler(
        str(file_path),
        retention_days=retention_days,
        compress=compress,
    )
    setattr(handler, _ATTACHED_MARKER, str(file_path))
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    handler.setLevel(logging.INFO)
    root.addHandler(handler)
    handler._maintenance()
