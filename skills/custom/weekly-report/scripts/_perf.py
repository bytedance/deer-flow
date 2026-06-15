#!/usr/bin/env python
"""日报性能埋点工具。

为七段计时（表单交互、组织树查询、当天 InS、对比日 InS、SMS、KPI 计算、导出）
提供统一的 ``PerfTracer`` 接口。每段计时输出结构化 JSON 到 stderr，同时追加到
``<output_dir>/.perf/<trace_id>.jsonl``。

设计约束：
- 埋点失败不阻塞报告生成（所有异常捕获后记 stderr）。
- 无外部依赖（仅 stdlib）。
- trace_id 由调用方在创建 PerfTracer 时传入（通常为 report_run_id）。
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class _Span:
    """一次计时区间的内部状态。"""

    __slots__ = ("step_name", "start_time")

    def __init__(self, step_name: str) -> None:
        self.step_name = step_name
        self.start_time = time.perf_counter()


class PerfTracer:
    """七段计时埋点采集器。

    Usage::

        tracer = PerfTracer(trace_id="run-xxx", output_dir=Path("/mnt/user-data/outputs"))
        tracer.start_span("ins_fetch_current")
        # ... do work ...
        tracer.end_span(record_count=1500)

    输出示例（stderr 单行）::

        {"trace_id": "run-xxx", "step_name": "ins_fetch_current", "duration_ms": 1234, "record_count": 1500, "timestamp": "2026-06-11T10:30:45.123Z"}
    """

    def __init__(
        self,
        trace_id: str,
        output_dir: str | Path | None = None,
        enabled: bool | None = None,
    ) -> None:
        self.trace_id = trace_id
        self._output_dir = Path(output_dir) if output_dir else self._default_output_dir()
        self._perf_dir = self._output_dir / ".perf"
        self._jsonl_path = self._perf_dir / f"{trace_id}.jsonl"
        self._active_span: _Span | None = None
        if enabled is None:
            enabled = os.environ.get("DAILY_REPORT_PERF_DISABLED", "").lower() not in ("1", "true", "yes")
        self._enabled = enabled

    @staticmethod
    def _default_output_dir() -> Path:
        return Path(os.environ.get("DAILY_REPORT_OUTPUT_DIR", "/mnt/user-data/outputs"))

    def start_span(self, step_name: str) -> None:
        """开始一段计时。同一时刻只允许一个活跃 span，重复调用会覆盖前一个。"""
        if not self._enabled:
            return
        try:
            self._active_span = _Span(step_name)
        except Exception as exc:  # noqa: BLE001 - 埋点不阻塞主流程
            self._log_error("start_span", exc)

    def end_span(self, record_count: int = 0, extra: dict[str, Any] | None = None) -> None:
        """结束当前活跃 span 并输出计时记录。"""
        if not self._enabled or self._active_span is None:
            return
        span = self._active_span
        self._active_span = None
        try:
            duration_ms = int((time.perf_counter() - span.start_time) * 1000)
            record = {
                "trace_id": self.trace_id,
                "step_name": span.step_name,
                "duration_ms": duration_ms,
                "record_count": record_count,
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            }
            if extra:
                record.update(extra)
            self._emit(record)
        except Exception as exc:  # noqa: BLE001
            self._log_error("end_span", exc)

    def _emit(self, record: dict[str, Any]) -> None:
        """输出计时记录到 stderr + JSONL 文件。"""
        line = json.dumps(record, ensure_ascii=False)
        try:
            print(line, file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            self._log_error("emit.stderr", exc)
        try:
            self._perf_dir.mkdir(parents=True, exist_ok=True)
            with self._jsonl_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception as exc:  # noqa: BLE001
            self._log_error("emit.jsonl", exc)

    def _log_error(self, context: str, exc: Exception) -> None:
        try:
            print(f"[perf] {context} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        except Exception:  # noqa: BLE001
            pass


_noop_tracer = PerfTracer(trace_id="", enabled=False)


def get_tracer(
    trace_id: str | None = None,
    output_dir: str | Path | None = None,
) -> PerfTracer:
    """获取 PerfTracer 实例。trace_id 为空时返回 noop tracer。"""
    if not trace_id:
        return _noop_tracer
    return PerfTracer(trace_id=trace_id, output_dir=output_dir)
