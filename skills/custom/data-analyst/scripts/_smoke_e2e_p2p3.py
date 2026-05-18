"""End-to-end smoke harness for P2 + P3 reports (Story S6 hard requirement).

Walks all 5 report pipelines without pytest. Mirrors the monthly Sprint's
``_smoke_e2e.py`` and exercises every §13.2 contract + factual contract
boundary the sprint plan enumerates.

Run from repo root:
    PYTHONIOENCODING=utf-8 python skills/custom/data-analyst/scripts/_smoke_e2e_p2p3.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

THIS_DIR = Path(__file__).parent
sys.path.insert(0, str(THIS_DIR))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, THIS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _run_case(label: str, func) -> tuple[bool, str]:
    print(f"\n=== {label} ===")
    try:
        func()
    except AssertionError as exc:
        print(f"  [FAIL] {exc}")
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] {type(exc).__name__}: {exc}")
        return False, f"{type(exc).__name__}: {exc}"
    print("  [OK]")
    return True, ""


def main() -> int:
    # Lazy-import all modules
    helpers = _load("_stub_helpers")  # noqa: F841
    query_trend = _load("query_trend")
    trend_analysis = _load("trend_analysis")
    query_fault_context = _load("query_fault_context")
    build_fault_timeline = _load("build_fault_timeline")
    diagnosis_analysis = _load("diagnosis_analysis")
    query_failure_data = _load("query_failure_data")
    failure_analysis = _load("failure_analysis")
    query_closure_items = _load("query_closure_items")
    closure_summary = _load("closure_summary")
    query_inspection = _load("query_inspection")
    inspection_summary = _load("inspection_summary")
    inspection_attachment_summary = _load("inspection_attachment_summary")

    base_dir = Path(tempfile.mkdtemp(prefix="p2p3-smoke-"))
    print(f"smoke run dir: {base_dir}")

    failures: list[str] = []

    # -------- S1: trend --------
    def case_trend():
        out = base_dir / "trend"
        sys.argv = [
            "query_trend.py",
            "--metric-keys", "runtime_rate,vibration_level,alarm_count,bearing_temp",
            "--date-range", "2026-04-01..2026-04-30",
            "--aggregation", "daily",
            "--forecast-horizon", "7",
            "--output-dir", str(out),
        ]
        assert query_trend.main() == 0
        sys.argv = ["trend_analysis.py", "--input", str(out / "data/trend_data.json"), "--output-dir", str(out)]
        assert trend_analysis.main() == 0
        analysis = json.loads((out / "data/trend_analysis.json").read_text(encoding="utf-8"))
        assert analysis["human_review_required"] is True
        assert "summary_markdown" not in analysis
        assert analysis["findings"], "trend findings empty"
        assert analysis["evidence"], "trend evidence empty"
        assert len(analysis["forecast"]) == 4, "one forecast per metric"

    # -------- S2: diagnosis --------
    def case_diagnosis():
        out = base_dir / "diagnosis"
        sys.argv = [
            "query_fault_context.py",
            "--fault-time", "2026-05-15",
            "--equipment-id", "P-001",
            "--symptom", "vibration high + bearing temp climbing",
            "--include-related-equipment",
            "--output-dir", str(out),
        ]
        assert query_fault_context.main() == 0
        sys.argv = ["build_fault_timeline.py", "--input", str(out / "data/fault_context.json"), "--output-dir", str(out)]
        assert build_fault_timeline.main() == 0
        sys.argv = [
            "diagnosis_analysis.py",
            "--input", str(out / "data/fault_context.json"),
            "--timeline", str(out / "data/fault_timeline.json"),
            "--output-dir", str(out),
        ]
        assert diagnosis_analysis.main() == 0
        analysis = json.loads((out / "data/diagnosis_analysis.json").read_text(encoding="utf-8"))
        assert analysis["human_review_required"] is True
        assert "summary_markdown" not in analysis

        # Each finding has ≥2 evidence
        from collections import Counter
        per_finding = Counter(e["finding_id"] for e in analysis["evidence"])
        for fid in {f["id"] for f in analysis["findings"]}:
            assert per_finding[fid] >= 2, f"finding {fid} has <2 evidence: {per_finding[fid]}"

        # source_type union ≥3
        src_types = {e["source_type"] for e in analysis["evidence"]}
        assert len({"timeseries", "alarm", "work_order", "maintenance_record"} & src_types) >= 3, src_types

    # -------- S3: failure-analysis (3 methods) --------
    def case_failure(method: str):
        out = base_dir / f"failure-{method}"
        sys.argv = [
            "query_failure_data.py",
            "--asset-id", "P-001",
            "--failure-mode", "轴承卡死",
            "--analysis-method", method,
            "--output-dir", str(out),
        ]
        assert query_failure_data.main() == 0
        sys.argv = ["failure_analysis.py", "--input", str(out / "data/failure_data.json"), "--output-dir", str(out)]
        assert failure_analysis.main() == 0
        analysis = json.loads((out / "data/failure_analysis.json").read_text(encoding="utf-8"))
        assert analysis["human_review_required"] is True
        assert "summary_markdown" not in analysis
        assert analysis["metadata"]["analysis_method"] == method

        block = analysis["method_block"]
        if method == "five_why":
            assert len(block["why_chain"]) == 5
        elif method == "fishbone":
            assert len(block["branches"]) == 6
        else:  # fmea
            for row in block["fmea_rows"]:
                expected = row["severity"] * row["occurrence"] * row["detection"]
                assert row["rpn"] == expected, f"RPN mismatch on {row['id']}"

    # -------- S4: closure --------
    def case_closure():
        out = base_dir / "closure"
        sys.argv = [
            "query_closure_items.py",
            "--issue-ids", "ISSUE-001,ISSUE-002,ISSUE-003,ISSUE-004,ISSUE-005,ISSUE-006,ISSUE-007",
            "--owner-department", "运行部",
            "--verification-period", "2026-04-01..2026-05-15",
            "--output-dir", str(out),
        ]
        assert query_closure_items.main() == 0
        sys.argv = ["closure_summary.py", "--input", str(out / "data/closure_items.json"), "--output-dir", str(out)]
        assert closure_summary.main() == 0
        summary = json.loads((out / "data/closure_summary.json").read_text(encoding="utf-8"))
        # Factual: NO §13.2 fields
        for forbidden in ("findings", "evidence", "confidence", "human_review_required", "summary_markdown"):
            assert forbidden not in summary, f"factual closure must not have {forbidden}"
        assert summary["overall_status"]["level"] == "critical"  # reopened item triggers critical

    # -------- S5: inspection --------
    def case_inspection():
        out = base_dir / "inspection"
        sys.argv = [
            "query_inspection.py",
            "--inspection-date", "2026-05-15",
            "--route", "RT-A",
            "--area", "A区",
            "--severity-min", "low",
            "--output-dir", str(out),
        ]
        assert query_inspection.main() == 0
        sys.argv = ["inspection_summary.py", "--input", str(out / "data/inspection_data.json"), "--output-dir", str(out)]
        assert inspection_summary.main() == 0
        sys.argv = ["inspection_attachment_summary.py", "--input", str(out / "data/inspection_data.json"), "--output-dir", str(out)]
        assert inspection_attachment_summary.main() == 0
        summary = json.loads((out / "data/inspection_summary.json").read_text(encoding="utf-8"))
        for forbidden in ("findings", "evidence", "confidence", "human_review_required", "summary_markdown"):
            assert forbidden not in summary

        # severity_distribution 4 rows
        assert [row["severity"] for row in summary["severity_distribution"]] == ["low", "medium", "high", "critical"]

        attachments = json.loads((out / "data/inspection_attachments.json").read_text(encoding="utf-8"))
        raw = json.loads((out / "data/inspection_data.json").read_text(encoding="utf-8"))
        assert len(attachments["attachment_summary"]) == len(raw["records"])

    cases: list[tuple[str, callable]] = [
        ("S6-1 trend pipeline + §13.2 contract", case_trend),
        ("S6-2 diagnosis pipeline + ≥2 evidence per finding + ≥3 source_types", case_diagnosis),
        ("S6-3a failure-analysis five_why pipeline", lambda: case_failure("five_why")),
        ("S6-3b failure-analysis fishbone pipeline", lambda: case_failure("fishbone")),
        ("S6-3c failure-analysis fmea pipeline + RPN formula", lambda: case_failure("fmea")),
        ("S6-4 closure pipeline + factual-only contract", case_closure),
        ("S6-5 inspection pipeline + factual-only contract", case_inspection),
    ]

    for label, func in cases:
        ok, msg = _run_case(label, func)
        if not ok:
            failures.append(f"{label}: {msg}")

    print("\n=== SUMMARY ===")
    if failures:
        print(f"FAILED ({len(failures)}/{len(cases)}):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"ALL CASES PASSED [OK] ({len(cases)}/{len(cases)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
