"""
planner.py — 规划编排核心（与 CLI 解耦，便于被 DeerFlow 直接 import 调用）

流程：校验入参 → 解析机构 → 构造共享 payload → 按固定顺序逐维度调用 → 统一信封汇总。
任何一步失败都返回结构化信封，绝不抛裸异常给上层。
"""

from __future__ import annotations

import uuid

from . import config, envelope
from .api_client import call_calculation
from .errors import SkillError, ApiError, NeedClarify
from .interpreters import INTERPRETERS
from .org_context import resolve_org_context
from .obs import log
from .validators import (
    normalize_month, validate_target_nbev, validate_dimensions, validate_ratio,
)


def _build_payload(org, target_nbev, month, request_id, session_id, opts) -> dict:
    payload = {
        "request_id": request_id,
        "session_id": session_id,
        "org_id": org.org_id,       # 来自 resolve_org_context（当前写死05/深圳）
        "org_name": org.org_name,
        "target_nbev": target_nbev,
        "month": month,
        "combination": opts.get("combination") or [],
    }
    for k in ("max_product_activity_rate", "max_avg_fyp_range", "max_double_gold_diamond_ratio"):
        if opts.get(k) is not None:
            payload[k] = opts[k]
    return payload


def plan(
    *,
    user_id: str,
    dimensions,
    target_nbev,
    month=None,
    request_id=None,
    session_id=None,
    **opts,
) -> dict:
    """
    主入口。返回 {request_id, org, results:[信封,...]}。
    opts 可含 combination / max_product_activity_rate / max_avg_fyp_range /
    max_double_gold_diamond_ratio。
    """
    request_id = request_id or f"req-{uuid.uuid4().hex[:12]}"
    session_id = session_id or f"sess-{uuid.uuid4().hex[:12]}"
    log("plan_start", request_id=request_id, dimensions=dimensions, target_nbev=target_nbev)

    # 0) 必填澄清：维度与目标NBEV缺失时，返回 needs_clarification（不报错、不猜测）
    missing = []
    if not dimensions:
        missing.append("dimensions")
    if target_nbev in (None, ""):
        missing.append("target_nbev")
    if missing:
        q = []
        if "dimensions" in missing:
            q.append("想从哪个维度看达成（产品/客户/队伍，可多选）")
        if "target_nbev" in missing:
            q.append("目标 NBEV 是多少万元")
        return {
            "request_id": request_id,
            "results": [envelope.from_error(
                request_id=request_id, dimension="-",
                err=NeedClarify(
                    "缺少必要信息，无法开始测算：" + "、".join(missing),
                    hint="请向用户澄清：" + "；".join(q),
                    fields=missing,
                ),
            )],
        }

    # 1) 入参校验（失败→单条结构化错误信封）
    try:
        dims = validate_dimensions(dimensions)
        tgt = validate_target_nbev(target_nbev)
        mon = normalize_month(month)
        validate_ratio("max_product_activity_rate", opts.get("max_product_activity_rate"))
        validate_ratio("max_avg_fyp_range", opts.get("max_avg_fyp_range"))
        validate_ratio("max_double_gold_diamond_ratio", opts.get("max_double_gold_diamond_ratio"))
    except SkillError as e:
        return {
            "request_id": request_id,
            "results": [envelope.from_error(request_id=request_id, dimension="-", err=e)],
        }

    # 2) 机构解析（当前恒为 05/深圳；未来换接口不动此处调用）
    org = resolve_org_context(user_id)

    payload = _build_payload(org, tgt, mon, request_id, session_id, opts)

    # 3) 按固定顺序逐维度调用（产品→队伍→客户）
    order = [d for d in config.DIMENSION_ORDER if d in dims]
    results = []
    for dim in order:
        try:
            raw = call_calculation(dim, payload)
            results.append(INTERPRETERS[dim](request_id, tgt, raw))
        except ApiError as e:
            results.append(envelope.from_error(request_id=request_id, dimension=dim, err=e))
        except Exception as e:  # 兜底：绝不让裸异常冒泡
            results.append(envelope.from_error(
                request_id=request_id, dimension=dim,
                err=ApiError("CALCULATION_EXCEPTION", f"{dim}维度测算异常：{e}",
                             hint="请稍后重试，若持续失败请反馈", retryable=True),
            ))

    statuses = {r["dimension"]: r["status"] for r in results}
    log("plan_done", request_id=request_id, org_id=org.org_id, month=mon, statuses=statuses)
    return {
        "request_id": request_id,
        "org": {"org_id": org.org_id, "org_name": org.org_name, "month": mon},
        "results": results,
    }
