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
            machine_lines.append(f"- 设备：{s.get('equipment_id', '—')}（运行阶段：{s.get('operation_phase', '—')}，告警状态：{s.get('alarm_status', '—')}）")
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
        if max_value:
            lines.append(
                f"- {s.get('equipment_id', '—')} · {max_value.get('point', '—')} · {max_value.get('feature', '—')} 最大值：{_format_value(max_value.get('value'))} {max_value.get('unit', '')}（告警：{s.get('alarm_status', '—')}）"
            )
        else:
            lines.append(f"- {s.get('equipment_id', '—')}（告警：{s.get('alarm_status', '—')}）")
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
        lines.append(
            f"| {idx} | {row.get('category', '—')} | {row.get('equipment_id', '—') or '—'} | {row.get('point', '—')} | "
            f"{row.get('feature', '—')} | {_format_value(row.get('value'))} | {_format_value(row.get('threshold'))} | "
            f"{_verdict_label(row.get('verdict', '—'))} |"
        )
    return "\n".join(lines) + "\n"


def _section_diagnosis(payload: dict) -> str:
    matches = payload.get("rule_matches", []) or []
    if not matches:
        return "## 4. 诊断结论\n\n_未匹配到任何规则；建议加密监测并由领域专家复核_\n"
    lines = ["## 4. 诊断结论", ""]
    primary = matches[0]
    lines.append(
        f"**主诊断**：{primary.get('fault_family', '—')}"
        + (f"（subtype: {primary.get('fault_subtype')}）" if primary.get("fault_subtype") else "")
    )
    lines.append("")
    lines.append(f"- 设备：{primary.get('equipment_id', '—')}")
    lines.append(f"- 置信度：{_confidence_label(primary.get('confidence', '—'))}")
    lines.append(f"- 命中规则节：{primary.get('rule_section', '—')}")
    supporting = primary.get("supporting_evidence_indices", []) or []
    marginal = primary.get("marginal_evidence_indices", []) or []
    lines.append(f"- 支持证据（exceed）：第 {', '.join(str(i) for i in supporting) or '—'} 行")
    if marginal:
        lines.append(f"- 边缘证据（marginal）：第 {', '.join(str(i) for i in marginal)} 行（不计入主诊断）")
    missing = primary.get("missing_evidence", []) or []
    if missing:
        lines.append(f"- 缺失证据：{', '.join(missing)}")
    return "\n".join(lines) + "\n"


def _section_differential(payload: dict) -> str:
    matches = payload.get("rule_matches", []) or []
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
            f"- {prefix}{case.get('equipment_id', '—')}（{case.get('fault_family', '—')}，{case.get('occurred_at', '—')}）：{case.get('summary', '—')}"
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
    """
    _ = thread_id  # reserved
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


def render_diagnosis_html(payload: dict) -> str:
    """Render diagnosis as HTML for PDF export.

    Reuses ``export_report._markdown_to_html`` indirectly via ``write_report``;
    this helper is kept thin so PDF and Markdown share the exact same content.
    """
    # Lazy import to avoid circular dependency at module load time
    from export_report import _markdown_to_html  # type: ignore[import-not-found]

    md = render_diagnosis_markdown(payload)
    return _markdown_to_html(md, payload=None, chart_images=None)
