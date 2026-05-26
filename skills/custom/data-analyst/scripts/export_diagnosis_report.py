"""Diagnosis report renderers.

Pure functions consumed by ``export_report.write_report(... report_type="diagnosis")``.
Markdown follows the 6-section template aligned with
``vibration-fault-diagnosis/SKILL.md``:

1. Machine and task
2. Key abnormal findings
3. Evidence chain
4. Diagnosis
5. Differential diagnosis
6. Recommendations

This module does not implement its own CLI; the existing ``export_report.py``
``main()`` already accepts ``--report-type diagnosis`` once registered there.
"""

from __future__ import annotations

from typing import Any

# --- Helpers ---


def _format_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def _equipment_label(item: dict) -> str:
    """Return human-readable label for an equipment-bearing row.

    Prefers ``equipment_name`` (or ``name``); falls back to ``equipment_id``.
    """
    if not isinstance(item, dict):
        return "—"
    label = item.get("equipment_name") or item.get("name") or item.get("equipment") or item.get("equipment_id")
    return str(label) if label else "—"


def _verdict_label(verdict: str) -> str:
    return {
        "exceed": "超阈值",
        "marginal": "边缘",
        "normal": "正常",
    }.get(verdict, verdict)


def _confidence_label(confidence: str) -> str:
    return {
        "high": "高",
        "medium": "中",
        "low": "低",
    }.get(confidence, confidence)


# --- Markdown sections ---


def _section_machine_and_task(payload: dict) -> str:
    meta = payload.get("report_meta", {}) or {}
    summary_list = payload.get("equipment_summary", []) or []
    machine_lines: list[str] = []
    if summary_list:
        for s in summary_list:
            machine_lines.append(f"- 设备：{_equipment_label(s)}（运行阶段：{s.get('operation_phase', '—')}，告警状态：{s.get('alarm_status', '—')}）")
    else:
        machine_lines.append("- 设备：—")
    return (
        "## 1. 设备与任务\n\n"
        f"- 设备类型 (kind)：{meta.get('kind', '—')}\n"
        f"- 规则集：{meta.get('rules_skill', '—')}\n"
        f"- 数据来源：{meta.get('data_source', '—')}\n"
        f"- 报告生成时间：{meta.get('generated_at', '—')}\n"
        + "\n".join(machine_lines)
        + "\n"
    )


def _section_key_findings(payload: dict) -> str:
    summary_list = payload.get("equipment_summary", []) or []
    if not summary_list:
        return "## 2. 异常发现\n\n_本次诊断未识别到异常_\n"
    lines = ["## 2. 异常发现", ""]
    for s in summary_list:
        max_value = s.get("max_value") or {}
        label = _equipment_label(s)
        if max_value:
            lines.append(
                f"- {label} · {max_value.get('point', '—')} · {max_value.get('feature', '—')} 最大值：{_format_value(max_value.get('value'))} {max_value.get('unit', '')}（告警：{s.get('alarm_status', '—')}）"
            )
        else:
            lines.append(f"- {label}（告警：{s.get('alarm_status', '—')}）")
    return "\n".join(lines) + "\n"


def _section_evidence_chain(payload: dict) -> str:
    chain = payload.get("evidence_chain", []) or []
    if not chain:
        return "## 3. 证据链\n\n_未收集到证据_\n"
    lines = [
        "## 3. 证据链",
        "",
        "| # | 类别 | 设备 | 测点 | 特征 | 数值 | 阈值 | 判定 |",
        "| - | ---- | ---- | ---- | ---- | ---- | ---- | ---- |",
    ]
    for idx, row in enumerate(chain):
        label = _equipment_label(row)
        lines.append(
            f"| {idx} | {row.get('category', '—')} | {label} | {row.get('point', '—')} | "
            f"{row.get('feature', '—')} | {_format_value(row.get('value'))} | {_format_value(row.get('threshold'))} | "
            f"{_verdict_label(row.get('verdict', '—'))} |"
        )
    return "\n".join(lines) + "\n"


