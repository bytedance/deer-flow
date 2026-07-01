"""ai-report status output (新写, 中文回执 + status dict).

Phase 1 政策:
- cell 不编码哨兵字符串; 哨兵聚合通过 metric_facts.status + evaluate.status
  + md_lint errors 走 build_status 集中计算.
- 中文回执永远输出到 stdout + 写 runlog (approved_table_runs.runlog_markdown 字段),
  不分 debug / 正常模式.
"""
from __future__ import annotations

SENTINEL_CODES = ["⚠️QUERY_FAILED", "⚠️CAST_FAILED", "⚠️COMPUTE_FAILED", "⚠️DESCRIPTION_FAILED", "⚠️LINT_FAILED"]


def build_status(report_id: str, sections: list[dict], design_md_path: str) -> dict:
    approved = sum(1 for s in sections if s.get("approval_status") == "approved")
    draft = sum(1 for s in sections if s.get("approval_status") == "draft")
    by_code: dict[str, int] = {code: 0 for code in SENTINEL_CODES}
    for s in sections:
        for k in s.get("sentinels", []):
            if k in by_code:
                by_code[k] += 1
        for _, code in s.get("computed_sentinels", {}).items():
            if code in by_code:
                by_code[code] += 1
    total = sum(by_code.values())
    return {
        "report_id": report_id,
        "total_sections": len(sections),
        "approved_sections": approved,
        "draft_sections": draft,
        "total_sentinels": total,
        "sentinels_by_code": by_code,
        "design_md_path": design_md_path,
        "report_md_path": f"/mnt/ai-report-data/{report_id}.report.md",
        "report_docx_path": f"/mnt/ai-report-data/{report_id}.report.docx",
    }


def format_zh_receipt(status: dict) -> str:
    breakdown = ", ".join(f"{k}={v}" for k, v in status["sentinels_by_code"].items() if v > 0) or "无"
    return (
        f"📊 ai-report 报告生成完成\n"
        f"  - 章节数: {status['approved_sections']}/{status['total_sections']} approved\n"
        f"  - 哨兵数: {status['total_sentinels']} ({breakdown})\n"
        f"  - 未设计章节: {status['draft_sections']}\n"
        f"  - 生成路径: {status['report_md_path']} / {status['report_docx_path']}"
    )


# ---------- CLI entry ---------- #

def main(argv: list[str] | None = None) -> int:
    """CLI entry: build status.json + 中文回执 from approved_runs in DuckDB.

    Exit codes: 0 = success, 1 = report_id not found, 2 = arg error.
    """
    import argparse
    import json
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(prog="assemble_status")
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--out", required=True, help="Path to write <report_id>.status.json")
    parser.add_argument(
        "--design-md-path",
        default=None,
        help="Override design_md_path in status; default uses /mnt/ai-report-data/<id>.design.md",
    )
    args = parser.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from duckdb_store import Store

    store = Store(db_path=args.db_path)
    store.open()
    try:
        meta = store.get_report_meta(args.report_id)
        if not meta:
            print(f"❌ report_id 不存在: {args.report_id}", file=sys.stderr)
            return 1
        rows = store.list_approved_tables(args.report_id)
        sections = [
            {
                "section_title": r["section_title"],
                "approval_status": "approved",
                "sentinels": (
                    json.loads(r["sentinels"])
                    if isinstance(r.get("sentinels"), str)
                    else (r.get("sentinels") or [])
                ),
                "computed_sentinels": {},
            }
            for r in rows
        ]
        design_md_path = (
            args.design_md_path or f"/mnt/ai-report-data/{args.report_id}.design.md"
        )
        status = build_status(args.report_id, sections, design_md_path)
    finally:
        store.close()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(format_zh_receipt(status), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())