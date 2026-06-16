"""
profiler.py — 画像编排核心（与 CLI 解耦）

流程：归一化维度+月份 → 解析机构 → 逐维度查询+聚合 → 统一信封汇总。
任何一步失败都返回结构化信封，绝不抛裸异常。
"""

from __future__ import annotations

import uuid

from . import config, envelope
from .api_client import query_dimension
from .errors import SkillError, ApiError
from .interpreters import INTERPRETERS
from .org_context import resolve_org_context
from .obs import log
from .validators import normalize_month, normalize_dimensions


def profile(*, user_id, dimensions=None, month=None, request_id=None) -> dict:
    """主入口。返回 {request_id, org, results:[信封,...]}。"""
    request_id = request_id or f"req-{uuid.uuid4().hex[:12]}"
    log("profile_start", request_id=request_id, dimensions=dimensions, month=month)

    # 1) 归一化（画像缺省维度=全部三维；缺省月份=当前月1号）
    try:
        dims = normalize_dimensions(dimensions)
        mon = normalize_month(month)
    except SkillError as e:
        return {
            "request_id": request_id,
            "results": [envelope.from_error(request_id=request_id, dimension="-", err=e)],
        }

    # 2) 机构解析（写死 05/深圳；branch_code == org_id）
    org = resolve_org_context(user_id)

    # 3) 逐维度查询（固定顺序：队伍→客户→产品）
    order = [d for d in config.DIMENSION_ORDER if d in dims]
    results = []
    for dim in order:
        try:
            rows = query_dimension(dim, request_id=request_id, org_id=org.org_id, month=mon)
            results.append(INTERPRETERS[dim](request_id, mon, rows))
        except ApiError as e:
            results.append(envelope.from_error(request_id=request_id, dimension=dim, err=e))
        except Exception as e:  # 兜底：绝不让裸异常冒泡
            results.append(envelope.from_error(
                request_id=request_id, dimension=dim,
                err=ApiError("PROFILE_EXCEPTION", f"{dim}画像异常：{e}",
                             hint="请稍后重试", retryable=True),
            ))

    statuses = {r["dimension"]: r["status"] for r in results}
    log("profile_done", request_id=request_id, org_id=org.org_id, month=mon, statuses=statuses)
    return {
        "request_id": request_id,
        "org": {"org_id": org.org_id, "org_name": org.org_name, "month": mon},
        "results": results,
    }