def _section_diagnosis(payload: dict) -> str:
    matches = payload.get("rule_matches", []) or []
    summary = payload.get("result_summary", {}) or {}
    if summary.get("overall_verdict") == "normal":
        return "## 4. 诊断结论\n\n**机组正常**：当前未发现准确率不低于 0.5 的故障诊断结果，建议保持常规监测。\n"
    if not matches:
        return "## 4. 诊断结论\n\n_未匹配到任何规则；建议加密监测并由领域专家复核_\n"
    lines = ["## 4. 诊断结论", ""]
    primary = matches[0]
    lines.append(
        f"**主诊断**：{primary.get('fault_family', '—')}"
        + (f"（subtype: {primary.get('fault_subtype')}）" if primary.get("fault_subtype") else "")
    )
    lines.append("")
    lines.append(f"- 设备：{_equipment_label(primary)}")
    lines.append(f"- 置信度：{_confidence_label(primary.get('confidence', '—'))}")
    lines.append(f"- 诊断得分：{_format_value(primary.get('score'))}")
    lines.append(f"- 命中规则节：{primary.get('rule_section', '—')}")
    supporting = primary.get("supporting_evidence_indices", []) or []
    marginal = primary.get("marginal_evidence_indices", []) or []
    lines.append(f"- 支持证据（exceed）：第 {', '.join(str(i) for i in supporting) or '—'} 行")
    if marginal:
        lines.append(f"- 边缘证据（marginal）：第 {', '.join(str(i) for i in marginal)} 行（不计入主诊断）")
    missing = primary.get("missing_evidence", []) or []
    if missing:
        lines.append(f"- 缺失证据：{', '.join(missing)}")
    if len(matches) > 1:
        lines.append("")
        lines.append("**并发故障候选**：")
        for candidate in matches[1:]:
            lines.append(
                f"- {candidate.get('fault_family', '—')}（置信度：{_confidence_label(candidate.get('confidence', '—'))}，得分：{_format_value(candidate.get('score'))}）"
            )
    return "\n".join(lines) + "\n"


def _section_differential(payload: dict) -> str:
    matches = payload.get("rule_matches", []) or []
    summary = payload.get("result_summary", {}) or {}
    if summary.get("overall_verdict") == "normal":
        return "## 5. 差异诊断\n\n_无需要展示的故障候选_\n"
    if len(matches) <= 1:
        return "## 5. 差异诊断\n\n_本次诊断未发现替代候选；建议补充更多测点 / 工艺联动数据后再判定_\n"
    lines = ["## 5. 差异诊断", ""]
    for m in matches[1:]:
        lines.append(
            f"- {m.get('fault_family', '—')}（{_confidence_label(m.get('confidence', '—'))}）："
            f"命中节 {m.get('rule_section', '—')}，"
            f"支持证据数 {len(m.get('supporting_evidence_indices', []) or [])}；"
            f"较主诊断弱"
        )
    return "\n".join(lines) + "\n"


def _section_recommendations(payload: dict) -> str:
    recs = payload.get("recommendations", []) or []
    if not recs:
        return "## 6. 处置建议\n\n_无具体建议；保持常规监测节奏_\n"
    lines = ["## 6. 处置建议", ""]
    for rec in recs:
        lines.append(f"- {rec}")
    return "\n".join(lines) + "\n"


def _section_historical_cases(payload: dict) -> str:
    cases = payload.get("historical_cases", []) or []
    if not cases:
        return ""
    lines = ["## 附：同类故障历史", ""]
    for case in cases:
        prefix = "演示 · " if case.get("data_source") == "demo_fallback" else ""
        lines.append(
            f"- {prefix}{_equipment_label(case)}（{case.get('fault_family', '—')}，{case.get('occurred_at', '—')}）：{case.get('summary', '—')}"
        )
    return "\n".join(lines) + "\n"


def _section_warnings(payload: dict) -> str:
    warnings = payload.get("warnings", []) or []
    if not warnings:
        return ""
    lines = ["> **执行告警**："]
    for w in warnings:
        lines.append(f"> - {w}")
    return "\n".join(lines) + "\n"


def render_diagnosis_markdown(payload: dict, thread_id: str | None = None) -> str:
    """Render the 6-section diagnosis report as Markdown.

    ``thread_id`` is accepted for symmetry with ``render_markdown`` /
    ``render_weekly_markdown`` (used to embed artifact links). The current
    diagnosis renderer does not embed inline assets, so the parameter is
    reserved for future spectrum / orbit SVG injection.

    Supports both single-device and multi-device aggregated report formats.
    """
    _ = thread_id  # reserved

    # Detect format: aggregated (has per_device) vs single device
    if "per_device" in payload:
        return _render_aggregated_markdown(payload)

    parts: list[str] = ["# 故障诊断报告", ""]
    parts.append(_section_warnings(payload))
    parts.append(_section_machine_and_task(payload))
    parts.append(_section_key_findings(payload))
    parts.append(_section_evidence_chain(payload))
    parts.append(_section_diagnosis(payload))
    parts.append(_section_differential(payload))
    parts.append(_section_recommendations(payload))
    parts.append(_section_historical_cases(payload))
    return "\n".join(p for p in parts if p)


# --- Aggregated report renderers (multi-device) ---


