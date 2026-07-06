"""chatbi-report Orchestrator — Phase 1 / Phase 2 in-process pipeline.

Replaces 9-step CLI pattern. See
docx/superpowers/specs/2026-07-06-chatbi-report-rewrite-design.md.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class OrchestratorConfig:
    """Single-run immutable config. CLI parsing produces this."""
    md_path: Path
    out_dir: Path
    mock_fixture: Path | None = None
    skip_docx: bool = False
    style_path: Path | None = None


@dataclass
class CheckpointSignal:
    """Orchestrator emits this at steps 1.5 / 3.5 / 8d.5.

    Agent maps to ask_clarification per spec §"CheckpointSignal → ask_clarification 映射".
    """
    step: str
    metrics: dict[str, Any]
    artifacts: dict[str, Path]
    message: str


@dataclass
class ForceContinue:
    """Second-call parameter to run_phase_1; skips user-confirmed checkpoints."""
    skip_lint_checkpoint: bool = False
    skip_query_checkpoint: bool = False


@dataclass
class Phase1Result:
    parsed: dict
    wide: list[dict]   # flat list[dict] with section_idx/report_idx per row (same shape as _cli_assemble_wide)
    ir: list[dict]
    description_prompts: list[str]
    metrics: dict[str, Any]
    runlog: list[dict]
    artifacts: dict[str, Path]


@dataclass
class RunResult:
    report_md: Path
    report_docx: Path | None
    status_json: Path
    metrics: dict[str, Any]


class Orchestrator:
    """Phase 1 / Phase 2 in-process pipeline. See spec."""

    def __init__(self, cfg: OrchestratorConfig, sqlbot: Any) -> None:
        self._cfg = cfg
        self._sqlbot = sqlbot

    def run_phase_1(
        self,
        *,
        force_continue: ForceContinue | None = None,
    ) -> Phase1Result | CheckpointSignal:
        from md_lint import lint_file
        from parse_md import parse_file

        metrics: dict[str, Any] = {}
        artifacts: dict[str, Path] = {}
        fc = force_continue or ForceContinue()

        # Step 1: lint
        lint = lint_file(str(self._cfg.md_path))
        metrics["1_lint"] = {"n_err": len(lint.errors), "n_warn": len(lint.warnings)}

        if not fc.skip_lint_checkpoint and lint.errors:
            return CheckpointSignal(
                step="1.5",
                metrics=metrics,
                artifacts=artifacts,
                message=f"lint 发现 {len(lint.errors)} 错误、{len(lint.warnings)} 警告",
            )

        # Step 2: parse
        parsed = parse_file(str(self._cfg.md_path))
        stem = self._cfg.md_path.stem
        parsed_path = self._cfg.out_dir / f"{stem}.parsed.json"
        parsed_path.write_text(
            json.dumps(parsed.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        artifacts["parsed"] = parsed_path
        n_sec = len(parsed.sections)
        n_rep = sum(len(s.reports) for s in parsed.sections)
        n_idx = len(parsed.all_idx_ids)
        metrics["2_parse"] = {"n_sec": n_sec, "n_rep": n_rep, "n_idx": n_idx}

        # Step 3: query
        from sqlbot_client import query_from_parsed

        query_payload = query_from_parsed(parsed.to_dict(), self._sqlbot)
        query_path = self._cfg.out_dir / f"{stem}.query.json"
        query_path.write_text(
            json.dumps(query_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        artifacts["query"] = query_path

        def _count_query_outcomes(payload: dict) -> tuple[int, int]:
            total = 0
            ok = 0
            for entry in payload.get("results", []):
                rows = entry.get("results", [])
                total += 1
                if rows and all(bool(r.get("success")) for r in rows):
                    ok += 1
            return ok, total

        ok, total = _count_query_outcomes(query_payload)
        metrics["3_query"] = {"ok": ok, "total": total}

        if not fc.skip_query_checkpoint and ok < total:
            return CheckpointSignal(
                step="3.5",
                metrics=metrics,
                artifacts=artifacts,
                message=f"SQLBot 查询 {ok}/{total} 成功,部分失败",
            )

        # Step 4: assemble-wide (flat list[dict] with section_idx/report_idx baked in,
        # matching the existing _cli_assemble_wide contract in compute.py:444-472)
        from compute import assemble_wide_table

        flat_wide: list[dict] = []
        for sec_idx, section in enumerate(parsed.sections):
            for rep_idx, report in enumerate(section.reports):
                per_idx = [
                    {
                        "idx_id": r["idx_id"],
                        "period": r.get("period"),
                        "results": r["results"],
                    }
                    for r in query_payload.get("results", [])
                    if r.get("section_idx") == sec_idx and r.get("report_idx") == rep_idx
                ]
                rows = assemble_wide_table(per_idx, report, sec_idx, rep_idx)
                flat_wide.extend(rows)
        wide_path = self._cfg.out_dir / f"{stem}.wide.json"
        wide_path.write_text(
            json.dumps(flat_wide, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        artifacts["wide"] = wide_path
        n_rows = len(flat_wide)
        n_cols = sum(
            len({k for k in r.keys() if k not in {"branch_num", "section_idx", "report_idx", "data_dt", "org_ecd"}})
            for r in flat_wide
        )
        metrics["4_assemble"] = {"rows": n_rows, "cols": n_cols}

        # Step 6: extract-ir (per report, all sections)
        from compute import extract_compute_ir

        ir: list[dict] = []
        description_prompts: list[str] = []
        for section in parsed.sections:
            for report in section.reports:
                for spec in extract_compute_ir(report):
                    ir.append({
                        "name": spec.name,
                        "formula_repr": spec.formula_repr,
                        "base_idx_ids": list(spec.base_idx_ids),
                        "periods": list(spec.periods),
                        "examples": list(spec.examples),
                    })
                if report.description_prompt:
                    description_prompts.append(report.description_prompt)
        ir_path = self._cfg.out_dir / f"{stem}.ir.json"
        ir_path.write_text(
            json.dumps(ir, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        artifacts["ir"] = ir_path
        metrics["6_ir"] = {"n_specs": len(ir)}

        return Phase1Result(
            parsed=parsed.to_dict(),
            wide=flat_wide,
            ir=ir,
            description_prompts=description_prompts,
            metrics=metrics,
            runlog=[],
            artifacts=artifacts,
        )

    def run_phase_2(
        self,
        parsed: dict,
        wide: list[dict],
        compute_sources: dict[str, str],
        descriptions_dir: str,
        stem: str,
    ) -> CheckpointSignal | RunResult:
        from compute import validate_ast, validate_signature

        metrics: dict[str, Any] = {
            "8a_validate": {"ok": 0, "total": 0},
        }
        sentinel_cols: set[str] = set()

        for col_name, src_path_str in compute_sources.items():
            src_path = Path(src_path_str)
            source = src_path.read_text(encoding="utf-8")
            metrics["8a_validate"]["total"] += 1
            ok = True
            try:
                validate_ast(source)
                validate_signature(source, col_name)
            except Exception:
                ok = False
                sentinel_cols.add(col_name)
            if ok:
                metrics["8a_validate"]["ok"] += 1

        # Mark sentinel in flat wide rows (column value replacement where present)
        if sentinel_cols:
            for row in wide:
                for col in sentinel_cols:
                    if col in row:
                        row[col] = "⚠️COMPUTE_FAILED"

        # Step 8b: evaluate (per compute source; failures continue)
        from compute import apply_computed_results, evaluate_column
        import pandas as pd

        computed: dict[str, dict] = {}
        eval_ok = 0
        eval_total = 0
        for col_name, src_path_str in compute_sources.items():
            if col_name in sentinel_cols:
                continue
            eval_total += 1
            try:
                # Build a DataFrame from wide rows (flat). Missing columns yield NaN;
                # sentinel-marked cells already short-circuit via 8a.
                df = pd.DataFrame(wide)
                series = evaluate_column(
                    source=Path(src_path_str).read_text(encoding="utf-8"),
                    function_name=col_name,
                    df=df,
                )
                computed[col_name] = {
                    str(idx): (None if pd.isna(v) else v)
                    for idx, v in series.items()
                }
                eval_ok += 1
            except Exception:
                sentinel_cols.add(col_name)
        metrics["8b_evaluate"] = {"ok": eval_ok, "total": eval_total}

        # Step 8c: apply-computed (in-place, preserves section_idx/report_idx)
        wide = apply_computed_results(wide, computed)
        metrics["8c_apply"] = {"n_columns": len(computed)}

        return self._finish_phase_2(parsed, wide, metrics, descriptions_dir, stem)

    def _finish_phase_2(
        self, parsed: dict, wide: list[dict], metrics: dict[str, Any],
        descriptions_dir: str, stem: str,
    ) -> RunResult:
        status_path = self._cfg.out_dir / "status.json"
        from assemble_status import write_status

        # Map detailed metrics → spec-pinned 8-key schema for status.json.
        # Detailed per-step metrics go to the sidecar orchestrator-metrics.json
        # so the schema stays untouched.
        flat_metrics = {
            "computed_count": metrics["8a_validate"]["total"],
            "compute_validation_failures": metrics["8a_validate"]["total"]
            - metrics["8a_validate"]["ok"],
        }
        write_status(
            out_path=str(status_path),
            exit_step="9",
            error_class=None,
            error_detail="",
            outputs={
                "report_md": str(self._cfg.out_dir / "report.md"),
                "report_docx": (
                    None if self._cfg.skip_docx
                    else str(self._cfg.out_dir / "report.docx")
                ),
            },
            metrics=flat_metrics,
        )
        # Sidecar for debug data
        sidecar = self._cfg.out_dir / "orchestrator-metrics.json"
        sidecar.write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return RunResult(
            report_md=self._cfg.out_dir / "report.md",
            report_docx=None if self._cfg.skip_docx else self._cfg.out_dir / "report.docx",
            status_json=status_path,
            metrics=metrics,
        )
