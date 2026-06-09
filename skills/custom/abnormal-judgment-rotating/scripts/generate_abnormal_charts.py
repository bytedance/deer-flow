#!/usr/bin/env python3
"""研判报告图表生成 — abnormal-judgment-rotating Skill。

从 abnormal_detail.json、abnormal_monitoring.json、judgment_result.json 生成 charts.json。

Usage:
    python generate_abnormal_charts.py \
      --detail /mnt/user-data/outputs/abnormal_detail.json \
      --monitoring /mnt/user-data/outputs/abnormal_monitoring.json \
      --verdict /mnt/user-data/outputs/judgment_result.json \
      --mac-name "设备名称" \
      --component-name "子设备名称" \
      --mac-path "设备路径" \
      --output-dir /mnt/user-data/outputs/

输出:
    charts.json — 包含所有图表配置，用 render_charts_file 批量渲染
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime


# ===== 辅助函数 =====

def _downsample_trend_hourly(values: list[list]) -> list[list]:
    """趋势数据按小时降采样。"""
    if not values:
        return []
    hourly_data = {}
    for time_ms, value in values:
        hour_key = time_ms // 3600000
        if hour_key not in hourly_data:
            hourly_data[hour_key] = []
        hourly_data[hour_key].append((time_ms, value))
    result = []
    for hour_key in sorted(hourly_data.keys()):
        points = hourly_data[hour_key]
        if points:
            result.append(points[0])
    return result


def _downsample_waveform(x_values: list, y_values: list, max_points: int = 200) -> tuple[list, list]:
    """波形数据降采样。"""
    if len(y_values) <= max_points:
        return x_values, y_values
    step = len(y_values) / max_points
    indices = [int(i * step) for i in range(max_points)]
    x_down = [x_values[i] for i in indices if i < len(x_values)]
    y_down = [y_values[i] for i in indices if i < len(y_values)]
    min_len = min(len(x_down), len(y_down))
    return x_down[:min_len], y_down[:min_len]


def _get_severity_label(level: int) -> str:
    """根据 eventLevel 返回严重程度。"""
    if level >= 60:
        return "紧急"
    elif level >= 41:
        return "重要"
    elif level >= 21:
        return "一般"
    else:
        return "提示"


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


def _get_verdict_cn(verdict: str) -> str:
    """判定结论中文名。"""
    verdict_map = {
        "real_fault": "真实故障",
        "suspected": "疑似异常",
        "false_alarm": "误报",
    }
    return verdict_map.get(verdict, verdict)


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


# ===== 图表生成函数 =====

def _generate_card(
    mac_name: str,
    component_name: str,
    mac_path: str,
    verdict: dict,
) -> dict:
    """生成健康状态卡片。"""
    overall_verdict = verdict.get("overall_verdict", "unknown")
    confidence = verdict.get("overall_confidence", 0)
    severity = verdict.get("severity", "low")
    suspected_fault = verdict.get("suspected_fault_type", "")

    # 构建显示值
    if overall_verdict == "real_fault":
        value = f"真实故障 ({_get_fault_type_cn(suspected_fault)})"
        status = "critical"
    elif overall_verdict == "suspected":
        value = f"疑似异常 ({_get_fault_type_cn(suspected_fault)})"
        status = "warning"
    else:
        value = "误报"
        status = "normal"

    return {
        "chart_type": "card",
        "props": {
            "title": f"{mac_name} - {component_name}",
            "status": status,
            "content": f"置信度 {int(confidence * 100)}% · {severity}",
            "extra": [
                {"label": "研判结论", "value": _get_verdict_cn(overall_verdict)},
                {"label": "严重程度", "value": severity},
                {"label": "设备路径", "value": mac_path},
            ],
        },
    }


def _generate_table(verdict: dict, detail: dict) -> dict:
    """生成异常事件明细表。"""
    events = detail.get("events", [])
    event_verdicts = verdict.get("event_verdicts", [])

    # 构建表格数据
    data = []
    for i, evt in enumerate(events):
        event_type = evt.get("type", "")
        event_level = evt.get("eventLevel", 0)
        desc = evt.get("description", "") or evt.get("desc", "")

        # 查找对应的研判结论
        ev = None
        for v in event_verdicts:
            if v.get("event_index") == i:
                ev = v
                break

        verdict_str = _get_verdict_cn(ev.get("verdict", "")) if ev else "未研判"
        confidence = f"{int(ev.get('confidence', 0) * 100)}%" if ev else "-"
        fault_type = _get_fault_type_cn(ev.get("suspected_fault_type", "")) if ev else "-"

        data.append({
            "type_cn": _get_type_cn(event_type),
            "desc": desc or _get_type_cn(event_type),
            "level": f"{event_level} ({_get_severity_label(event_level)})",
            "verdict_cn": verdict_str,
            "confidence": confidence,
            "fault_type": fault_type,
        })

    return {
        "chart_type": "table",
        "props": {
            "title": "异常事件研判明细",
            "columns": [
                {"key": "type_cn", "label": "类型"},
                {"key": "desc", "label": "异常描述"},
                {"key": "level", "label": "等级"},
                {"key": "verdict_cn", "label": "判定"},
                {"key": "confidence", "label": "置信度"},
                {"key": "fault_type", "label": "疑似故障"},
            ],
            "data": data,
        },
    }


def _generate_trend_chart(
    point_id: str,
    point_name: str,
    trend_data: list[dict],
) -> dict | None:
    """生成趋势折线图。"""
    if not trend_data:
        return None

    # 提取 pp_value 或第一个可用特征
    raw_values = []
    for row in trend_data:
        time_ms = row.get("time_ms", 0)
        values = row.get("values", {})
        # 优先使用 pp_value (峰峰值)，否则用 rms
        value = values.get("pp_value") or values.get("rms") or values.get("value")
        if value is not None:
            raw_values.append([time_ms, value])

    if not raw_values:
        return None

    # 按小时降采样
    values = _downsample_trend_hourly(raw_values)

    # 构建 echarts option
    option = {
        "tooltip": {"trigger": "axis"},
        "grid": {"left": "3%", "right": "4%", "bottom": "3%", "containLabel": True},
        "xAxis": {"type": "time"},
        "yAxis": {"type": "value", "name": "振动值 (μm)"},
        "series": [{
            "type": "line",
            "data": values,
            "lineStyle": {"color": "#5470C6"},
            "itemStyle": {"color": "#5470C6"},
            "symbol": "none",
            "areaStyle": {"color": "rgba(84, 112, 198, 0.1)"},
        }],
    }

    return {
        "point_id": point_id,
        "point_name": point_name,
        "chart_type": "trend",
        "feature": "pp_value",
        "props": {
            "title": f"{point_name} 趋势图",
            "option": option,
        },
    }


def _generate_spectrum_chart(
    point_id: str,
    point_name: str,
    waveform: dict,
) -> dict | None:
    """生成频谱图。"""
    spec_x = waveform.get("spec_x", [])
    spec_y = waveform.get("spec_y", [])

    if not spec_x or not spec_y:
        return None

    # 降采样
    spec_x, spec_y = _downsample_waveform(spec_x, spec_y, max_points=200)

    data = [[spec_x[i], spec_y[i]] for i in range(len(spec_x))]

    option = {
        "tooltip": {"trigger": "axis"},
        "grid": {"left": "3%", "right": "4%", "bottom": "3%", "containLabel": True},
        "xAxis": {"type": "value", "name": "频率 (Hz)"},
        "yAxis": {"type": "value", "name": "振幅 (μm)"},
        "series": [{
            "type": "bar",
            "data": data,
            "itemStyle": {"color": "#91CC75"},
        }],
    }

    # 添加 1X/2X 标注线（如果有转速信息）
    speed = waveform.get("speed")
    if speed and speed > 0:
        freq_1x = speed / 60
        freq_2x = speed / 30
        mark_lines = [
            {"xAxis": freq_1x, "label": {"formatter": "1X"}, "lineStyle": {"color": "#EE6666", "type": "dashed"}},
            {"xAxis": freq_2x, "label": {"formatter": "2X"}, "lineStyle": {"color": "#FAC858", "type": "dashed"}},
        ]
        option["series"][0]["markLine"] = {"silent": True, "data": mark_lines}

    return {
        "point_id": point_id,
        "point_name": point_name,
        "chart_type": "spectrum",
        "props": {
            "title": f"{point_name} 频谱图",
            "option": option,
        },
    }


def _generate_conclusion_markdown(verdict: dict) -> dict:
    """生成综合结论 markdown。"""
    overall_verdict = verdict.get("overall_verdict", "unknown")
    confidence = verdict.get("overall_confidence", 0)
    severity = verdict.get("severity", "low")
    suspected_fault = verdict.get("suspected_fault_type", "")
    evidence = verdict.get("evidence_summary", [])
    recommendations = verdict.get("recommendations", [])

    lines = [
        "## 综合结论",
        "",
        f"**研判结论**: {_get_verdict_cn(overall_verdict)}",
        "",
        f"**置信度**: {int(confidence * 100)}%",
        "",
        f"**严重程度**: {severity}",
        "",
    ]

    if suspected_fault:
        lines.append(f"**疑似故障**: {_get_fault_type_cn(suspected_fault)}")
        lines.append("")

    if evidence:
        lines.append("### 证据链")
        lines.append("")
        for e in evidence:
            lines.append(f"- {e}")
        lines.append("")

    if recommendations:
        lines.append("### 处置建议")
        lines.append("")
        for r in recommendations:
            lines.append(f"- {r}")
        lines.append("")

    return {
        "chart_type": "markdown",
        "props": {
            "content": "\n".join(lines),
        },
    }


# ===== 主函数 =====

def main():
    p = argparse.ArgumentParser(description="研判报告图表生成")
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

    charts = []

    # 1. 健康状态卡片
    charts.append(_generate_card(args.mac_name, args.component_name, args.mac_path, verdict))

    # 2. 异常事件明细表
    charts.append(_generate_table(verdict, detail))

    # 3. 趋势图（每个测点）
    trend_data = monitoring.get("trend", {})
    points_info = {pt["point_id"]: pt for pt in monitoring.get("points", [])}

    for point_id, data in trend_data.items():
        point_name = points_info.get(point_id, {}).get("name", point_id)
        chart = _generate_trend_chart(point_id, point_name, data)
        if chart:
            charts.append(chart)

    # 4. 频谱图（有波形的测点）
    waveform_data = monitoring.get("waveform", {})
    for point_id, data in waveform_data.items():
        point_name = points_info.get(point_id, {}).get("name", point_id)
        chart = _generate_spectrum_chart(point_id, point_name, data)
        if chart:
            charts.append(chart)

    # 5. 综合结论 markdown
    charts.append(_generate_conclusion_markdown(verdict))

    # 输出（必须是 {"charts": [...]} 格式）
    output_file = os.path.join(args.output_dir, "charts.json")
    os.makedirs(args.output_dir, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({"charts": charts}, f, ensure_ascii=False, indent=2)

    print(f"[charts] 输出: {output_file} ({len(charts)} 个图表)", file=sys.stderr)


if __name__ == "__main__":
    main()
