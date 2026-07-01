"""ai-report runtime pipeline (新写, 5-step orchestrator).

Phase 1 fixes vs spec:
- 去掉冗余 store.init_schema() (open() 自动调, CREATE TABLE IF NOT EXISTS 幂等)
- 默认 style_path = scripts/report_style.json (同 report_docx.py)
- 中文回执永远输出 (no debug mode), build_status + format_zh_receipt
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from assemble_status import build_status, format_zh_receipt
from duckdb_store import DEFAULT_DB_PATH, Store
from render_docx import render_docx
from render_markdown import render_markdown
from report_md import build_runtime_payload


class RuntimePipeline:
    def __init__(self, store: Store, *, strict: bool = False):
        self.store = store
        self.strict = strict

    def run_report(self, report_id: str, *, out_dir: str = "/mnt/ai-report-data") -> dict:
        # R-0: existence check
        meta = self.store.get_report_meta(report_id)
        if not meta:
            return {"status": "not_found", "error": f"report_id={report_id} 不存在"}
        # R-1: pull approved
        rows = self.store.list_approved_tables(report_id)
        if not rows:
            if self.strict:
                raise RuntimeError(f"strict mode: no approved tables for {report_id}")
            return {"status": "empty", "report_id": report_id}
        # R-2: build payload
        payload = build_runtime_payload(self.store, report_id)
        # R-2.5: ensure out_dir exists (CLI first-run path)
        out_dir_path = Path(out_dir)
        out_dir_path.mkdir(parents=True, exist_ok=True)
        # R-3: render md
        out_md = out_dir_path / f"{report_id}.report.md"
        out_md.write_text(render_markdown(payload), encoding="utf-8")
        # R-4: render docx
        out_docx = out_dir_path / f"{report_id}.report.docx"
        style_path = str(Path(__file__).resolve().parent / "report_style.json")
        render_docx(payload, out_path=str(out_docx), style_path=style_path)
        # R-5: 中文回执 (永远输出 + 写 status dict + status.json)
        sections = [
            {
                "section_title": r["section_title"],
                "approval_status": "approved",
                "sentinels": json.loads(r["sentinels"]) if isinstance(r["sentinels"], str) else r["sentinels"],
                "computed_sentinels": {},
            }
            for r in rows
        ]
        status = build_status(
            report_id, sections,
            design_md_path=f"/mnt/ai-report-data/{report_id}.design.md",
        )
        receipt = format_zh_receipt(status)
        out_status = out_dir_path / f"{report_id}.status.json"
        out_status.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        print(receipt, flush=True)
        return {
            "status": "completed",
            "report_id": report_id,
            "out_md": str(out_md),
            "out_docx": str(out_docx),
            "out_status": str(out_status),
            "receipt": receipt,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="runtime_pipeline")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--out-dir", default="/mnt/ai-report-data")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    store = Store(db_path=args.db_path)
    try:
        store.open()  # auto-inits schema
        pipeline = RuntimePipeline(store, strict=args.strict)
        result = pipeline.run_report(args.report_id, out_dir=args.out_dir)
        if result["status"] == "not_found":
            print(f"❌ report_id 不存在: {args.report_id}", file=sys.stderr)
            return 1
        if result["status"] == "empty":
            print(
                f"⚠️ 报告 {args.report_id} 没有任何 approved section, "
                "请先运行 design pipeline 完成 design",
                file=sys.stderr,
            )
            return 1
        return 0
    except Exception as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    finally:
        try:
            store.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())