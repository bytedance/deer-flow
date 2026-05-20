from __future__ import annotations

from typing import Any

from models import BearingRef, DeviceContext, ProbeRef


def _safe_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _point_type_key(point_type: str) -> str:
    text = point_type.strip()
    mapping = {
        "轴振": "shaft_vibration",
        "轴位移": "shaft_displacement",
        "轴位移波形": "shaft_displacement_waveform",
        "轴承温度": "bearing_temperature",
        "润滑油温度": "lube_oil_temperature",
        "防喘振阀开度": "valve_position",
        "压缩机进气参数": "process_pressure",
        "出口温度": "process_temperature",
        "入口流量": "process_flow",
        "其他工艺参数": "other_process",
        "其他": "other_process",
    }
    return mapping.get(text, text or "unknown")


def build_device_context_index(device_analysis_result: dict[str, Any]) -> DeviceContext:
    child_device_list = device_analysis_result.get("child_device_list") or []
    root_name = None
    if child_device_list and isinstance(child_device_list[0], dict):
        root_name = str(child_device_list[0].get("name") or "")

    context = DeviceContext(
        device_id=str(device_analysis_result.get("device_id") or ""),
        device_name=root_name or None,
        device_type=str(((device_analysis_result.get("device_type") or {}).get("value")) or "未知"),
        process_type=str(((device_analysis_result.get("process_type") or {}).get("value")) or "") or None,
        device_structure=str(((device_analysis_result.get("device_structure") or {}).get("value")) or "") or None,
        child_device_summary=[str(x) for x in (device_analysis_result.get("child_device_summary") or []) if isinstance(x, str)],
        child_device_tree=child_device_list if isinstance(child_device_list, list) else [],
    )

    def walk(
        node: dict[str, Any],
        owner_device: dict[str, Any] | None = None,
        bearing: dict[str, Any] | None = None,
    ) -> None:
        unit_type = node.get("unit_type")
        type_num = node.get("type_num")

        if unit_type == 2 and type_num == 80:
            owner_device = node
            owner_id = str(node.get("id") or "")
            if owner_id:
                context.rotor_device_ids.append(owner_id)
                node_type = str(node.get("type") or "").strip()
                if node_type:
                    context.rotor_device_type_map[owner_id] = node_type

        if unit_type == 2 and type_num == 70:
            bearing = node
            bearing_id = str(node.get("id") or "")
            shaft_id = None
            bearing_ref = BearingRef(
                bearing_id=bearing_id,
                bearing_name=str(node.get("name") or ""),
                owner_device_id=str((owner_device or {}).get("id") or "") or None,
                owner_device_name=str((owner_device or {}).get("name") or "") or None,
                direction=str(node.get("direction") or "") or None,
                bearing_types=[
                    str(item) for item in (node.get("bearing_type") or []) if isinstance(item, str)
                ],
                shaft_id=shaft_id,
            )
            context.bearings.append(bearing_ref)
            if bearing_id:
                context.bearing_index[bearing_id] = bearing_ref

        if unit_type == 3:
            point_id = str(node.get("id") or "")
            point_type = str(node.get("type") or "未知")
            shaft_id = str(node.get("belongShaftId") or "") or None
            bearing_id = str((bearing or {}).get("id") or "") or None
            probe = ProbeRef(
                point_id=point_id,
                point_name=str(node.get("name") or ""),
                point_type=point_type,
                owner_device_id=str((owner_device or {}).get("id") or "") or None,
                owner_device_name=str((owner_device or {}).get("name") or "") or None,
                bearing_id=bearing_id,
                bearing_name=str((bearing or {}).get("name") or "") or None,
                bearing_direction=str((bearing or {}).get("direction") or "") or None,
                bearing_types=[str(item) for item in ((bearing or {}).get("bearing_type") or []) if isinstance(item, str)],
                shaft_id=shaft_id,
                h_alarm=_safe_float(node.get("h_alarm")),
                hh_alarm=_safe_float(node.get("hh_alarm")),
                unit_type=unit_type if isinstance(unit_type, int) else None,
                type_num=type_num if isinstance(type_num, int) else None,
            )
            context.probes.append(probe)
            if point_id:
                context.probe_index[point_id] = probe
            if bearing_id:
                context.bearing_probe_map.setdefault(bearing_id, []).append(point_id)
                bearing_ref = context.bearing_index.get(bearing_id)
                if bearing_ref is not None:
                    bearing_ref.probes.append(probe)
            if shaft_id:
                context.shaft_probe_map.setdefault(shaft_id, []).append(point_id)

            key = _point_type_key(point_type)
            if key.startswith("process_") or key in {"valve_position", "other_process", "lube_oil_temperature"}:
                context.process_points.append(probe)
                context.process_point_map.setdefault(key, []).append(point_id)

        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child, owner_device=owner_device, bearing=bearing)

    for root in context.child_device_tree:
        if isinstance(root, dict):
            walk(root)

    return context


def resolve_sub_device_targets(context: DeviceContext, sub_device_id: str) -> dict[str, list[str] | str | None]:
    probe = context.probe_index.get(sub_device_id)
    bearing = context.bearing_index.get(sub_device_id)

    if probe is not None:
        related_probe_ids: list[str] = [probe.point_id]
        if probe.bearing_id:
            related_probe_ids = context.bearing_probe_map.get(probe.bearing_id, related_probe_ids)
        return {
            "target_kind": "probe",
            "probe_ids": related_probe_ids,
            "waveform_probe_ids": [probe.point_id],
            "bearing_ids": [probe.bearing_id] if probe.bearing_id else [],
            "owner_device_id": probe.owner_device_id,
        }

    if bearing is not None:
        bearing_probe_ids = context.bearing_probe_map.get(bearing.bearing_id, [])
        shaft_vibration_ids = [
            point_id
            for point_id in bearing_probe_ids
            if (context.probe_index.get(point_id) and context.probe_index[point_id].point_type == "轴振")
        ]
        return {
            "target_kind": "bearing",
            "probe_ids": bearing_probe_ids,
            "waveform_probe_ids": shaft_vibration_ids or bearing_probe_ids[:1],
            "bearing_ids": [bearing.bearing_id],
            "owner_device_id": bearing.owner_device_id,
        }

    if sub_device_id in context.rotor_device_ids:
        device_probe_ids = [
            probe_ref.point_id
            for probe_ref in context.probes
            if probe_ref.owner_device_id == sub_device_id
        ]
        device_bearing_ids = [
            bearing_ref.bearing_id
            for bearing_ref in context.bearings
            if bearing_ref.owner_device_id == sub_device_id
        ]
        shaft_vibration_ids = [
            point_id
            for point_id in device_probe_ids
            if (context.probe_index.get(point_id) and context.probe_index[point_id].point_type == "轴振")
        ]
        return {
            "target_kind": "rotor_device",
            "probe_ids": device_probe_ids,
            "waveform_probe_ids": shaft_vibration_ids or device_probe_ids[:1],
            "bearing_ids": device_bearing_ids,
            "owner_device_id": sub_device_id,
        }

    return {
        "target_kind": "unknown",
        "probe_ids": [],
        "waveform_probe_ids": [],
        "bearing_ids": [],
        "owner_device_id": None,
    }