def _render_aggregated_markdown(payload: dict) -> str:
    """Render multi-device aggregated diagnosis report."""
    parts: list[str] = ["# 多设备故障诊断报告", ""]

    # Report metadata
    parts.append(_section_report_meta(payload))

    # Per-device summaries
    parts.append(_section_per_device_summaries(payload))

    # Cross-device correlation (Pro/Ultra)
    parts.append(_section_cross_device_correlation(payload))

    # Impact assessment
    parts.append(_section_impact_assessment(payload))

    # Root cause ranking
    parts.append(_section_root_cause_ranking(payload))

    # Recommendations
    parts.append(_section_aggregated_recommendations(payload))

    # Data quality warnings
    parts.append(_section_data_quality(payload))

    return "\n".join(p for p in parts if p)


def _section_report_meta(payload: dict) -> str:
    """Render report metadata section."""
    meta = payload.get("report_meta", {}) or {}
    capability_tier = meta.get("capability_tier") or payload.get("capability_tier", "basic")
    model_fallback = payload.get("model_fallback", False)
    schedule_label = payload.get("schedule_label", "")

    lines = ["## 报告信息", ""]
    lines.append(f"- **能力等级**：{capability_tier.upper()}")
    lines.append(f"- **设备类型**：{meta.get('kind', '—')}")
    lines.append(f"- **规则集**：{meta.get('rules_skill', '—')}")
    lines.append(f"- **数据来源**：{meta.get('data_source', '—')}")
    lines.append(f"- **生成时间**：{meta.get('generated_at', '—')}")
    lines.append(f"- **设备数量**：{meta.get('total_devices', 0)}")

    if model_fallback:
        lines.append("")
        lines.append("> ⚠️ **模型回退**：Ultra 模型不可用，已自动回退到 Pro 等级")

    if schedule_label:
        lines.append(f"- **调度标签**：{schedule_label}")

    return "\n".join(lines) + "\n"


def _section_per_device_summaries(payload: dict) -> str:
    """Render per-device summary sections."""
    per_device = payload.get("per_device", []) or []
    if not per_device:
        return "## 设备诊断摘要\n\n_无设备数据_\n"

    lines = ["## 设备诊断摘要", ""]

    for device in per_device:
        eq_name = device.get("equipment_name", device.get("equipment_id", "未知设备"))
        eq_id = device.get("equipment_id", "")

        lines.append(f"### {eq_name} ({eq_id})")
        lines.append("")

        # Key findings
        key_findings = device.get("key_findings", []) or []
        if key_findings:
            lines.append("**异常发现**：")
            for finding in key_findings:
                severity = finding.get("severity", "medium")
                severity_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(severity, "⚪")
                lines.append(
                    f"- {severity_icon} {finding.get('point', '—')} · {finding.get('feature', '—')}："
                    f"{_format_value(finding.get('value'))} / {_format_value(finding.get('threshold'))}"
                    f"（{_verdict_label(finding.get('verdict', '—'))}）"
                )
            lines.append("")

        # Root causes
        root_causes = device.get("root_causes", []) or []
        if root_causes:
            lines.append("**根因分析**：")
            for rc in root_causes[:3]:  # Top 3
                confidence = _confidence_label(rc.get("confidence", "low"))
                lines.append(
                    f"- {rc.get('root_cause_label', '—')}（{confidence}置信度，"
                    f"可能性：{rc.get('likelihood', '—')}，严重度：{rc.get('severity', '—')}）"
                )
            lines.append("")

        # Recommendations
        recommendations = device.get("recommendations", []) or []
        if recommendations:
            lines.append("**维护建议**：")
            for rec in recommendations[:3]:  # Top 3
                priority = rec.get("priority", "routine")
                priority_label = {"urgent": "紧急", "important": "重要", "routine": "常规"}.get(priority, "常规")
                lines.append(f"- [{priority_label}] {rec.get('action', '—')}")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def _section_cross_device_correlation(payload: dict) -> str:
    """Render cross-device correlation section (Pro/Ultra)."""
    correlation = payload.get("cross_device_correlation", {}) or {}
    correlated_root_causes = correlation.get("correlated_root_causes", []) or []

    if not correlated_root_causes:
        return ""

    lines = ["## 跨设备根因关联", ""]

    for rc in correlated_root_causes:
        strength = rc.get("correlation_strength", "low")
        strength_label = {"high": "强关联", "medium": "中等关联", "low": "弱关联"}.get(strength, "弱关联")
        strength_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(strength, "⚪")

        affected_devices = rc.get("affected_devices", []) or []
        device_names = [d.get("equipment_name", d.get("equipment_id", "")) for d in affected_devices]

        lines.append(f"### {strength_icon} {rc.get('root_cause_label', '—')}")
        lines.append("")
        lines.append(f"- **关联强度**：{strength_label}")
        lines.append(f"- **影响设备**：{', '.join(device_names)}")
        lines.append(f"- **最大严重度**：{rc.get('max_severity', '—')}")
        lines.append(f"- **最大可能性**：{rc.get('max_likelihood', '—')}")
        lines.append("")

    return "\n".join(lines)


