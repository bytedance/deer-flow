#!/usr/bin/env python3
"""图表生成脚本 — monitoring-analysis Skill。

从 monitoring_data.json 和 monitoring_features.json 生成标准 echarts 图表配置。
Agent 只需调用脚本，然后用 render_ui 渲染输出的 JSON。

Usage:
    python generate_charts.py \\
      --output-dir /mnt/user-data/outputs/ \\
      --ma-window 50

输出:
    /mnt/user-data/outputs/charts.json — 包含所有图表配置
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime


def _calculate_moving_average(values: list, window: int) -> list:
    """计算移动平均。"""
    ma = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        avg = sum(values[j] for j in range(start, i + 1)) / (i - start + 1)
        ma.append(round(avg, 4))
    return ma


def _downsample_trend_hourly(values: list[list]) -> list[list]:
    """趋势数据按小时降采样，每小时取一个点。

    Args:
        values: [[time_ms, value], ...] 格式的数据点列表

    Returns:
        降采样后的数据点列表，每小时最多一个点
    """
    if not values:
        return []

    # 按小时分组
    hourly_data = {}
    for time_ms, value in values:
        hour_key = time_ms // 3600000  # 毫秒转小时
        if hour_key not in hourly_data:
            hourly_data[hour_key] = []
        hourly_data[hour_key].append((time_ms, value))

    # 每小时取第一个点
    result = []
    for hour_key in sorted(hourly_data.keys()):
        points = hourly_data[hour_key]
        if points:
            result.append(points[0])  # 取该小时的第一个点

    return result


def _downsample_waveform(x_values: list, y_values: list, max_points: int = 200) -> tuple[list, list]:
    """波形数据降采样。

    Args:
        x_values: X轴数据（时间或频率）
        y_values: Y轴数据（振幅）
        max_points: 最大保留点数，默认200

    Returns:
        (降采样后的X, Y) 元组
    """
    if len(y_values) <= max_points:
        return x_values, y_values

    # 等间隔采样
    step = len(y_values) / max_points
    indices = [int(i * step) for i in range(max_points)]

    x_downsampled = [x_values[i] for i in indices if i < len(x_values)]
    y_downsampled = [y_values[i] for i in indices if i < len(y_values)]

    # 确保长度一致
    min_len = min(len(x_downsampled), len(y_downsampled))
    return x_downsampled[:min_len], y_downsampled[:min_len]


def _generate_trend_chart(
    point_id: str,
    point_name: str,
    feature_name: str,
    unit: str,
    trend_rows: list[dict],
    warning_threshold: float | None = None,
    critical_threshold: float | None = None,
    ma_window: int = 50,
) -> dict:
    """生成趋势折线图 echarts option。"""
    # 提取数据
    raw_values = []
    for row in trend_rows:
        time_ms = row.get("time_ms", 0)
        value = row.get("values", {}).get(feature_name)
        if value is not None:
            raw_values.append([time_ms, value])

    if not raw_values:
        return None

    # 按小时降采样
    values = _downsample_trend_hourly(raw_values)
    print(f"[charts] 趋势图 {point_name}/{feature_name}: {len(raw_values)} → {len(values)} 点", file=sys.stderr)

    # 计算移动平均
    raw_y = [v[1] for v in values]
    ma_values = _calculate_moving_average(raw_y, ma_window)
    ma_series = [[values[i][0], ma_values[i]] for i in range(len(values))]

    # 构建 echarts option
    option = {
        "tooltip": {"trigger": "axis"},
        "legend": {"data": [feature_name, "移动平均"]},
        "grid": {"left": "3%", "right": "4%", "bottom": "3%", "containLabel": True},
        "xAxis": {"type": "time"},
        "yAxis": {"type": "value", "name": unit},
        "series": [
            {
                "name": feature_name,
                "type": "line",
                "data": values,
                "lineStyle": {"color": "#5470C6"},
                "itemStyle": {"color": "#5470C6"},
            },
            {
                "name": "移动平均",
                "type": "line",
                "data": ma_series,
                "lineStyle": {"color": "#91CC75", "type": "dashed"},
                "itemStyle": {"color": "#91CC75"},
            },
        ],
    }

    # 添加阈值线
    mark_lines = []
    if warning_threshold is not None:
        mark_lines.append({
            "yAxis": warning_threshold,
            "label": {"formatter": "预警线"},
            "lineStyle": {"color": "#FAC858", "type": "dotted"},
        })
    if critical_threshold is not None:
        mark_lines.append({
            "yAxis": critical_threshold,
            "label": {"formatter": "报警线"},
            "lineStyle": {"color": "#EE6666", "type": "dotted"},
        })

    if mark_lines:
        option["series"][0]["markLine"] = {"silent": True, "data": mark_lines}

    return {
        "point_id": point_id,
        "point_name": point_name,
        "chart_type": "trend",
        "feature": feature_name,
        "props": {
            "title": f"{point_name} {feature_name} 趋势",
            "option": option,
        },
    }


def _generate_waveform_chart(
    point_id: str,
    point_name: str,
    waveform: dict,
) -> dict:
    """生成波形图 echarts option。"""
    wave_x = waveform.get("wave_x", [])
    wave_y = waveform.get("wave_y", [])

    if not wave_x or not wave_y:
        return None

    # 波形数据降采样到200个点
    wave_x, wave_y = _downsample_waveform(wave_x, wave_y, max_points=200)
    print(f"[charts] 波形图 {point_name}: 降采样到 {len(wave_x)} 点", file=sys.stderr)

    data = [[wave_x[i], wave_y[i]] for i in range(len(wave_x))]

    option = {
        "tooltip": {"trigger": "axis"},
        "grid": {"left": "3%", "right": "4%", "bottom": "3%", "containLabel": True},
        "xAxis": {"type": "value", "name": "时间 (ms)"},
        "yAxis": {"type": "value", "name": "振幅"},
        "series": [{
            "type": "line",
            "data": data,
            "lineStyle": {"color": "#5470C6", "width": 1},
            "itemStyle": {"color": "#5470C6"},
            "symbol": "none",
        }],
    }

    return {
        "point_id": point_id,
        "point_name": point_name,
        "chart_type": "waveform",
        "props": {
            "title": f"{point_name} 波形图",
            "option": option,
        },
    }


def _generate_spectrum_chart(
    point_id: str,
    point_name: str,
    waveform: dict,
    speed: float | None = None,
) -> dict:
    """生成频谱图 echarts option。"""
    spec_x = waveform.get("spec_x", [])
    spec_y = waveform.get("spec_y", [])

    if not spec_x or not spec_y:
        return None

    # 频谱数据降采样到200个点
    spec_x, spec_y = _downsample_waveform(spec_x, spec_y, max_points=200)
    print(f"[charts] 频谱图 {point_name}: 降采样到 {len(spec_x)} 点", file=sys.stderr)

    data = [[spec_x[i], spec_y[i]] for i in range(len(spec_x))]

    option = {
        "tooltip": {"trigger": "axis"},
        "grid": {"left": "3%", "right": "4%", "bottom": "3%", "containLabel": True},
        "xAxis": {"type": "value", "name": "频率 (Hz)", "min": 0},
        "yAxis": {"type": "value", "name": "幅值"},
        "series": [{
            "type": "bar",
            "data": data,
            "barWidth": 1,
            "itemStyle": {"color": "#91CC75"},
        }],
    }

    # 添加转速频率标记线
    if speed and speed > 0:
        freq_1x = speed / 60.0
        freq_2x = speed / 30.0
        option["series"][0]["markLine"] = {
            "silent": True,
            "data": [
                {"xAxis": freq_1x, "label": {"formatter": f"1X ({freq_1x:.1f}Hz)"}, "lineStyle": {"color": "#EE6666"}},
                {"xAxis": freq_2x, "label": {"formatter": f"2X ({freq_2x:.1f}Hz)"}, "lineStyle": {"color": "#FAC858"}},
            ],
        }

    return {
        "point_id": point_id,
        "point_name": point_name,
        "chart_type": "spectrum",
        "props": {
            "title": f"{point_name} 频谱图",
            "option": option,
        },
    }


def _generate_health_cards(
    point_features: list[dict],
) -> list[dict]:
    """生成测点健康状态卡片。"""
    cards = []
    for pf in point_features:
        point_name = pf.get("point_name", "")
        health_status = pf.get("health_status", "normal")
        summary = pf.get("summary", "")
        category = pf.get("category", "")
        series = pf.get("endpoint_series", "").upper()
        anomaly_count = len(pf.get("anomalies", []))

        cards.append({
            "point_id": pf.get("point_id", ""),
            "point_name": point_name,
            "chart_type": "card",
            "props": {
                "title": point_name,
                "status": health_status,
                "content": summary,
                "extra": [
                    {"label": "测点类别", "value": category},
                    {"label": "数据系列", "value": series},
                    {"label": "异常数", "value": anomaly_count},
                ],
            },
        })
    return cards


def _generate_summary_table(
    point_features: list[dict],
) -> dict:
    """生成特征汇总表。"""
    rows = []
    for pf in point_features:
        # 提取当前值
        trend_features = pf.get("trend_features", {})
        feature_stats = trend_features.get("feature_stats", {})
        current_value = ""
        if feature_stats:
            first_feature = next(iter(feature_stats.values()), {})
            current_value = first_feature.get("current", "")
            if isinstance(current_value, float):
                current_value = round(current_value, 2)

        rows.append({
            "point_name": pf.get("point_name", ""),
            "category": pf.get("category", ""),
            "health_status": pf.get("health_status", ""),
            "current_value": str(current_value),
            "anomaly_count": len(pf.get("anomalies", [])),
            "summary": pf.get("summary", ""),
        })

    return {
        "chart_type": "table",
        "props": {
            "title": "特征汇总",
            "columns": [
                {"key": "point_name", "label": "测点"},
                {"key": "category", "label": "类别"},
                {"key": "health_status", "label": "状态"},
                {"key": "current_value", "label": "当前值"},
                {"key": "anomaly_count", "label": "异常数"},
                {"key": "summary", "label": "摘要"},
            ],
            "data": rows,
        },
    }


def generate_charts(
    data_file: str,
    features_file: str,
    ma_window: int = 50,
) -> dict:
    """生成所有图表配置。"""
    # 读取数据
    with open(data_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    with open(features_file, "r", encoding="utf-8") as f:
        features = json.load(f)

    trend_data = data.get("trend", {})
    waveform_data = data.get("waveform", {})
    point_features = features.get("point_features", [])
    point_metadata = {p["point_id"]: p for p in data.get("points", [])}

    charts = []

    # 1. 健康状态卡片
    cards = _generate_health_cards(point_features)
    charts.extend(cards)
    print(f"[charts] 生成 {len(cards)} 张健康状态卡片", file=sys.stderr)

    # 2. 趋势图
    for pf in point_features:
        pid = pf.get("point_id", "")
        point_name = pf.get("point_name", "")
        meta = point_metadata.get(pid, {})
        point_type = meta.get("point_type", 0)

        trend_rows = trend_data.get(pid, [])
        if not trend_rows:
            continue

        # 获取特征名
        trend_features = pf.get("trend_features", {})
        feature_stats = trend_features.get("feature_stats", {})
        feature_names = list(feature_stats.keys())

        if not feature_names:
            continue

        # 确定要渲染的特征
        features_to_render = []

        if point_type == 83:
            # 振动测点 (type=83)：默认只渲染 pp_value，有异常则额外渲染异常特征
            features_to_render.append("pp_value")

            # 检查是否有异常特征
            anomalies = pf.get("anomalies", [])
            anomaly_features = set()
            for anomaly in anomalies:
                feature = anomaly.get("feature")
                if feature:
                    anomaly_features.add(feature)

            # 添加异常特征（去重）
            for feature in anomaly_features:
                if feature not in features_to_render:
                    features_to_render.append(feature)

            print(f"[charts] 测点 {point_name} (type=83): 渲染特征 {features_to_render} (异常特征: {anomaly_features})", file=sys.stderr)
        else:
            # 其他类型测点：渲染所有特征
            features_to_render = feature_names

        # 为每个特征生成趋势图
        for feature_name in features_to_render:
            chart = _generate_trend_chart(
                point_id=pid,
                point_name=point_name,
                feature_name=feature_name,
                unit=meta.get("category", ""),
                trend_rows=trend_rows,
                ma_window=ma_window,
            )
            if chart:
                charts.append(chart)

    print(f"[charts] 生成趋势图: {sum(1 for c in charts if c['chart_type'] == 'trend')}", file=sys.stderr)

    # 3. 波形图和频谱图
    for pf in point_features:
        pid = pf.get("point_id", "")
        point_name = pf.get("point_name", "")

        waveform = waveform_data.get(pid)
        if not waveform:
            continue

        # 波形图
        wave_chart = _generate_waveform_chart(pid, point_name, waveform)
        if wave_chart:
            charts.append(wave_chart)

        # 频谱图
        speed = waveform.get("speed")
        spec_chart = _generate_spectrum_chart(pid, point_name, waveform, speed)
        if spec_chart:
            charts.append(spec_chart)

    wave_count = sum(1 for c in charts if c["chart_type"] == "waveform")
    spec_count = sum(1 for c in charts if c["chart_type"] == "spectrum")
    print(f"[charts] 生成波形图: {wave_count}, 频谱图: {spec_count}", file=sys.stderr)

    # 4. 汇总表
    table = _generate_summary_table(point_features)
    charts.append(table)
    print(f"[charts] 生成特征汇总表", file=sys.stderr)

    return {
        "generated_at": datetime.now().isoformat(),
        "total_charts": len(charts),
        "charts": charts,
    }


def main():
    parser = argparse.ArgumentParser(description="生成监测分析图表")
    parser.add_argument("--data-file", default="/mnt/user-data/outputs/monitoring_data.json")
    parser.add_argument("--features-file", default="/mnt/user-data/outputs/monitoring_features.json")
    parser.add_argument("--output-dir", default="/mnt/user-data/outputs/")
    parser.add_argument("--ma-window", type=int, default=50, help="移动平均窗口大小")
    args = parser.parse_args()

    if not os.path.exists(args.data_file):
        print(f"[charts] 错误: 数据文件不存在: {args.data_file}", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(args.features_file):
        print(f"[charts] 错误: 特征文件不存在: {args.features_file}", file=sys.stderr)
        sys.exit(1)

    result = generate_charts(args.data_file, args.features_file, args.ma_window)

    # 写入输出文件
    os.makedirs(args.output_dir, exist_ok=True)
    output_path = os.path.join(args.output_dir, "charts.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[charts] 图表配置已生成: {output_path}", file=sys.stderr)
    print(f"[charts] 总计 {result['total_charts']} 个图表", file=sys.stderr)


if __name__ == "__main__":
    main()
