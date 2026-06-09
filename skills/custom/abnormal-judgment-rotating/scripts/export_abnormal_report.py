#!/usr/bin/env python3
"""研判报告导出 — abnormal-judgment-rotating Skill。

生成 Markdown 格式的异常研判报告。

Usage:
    python export_abnormal_report.py \
      --detail /mnt/user-data/outputs/abnormal_detail.json \
      --monitoring /mnt/user-data/outputs/abnormal_monitoring.json \
      --verdict /mnt/user-data/outputs/judgment_result.json \
      --mac-name "设备名称" \
      --component-name "子设备名称" \
      --output-dir /mnt/user-data/outputs/

输出:
    judgment_report.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime


def _get_verdict_cn(verdict: str) -> str:
    """判定结论中文名。"""
    verdict_map = {
        "real_fault": "真实故障",
        "suspected": "疑似异常",
        "false_alarm": "误报",
    }
    return verdict_map.get(verdict, verdict)


def _get_type_cn(event_type: str) -> str:
    """事件类型中文名。"""
    type_map = {
        "sensor": "传感器异常",
        "t": "阈值超限",
        "w": "波动异常",
        "k": "趋势异常",
        "d": "升速曲线偏差",
    }
    return type_map.get(event_type, event_type)


def _get_severity_label(level: int) -> str:
    """根据 eventLevel 返回严重程度。"""
    if level >= 60:
        return "🔴 紧急"
    elif level >= 41:
        return "🟠 重要"
    elif level >= 21:
        return "🟡 一般"
    else:
        return "🔵 提示"


def _get_fault_type_cn(fault_type: str) -> str:
    """故障码中文名。"""
    fault_map = {
        "unbalance_1x": "不平衡",
        "misalignment": "不对中",
        "critical_response": "临界响应大",
        "thermal_bend": "转子热弯曲",
        "permanent_bend": "转子永久性弯曲",
        "rub_seal": "动静摩擦/密封摩擦",
        "support_bearing": "支撑轴承装配异常",
        "rotating_stall_surge": "旋转失速/喘振",
        "runout": "晃度",
        "axial_offset_calibration": "轴位移零点调校异常",
        "bearing_temperature_high": "支撑轴承温度异常",
        "thrust_bearing_temperature_high": "推力轴承温度异常",
    }
    return fault_map.get(fault_type, fault_type)


def _ms_to_str(ms: int) -> str:
    """毫秒时间戳转可读字符串。"""
    if not ms:
        return "-"
    dt = datetime.fromtimestamp(ms / 1000)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def render_report(
    mac_name: str,
    component_name: str,
    mac_path: str,
    detail: dict,
    monitoring: dict,
    verdict: dict,
) -> str:
    """渲染 Markdown 报告。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    overall_verdict = verdict.get("overall_verdict", "unknown")
    confidence = verdict.get("overall_confidence", 0)
    severity = verdict.get("severity", "low")
    suspected_fault = verdict.get("suspected_fault_type", "")
    evidence = verdict.get("evidence_summary", [])
    recommendations = verdict.get("recommendations", [])
    event_verdicts = verdict.get("event_verdicts", [])
    events = detail.get("events", [])

    lines = [
        f"# 异常研判报告",
        "",
        f"**设备**: {mac_name} - {component_name}",
        "",
        f"**路径**: {mac_path}",
        "",
        f"**研判时间**: {now}",
        "",
        "---",
        "",
        "## 综合结论",
        "",
        f"| 项目 | 结论 |",
        f"|------|------|",
        f"| **研判结论** | {_get_verdict_cn(overall_verdict)} |",
        f"| **置信度** | {int(confidence * 100)}% |",
        f"| **严重程度** | {severity} |",
    ]

    if suspected_fault:
        lines.append(f"| **疑似故障** | {_get_fault_type_cn(suspected_fault)} |")

    lines.extend([
        "",
        "---",
        "",
        "## 异常事件明细",
        "",
        f"共 {len(events)} 个异常事件：",
        "",
        "| 序号 | 类型 | 等级 | 时间 | 判定 | 置信度 | 疑似故障 |",
        "|:----:|------|:----:|------|:----:|:------:|---------|",
    ])

    for i, evt in enumerate(events):
        event_type = evt.get("type", "")
        event_level = evt.get("eventLevel", 0)
        event_time = _ms_to_str(evt.get("time", 0))

        # 查找对应的研判结论
        ev = None
        for v in event_verdicts:
            if v.get("event_index") == i:
                ev = v
                break

        verdict_str = _get_verdict_cn(ev.get("verdict", "")) if ev else "-"
        conf_str = f"{int(ev.get('confidence', 0) * 100)}%" if ev else "-"
        fault_str = _get_fault_type_cn(ev.get("suspected_fault_type", "")) if ev else "-"

        lines.append(
            f"| {i + 1} | {_get_type_cn(event_type)} | {_get_severity_label(event_level)} | "
            f"{event_time} | {verdict_str} | {conf_str} | {fault_str} |"
        )

    if evidence:
        lines.extend([
            "",
            "---",
            "",
            "## 证据链",
            "",
        ])
        for e in evidence:
            lines.append(f"- {e}")

    if recommendations:
        lines.extend([
            "",
            "---",
            "",
            "## 处置建议",
            "",
        ])
        for r in recommendations:
            lines.append(f"- {r}")

    # 测点数据概览
    points_info = monitoring.get("points", [])
    trend_data = monitoring.get("trend", {})
    waveform_data = monitoring.get("waveform", {})

    if points_info:
        lines.extend([
            "",
            "---",
            "",
            "## 监测数据概览",
            "",
            f"- 分析测点: {len(points_info)} 个",
            f"- 趋势数据: {len(trend_data)} 个测点",
            f"- 波形数据: {len(waveform_data)} 个测点",
            "",
            "| 测点 | 类别 | 有波形 |",
            "|------|------|:------:|",
        ])
        for pt in points_info:
            pid = pt.get("point_id", "")
            name = pt.get("name", pid)
            category = pt.get("category", "-")
            has_wave = "✅" if pid in waveform_data else "❌"
            lines.append(f"| {name} | {category} | {has_wave} |")

    lines.extend([
        "",
        "---",
        "",
        f"*报告生成时间: {now}*",
    ])

    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="研判报告导出")
    p.add_argument("--detail", required=True, help="abnormal_detail.json 路径")
    p.add_argument("--monitoring", required=True, help="abnormal_monitoring.json 路径")
    p.add_argument("--verdict", required=True, help="judgment_result.json 路径")
    p.add_argument("--mac-name", default="", help="设备名称")
    p.add_argument("--component-name", default="", help="子设备名称")
    p.add_argument("--mac-path", default="", help="设备路径")
    p.add_argument("--output-dir", default="/mnt/user-data/outputs", help="输出目录")
    args = p.parse_args()

    # 读取输入文件
    with open(args.detail, encoding="utf-8") as f:
        detail = json.load(f)
    detail = detail.get("data", detail) if isinstance(detail, dict) else detail

    with open(args.monitoring, encoding="utf-8") as f:
        monitoring = json.load(f)

    with open(args.verdict, encoding="utf-8") as f:
        verdict = json.load(f)

    # 渲染报告
    report = render_report(
        mac_name=args.mac_name,
        component_name=args.component_name,
        mac_path=args.mac_path,
        detail=detail,
        monitoring=monitoring,
        verdict=verdict,
    )

    # 输出
    output_file = os.path.join(args.output_dir, "judgment_report.md")
    os.makedirs(args.output_dir, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"[export] 输出: {output_file}", file=sys.stderr)
    print(f"[export] 报告长度: {len(report)} 字符", file=sys.stderr)


if __name__ == "__main__":
    main()
