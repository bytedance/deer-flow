"""envelope.py — 画像统一返回信封。"""

from __future__ import annotations

from .errors import SkillError


def ok(*, request_id, dimension, data, summary, table=None) -> dict:
    return {
        "status": "success",
        "request_id": request_id,
        "dimension": dimension,
        "data": data,          # 聚合后的结构化画像
        "table_md": table,     # 预渲染的 Markdown 表格（供直接展示）
        "error": None,
        "summary": summary,
    }


def from_error(*, request_id, dimension, err: SkillError, summary: str | None = None) -> dict:
    if err.code == "NEED_CLARIFY":
        status = "needs_clarification"
    elif err.code in ("PROFILE_EMPTY", "DIMENSION_DATA_EMPTY"):
        status = "no_data"
    else:
        status = "runtime_error" if err.retryable else "validation_error"
    return {
        "status": status,
        "request_id": request_id,
        "dimension": dimension,
        "data": None,
        "table_md": None,
        "error": err.to_error(),
        "summary": summary or err.message,
    }
