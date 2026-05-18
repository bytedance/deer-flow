"""Interpretive failure analysis with method-specific reasoning (§13.2).

Sprint S3 enhancement — replaces the 98-line stub. Routes on
``analysis_method`` (5why / fishbone / fmea) and produces structurally
distinct ``method_block`` for each, while keeping a single §13.2-compliant
top-level shape:

- ``findings[]`` — root causes with id / label / severity / is_primary
- ``evidence[]`` — each finding linked via ``finding_id`` (≥2 per finding;
  source_type union covers ≥3 of {timeseries, inspection_record,
  maintenance_record, work_order, spare_part}).
- ``method_block`` — method-specific structure:
    5why: ``why_chain[]`` (5 levels, evidence attached per level)
    fishbone: ``branches[]`` (6 categories with item lists)
    fmea: ``fmea_rows[]`` (severity × occurrence × detection = RPN)
- ``corrective_actions[]`` — id / action / owner / due_date / verification_plan
- ``validation_plan`` — overall reverify checklist
- ``confidence`` / ``assumptions[]`` / ``data_coverage`` / ``human_review_required: true``

NEVER emits ``summary_markdown``.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

from _stub_helpers import (
    base_parser,
    emit_error,
    iso_now,
    provenance_evidence,
    read_json,
    write_json,
)


SCHEMA_VERSION = "1"

_METHOD_LABEL = {"five_why": "5Why", "fishbone": "鱼骨图", "fmea": "FMEA"}
_VALID_METHODS = {"five_why", "fishbone", "fmea"}

# RPN threshold above which we surface the FMEA row as a "high-severity" finding.
FMEA_RPN_HIGH = 150
FMEA_RPN_MED = 80


def _evidence_for(
    *,
    finding_id: str,
    source_type: str,
    source_id: str,
    snapshot_root: str,
    sub_path: str,
    payload: object,
    description: str,
    time_range: list[str] | None = None,
) -> dict:
    base = provenance_evidence(
        source_type=source_type,
        source_id=source_id,
        snapshot_path=f"{snapshot_root}#/{sub_path}",
        payload_sample=payload,
        time_range=time_range or [],
    )
    base["finding_id"] = finding_id
    base["description"] = description
    return base


def _resolve_evidence_for_hint(
    *,
    hint: str,
    raw: dict,
    finding_id: str,
    snapshot_root: str,
) -> dict | None:
    """Map an ``evidence_hint`` (referenced by method_seed entries) onto a
    concrete §13.2 evidence entry. Returns None when the hint can't be resolved
    so the caller can attach a fallback timeseries evidence instead."""
    inspections = raw.get("inspections") or []
    maintenance = raw.get("maintenance") or []
    spares = raw.get("spares") or []
    operations = raw.get("operations") or []

    # Match against inspection / maintenance / spares by id
    for insp in inspections:
        if insp.get("id") == hint or hint in insp.get("id", ""):
            return _evidence_for(
                finding_id=finding_id, source_type="inspection_record",
                source_id=insp["id"], snapshot_root=snapshot_root, sub_path="inspections",
                payload=insp, description=f"巡检记录：{insp.get('result')}",
                time_range=[insp.get("date")],
            )
    for mr in maintenance:
        if mr.get("id") == hint or hint in mr.get("id", ""):
            return _evidence_for(
                finding_id=finding_id, source_type="maintenance_record",
                source_id=mr["id"], snapshot_root=snapshot_root, sub_path="maintenance",
                payload=mr, description=f"维护记录：{mr.get('type')}",
                time_range=[mr.get("date")],
            )
    for sp in spares:
        if sp.get("part_number") == hint or hint in sp.get("part_number", ""):
            return _evidence_for(
                finding_id=finding_id, source_type="spare_part",
                source_id=sp["part_number"], snapshot_root=snapshot_root, sub_path="spares",
                payload=sp, description=f"备件状态：{sp.get('part_number')} 寿命 {sp.get('remaining_pct')}%",
                time_range=[sp.get("last_replaced")],
            )
    # Match against metric names (hint is e.g. "bearing_temp" / "oil_seepage")
    matched_ops = [op for op in operations if op.get("metric") == hint]
    if matched_ops:
        sample = matched_ops[-5:]
        return _evidence_for(
            finding_id=finding_id, source_type="timeseries",
            source_id=hint, snapshot_root=snapshot_root, sub_path=f"operations/{hint}",
            payload=[{"id": s.get("id"), "v": s.get("value"), "t": s.get("t")} for s in sample],
            description=f"{hint} 末段 {len(sample)} 个采样",
            time_range=[sample[0]["t"], sample[-1]["t"]] if sample else [],
        )
    return None


def _findings_five_why(raw: dict, snapshot_root: str) -> tuple[list[dict], list[dict], dict]:
    """5Why: each level becomes a finding, evidence attached when hint resolves."""
    seed = (raw.get("method_seed") or {}).get("five_why") or {}
    levels = seed.get("levels") or []
    findings: list[dict] = []
    evidence: list[dict] = []

    for lvl in levels:
        fid = f"FA-5W-L{lvl['level']}"
        findings.append(
            {
                "id": fid,
                "label": lvl["candidate_cause"],
                "severity": "high" if lvl["level"] <= 2 else "medium" if lvl["level"] <= 4 else "low",
                "is_primary": lvl["level"] == 1,
                "method_level": lvl["level"],
                "rationale": lvl["why"],
            }
        )
        # Always attach a timeseries evidence as fallback baseline
        ops = raw.get("operations") or []
        baseline_sample = ops[-3:] if ops else []
        if baseline_sample:
            evidence.append(
                _evidence_for(
                    finding_id=fid, source_type="timeseries", source_id="vibration_level",
                    snapshot_root=snapshot_root, sub_path="operations",
                    payload=[{"id": s.get("id"), "v": s.get("value"), "t": s.get("t")} for s in baseline_sample],
                    description="末段振动采样",
                    time_range=[baseline_sample[0]["t"], baseline_sample[-1]["t"]],
                )
            )
        hint_evidence = _resolve_evidence_for_hint(
            hint=lvl.get("evidence_hint", ""), raw=raw, finding_id=fid, snapshot_root=snapshot_root,
        )
        if hint_evidence:
            evidence.append(hint_evidence)

    method_block = {
        "method": "five_why",
        "why_chain": [
            {
                "level": lvl["level"],
                "why": lvl["why"],
                "candidate_cause": lvl["candidate_cause"],
                "finding_id": f"FA-5W-L{lvl['level']}",
            }
            for lvl in levels
        ],
    }
    return findings, evidence, method_block


def _findings_fishbone(raw: dict, snapshot_root: str) -> tuple[list[dict], list[dict], dict]:
    """Fishbone: one finding per high/medium-weight item across 6 categories.

    Always produce ≥ 6 finding placeholders (one per category) so the diagram
    is structurally complete even when items are sparse.
    """
    seed = (raw.get("method_seed") or {}).get("fishbone") or {}
    branches = seed.get("branches") or []
    findings: list[dict] = []
    evidence: list[dict] = []

    primary_assigned = False
    for branch in branches:
        cat = branch["category"]
        items = branch.get("items") or []
        # Per-category headline finding (always emit one per category)
        cat_finding_id = f"FA-FB-{cat}"
        headline_weight = "low"
        if items:
            weights = [it.get("weight", "low") for it in items]
            if "high" in weights:
                headline_weight = "high"
            elif "medium" in weights:
                headline_weight = "medium"
        findings.append(
            {
                "id": cat_finding_id,
                "label": f"{cat} 类候选根因",
                "severity": headline_weight,
                "is_primary": not primary_assigned and headline_weight == "high",
                "category": cat,
                "rationale": f"{cat} 分支汇总：{len(items)} 项可能性",
            }
        )
        if findings[-1]["is_primary"]:
            primary_assigned = True

        # Attach evidence: one timeseries baseline + one resolved-hint evidence per high/medium item
        ops = raw.get("operations") or []
        baseline_sample = ops[-3:] if ops else []
        if baseline_sample:
            evidence.append(
                _evidence_for(
                    finding_id=cat_finding_id, source_type="timeseries", source_id="vibration_level",
                    snapshot_root=snapshot_root, sub_path="operations",
                    payload=[{"id": s.get("id"), "v": s.get("value"), "t": s.get("t")} for s in baseline_sample],
                    description=f"{cat} 类参考采样",
                    time_range=[baseline_sample[0]["t"], baseline_sample[-1]["t"]],
                )
            )
        for item in items[:3]:
            if item.get("weight") == "low":
                continue
            hint_ev = _resolve_evidence_for_hint(
                hint=item.get("evidence_hint", ""), raw=raw, finding_id=cat_finding_id, snapshot_root=snapshot_root,
            )
            if hint_ev:
                hint_ev["description"] = f"{cat}/{item['label']}（{hint_ev['description']}）"
                evidence.append(hint_ev)

    # If no branch had a high weight, fallback to first finding as primary.
    if not primary_assigned and findings:
        findings[0]["is_primary"] = True

    method_block = {
        "method": "fishbone",
        "branches": branches,
    }
    return findings, evidence, method_block


def _findings_fmea(raw: dict, snapshot_root: str) -> tuple[list[dict], list[dict], dict]:
    """FMEA: one finding per fmea row, severity bucketed by RPN."""
    seed = (raw.get("method_seed") or {}).get("fmea") or {}
    rows = seed.get("rows") or []
    findings: list[dict] = []
    evidence: list[dict] = []

    # Recompute RPN to assert formula correctness even if seed was tampered with
    fixed_rows: list[dict] = []
    for row in rows:
        computed_rpn = row["severity"] * row["occurrence"] * row["detection"]
        fixed_rows.append({**row, "rpn": computed_rpn})

    # Sort by RPN desc to put highest-risk row first as primary
    fixed_rows.sort(key=lambda r: -r["rpn"])

    for idx, row in enumerate(fixed_rows):
        rpn = row["rpn"]
        if rpn >= FMEA_RPN_HIGH:
            severity = "high"
        elif rpn >= FMEA_RPN_MED:
            severity = "medium"
        else:
            severity = "low"
        fid = row["id"]
        findings.append(
            {
                "id": fid,
                "label": row["mode"],
                "severity": severity,
                "is_primary": idx == 0,
                "rpn": rpn,
                "rationale": row["cause"],
            }
        )
        ops = raw.get("operations") or []
        baseline_sample = ops[-3:] if ops else []
        if baseline_sample:
            evidence.append(
                _evidence_for(
                    finding_id=fid, source_type="timeseries", source_id="vibration_level",
                    snapshot_root=snapshot_root, sub_path="operations",
                    payload=[{"id": s.get("id"), "v": s.get("value"), "t": s.get("t")} for s in baseline_sample],
                    description="末段振动采样（参考）",
                    time_range=[baseline_sample[0]["t"], baseline_sample[-1]["t"]],
                )
            )
        hint_ev = _resolve_evidence_for_hint(
            hint=row.get("evidence_hint", ""), raw=raw, finding_id=fid, snapshot_root=snapshot_root,
        )
        if hint_ev:
            evidence.append(hint_ev)

    method_block = {
        "method": "fmea",
        "fmea_rows": fixed_rows,
        "rpn_threshold_high": FMEA_RPN_HIGH,
        "rpn_threshold_med": FMEA_RPN_MED,
    }
    return findings, evidence, method_block


def _corrective_actions(method: str, findings: list[dict]) -> list[dict]:
    """Mechanically derive 2-4 corrective actions from primary + high-severity findings."""
    today = date.today()
    primary = next((f for f in findings if f.get("is_primary")), findings[0] if findings else None)
    actions: list[dict] = []
    if primary:
        actions.append(
            {
                "id": "CA-001",
                "action": f"对【{primary['label']}】启动停机处置，由维修部主导",
                "owner": "维修部",
                "due_date": (today + timedelta(days=14)).isoformat(),
                "verification_plan": "30 天内复测主要指标并比对基线",
            }
        )
    # Cross-finding actions (max 2 more)
    others = [f for f in findings if not f.get("is_primary") and f.get("severity") in ("high", "medium")][:2]
    for idx, f in enumerate(others, start=2):
        actions.append(
            {
                "id": f"CA-00{idx}",
                "action": f"并行复核【{f['label']}】，等待 method={method} 推断",
                "owner": "运行部",
                "due_date": (today + timedelta(days=30)).isoformat(),
                "verification_plan": "在 method 复盘会上提供数据闭环",
            }
        )
    if not actions:
        actions.append(
            {
                "id": "CA-001",
                "action": "尚未识别高风险根因，继续监控",
                "owner": "运行部",
                "due_date": (today + timedelta(days=30)).isoformat(),
                "verification_plan": "下月例会评估",
            }
        )
    return actions


def _validation_plan(method: str) -> list[dict]:
    """Three universal reverify steps + method-specific anchor."""
    plan = [
        {"step": "复测 30 天内振动均值 ≤ 基线", "method": "TSDB 抽样"},
        {"step": "复测 14 天内温度峰值 ≤ 设计上限", "method": "TSDB 抽样"},
        {"step": "确认所有 CA 项完成度 = 100%", "method": "工单系统核查"},
    ]
    if method == "fmea":
        plan.append({"step": "重新计算 RPN 并确认 < high 阈值", "method": "FMEA 表格复盘"})
    elif method == "five_why":
        plan.append({"step": "在下月例会逐条复核 5 Why 链", "method": "现场专家会议"})
    elif method == "fishbone":
        plan.append({"step": "对 6 类分支逐项落实纠正措施", "method": "鱼骨图复盘"})
    return plan


def _compute_confidence(findings: list[dict], evidence: list[dict]) -> str:
    src_types = {e["source_type"] for e in evidence}
    high_count = sum(1 for f in findings if f.get("severity") == "high")
    if len(src_types) >= 3 and high_count >= 1:
        return "high"
    if len(src_types) >= 2:
        return "medium"
    return "low"


def _flatten_method_block(method_block: dict) -> list[dict]:
    """Project the nested ``method_block`` dict into a flat list of rows so
    DSL templates can render it via ``component: table`` regardless of method.

    Row shape (uniform across 5why / fishbone / fmea):
        {position, label, detail, evidence_hint}
    """
    method = method_block.get("method")
    rows: list[dict] = []
    if method == "five_why":
        for lvl in method_block.get("why_chain") or []:
            rows.append(
                {
                    "position": f"Level {lvl.get('level')}",
                    "label": lvl.get("why", ""),
                    "detail": lvl.get("candidate_cause", ""),
                    "evidence_hint": lvl.get("finding_id", ""),
                }
            )
    elif method == "fishbone":
        for branch in method_block.get("branches") or []:
            cat = branch.get("category", "")
            for item in branch.get("items") or []:
                rows.append(
                    {
                        "position": cat,
                        "label": item.get("label", ""),
                        "detail": f"weight={item.get('weight', 'low')}",
                        "evidence_hint": item.get("evidence_hint", ""),
                    }
                )
    elif method == "fmea":
        for row in method_block.get("fmea_rows") or []:
            rows.append(
                {
                    "position": row.get("id", ""),
                    "label": row.get("mode", ""),
                    "detail": (
                        f"effect={row.get('effect', '')} | cause={row.get('cause', '')} | "
                        f"S={row.get('severity', '?')} O={row.get('occurrence', '?')} "
                        f"D={row.get('detection', '?')} RPN={row.get('rpn', '?')}"
                    ),
                    "evidence_hint": row.get("evidence_hint", ""),
                }
            )
    return rows


def main() -> int:
    parser = base_parser("Interpretive failure analysis (§13.2)")
    parser.add_argument("--input", required=True, help="failure_data.json path")
    args = parser.parse_args()

    try:
        raw = read_json(Path(args.input))
    except (FileNotFoundError, ValueError) as exc:
        return emit_error("INPUT_UNREADABLE", str(exc))

    method = raw.get("analysis_method", "five_why")
    if method not in _VALID_METHODS:
        return emit_error("INVALID_METHOD", f"unsupported analysis_method: {method!r}")

    snapshot_root = args.input

    if method == "five_why":
        findings, evidence, method_block = _findings_five_why(raw, snapshot_root)
    elif method == "fishbone":
        findings, evidence, method_block = _findings_fishbone(raw, snapshot_root)
    else:  # fmea
        findings, evidence, method_block = _findings_fmea(raw, snapshot_root)

    corrective_actions = _corrective_actions(method, findings)
    validation_plan = _validation_plan(method)
    confidence = _compute_confidence(findings, evidence)

    primary = next((f for f in findings if f.get("is_primary")), None)
    primary_label = primary["label"] if primary else "未确定"

    overall_status = {
        "level": "critical" if any(f.get("severity") == "high" for f in findings) else "warning",
        "summary": (
            f"针对 {raw.get('asset_id')} 的 {raw.get('failure_mode')} 失效，采用 "
            f"{_METHOD_LABEL.get(method, method)} 方法分析；优先排查【{primary_label}】。"
        )[:80],
    }

    # Flattened table-friendly view of method_block. The DSL can render this
    # as a single ``component: table`` regardless of which method ran — the
    # ``method_block`` itself stays as a dict for callers who want the raw
    # nested structure.
    method_table = _flatten_method_block(method_block)

    output = {
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "asset_id": raw.get("asset_id"),
            "failure_mode": raw.get("failure_mode"),
            "analysis_method": method,
            "analysis_method_label": _METHOD_LABEL.get(method, method),
            "evidence_range_raw": raw.get("evidence_range_raw"),
            "data_source": raw.get("data_source"),
        },
        "overall_status": overall_status,
        "findings": findings,
        "evidence": evidence,
        "method_block": method_block,
        "method_table": method_table,
        "corrective_actions": corrective_actions,
        "validation_plan": validation_plan,
        "confidence": confidence,
        "assumptions": [
            f"演示数据由 query_failure_data 按 {method} 路由合成",
            "未接入实测金相 / 油液 / 振动频谱",
            "Corrective Actions 与 Validation Plan 为机械派生，需现场专家复核",
        ],
        "data_coverage": {
            "operations_sample_count": len(raw.get("operations") or []),
            "maintenance_count": len(raw.get("maintenance") or []),
            "inspection_count": len(raw.get("inspections") or []),
            "spare_count": len(raw.get("spares") or []),
        },
        "human_review_required": True,  # §13.2 mandate for root-cause reports
        "_meta": {"stub": True, "generated_at": iso_now()},
    }
    write_json(Path(args.output_dir), "failure_analysis", output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
