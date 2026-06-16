"""
obs.py — 轻量可观测性（结构化日志）

harness engineering 要求"出问题能定位"。线上排障靠的是带 request_id 的结构化日志，
而不是猜。这里用标准库 logging，零额外依赖，默认输出到 stderr（不污染 stdout 的结果）。

用法：
    from .obs import log
    log("call_api", request_id=rid, dimension="team", url=url)
日志级别由环境变量 NBEV_LOG_LEVEL 控制（默认 INFO），可设 DEBUG/WARNING/ERROR。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time

_LEVEL = os.getenv("NBEV_LOG_LEVEL", "INFO").upper()
_logger = logging.getLogger("nbev_profile")

if not _logger.handlers:  # 防止重复加 handler（多次 import）
    _h = logging.StreamHandler(sys.stderr)  # stderr，避免污染 stdout 结果
    _h.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_h)
    _logger.setLevel(getattr(logging, _LEVEL, logging.INFO))
    _logger.propagate = False


def log(event: str, *, level: str = "INFO", **fields) -> None:
    """输出一行结构化 JSON 日志。失败绝不影响主流程。"""
    try:
        record = {"ts": round(time.time(), 3), "event": event, **fields}
        line = json.dumps(record, ensure_ascii=False, default=str)
        _logger.log(getattr(logging, level.upper(), logging.INFO), line)
    except Exception:
        pass  # 日志永远不能成为故障源
