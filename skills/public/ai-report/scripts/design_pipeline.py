"""ai-report design pipeline (新写, LangGraph make_lead_agent 入口 + 6 checkpoints).

Per-section 14-step orchestrator. Phase 1 fixes vs the original plan:
- Step 6-9 sentinel: validate/evaluate failure → cell=None, NOT sentinel string
  (Phase 1 政策). 哨兵聚合由 task 13 build_status 负责.
- Step 10 unit_convert: Python 端 apply_units 取代 DuckDB UPDATE.
  - Decimal / Decimal 保留银行精度, 无 float round-trip
  - headers_2d 是 dict (asdict(Th)), DuckDB UPDATE 路径 getattr 拿不到, no-op
  - 无 shared-conn / write_lock / schema 污染问题
- validate 用 per-call :memory: conn (同 evaluate), 不污染 store schema
- 持久化前 wide cell Decimal → str (JSON 序列化需要)
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import duckdb

from compute import (
    ComputeIR, apply_computed, assemble_wide, evaluate, extract_ir, validate,
)
from duckdb_store import (
    Store, make_report_id, make_run_id, make_section_id,
)
from md_lint import lint_markdown
from parse_md import parse_markdown
from report_split import split_report
from sqlbot_client import SQLBotError
from unit_convert import apply_units


# 这些函数在 runtime 由 lead agent / LLM 替换, 测试里 monkeypatch
def _llm_codegen(ir: ComputeIR, wide_sample: list[dict]) -> str:
    """占位: lead agent in-turn 调 compute_codegen.md prompt 生成 DuckDB SQL."""
    raise NotImplementedError("LLM codegen not wired in unit test; monkeypatch this")


def _llm_describe(wide_rows: list[dict], report_title: str, description_prompt: str | None = None) -> str:
    raise NotImplementedError("LLM describe not wired in unit test; monkeypatch this")


def _checkpoint(message: str, options: list[str]) -> str:
    """占位: lead agent 调 ask_clarification. 测试里 monkeypatch auto-approve."""
    raise NotImplementedError("ask_clarification not wired in unit test; monkeypatch this")


def _parse_decimal_or_none(raw: Any) -> tuple[Decimal | None, str]:
    """SQLBot response: try cast `raw` to Decimal. Returns (value, status)."""
    if raw is None:
        return None, "cast_failed"
    try:
        return Decimal(str(raw)), "ok"
    except (ValueError, ArithmeticError, TypeError):
        return None, "cast_failed"


def _jsonify_wide(wide: list[dict]) -> list[dict]:
    """Convert Decimal cells to str for JSON serialization to DuckDB JSON column.

    Precision is preserved by str(Decimal) (e.g. Decimal('1234567890.1234567890')
    → '1234567890.1234567890'). Renderers parse str back as Decimal/float.
    """
    out = []
    for row in wide:
        new_row = {}
        for k, v in row.items():
            if isinstance(v, Decimal):
                new_row[k] = str(v)
            else:
                new_row[k] = v
        out.append(new_row)
    return out


class DesignPipeline:
    def __init__(self, store: Store, sqlbot: Any):
        self.store = store
        self.sqlbot = sqlbot

    def _step_query_metrics(
        self, run_id: str, table_id: str, report_id: str,
        all_idx: list[str], time_info: list[str], org_ctxs: list[dict],
    ) -> list[dict]:
        """Step 2-3: per (idx, period) call sqlbot → fact row. status='query_failed' or 'ok'/'cast_failed'.

        Issue 3 修复: SQLBot 业务错误 (SQLBotError) 被降级为 query_failed fact,
        而不是冒泡终止整个 section pipeline.
        """
        facts: list[dict] = []
        for idx_id in all_idx:
            for period in time_info:
                # MockSQLBotClient convention: pass bare idx_id + time_info, mock composes lookup
                # (RealSQLBotClient: same convention — see sqlbot_client.py docstring)
                try:
                    resp = self.sqlbot.query_report_info(
                        org_info=org_ctxs,
                        index_info=[{"idx_id": idx_id}],
                        time_info=[period],
                    )
                except SQLBotError as e:
                    facts.append({
                        "branch_num": org_ctxs[0].get("org_ecd", "1") if org_ctxs else "1",
                        "branch_short_name": org_ctxs[0].get("org_name") if org_ctxs else None,
                        "idx_id": idx_id,
                        "period_alias": period,
                        "period_value": period,
                        "raw_value": None,
                        "numeric_value": None,
                        "status": "query_failed",
                        "error_message": f"SQLBotError: {e}",
                    })
                    continue
                elem = resp.data[0] if resp.data else {"success": False, "data": []}
                success = bool(elem.get("success", False))
                if not success:
                    # query_failed: still emit a fact with status='query_failed' for sentinel aggregation
                    facts.append({
                        "branch_num": org_ctxs[0].get("org_ecd", "1") if org_ctxs else "1",
                        "branch_short_name": org_ctxs[0].get("org_name") if org_ctxs else None,
                        "idx_id": idx_id,
                        "period_alias": period,
                        "period_value": period,
                        "raw_value": None,
                        "numeric_value": None,
                        "status": "query_failed",
                        "error_message": elem.get("msg"),
                    })
                    continue
                for row in elem.get("data", []):
                    num, cast_status = _parse_decimal_or_none(row.get("value"))
                    facts.append({
                        "branch_num": row.get("org_ecd", "1"),
                        "branch_short_name": row.get("idx_name"),
                        "idx_id": idx_id,
                        "period_alias": period,
                        "period_value": str(row.get("data_dt", period)),
                        "raw_value": str(row.get("value")) if row.get("value") is not None else None,
                        "numeric_value": num,
                        "status": cast_status,
                        "error_message": None,
                    })
        self.store.insert_metric_facts(run_id, table_id, report_id, facts)
        return facts

    def _step_compute(
        self, wide: list[dict], irs: list[ComputeIR], run_id: str,
    ) -> tuple[list[dict], list[str]]:
        """Step 6-9: codegen → validate → evaluate → apply-computed.

        Phase 1 fix: failed compute → cell=None (not sentinel string), 哨兵名 list
        returned for build_status aggregation.

        Defensive fixes (P2):
        - Issue 1: _llm_codegen NotImplementedError / Exception → mark compute_failed,
          don't kill the section.
        - Issue 6/15: example value None / dict / list → None, don't InvalidOperation.
        """
        computed: dict[str, list] = {}
        failed_compute: list[str] = []

        def _safe_example_expected(ir: ComputeIR) -> Decimal | None:
            if not ir.examples:
                return None
            raw = ir.examples[0].get("value")
            if raw is None or isinstance(raw, (dict, list)):
                return None
            try:
                return Decimal(str(raw))
            except (InvalidOperation, ValueError):
                return None

        for ir in irs:
            # Issue 1: catch LLM codegen failures (LLM not wired in dev / exception)
            try:
                sql = _llm_codegen(ir, wide[:3])
            except (NotImplementedError, Exception) as e:
                print(f"  ⚠️ _llm_codegen failed for {ir.name}: {e}", file=sys.stderr)
                computed[ir.name] = [None] * len(wide)
                failed_compute.append(ir.name)
                continue
            # validate: per-call :memory: conn (avoids polluting store schema / concurrency)
            with duckdb.connect(":memory:") as conn:
                vr = validate(
                    conn, sql, wide, ["branch_num", ir.name],
                    example_input=ir.examples[0] if ir.examples else None,
                    example_expected=_safe_example_expected(ir),
                )
            if not vr.passed:
                computed[ir.name] = [None] * len(wide)
                failed_compute.append(ir.name)
                continue
            values, _status = evaluate(sql, wide, ir.name)
            computed[ir.name] = values
            if all(v is None for v in values):
                failed_compute.append(ir.name)
        wide = apply_computed(wide, computed)
        return wide, failed_compute

    def run_section(self, table_id: str) -> dict:
        """Per-section 14-step pipeline. Returns final state dict."""
        table = self.store.get_table(table_id)
        if table is None:
            return {"approval_status": "draft", "stopped_at": "table_not_found"}
        run_id = make_run_id()
        parsed_raw = table.get("parsed_payload")
        if isinstance(parsed_raw, str):
            parsed = json.loads(parsed_raw)
        else:
            parsed = parsed_raw or {}

        # Step 2-3: query metrics
        facts = self._step_query_metrics(
            run_id, table_id, table["report_id"],
            parsed.get("all_idx_ids", []),
            parsed.get("time_info", []),
            parsed.get("org_contexts", []),
        )

        # Checkpoint 3.5: query done
        ok = sum(1 for f in facts if f["status"] == "ok")
        reply = _checkpoint(
            f"🔍 Checkpoint 3.5: {ok}/{len(facts)} 指标成功, 继续?",
            ["continue", "stop"],
        )
        if reply == "stop":
            return {"approval_status": "draft", "stopped_at": "checkpoint_3.5", "run_id": run_id}

        # Step 4-5: assemble-wide + extract-ir
        wide = assemble_wide(facts, run_id, table_id)
        irs = extract_ir(parsed.get("compute_block_md", ""))

        # Step 6-9: codegen + validate + evaluate + apply-computed
        wide, failed_compute = self._step_compute(wide, irs, run_id)

        # Step 10: unit_convert (Python path, Decimal precision)
        wide = apply_units(wide, parsed.get("headers_2d", []))

        # Step 11: describe (pass the user-provided prompt hint if any)
        desc = _llm_describe(wide, parsed.get("title", ""), parsed.get("description_prompt"))

        # Checkpoint 8d.5: describe (only if description_prompt was provided)
        if parsed.get("description_prompt"):
            reply = _checkpoint(
                f"🚦 Checkpoint 8d.5: 描述生成完成, 继续?",
                ["continue", "stop"],
            )
            if reply == "stop":
                return {"approval_status": "draft", "stopped_at": "checkpoint_8d.5", "run_id": run_id}

        # Step 12-13: render preview (just build dict; lead agent displays)
        preview = {
            "title": parsed.get("title", ""),
            "headers": parsed.get("headers_2d", []),
            "rows": wide,
            "description": desc,
        }

        # Checkpoint 10: preview approve
        reply = _checkpoint(
            f"🚦 Checkpoint 10: section preview 准备好, approve?",
            ["approve", "modify", "reject"],
        )
        if reply != "approve":
            return {"approval_status": "draft", "stopped_at": "checkpoint_10", "run_id": run_id}

        # Step 14: save approved run
        design_md_path = f"/mnt/ai-report-data/{table['report_id']}.design.md"
        runlog = f"# Run {run_id}\nSection {table_id} approved at {design_md_path}"
        # Sentinels: ⚠️ codes (matches assemble_status.build_status aggregator contract).
        # Phase 1: each failing fact/column emits one code so the breakdown counts
        # real failures. Storing raw names like "利润率" or "BAS_001@202603" instead
        # of codes would silently drop them from build_status (by_code miss).
        sentinels: list[str] = []
        for f in facts:
            if f["status"] == "query_failed":
                sentinels.append("⚠️QUERY_FAILED")
            elif f["status"] == "cast_failed":
                sentinels.append("⚠️CAST_FAILED")
        for _ in failed_compute:
            sentinels.append("⚠️COMPUTE_FAILED")
        # Status: 'ok' only when all facts ok AND all computes passed.
        has_failure = bool(failed_compute) or any(
            f["status"] in ("query_failed", "cast_failed") for f in facts
        )
        run_status = "partial" if has_failure else "ok"
        self.store.save_approved_run(
            run_id, table_id, table["report_id"], table["section_id"],
            _jsonify_wide(wide), list(parsed.get("headers_2d", [])), [desc], run_status,
            sentinels, runlog, design_md_path,
        )
        return {"approval_status": "approved", "run_id": run_id}


def run_report(store: Store, sqlbot: Any, md_path: str) -> dict:
    """整本首次导入 + 逐节 design. Checkpoint 0/1.5/11 在这里处理."""
    md = Path(md_path).read_text(encoding="utf-8")
    lint = lint_markdown(md)
    if lint.errors:
        reply = _checkpoint(
            f"🚦 Checkpoint 0: lint 失败 {len(lint.errors)} 处, 继续?",
            ["continue", "stop"],
        )
        if reply == "stop":
            return {"status": "lint_aborted", "errors": [e.message for e in lint.errors]}

    # Checkpoint 1.5: informational (lint passed; honor user's 'stop' reply)
    reply = _checkpoint(
        f"🚦 Checkpoint 1.5: lint pass {len(lint.warnings)} warning, 继续?",
        ["continue", "stop"],
    )
    if reply == "stop":
        return {"status": "user_aborted", "stopped_at": "checkpoint_1.5"}

    report_id = make_report_id(md_path)
    src_hash = hashlib.sha256(md.encode("utf-8")).hexdigest()
    doc = parse_markdown(md)
    store.upsert_report(report_id, doc.title, md_path, src_hash)
    section_blocks = split_report(md)
    for sb in section_blocks:
        sec_id = store.upsert_section(report_id, sb.section_order, sb.section_title)
        # 1 section → 1 table (王益联社 sample 简化为 1 节 1 表)
        sec_report = doc.sections[sb.section_order].reports[0]
        store.upsert_table(
            report_id, sec_id, 0, sec_report.title,
            sb.source_md, src_hash,
            {
                "title": sec_report.title,
                "all_idx_ids": list(doc.all_idx_ids),
                "org_contexts": [asdict(o) for o in sec_report.org_contexts],
                "time_info": sec_report.time_info,
                "headers_2d": [[asdict(th) for th in row] for row in sec_report.headers],
                "compute_block_md": sb.source_md,
                "description_prompt": sec_report.description_prompt,
            },
        )

    pipeline = DesignPipeline(store, sqlbot)
    results = []
    for sb in section_blocks:
        sec_id = make_section_id(report_id, sb.section_order)
        for tbl in store.list_tables_by_section(sec_id):
            r = pipeline.run_section(tbl["table_id"])
            results.append(r)
            if r.get("approval_status") != "approved":
                continue
            reply = _checkpoint(
                f"🚦 Checkpoint 11: section {sb.section_order} approved, 继续?",
                ["continue", "jump", "preview", "done"],
            )
            if reply == "done":
                return {"status": "done", "results": results}

    return {"status": "completed", "results": results}