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