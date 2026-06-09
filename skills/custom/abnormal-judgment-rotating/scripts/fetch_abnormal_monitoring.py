#!/usr/bin/env python3
"""监测数据获取适配层 — abnormal-judgment-rotating Skill。

从 abnormal_detail.json 提取测点参数，调用 monitoring-data Skill 获取趋势/波形数据。

Usage:
    python fetch_abnormal_monitoring.py \
      --input /mnt/user-data/outputs/abnormal_detail.json \
      --include-waveform auto \
      --output-dir /mnt/user-data/outputs/

输出:
    abnormal_monitoring.json — 与 monitoring_data.json 格式一致
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

# monitoring-data 脚本路径
MONITORING_DATA_SCRIPT = "/mnt/skills/custom/monitoring-data/scripts/fetch_monitoring_data.py"


def _ms_to_iso(ms: int) -> str:
    """毫秒时间戳转 ISO 格式字符串。"""
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _infer_position_type(value_type: str, point_name: str) -> int:
    """从 valueType 和 pointName 推断 positionType。

    Returns:
        83: 轴振（有波形）
        82: 其他（轴位移、温度等，无波形）
    """
    vt = (value_type or "").lower()
    name = (point_name or "").lower()

    # 振动类 → 83（有波形）
    if any(kw in vt or kw in name for kw in ["振动", "轴振", "振速", "vibration"]):
        return 83

    # 默认 → 82
    return 82


def _should_include_waveform(event_type: str, event_level: int, include_waveform: str) -> bool:
    """判断是否获取波形数据。"""
    if include_waveform == "true":
        return True
    if include_waveform == "false":
        return False
    # auto: 仅对 type=t/w 且 eventLevel>=21 获取波形
    return event_type in ("t", "w") and event_level >= 21


def _extract_points_from_detail(detail: dict) -> list[dict]:
    """从 abnormal_detail.json 提取所有测点信息。

    Returns:
        [{"point_id": "...", "point_name": "...", "value_type": "...", "point_type": 83,
          "factory_id": "...", "start_ms": 0, "end_ms": 0, "event_type": "...", "event_level": 0}]
    """
    points = []
    events = detail.get("events", [])

    for evt in events:
        jp = evt.get("jumpParams", {}) or {}
        factory_id = str(jp.get("factoryId", ""))
        start_ms = jp.get("startTime", 0)
        end_ms = jp.get("endTime", 0)

        # 如果没有时间范围，用事件时间 ± 2小时
        if not start_ms or not end_ms:
            evt_time = evt.get("time", 0)
            if evt_time:
                start_ms = evt_time - 2 * 3600 * 1000
                end_ms = evt_time + 2 * 3600 * 1000

        event_type = evt.get("type", "")
        event_level = evt.get("eventLevel", 0)

        for pt in jp.get("points", []):
            point_id = str(pt.get("pointId", ""))
            if not point_id:
                continue

            # 优先使用原始数据中的 pointType，如果没有再推断
            point_type = pt.get("pointType")
            if point_type is None:
                point_type = _infer_position_type(pt.get("valueType", ""), pt.get("pointName", ""))

            points.append({
                "point_id": point_id,
                "point_name": pt.get("pointName", ""),
                "value_type": pt.get("valueType", ""),
                "point_type": point_type,
                "factory_id": factory_id,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "event_type": event_type,
                "event_level": event_level,
            })

    return points


def _group_points_by_time_range(points: list[dict]) -> dict[tuple, list[dict]]:
    """按时间范围分组测点（相同时间范围的合并为一次调用）。"""
    groups = {}
    for pt in points:
        key = (pt["factory_id"], pt["start_ms"], pt["end_ms"])
        if key not in groups:
            groups[key] = []
        groups[key].append(pt)
    return groups


def _call_fetch_monitoring_data(
    point_ids: list[str],
    point_metadata: dict,
    start_ms: int,
    end_ms: int,
    include_waveform: bool,
    output_dir: str,
) -> dict | None:
    """调用 monitoring-data/fetch_monitoring_data.py。"""
    if not os.path.exists(MONITORING_DATA_SCRIPT):
        print(f"[fetch_abnormal] 错误: monitoring-data 脚本不存在: {MONITORING_DATA_SCRIPT}", file=sys.stderr)
        return None

    cmd = [
        "python",
        MONITORING_DATA_SCRIPT,
        "--point-ids", ",".join(point_ids),
        "--point-metadata", json.dumps(point_metadata, ensure_ascii=False),
        "--start", _ms_to_iso(start_ms),
        "--end", _ms_to_iso(end_ms),
        "--include-waveform", "true" if include_waveform else "false",
        "--output-dir", output_dir,
    ]

    print(f"[fetch_abnormal] 调用: {' '.join(cmd[:6])}...", file=sys.stderr)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"[fetch_abnormal] 脚本错误: {result.stderr}", file=sys.stderr)
            return None

        # 读取输出文件
        output_file = os.path.join(output_dir, "monitoring_data.json")
        if os.path.exists(output_file):
            with open(output_file, encoding="utf-8") as f:
                return json.load(f)
        return None
    except subprocess.TimeoutExpired:
        print("[fetch_abnormal] 脚本超时", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[fetch_abnormal] 调用异常: {e}", file=sys.stderr)
        return None


def _merge_results(results: list[dict]) -> dict:
    """合并多次调用的结果。"""
    merged = {
        "schema_version": "2.0",
        "points": [],
        "time_range": {"start_ms": 0, "end_ms": 0},
        "trend": {},
        "waveform": {},
        "events": {},
        "data_source": "ins",
        "data_notes": [],
        "events_source": "abnormal_detail.json",
    }

    seen_points = set()
    for r in results:
        if not r:
            continue

        # 合并 points（去重）
        for pt in r.get("points", []):
            pid = pt.get("point_id")
            if pid and pid not in seen_points:
                seen_points.add(pid)
                merged["points"].append(pt)

        # 合并 trend
        for pid, data in r.get("trend", {}).items():
            if pid not in merged["trend"]:
                merged["trend"][pid] = data

        # 合并 waveform
        for pid, data in r.get("waveform", {}).items():
            if pid not in merged["waveform"]:
                merged["waveform"][pid] = data

        # 合并 events
        for mid, evts in r.get("events", {}).items():
            if mid not in merged["events"]:
                merged["events"][mid] = evts

        # 合并 data_notes
        for note in r.get("data_notes", []):
            if note not in merged["data_notes"]:
                merged["data_notes"].append(note)

        # 更新时间范围
        tr = r.get("time_range", {})
        if tr.get("start_ms") and (not merged["time_range"]["start_ms"] or tr["start_ms"] < merged["time_range"]["start_ms"]):
            merged["time_range"]["start_ms"] = tr["start_ms"]
        if tr.get("end_ms") and tr["end_ms"] > merged["time_range"]["end_ms"]:
            merged["time_range"]["end_ms"] = tr["end_ms"]

    return merged


def main():
    p = argparse.ArgumentParser(description="监测数据获取适配层")
    p.add_argument("--input", required=True, help="abnormal_detail.json 路径")
    p.add_argument("--include-waveform", default="auto", help="是否获取波形: auto/true/false")
    p.add_argument("--output-dir", default="/mnt/user-data/outputs", help="输出目录")
    args = p.parse_args()

    # 读取异常详情
    with open(args.input, encoding="utf-8") as f:
        raw = json.load(f)
    detail = raw.get("data", raw) if isinstance(raw, dict) else raw

    # 提取测点
    points = _extract_points_from_detail(detail)
    if not points:
        print("[fetch_abnormal] 警告: 未找到任何测点", file=sys.stderr)
        # 输出空结果
        result = {
            "schema_version": "2.0",
            "points": [],
            "time_range": {},
            "trend": {},
            "waveform": {},
            "events": {},
            "data_source": "ins",
            "data_notes": ["no points found in abnormal_detail.json"],
            "events_source": "abnormal_detail.json",
        }
        output_file = os.path.join(args.output_dir, "abnormal_monitoring.json")
        os.makedirs(args.output_dir, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"[fetch_abnormal] 输出空结果: {output_file}", file=sys.stderr)
        return

    print(f"[fetch_abnormal] 提取到 {len(points)} 个测点", file=sys.stderr)

    # 按时间范围分组
    groups = _group_points_by_time_range(points)
    print(f"[fetch_abnormal] 分为 {len(groups)} 组调用", file=sys.stderr)

    # 逐组调用
    results = []
    for (factory_id, start_ms, end_ms), group_points in groups.items():
        point_ids = [pt["point_id"] for pt in group_points]

        # 构建 point_metadata
        point_metadata = {}
        include_waveform = False
        for pt in group_points:
            pid = pt["point_id"]
            # 使用提取时已确定的 point_type（优先原始数据，其次推断）
            position_type = pt["point_type"]
            point_metadata[pid] = {
                "type": position_type,
                "machineId": factory_id,
                "name": pt["point_name"],
                "componentName": "",
            }
            # 判断是否需要波形
            if _should_include_waveform(pt["event_type"], pt["event_level"], args.include_waveform):
                include_waveform = True

        # 调用 monitoring-data
        result = _call_fetch_monitoring_data(
            point_ids=point_ids,
            point_metadata=point_metadata,
            start_ms=start_ms,
            end_ms=end_ms,
            include_waveform=include_waveform,
            output_dir=args.output_dir,
        )
        results.append(result)

    # 合并结果
    merged = _merge_results(results)

    # 输出
    output_file = os.path.join(args.output_dir, "abnormal_monitoring.json")
    os.makedirs(args.output_dir, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"[fetch_abnormal] 输出: {output_file}", file=sys.stderr)
    print(f"[fetch_abnormal] 测点: {len(merged['points'])} 个, 趋势: {len(merged['trend'])} 个, 波形: {len(merged['waveform'])} 个", file=sys.stderr)


if __name__ == "__main__":
    main()