def _section_impact_assessment(payload: dict) -> str:
    """Render impact assessment section."""
    impact = payload.get("impact_assessment", {}) or {}
    if not impact:
        return ""

    lines = ["## 影响评估", ""]
    lines.append(f"- **受影响设备数**：{impact.get('affected_equipment_count', 0)}")

    severity_dist = impact.get("severity_distribution", {}) or {}
    if severity_dist:
        lines.append("- **严重度分布**：")
        lines.append(f"  - 严重：{severity_dist.get('critical', 0)}")
        lines.append(f"  - 高：{severity_dist.get('high', 0)}")
        lines.append(f"  - 中：{severity_dist.get('medium', 0)}")
        lines.append(f"  - 低：{severity_dist.get('low', 0)}")

    downtime = impact.get("estimated_downtime_hours")
    if downtime is not None:
        lines.append(f"- **预估停机时间**：{downtime} 小时")

    business_impact = impact.get("business_impact", "")
    if business_impact:
        lines.append(f"- **业务影响**：{business_impact}")

    return "\n".join(lines) + "\n"


def _section_root_cause_ranking(payload: dict) -> str:
    """Render root cause ranking table."""
    ranking = payload.get("root_cause_ranking", []) or []
    if not ranking:
        return "## 根因排序\n\n_无根因数据_\n"

    lines = ["## 根因排序", ""]
    lines.append("| 排名 | 设备 | 根因 | 可能性 | 严重度 | 置信度 | 主要根因 |")
    lines.append("|------|------|------|--------|--------|--------|----------|")

    for rc in ranking:
        is_primary = rc.get("is_primary", False)
        primary_mark = "⭐" if is_primary else ""

        lines.append(
            f"| {rc.get('rank', '—')} "
            f"| {rc.get('equipment_name', '—')} "
            f"| {rc.get('root_cause_label', '—')} "
            f"| {rc.get('likelihood', '—')} "
            f"| {rc.get('severity', '—')} "
            f"| {_confidence_label(rc.get('confidence', 'low'))} "
            f"| {primary_mark} |"
        )

    return "\n".join(lines) + "\n"


def _section_aggregated_recommendations(payload: dict) -> str:
    """Render aggregated recommendations section."""
    recommendations = payload.get("recommendations", []) or []
    if not recommendations:
        return "## 维护建议\n\n_暂无建议_\n"

    lines = ["## 维护建议", ""]

    # Group by priority
    urgent = [r for r in recommendations if r.get("priority") == "urgent"]
    important = [r for r in recommendations if r.get("priority") == "important"]
    routine = [r for r in recommendations if r.get("priority") == "routine"]

    if urgent:
        lines.append("### 🔴 紧急")
        for rec in urgent:
            lines.append(f"- **{rec.get('equipment_name', '—')}**：{rec.get('action', '—')}")
            if rec.get("rationale"):
                lines.append(f"  - 理由：{rec.get('rationale')}")
        lines.append("")

    if important:
        lines.append("### 🟡 重要")
        for rec in important:
            lines.append(f"- **{rec.get('equipment_name', '—')}**：{rec.get('action', '—')}")
            if rec.get("rationale"):
                lines.append(f"  - 理由：{rec.get('rationale')}")
        lines.append("")

    if routine:
        lines.append("### 🟢 常规")
        for rec in routine:
            lines.append(f"- **{rec.get('equipment_name', '—')}**：{rec.get('action', '—')}")
        lines.append("")

    return "\n".join(lines)


def _section_data_quality(payload: dict) -> str:
    """Render data quality warnings section."""
    data_quality = payload.get("data_quality", []) or []
    if not data_quality:
        return ""

    lines = ["## 数据质量警告", ""]
    for warning in data_quality:
        lines.append(f"- {warning}")

    return "\n".join(lines) + "\n"


def render_diagnosis_html(payload: dict) -> str:
    """Render diagnosis as HTML for PDF export.

    Reuses ``export_report._markdown_to_html`` indirectly via ``write_report``;
    this helper is kept thin so PDF and Markdown share the exact same content.
    """
    # Lazy import to avoid circular dependency at module load time
    from export_report import _markdown_to_html  # type: ignore[import-not-found]

    md = render_diagnosis_markdown(payload)
    return _markdown_to_html(md, payload=None, chart_images=None)
