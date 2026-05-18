#!/usr/bin/env python
"""Compute diagnosis features from query_diagnosis.json.

Stage 2 of the fault-diagnosis pipeline (see docs/plans/2026-05-18-fault-diagnosis-design.md
§4.5 step 4 + §5.2): consume the trend payload produced by ``query_diagnosis.py``,
optionally read LLM-written ``spectrum_*.json`` / ``orbit_*.json`` deep-sample files,
load the corresponding rule book, run a best-effort rule match against the user's
focus codes, and emit ``diagnosis_features.json`` ready for the SOUL renderer
plus ``export_diagnosis_report.py``.

The script does **not** replace LLM reasoning. It produces:

- a structured ``evidence_chain`` (each row scored ``exceed`` / ``marginal`` / ``normal``)
- a ``rule_matches`` candidate list (each match scored ``high`` / ``medium`` / ``low``
  by how many ``exceed`` evidences support it)
- ECharts options ready to drop into ``echart`` GenUI blocks
- a ``historical_cases`` placeholder (with ``data_source`` so the SOUL knows it
  is demo-only until the real history API lands)
- ``recommendations`` synthesized from matched rules

Output contract: design doc §7.2.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_OUTPUT_DIR = "/mnt/user-data/outputs"
INPUT_FILENAME = "query_diagnosis.json"
OUTPUT_FILENAME = "diagnosis_features.json"
DEFAULT_SKILLS_ROOT = "/mnt/skills/custom"

VALID_RULES_SKILLS = {
    "vibration-fault-diagnosis",
    "pump-fault-diagnosis",
    "reciprocating-fault-diagnosis",
}

VERDICT_EXCEED = "exceed"
VERDICT_MARGINAL = "marginal"
VERDICT_NORMAL = "normal"

# Marginal threshold: value within ±5% of threshold counts as marginal,
# above threshold = exceed, below = normal.
MARGINAL_BAND_RATIO = 0.05


def _output_dir() -> Path:
    return Path(os.environ.get("DIAGNOSIS_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))


def _skills_root() -> Path:
    return Path(os.environ.get("DIAGNOSIS_SKILLS_ROOT", DEFAULT_SKILLS_ROOT))


# --- Rule book loader ---


_CODE_MAPPING_HEADER_RE = re.compile(r"^##\s+Fault family code mapping", re.MULTILINE)
_CODE_TABLE_ROW_RE = re.compile(r"^\|\s*`([a-z_]+)`\s*\|\s*([^|]+?)\s*\|", re.MULTILINE)
_RULE_SECTION_RE = re.compile(r"^###\s+([^\n]+)$", re.MULTILINE)


def load_rule_book(rules_skill: str, skills_root: Path | None = None) -> dict:
    """Load fault code → rule section mapping for one rules-skill.

    Returns ``{"codes": {<code>: <chinese_section_keyword>}, "sections": {<section_title>: <body>}, "warnings": [...]}``.

    On any failure (missing file / unparseable mapping), returns an empty
    structure with a recorded warning so the caller can still emit a valid
    payload with ``rule_matches: []``.
    """
    root = skills_root or _skills_root()
    skill_md = root / rules_skill / "SKILL.md"
    rules_md = root / rules_skill / "references" / "diagnosis-rules.md"
    out: dict = {"codes": {}, "sections": {}, "warnings": [], "rules_skill": rules_skill}

    if not skill_md.exists():
        out["warnings"].append(f"SKILL.md not found: {skill_md}")
    else:
        try:
            text = skill_md.read_text(encoding="utf-8")
            mapping_match = _CODE_MAPPING_HEADER_RE.search(text)
            if mapping_match:
                tail = text[mapping_match.end():]
                # Stop at next ## header to avoid leaking into Status section
                next_h2 = re.search(r"^##\s+", tail, re.MULTILINE)
                segment = tail[: next_h2.start()] if next_h2 else tail
                for m in _CODE_TABLE_ROW_RE.finditer(segment):
                    code = m.group(1).strip()
                    section = m.group(2).strip()
                    # Skip the table header row "code | references 章节中文 | ..."
                    if code in ("code",):
                        continue
                    out["codes"][code] = section
            else:
                out["warnings"].append(f"no 'Fault family code mapping' section in {skill_md}")
        except OSError as exc:
            out["warnings"].append(f"failed to read SKILL.md: {exc}")

    if not rules_md.exists():
        out["warnings"].append(f"diagnosis-rules.md not found: {rules_md}")
    else:
        try:
            text = rules_md.read_text(encoding="utf-8")
            sections: dict = {}
            matches = list(_RULE_SECTION_RE.finditer(text))
            for i, m in enumerate(matches):
                title = m.group(1).strip()
                body_start = m.end()
                body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                sections[title] = text[body_start:body_end].strip()
            out["sections"] = sections
        except OSError as exc:
            out["warnings"].append(f"failed to read diagnosis-rules.md: {exc}")

    return out


def find_section_for_code(rule_book: dict, code: str) -> tuple[str | None, str | None]:
    """Resolve a code → (section_title, section_body).

    Code mapping table column 2 may say "不平衡类 / 初始不平衡" — we split on '/'
    and try each candidate against ``rule_book["sections"]`` keys.
    Returns (None, None) if nothing matches.
    """
    keyword = rule_book["codes"].get(code)
    if not keyword:
        return None, None
    candidates = [c.strip() for c in re.split(r"[/／]", keyword) if c.strip()]
    sections = rule_book["sections"]
    for cand in candidates:
        # Direct hit first
        if cand in sections:
            return cand, sections[cand]
        # Fuzzy: section title contains the candidate keyword
        for title, body in sections.items():
            if cand in title:
                return title, body
    return None, None


# --- Feature extraction from query_diagnosis payload ---


def _classify_verdict(value: float, threshold: float) -> str:
    if threshold <= 0:
        return VERDICT_NORMAL
    band = threshold * MARGINAL_BAND_RATIO
    if value > threshold + band:
        return VERDICT_EXCEED
    if value >= threshold - band:
        return VERDICT_MARGINAL
    return VERDICT_NORMAL


def _format_time_ms(time_ms: int | None) -> str | None:
    if not time_ms:
        return None
    try:
        return datetime.fromtimestamp(time_ms / 1000).isoformat(timespec="seconds")
    except (OSError, ValueError, OverflowError):
        return None


def build_evidence_chain(query_payload: dict) -> list[dict]:
    """Convert points[].trend_summary.notable_points + process_signals into evidence rows."""
    rows: list[dict] = []
    for point in query_payload.get("points", []):
        eq = point.get("equipment_id", "")
        pname = point.get("point_name", "")
        for np_ in point.get("trend_summary", {}).get("notable_points", []):
            value = np_.get("value")
            threshold = np_.get("threshold")
            if value is None or threshold is None:
                continue
            verdict = _classify_verdict(float(value), float(threshold))
            rows.append(
                {
                    "category": "trend",
                    "equipment_id": eq,
                    "point": pname,
                    "feature": np_.get("feature"),
                    "value": value,
                    "threshold": threshold,
                    "verdict": verdict,
                    "time": _format_time_ms(np_.get("time_ms")),
                }
            )

    # Process signals carry a rolling-std-style anomaly hint by default in demo data;
    # we synthesize one evidence row per channel using last-vs-mean comparison.
    proc = query_payload.get("process_signals") or {}
    for channel_name, channel in proc.items():
        series = channel.get("series") or []
        if len(series) < 2:
            continue
        values = [s.get("value") for s in series if isinstance(s.get("value"), (int, float))]
        if not values:
            continue
        mean = sum(values) / len(values)
        last = values[-1]
        # Marginal/exceed band uses 10% deviation from mean as the soft threshold
        threshold = abs(mean) * 1.1 if mean else 1.0
        verdict = _classify_verdict(abs(last), threshold)
        rows.append(
            {
                "category": "process",
                "equipment_id": "",
                "point": channel_name,
                "feature": "rolling_drift",
                "value": round(last, 4),
                "threshold": round(threshold, 4),
                "verdict": verdict,
                "time": _format_time_ms(series[-1].get("time_ms")),
            }
        )

    return rows


def build_equipment_summary(query_payload: dict, evidence_chain: list[dict]) -> list[dict]:
    summary: list[dict] = []
    points = query_payload.get("points", [])
    by_equipment: dict[str, list[dict]] = {}
    for p in points:
        by_equipment.setdefault(p.get("equipment_id", ""), []).append(p)

    for eq, eq_points in by_equipment.items():
        # Operation phase: demo path uses "steady_state" placeholder
        max_row: dict | None = None
        for row in evidence_chain:
            if row.get("category") != "trend" or row.get("equipment_id") != eq:
                continue
            if not isinstance(row.get("value"), (int, float)):
                continue
            if max_row is None or row["value"] > max_row["value"]:
                max_row = row

        # Alarm status from worst verdict on this equipment
        worst = VERDICT_NORMAL
        for row in evidence_chain:
            if row.get("equipment_id") != eq:
                continue
            if row.get("verdict") == VERDICT_EXCEED:
                worst = VERDICT_EXCEED
                break
            if row.get("verdict") == VERDICT_MARGINAL and worst != VERDICT_EXCEED:
                worst = VERDICT_MARGINAL

        alarm = {VERDICT_EXCEED: "warning", VERDICT_MARGINAL: "info", VERDICT_NORMAL: "ok"}[worst]
        entry: dict = {
            "equipment_id": eq,
            "operation_phase": "steady_state",
            "alarm_status": alarm,
        }
        if max_row:
            entry["max_value"] = {
                "point": max_row["point"],
                "feature": max_row["feature"],
                "value": max_row["value"],
                "unit": "μm" if max_row.get("feature") in {"pp_value", "rms"} else "",
            }
        summary.append(entry)
    return summary


# --- ECharts option builders ---


def build_trend_chart(query_payload: dict) -> dict:
    """Multi-series ECharts line chart from process_signals.

    Returns a complete ECharts option dict (title/tooltip/legend/xAxis/yAxis/series)
    suitable for the GenUI ``echart`` block.
    """
    proc = query_payload.get("process_signals") or {}
    series_list: list[dict] = []
    legend: list[str] = []
    x_labels: list[str] = []

    for channel_name, channel in proc.items():
        series_data = []
        for s in channel.get("series") or []:
            iso_t = _format_time_ms(s.get("time_ms")) or ""
            if iso_t and iso_t not in x_labels:
                x_labels.append(iso_t)
            series_data.append(s.get("value"))
        legend.append(channel_name)
        series_list.append(
            {
                "name": channel_name,
                "type": "line",
                "data": series_data,
                "smooth": True,
            }
        )
    x_labels.sort()
    return {
        "title": {"text": "诊断时间窗工艺联动趋势"},
        "tooltip": {"trigger": "axis"},
        "legend": {"data": legend},
        "xAxis": {"type": "category", "data": x_labels},
        "yAxis": {"type": "value"},
        "series": series_list,
    }


def _read_optional_json(path: Path, warnings: list[str]) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(f"failed to read {path.name}: {exc}")
        return None


def collect_spectrum_charts(input_dir: Path, warnings: list[str]) -> list[dict]:
    """Read LLM-written ``spectrum_*.json`` deep-sample files in input_dir.

    Each file should contain ``{"point": str, "option": <ECharts option>}``.
    Missing or malformed files are skipped with a warning rather than aborting.
    """
    charts: list[dict] = []
    if not input_dir.exists():
        return charts
    for path in sorted(input_dir.glob("spectrum_*.json")):
        payload = _read_optional_json(path, warnings)
        if isinstance(payload, dict) and "option" in payload:
            charts.append(
                {
                    "point": payload.get("point", path.stem),
                    "option": payload["option"],
                }
            )
    return charts


def collect_orbit_charts(query_payload: dict, input_dir: Path, warnings: list[str]) -> list[dict]:
    """Read orbit_*.json files. Reciprocating kinds skip orbit by design."""
    kind = query_payload.get("kind", "")
    if kind in {"reciprocating_compressor", "reciprocating_pump"}:
        return []
    charts: list[dict] = []
    if not input_dir.exists():
        return charts
    for path in sorted(input_dir.glob("orbit_*.json")):
        payload = _read_optional_json(path, warnings)
        if isinstance(payload, dict) and "option" in payload:
            charts.append(
                {
                    "bearing": payload.get("bearing", path.stem),
                    "option": payload["option"],
                }
            )
    return charts


# --- Rule matching ---


def _section_matches_evidence(section_body: str, evidence_row: dict) -> bool:
    """Best-effort: check if the rule section body mentions the evidence feature."""
    feature = (evidence_row.get("feature") or "").lower()
    if not feature:
        return False
    body_lower = section_body.lower()
    # Some heuristic equivalences: 1X dominance ~ "1x" / "1 x"; pp_value ~ "峰峰" / "pp"
    aliases = {
        "pp_value": ["pp_value", "pp ", "峰峰", "pp\xa0"],
        "rms": ["rms"],
        "one_freq_x": ["1x", "1 x", "1 倍", "one"],
        "one_freq_y": ["1x", "1 x"],
        "two_freq_x": ["2x", "2 x", "2 倍"],
        "two_freq_y": ["2x", "2 x"],
        "half_freq": ["0.5x", "1/2", "分数次", "subharmonic"],
        "remain_freq": ["broadband", "宽频"],
        "rolling_drift": ["流量", "压力", "电流", "工艺", "process"],
    }
    for alias in aliases.get(feature, [feature]):
        if alias in body_lower:
            return True
    return False


def match_rules(
    rule_book: dict,
    focus_codes: list[str],
    evidence_chain: list[dict],
    equipment_ids: list[str],
    kind: str,
) -> list[dict]:
    """Score each focus code by how many ``exceed`` evidences match the rule section.

    Each rule_match entry references evidence rows by their indices in
    ``evidence_chain`` (so the SOUL / report renderer can cite without copying).
    """
    matches: list[dict] = []
    for code in focus_codes:
        section_title, section_body = find_section_for_code(rule_book, code)
        if not section_body:
            continue
        # Count exceed/marginal evidence rows whose feature is mentioned in the section
        supporting: list[int] = []
        marginal_supporting: list[int] = []
        for idx, row in enumerate(evidence_chain):
            if not _section_matches_evidence(section_body, row):
                continue
            if row.get("verdict") == VERDICT_EXCEED:
                supporting.append(idx)
            elif row.get("verdict") == VERDICT_MARGINAL:
                marginal_supporting.append(idx)

        if not supporting and not marginal_supporting:
            # Code in focus list but no supporting evidence — skip
            continue

        # Confidence scoring
        if len(supporting) >= 3:
            confidence = "high"
        elif len(supporting) >= 1:
            confidence = "medium"
        else:
            confidence = "low"

        # Pick the equipment with the most supporting evidence
        eq_counts: dict[str, int] = {}
        for idx in supporting:
            eq = evidence_chain[idx].get("equipment_id") or ""
            if eq:
                eq_counts[eq] = eq_counts.get(eq, 0) + 1
        best_equipment = (
            max(eq_counts.items(), key=lambda kv: kv[1])[0]
            if eq_counts
            else (equipment_ids[0] if equipment_ids else "")
        )

        matches.append(
            {
                "equipment_id": best_equipment,
                "kind": kind,
                "fault_family": code,
                "fault_subtype": None,
                "confidence": confidence,
                "supporting_evidence_indices": supporting,
                "marginal_evidence_indices": marginal_supporting,
                "missing_evidence": [],
                "rule_section": section_title,
            }
        )
    return matches


# --- Historical cases (demo placeholder per design risk row 9.1) ---


def build_historical_cases(rule_matches: list[dict]) -> list[dict]:
    """Demo historical cases. Marked with data_source so SOUL can prefix '演示'."""
    cases: list[dict] = []
    for m in rule_matches[:3]:
        cases.append(
            {
                "equipment_id": m["equipment_id"] or "DEMO-EQ",
                "fault_family": m["fault_family"],
                "occurred_at": "2026-04-08",
                "summary": f"演示历史案例：{m['fault_family']} 在前一次发生时通过停机检修恢复",
                "data_source": "demo_fallback",
            }
        )
    return cases


# --- Recommendations ---


_GENERIC_RECOMMENDATIONS = {
    "unbalance": [
        "下次停机执行高速动平衡",
        "排查叶轮 / 转子积垢与腐蚀",
    ],
    "misalignment": [
        "重新校核联轴器对中（冷态 / 热态）",
        "检查热膨胀补偿与基础螺栓松动",
    ],
    "bearing_damage": [
        "评估剩余寿命，安排停机更换轴承",
        "检查润滑油牌号 / 油压 / 油温",
    ],
    "cavitation": [
        "提升吸入压力 / 降低液体温度 / 改善 NPSH 余量",
        "检查吸入管路阻力、过滤器堵塞情况",
    ],
    "min_flow_violation": [
        "强制开启再循环阀（最小连续流量阀）",
        "排查工艺需求长期偏离设计点的根因",
    ],
    "valve_failure": [
        "计划停机检查异常缸的吸气阀 / 排气阀",
        "记录 PV 图与阀门事件曲轴角偏移",
    ],
    "piston_ring_wear": [
        "停机检查活塞环磨损量与端部间隙",
        "评估润滑油牌号 / 加油量是否合适",
    ],
    "crosshead_knock": [
        "立即降负荷或停车，避免连杆 / 轴瓦剧烈损坏",
        "停机检查十字头销 / 连杆瓦 / 螺栓预紧力",
    ],
}


def build_recommendations(rule_matches: list[dict], evidence_chain: list[dict]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for m in rule_matches:
        for rec in _GENERIC_RECOMMENDATIONS.get(m["fault_family"], []):
            if rec not in seen:
                seen.add(rec)
                out.append(rec)
    if not out:
        # No matched rules at all — give a generic monitoring recommendation
        any_exceed = any(r.get("verdict") == VERDICT_EXCEED for r in evidence_chain)
        if any_exceed:
            out.append("当前存在超阈值证据但未匹配到规则；建议加密监测并由领域专家复核")
        else:
            out.append("未发现超阈值证据；建议保持常规监测节奏")
    return out


# --- Build ---


def build_features(
    query_payload: dict,
    focus_codes: list[str],
    rules_skill: str,
    input_dir: Path,
    skills_root: Path | None = None,
) -> dict:
    warnings: list[str] = []
    rule_book = load_rule_book(rules_skill, skills_root=skills_root)
    warnings.extend(rule_book.get("warnings", []))

    evidence_chain = build_evidence_chain(query_payload)
    equipment_summary = build_equipment_summary(query_payload, evidence_chain)
    trend_chart = build_trend_chart(query_payload)
    spectrum_charts = collect_spectrum_charts(input_dir, warnings)
    orbit_charts = collect_orbit_charts(query_payload, input_dir, warnings)

    # If rule book load failed catastrophically, return empty rule_matches but valid payload
    rule_matches = (
        match_rules(
            rule_book=rule_book,
            focus_codes=focus_codes,
            evidence_chain=evidence_chain,
            equipment_ids=query_payload.get("equipment_ids", []),
            kind=query_payload.get("kind", ""),
        )
        if rule_book.get("codes")
        else []
    )

    historical = build_historical_cases(rule_matches)
    recommendations = build_recommendations(rule_matches, evidence_chain)

    return {
        "report_meta": {
            "kind": query_payload.get("kind", ""),
            "rules_skill": rules_skill,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "data_source": query_payload.get("data_source", ""),
        },
        "equipment_summary": equipment_summary,
        "evidence_chain": evidence_chain,
        "trend_chart": trend_chart,
        "spectrum_charts": spectrum_charts,
        "orbit_charts": orbit_charts,
        "rule_matches": rule_matches,
        "historical_cases": historical,
        "recommendations": recommendations,
        "warnings": warnings,
    }


def write_payload(result: dict, out_path: Path | None = None) -> Path:
    target = out_path or (_output_dir() / OUTPUT_FILENAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


# --- CLI ---


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _error(message: str) -> int:
    print(json.dumps({"error": message}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute diagnosis features (stage 2)")
    parser.add_argument("--input", default=None, help="Path to query_diagnosis.json")
    parser.add_argument("--focus", required=True, help="Comma-separated fault family codes")
    parser.add_argument("--rules-skill", required=True, help=f"One of {sorted(VALID_RULES_SKILLS)}")
    parser.add_argument("--output", default=None, help="Override output path")
    args = parser.parse_args()

    try:
        if args.rules_skill not in VALID_RULES_SKILLS:
            return _error(f"--rules-skill must be one of {sorted(VALID_RULES_SKILLS)}, got: {args.rules_skill}")

        focus_codes = _parse_csv(args.focus)
        if not focus_codes:
            return _error("--focus must be a non-empty CSV of fault family codes")

        input_path = Path(args.input) if args.input else (_output_dir() / INPUT_FILENAME)
        if not input_path.exists():
            return _error(f"input file not found: {input_path}")

        try:
            query_payload = json.loads(input_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return _error(f"failed to read {input_path.name}: {exc}")

        out_path = Path(args.output) if args.output else (_output_dir() / OUTPUT_FILENAME)
        result = build_features(
            query_payload=query_payload,
            focus_codes=focus_codes,
            rules_skill=args.rules_skill,
            input_dir=input_path.parent,
        )
        write_payload(result, out_path)
        print(
            json.dumps(
                {
                    "output": str(out_path),
                    "rules_skill": args.rules_skill,
                    "evidence_count": len(result["evidence_chain"]),
                    "rule_matches_count": len(result["rule_matches"]),
                    "warnings": result["warnings"],
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001 — script convention: structured stdout
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 0


if __name__ == "__main__":
    sys.exit(main())
