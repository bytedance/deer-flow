"""
envelope.py — 统一返回信封

三接口失败表达不一（产品兜底卡片 / 客户·队伍空 dict），统一包成同一信封，
让 LLM 只读 status + summary + validation，不必从原始大 JSON 自由发挥。
"""

from __future__ import annotations

from .errors import SkillError


def ok(*, request_id, dimension, data, summary, validation=None) -> dict:
    return {
        "status": "success",
        "request_id": request_id,
        "dimension": dimension,
        "data": data,
        "validation": validation or {"passed": True, "checks": []},
        "error": None,
        "summary": summary,
    }


def from_error(*, request_id, dimension, err: SkillError, summary: str | None = None) -> dict:
    # 区分对待不同性质的失败，便于 LLM 采取正确动作
    if err.code == "TARGET_UNREACHABLE":
        status = "target_unreachable"
    elif err.code == "NEED_CLARIFY":
        status = "needs_clarification"
    else:
        status = "runtime_error" if err.retryable else "validation_error"
    return {
        "status": status,
        "request_id": request_id,
        "dimension": dimension,
        "data": None,
        "validation": {"passed": False, "checks": []},
        "error": err.to_error(),
        "summary": summary or err.message,
    }
