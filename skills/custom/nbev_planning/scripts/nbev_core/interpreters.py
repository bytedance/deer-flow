"""
interpreters.py — 把三接口原始响应解读为统一信封

职责：
1. 识别隐性失败（产品兜底卡片 / 客户·队伍空 dict）；
2. 运行结果级业务护栏（C2 寿钻80-90%、C4 触边）；
3. 生成给 LLM 复述的 summary。
"""

from __future__ import annotations

from . import config, envelope
from .errors import ApiError, TargetUnreachable


def _f(x, default=None):
    """安全转 float：脏数据返回 default，绝不抛异常（保证准确性判断不被脏数据带偏）。"""
    if x is None or x == "":
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _pct(x) -> str:
    v = _f(x)
    return f"{v:.2%}" if v is not None else "—"


def _achievement_check(achievement_rate, predicted, target):
    """
    达标校验（准确性核心）：明确判断方案是否达成目标。
    achievementRate 优先；缺失时用 predicted/target 兜底计算。
    返回 (passed, rate_float_or_None)。
    """
    rate = _f(achievement_rate)
    if rate is None:
        p, t = _f(predicted), _f(target)
        rate = (p / t) if (p is not None and t) else None
    if rate is None:
        return True, None  # 无法判断时不误报
    return rate >= 0.999, rate  # 允许千分之一浮点误差


# ── 产品 ──
def interpret_product(request_id: str, target_nbev: float, raw: dict) -> dict:
    if not raw or not raw.get("productPathEstimation"):
        return envelope.from_error(
            request_id=request_id, dimension="product",
            err=ApiError(
                "PRODUCT_RESULT_EMPTY", "产品达成测算未返回有效结果",
                hint="可能是机构产品历史数据或下发配置缺失，请稍后重试或更换月份",
                retryable=True,
            ),
        )
    s = raw.get("calculationSummary", {})
    predicted = _f(s.get("predictedNbev"), 0.0)
    details = raw.get("productPathEstimation", {}).get("productDetails", [])

    # 兜底卡片识别：predicted≈0 且无明细（用安全浮点比较，避免字符串/None 误判）
    if predicted == 0 and not details:
        ai = (raw.get("aiInsight", {}) or {}).get("analysisText", "")
        return envelope.from_error(
            request_id=request_id, dimension="product",
            err=ApiError(
                "PRODUCT_FALLBACK_CARD", "产品达成测算返回兜底结果（无有效历史数据/配置）",
                hint=(ai[:80] if ai else "请确认该机构当月是否有下发产品及历史数据"),
                retryable=True,
            ),
        )

    # C4：统计触边缴期
    boundary = [
        f"{p.get('productName','')}-{it.get('paymentPeriod','')}"
        for p in details for it in p.get("items", [])
        if it.get("activityRateStatus") in (-1, 1) or it.get("avgPolNumFypStatus") in (-1, 1)
    ]
    has_supplement = any(
        it.get("isDistributed") is False
        for p in details for it in p.get("items", [])
    )
    ach_pass, rate = _achievement_check(s.get("achievementRate"), predicted, target_nbev)
    checks = [
        {"code": "ACH_target_met", "passed": ach_pass, "value": rate},
        {"code": "C4_boundary_touch", "passed": not boundary,
         "detail": f"{len(boundary)}个缴期活动率/件均FYP触边", "items": boundary[:10]},
    ]
    note = "（含\"其他\"补差）" if has_supplement else ""
    summary = (
        f"产品达成测算完成：目标 {target_nbev} 万元，预测达成 {predicted} 万元，"
        f"达成率 {_pct(s.get('achievementRate'))}{note}。"
    )
    if not ach_pass:
        summary += " ⚠️ 预测未达目标，需进一步调整产品组合或下调目标。"
    if boundary:
        summary += f" 注意：{len(boundary)} 个缴期活动率/件均FYP已触边，继续上调需业务确认。"
    return envelope.ok(
        request_id=request_id, dimension="product", data=raw, summary=summary,
        validation={"passed": ach_pass and not boundary, "checks": checks},
    )


# ── 客户 ──
def interpret_customer(request_id: str, target_nbev: float, raw: dict) -> dict:
    if not raw:
        return envelope.from_error(
            request_id=request_id, dimension="customer",
            err=TargetUnreachable("客户", target_nbev,
                                  "当前在职客户与历史客均NBEV下无可行解。"),
        )
    s = raw.get("calculationSummary", {})
    predicted = s.get("predictedNbev", 0)
    ach_pass, rate = _achievement_check(s.get("achievementRate"), predicted, target_nbev)
    summary = (
        f"客户达成测算完成：目标 {target_nbev} 万元，预测达成 {predicted} 万元，"
        f"达成率 {_pct(s.get('achievementRate'))}，需签单客户约 {s.get('totalCustomers',0)} 人"
        f"（已按客温×客价九宫格分配）。"
    )
    if not ach_pass:
        summary += " ⚠️ 预测未达目标，建议下调目标或结合其他维度。"
    return envelope.ok(
        request_id=request_id, dimension="customer", data=raw, summary=summary,
        validation={"passed": ach_pass,
                    "checks": [{"code": "ACH_target_met", "passed": ach_pass, "value": rate}]},
    )


# ── 队伍 ──
def interpret_team(request_id: str, target_nbev: float, raw: dict) -> dict:
    if not raw:
        return envelope.from_error(
            request_id=request_id, dimension="team",
            err=TargetUnreachable("队伍", target_nbev,
                                  "整数规划无可行解（目标与历史钻石结构差距过大）。"),
        )
    s = raw.get("calculationSummary", {})
    breakdown = s.get("workforceBreakdown", [])
    shouzuan_ratio = _f(next(
        (r.get("nbevRatio") for r in breakdown if r.get("diamondGroup") == "钻石及以上占比"),
        None,
    ))
    lo, hi = config.SHOUZUAN_NBEV_RATIO_RANGE
    c2_pass = shouzuan_ratio is None or (lo <= shouzuan_ratio <= hi)
    predicted = s.get("predictedNbev", 0)
    ach_pass, rate = _achievement_check(s.get("achievementRate"), predicted, target_nbev)
    checks = [
        {"code": "ACH_target_met", "passed": ach_pass, "value": rate},
        {"code": "C2_shouzuan_nbev_ratio", "passed": c2_pass,
         "value": shouzuan_ratio, "range": [lo, hi]},
    ]
    summary = (
        f"队伍达成测算完成：目标 {target_nbev} 万元，预测达成 {predicted} 万元，"
        f"达成率 {_pct(s.get('achievementRate'))}，总在职人力 {s.get('onJobHr',0)} 人。"
    )
    if not ach_pass:
        summary += " ⚠️ 预测未达目标，需进一步调整人力结构或下调目标。"
    if shouzuan_ratio is not None:
        summary += f" 钻石及以上NBEV贡献占比 {_pct(shouzuan_ratio)}"
        summary += f"（在{lo:.0%}-{hi:.0%}合理区间内）。" if c2_pass else f"（已偏离{lo:.0%}-{hi:.0%}合理区间，请关注）。"
    return envelope.ok(
        request_id=request_id, dimension="team", data=raw, summary=summary,
        validation={"passed": c2_pass and ach_pass, "checks": checks},
    )


INTERPRETERS = {
    "product": interpret_product,
    "customer": interpret_customer,
    "team": interpret_team,
}
