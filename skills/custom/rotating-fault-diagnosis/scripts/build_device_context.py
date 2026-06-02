#!/usr/bin/env python3
"""Build device_context.json from raw device tree.

Handles ALL mechanical work required by rotating-device-context SKILL.md:
- Tree hierarchy preservation
- Orphan point re-mounting by belongShaftId + direction keywords
- Point type inference (type_82 name → category, type_83 → 轴振/轴位移波形)
- target_info construction (probe_ids, waveform_probe_ids, bearing_ids, owner_device_id)

LLM only needs to fill: device_type, process_type, device_structure (value/confidence/reason).

Usage:
    python build_device_context.py \
      --input /mnt/user-data/outputs/device_tree_raw.json \
      --machine-id <id> --component-id <id> \
      --output /mnt/user-data/outputs/device_context.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from typing import Any

# ── Point type inference for type_82 ──────────────────────────────────────

_TYPE_82_CATEGORIES = [
    (re.compile(r"轴承温度|轴瓦温度|支撑轴承温度|止推轴瓦温度"), "轴承温度"),
    (re.compile(r"轴位移|位移"), "轴位移"),
    (re.compile(r"入口流量"), "入口流量"),
    (re.compile(r"入口压力|入口温度|进气"), "压缩机进气参数"),
    (re.compile(r"出口温度|排气温度"), "出口温度"),
    (re.compile(r"油温|润滑油温度|回油温度|进油温度"), "润滑油温度"),
    (re.compile(r"防喘振阀|防喘阀|防喘"), "防喘振阀开度"),
]

DIRECTION_KEYWORDS = [
    (re.compile(r"联端|驱动端|耦合端"), "联端"),
    (re.compile(r"非联端|非驱动端|自由端"), "非联端"),
]

# ── Tree walking ──────────────────────────────────────────────────────────

def _find_node(root: dict, target_id: str) -> dict | None:
    if root.get("id") == target_id:
        return root
    for child in root.get("children", []):
        if isinstance(child, dict):
            r = _find_node(child, target_id)
            if r:
                return r
    return None


def _walk(root: dict, fn, depth: int = 0) -> None:
    fn(root, depth)
    for child in root.get("children", []):
        if isinstance(child, dict):
            _walk(child, fn, depth + 1)


def _infer_direction(name: str) -> str:
    for pattern, label in DIRECTION_KEYWORDS:
        if pattern.search(name):
            return label
    return ""


def _infer_bearing_type(name: str) -> list[str]:
    types = []
    if re.search(r"止推|推力轴承|推力瓦|主止推|副止推", name):
        types.append("推力轴承")
    if re.search(r"支撑轴承|径向轴承|轴瓦(?!温度)", name) or not types:
        types.append("支撑轴承")
    if not types:
        types.append("无法推断")
    return types


def _infer_point_type(node: dict) -> str:
    """Infer the human-readable type for a measurement point."""
    tn = node.get("type_num", 0)
    name = node.get("name", "")
    if tn == 83:
        return "轴位移波形" if "波形" in name else "轴振"
    if tn == 81:
        return "键相"
    if tn == 82:
        for pattern, label in _TYPE_82_CATEGORIES:
            if pattern.search(name):
                return label
        return "其他工艺参数"
    return f"未知(type_num={tn})"


# ── Device type hint for type_80 nodes ────────────────────────────────────

def _infer_80_device_type(name: str) -> str:
    if re.search(r"汽轮机|透平", name):
        return "汽轮机"
    if re.search(r"齿轮箱", name):
        return "齿轮箱"
    if re.search(r"螺杆", name):
        return "螺杆式压缩机"
    if re.search(r"烟气轮机", name):
        return "烟气轮机"
    if re.search(r"发电机", name):
        return "发电机"
    if re.search(r"电机", name):
        return "电机"
    if re.search(r"压缩机|增压机|空压机|低压缸|高压缸|中压缸", name):
        return "离心式压缩机"
    return "未知"


def _infer_80_system(name: str) -> str:
    if re.search(r"汽轮机|透平", name):
        return "动力部分"
    if re.search(r"齿轮|变速", name):
        return "传动部分"
    if re.search(r"压缩机|增压机|空压机|低压缸|高压缸|中压缸|发电机|电机", name):
        return "工作部分"
    return ""


# ── Orphan re-mounting ────────────────────────────────────────────────────

def _build_bearing_index(root: dict) -> dict[str, list[dict]]:
    """Build index: shaft_id → list of bearing nodes (type_70)."""
    index: dict[str, list[dict]] = defaultdict(list)

    def fn(node: dict, depth: int) -> None:
        if node.get("unit_type") == 2 and node.get("type_num") == 70:
            # Find the shaft this bearing belongs to
            sid = str(node.get("belongShaftId", ""))
            if not sid:
                # Try to infer from children
                for c in node.get("children", []):
                    sid = str(c.get("belongShaftId", ""))
                    if sid:
                        break
            if sid:
                index[sid].append(node)

    _walk(root, fn)
    return index


def _remount_orphans(root: dict, all_points: list[dict], bearings_by_shaft: dict[str, list[dict]]):
    """Return orphan points that should be re-mounted, grouped by their target location.

    Returns: list of (target_parent_id, point_dict) tuples.
    """
    orphans: list[tuple[str | None, dict]] = []

    for pt in all_points:
        # Check if point is already under a correct 80/70 hierarchy
        sid = str(pt.get("belongShaftId", ""))
        name = pt.get("name", "")
        if not sid:
            # Try key-phase shaft inference
            tn = pt.get("type_num", 0)
            if tn == 81:
                # Key-phase: try to match to any shaft by name
                for s, bearings in bearings_by_shaft.items():
                    # Use first bearing's shaft
                    if bearings:
                        sid = s
                        break

        if not sid:
            orphans.append((None, pt))  # Can't determine shaft, leave as root orphan
            continue

        # Find matching bearing on this shaft
        bearings = bearings_by_shaft.get(sid, [])
        direction = _infer_direction(name)
        target_bearing = None

        # Exact direction match
        for b in bearings:
            b_dir = _infer_direction(b.get("name", ""))
            if direction and b_dir == direction:
                target_bearing = b
                break

        # Fallback: first bearing on this shaft
        if not target_bearing and bearings:
            target_bearing = bearings[0]

        if target_bearing:
            orphans.append((target_bearing["id"], pt))
        else:
            orphans.append((None, pt))

    return orphans


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Build complete device_context.json from raw tree")
    p.add_argument("--input", required=True, help="Path to device_tree_raw.json")
    p.add_argument("--machine-id", required=True, help="Machine / equipment ID")
    p.add_argument("--component-id", required=True, help="Target component / sub-device ID")
    p.add_argument("--output", required=True, help="Output path for device_context.json")
    args = p.parse_args()

    with open(args.input, encoding="utf-8") as f:
        root = json.load(f)

    # Find the target component
    component = _find_node(root, args.component_id)
    if component is None:
        print(f"ERROR: component {args.component_id} not found in tree", file=sys.stderr)
        sys.exit(1)

    component_name = component.get("name", "")

    # ── Collect all points and build shaft index ──────────────────────
    all_points: list[dict] = []

    def _collect(n: dict, depth: int) -> None:
        if n.get("unit_type") == 3:
            all_points.append(n)

    _walk(root, _collect)

    bearings_by_shaft = _build_bearing_index(root)
    remounts = _remount_orphans(root, all_points, bearings_by_shaft)

    # Stats
    type_83_count = sum(1 for p in all_points if p.get("type_num") == 83)
    type_82_count = sum(1 for p in all_points if p.get("type_num") == 82)
    type_81_count = sum(1 for p in all_points if p.get("type_num") == 81)

    # ── Build child_device_list preserving hierarchy ───────────────────
    # Find the machine root node (unit_type=1, type_num=1)
    machine_root = root
    if machine_root.get("unit_type") != 1:
        # Walk to find root
        def _find_machine(n: dict, depth: int) -> None:
            nonlocal machine_root
            if n.get("unit_type") == 1 and n.get("type_num") == 1:
                machine_root = n

        _walk(root, _find_machine)

    def _build_device_node(node: dict) -> dict:
        """Recursively build a child_device_list node, keeping valid hierarchy."""
        ut = node.get("unit_type", 0)
        tn = node.get("type_num", 0)
        name = node.get("name", "")
        nid = node.get("id", "")

        result: dict[str, Any] = {
            "id": nid,
            "name": name,
        }

        if ut == 1:
            result["unit_type"] = 1
            result["type_num"] = 1
        elif ut == 2 and tn == 80:
            result["unit_type"] = 2
            result["type_num"] = 80
            result["system"] = _infer_80_system(name)
            result["type"] = _infer_80_device_type(name)
        elif ut == 2 and tn == 70:
            result["unit_type"] = 2
            result["type_num"] = 70
            result["direction"] = _infer_direction(name)
            result["bearing_type"] = _infer_bearing_type(name)
        elif ut == 3:
            result["unit_type"] = 3
            result["type_num"] = tn
            result["h_alarm"] = node.get("h_alarm", "")
            result["hh_alarm"] = node.get("hh_alarm", "")
            result["belongShaftId"] = node.get("belongShaftId", "")
            result["type"] = _infer_point_type(node)
        else:
            # Intermediate nodes: preserve but don't classify
            result["unit_type"] = ut
            result["type_num"] = tn

        # Build children
        children = []
        for child in node.get("children", []):
            if isinstance(child, dict):
                cu = child.get("unit_type", 0)
                # Only preserve 80/70/3 nodes; skip intermediate org nodes
                if cu in (2, 3):
                    children.append(_build_device_node(child))
                elif cu == 1:
                    children.append(_build_device_node(child))

        # Add remounted orphans to their target bearings
        for target_id, pt in remounts:
            if target_id == nid:
                children.append({
                    "id": pt["id"],
                    "name": pt["name"],
                    "unit_type": 3,
                    "type_num": pt.get("type_num", 0),
                    "h_alarm": pt.get("h_alarm", ""),
                    "hh_alarm": pt.get("hh_alarm", ""),
                    "belongShaftId": pt.get("belongShaftId", ""),
                    "type": _infer_point_type(pt),
                    "_remounted": True,
                })

        if children:
            result["children"] = children

        return result

    child_device_list = [_build_device_node(machine_root)]

    # Add fully orphan points (no shaft match) to root
    root_orphans = [pt for tid, pt in remounts if tid is None and pt.get("type_num") != 3]
    for pt in root_orphans:
        child_device_list.append({
            "id": pt["id"],
            "name": pt["name"],
            "unit_type": 3,
            "type_num": pt.get("type_num", 0),
            "h_alarm": pt.get("h_alarm", ""),
            "hh_alarm": pt.get("hh_alarm", ""),
            "belongShaftId": pt.get("belongShaftId", ""),
            "type": _infer_point_type(pt),
            "_orphan": True,
        })

    # ── Build target_info ──────────────────────────────────────────────
    target_node = _find_node(machine_root, args.component_id)
    target_ut = target_node.get("unit_type", 0) if target_node else 0
    target_tn = target_node.get("type_num", 0) if target_node else 0

    if target_ut == 3:
        target_kind = "probe"
    elif target_tn == 70:
        target_kind = "bearing"
    elif target_tn == 80:
        target_kind = "rotor_device"
    else:
        target_kind = "unknown"

    # Collect all point IDs related to target
    probe_ids: list[str] = []
    waveform_probe_ids: list[str] = []
    bearing_ids: list[str] = []
    owner_device_id: str = ""

    if target_node:
        # All points under target
        sub_points: list[dict] = []

        def _collect_sub(n: dict, depth: int) -> None:
            if n.get("unit_type") == 3:
                sub_points.append(n)

        _walk(target_node, _collect_sub)

        for pt in sub_points:
            pid = pt["id"]
            probe_ids.append(pid)
            if pt.get("type_num") == 83:
                waveform_probe_ids.append(pid)

        # Find bearing IDs
        def _collect_bearings(n: dict, depth: int) -> None:
            if n.get("unit_type") == 2 and n.get("type_num") == 70:
                bearing_ids.append(n["id"])

        _walk(target_node, _collect_bearings)

        # If target is a probe, also include paired X/Y probes under same bearing
        if target_kind == "probe":
            # Find the parent bearing
            parent = None
            def _find_parent_of(n: dict, tid: str) -> dict | None:
                for c in n.get("children", []):
                    if isinstance(c, dict):
                        if c.get("id") == tid:
                            return n
                        r = _find_parent_of(c, tid)
                        if r:
                            return r
                return None

            bearing_parent = _find_parent_of(machine_root, args.component_id)
            if bearing_parent and bearing_parent.get("type_num") == 70:
                bearing_ids.append(bearing_parent["id"])
                # Add sibling probes under same bearing
                for c in bearing_parent.get("children", []):
                    if isinstance(c, dict) and c.get("unit_type") == 3:
                        cid = c["id"]
                        if cid not in probe_ids:
                            probe_ids.append(cid)
                        if c.get("type_num") == 83 and cid not in waveform_probe_ids:
                            waveform_probe_ids.append(cid)

                # Find owner device (type_80 parent)
                owner = _find_parent_of(machine_root, bearing_parent["id"])
                if owner and owner.get("type_num") == 80:
                    owner_device_id = owner["id"]

    target_info = {
        "target_kind": target_kind,
        "probe_ids": sorted(set(probe_ids)),
        "waveform_probe_ids": sorted(set(waveform_probe_ids)),
        "bearing_ids": sorted(set(bearing_ids)),
        "owner_device_id": owner_device_id or args.component_id,
        "target_device_type": _infer_80_device_type(component.get("name", "")) if component else "未知",
    }

    # ── Summary ────────────────────────────────────────────────────────
    summary_lines = [
        f"{component_name}，共{len(all_points)}个测点",
    ]
    if type_83_count:
        summary_lines.append(f"轴振/轴位移波形测点(type_83): {type_83_count}个，分布在{len(bearings_by_shaft)}根轴上")
    if type_82_count:
        summary_lines.append(f"工艺参数测点(type_82): {type_82_count}个")
    if type_81_count:
        summary_lines.append(f"键相测点(type_81): {type_81_count}个")

    # ── Output ─────────────────────────────────────────────────────────
    device_context = {
        "device_id": args.machine_id,
        "child_device_summary": summary_lines,
        "device_type": {"value": "", "confidence": "", "reason": ""},
        "process_type": {"value": "", "confidence": "", "reason": ""},
        "device_structure": {"value": "", "confidence": "", "reason": ""},
        "child_device_list": child_device_list,
        "target_info": target_info,
    }

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(device_context, f, ensure_ascii=False, indent=2)

    # ── Stderr summary for LLM ────────────────────────────────────────
    print(f"[build_device_context] {type_83_count} vibration, {type_82_count} process, "
          f"{type_81_count} key-phase, {len(bearings_by_shaft)} shafts, "
          f"target_kind={target_kind} → {args.output}",
          file=sys.stderr)

    # Print device hierarchy summary
    def _print_hierarchy(node: dict, indent: int = 0) -> None:
        prefix = "  " * indent
        ut = node.get("unit_type", "?")
        tn = node.get("type_num", "?")
        name = node.get("name", "?")
        extra = ""
        if ut == 2 and tn == 80:
            extra = f" [{node.get('type', '')}] [{node.get('system', '')}]"
        elif ut == 2 and tn == 70:
            extra = f" [{node.get('direction', '')}] {node.get('bearing_type', [])}"
        elif ut == 3:
            extra = f" [{node.get('type', '')}]"
        print(f"{prefix}[{ut}/{tn}] {name}{extra}", file=sys.stderr)
        for c in node.get("children", []):
            _print_hierarchy(c, indent + 1)

    print("=== DEVICE HIERARCHY ===", file=sys.stderr)
    for item in child_device_list:
        _print_hierarchy(item)
    print("=== END HIERARCHY ===", file=sys.stderr)
    print(f"target_info: kind={target_kind} probes={len(probe_ids)} waveform={len(waveform_probe_ids)} bearings={len(bearing_ids)}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
