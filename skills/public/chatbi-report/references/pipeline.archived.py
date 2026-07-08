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

        # Step 8d: attach descriptions via render_markdown's standard API
        # (sets report.description_text, NOT _description_text — see render_markdown:96-112).
        from render_markdown import attach_description_files, doc_from_dict

        doc = doc_from_dict(parsed)
        attach_description_files(doc, descriptions_dir, stem=stem)

        # Detect failures: any report with description_prompt that didn't get description_text.
        d_total = 0
        d_found = 0
        for section in doc.sections:
            for report in section.reports:
                if not report.description_prompt:
                    continue
                d_total += 1
                if getattr(report, "description_text", None):
                    d_found += 1
        metrics["8d_describe"] = {"ok": d_found, "total": d_total}

        # Step 8d.5: description checkpoint (per spec §"用户回复路由" — 8d.5 always triggers
        # when any description file is missing AND prompts existed, 2026-06-27 policy reversal).
        if d_total > 0 and d_found < d_total:
            return CheckpointSignal(
                step="8d.5",
                metrics=metrics,
                artifacts={"parsed": self._cfg.out_dir / f"{stem}.parsed.json"},
                message=f"description 生成 {d_found}/{d_total} 失败",
            )

        return self._finish_phase_2(parsed, wide, metrics, descriptions_dir, stem)

    def _finish_phase_2(
        self, parsed: dict, wide: list[dict], metrics: dict[str, Any],
        descriptions_dir: str,
        stem: str,
    ) -> RunResult:
        from render_docx import render_docx
        from render_markdown import (
            attach_description_files,
            doc_from_dict,
            normalize_wide_by_report,
            render_markdown,
        )

        doc = doc_from_dict(parsed)

        # wide is flat list[dict] (from disk or Phase1Result.wide). Filter per report
        # and reshape to the {data_dt, org_ecd, branch_num, cells, raw_cells} format
        # render_markdown / render_docx expect. Mirrors _cli_assemble_wide +
        # normalize_wide_by_report semantics.
        wide_by_report: list[list[dict]] = []
        for sec_idx, section in enumerate(doc.sections):
            for rep_idx, _ in enumerate(section.reports):
                rows = [
                    r for r in wide
                    if r.get("section_idx") == sec_idx and r.get("report_idx") == rep_idx
                ]
                if not rows:
                    wide_by_report.append([])
                    continue
                wide_by_report.append(normalize_wide_by_report(doc, rows)[0])

        # Attach description text via the existing render_markdown API
        # (sets report.description_text, NOT _description_text — see render_markdown:96-112).
        # Idempotent: 8d already called this, but no-op when description_text is set.
        attach_description_files(doc, descriptions_dir, stem=stem)
        compute_status: dict[str, str] = {}

        report_md_path = self._cfg.out_dir / "report.md"
        # render_markdown returns str; we write to file ourselves (signature: render_markdown:243).
        md_text = render_markdown(
            doc=doc,
            wide_by_report=wide_by_report,
            compute_status=compute_status,
        )
        report_md_path.write_text(md_text, encoding="utf-8")

        report_docx_path: Path | None = None
        if not self._cfg.skip_docx:
            report_docx_path = self._cfg.out_dir / "report.docx"
            # style_path is REQUIRED (no default in render_docx:122-128); use bundled default.
            resolved_style = self._cfg.style_path or (
                Path(__file__).resolve().parents[1] / "example" / "style.json"
            )
            render_docx(
                doc,
                wide_by_report,
                out_path=str(report_docx_path),
                style_path=str(resolved_style),
            )

        # Translate orchestrator-shaped metrics → write_status schema (8 flat keys,
        # see assemble_status.py:54-63). Detailed per-step metrics are NOT persisted
        # in status.json by design (spec-pinned schema).
        from assemble_status import write_status

        def _ok_total(entry: dict | None) -> tuple[int, int]:
            if not entry:
                return 0, 0
            return int(entry.get("ok", 0)), int(entry.get("total", 0))

        q_ok, q_total = _ok_total(metrics.get("3_query"))
        if q_total == 0:
            # Phase 2 invocation: re-derive query counts from query.json on disk
            # (Phase 1 stored the same numbers in metrics; CLI invocations don't
            # carry Phase 1 metrics into Phase 2).
            q_path = self._cfg.out_dir / f"{stem}.query.json"
            if q_path.exists():
                payload = json.loads(q_path.read_text(encoding="utf-8"))
                entries = payload.get("results", [])
                q_total = len(entries)
                q_ok = sum(
                    1 for e in entries
                    if e.get("results") and all(bool(r.get("success")) for r in e["results"])
                )
        a_ok, a_total = _ok_total(metrics.get("8a_validate"))
        d_ok, d_total = _ok_total(metrics.get("8d_describe"))
        flat_metrics = {
            "queried_count": q_total,
            "query_failures": q_total - q_ok,
            "computed_count": a_total,
            "compute_validation_failures": a_total - a_ok,
            "descriptions_generated": d_ok,
            "description_failures": d_total - d_ok,
            "llm_calls": 0,  # orchestrator never invokes the LLM directly
            "duration_seconds": float(metrics.get("duration_seconds", 0.0)),
        }
        # Keep orchestrator's detailed metrics in a sidecar for debugging —
        # NOT status.json (spec-pinned schema).
        sidecar_path = self._cfg.out_dir / "orchestrator-metrics.json"
        sidecar_path.write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

        status_path = self._cfg.out_dir / "status.json"
        outputs: dict[str, str] = {"report_md": str(report_md_path)}
        if report_docx_path is not None:
            outputs["report_docx"] = str(report_docx_path)
        write_status(
            out_path=status_path,
            exit_step="9",
            error_class=None,
            error_detail=None,
            outputs=outputs,
            metrics=flat_metrics,
        )
        return RunResult(
            report_md=report_md_path,
            report_docx=report_docx_path,
            status_json=status_path,
            metrics=metrics,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _emit_wire_format(result: Phase1Result | CheckpointSignal | RunResult) -> None:
    """Print last-line JSON for the lead agent to parse."""
    if isinstance(result, Phase1Result):
        payload = {
            "kind": "phase1_result",
            "result": {
                "parsed": result.parsed,
                "wide": result.wide,
                "ir": result.ir,
                "description_prompts": result.description_prompts,
                "metrics": result.metrics,
                "artifacts": {k: str(v) for k, v in result.artifacts.items()},
            },
        }
    elif isinstance(result, CheckpointSignal):
        payload = {
            "kind": "checkpoint",
            "step": result.step,
            "metrics": result.metrics,
            "artifacts": {k: str(v) for k, v in result.artifacts.items()},
            "message": result.message,
        }
    elif isinstance(result, RunResult):
        payload = {
            "kind": "phase2_result",
            "result": {
                "report_md": str(result.report_md),
                "report_docx": str(result.report_docx) if result.report_docx else None,
                "status_json": str(result.status_json),
                "metrics": result.metrics,
            },
        }
    else:
        raise TypeError(f"unexpected result type: {type(result).__name__}")
    print(json.dumps(payload, ensure_ascii=False, default=str))


def _parse_kv_list(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"expected key=value, got: {item!r}")
        k, v = item.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    from sqlbot_client import MockSQLBotClient, RealSQLBotClient

    parser = argparse.ArgumentParser(prog="pipeline", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("phase1", help="Run Phase 1 (steps 1–6).")
    p1.add_argument("--md", required=True)
    p1.add_argument("--out-dir", required=True)
    p1.add_argument("--mock-fixture", default=None)
    # force_continue flags — set when the user has already acknowledged the
    # checkpoint at 1.5 / 3.5 (see spec §"用户回复路由" — agent re-invokes
    # `phase1` with these set after user picks "继续").
    p1.add_argument("--skip-lint-checkpoint", action="store_true",
                    help="Skip the 1.5 lint checkpoint (user confirmed continue).")
    p1.add_argument("--skip-query-checkpoint", action="store_true",
                    help="Skip the 3.5 query checkpoint (user confirmed continue).")

    p2 = sub.add_parser("phase2", help="Run Phase 2 (steps 8a–9).")
    p2.add_argument("--md", required=True)
    p2.add_argument("--out-dir", required=True)
    p2.add_argument("--compute-source", action="append", default=[],
                    help="colname=/path/to/source.py (repeatable)")
    p2.add_argument("--descriptions-dir", default=None,
                    help="dir containing <stem>.description.report-<idx>.txt files "
                         "(defaults to <out_dir>)")
    p2.add_argument("--skip-docx", action="store_true")
    p2.add_argument("--style-path", default=None,
                    help="DOCX style JSON (defaults to example/style.json)")

    args = parser.parse_args(argv)

    cfg = OrchestratorConfig(
        md_path=Path(args.md),
        out_dir=Path(args.out_dir),
        mock_fixture=Path(args.mock_fixture) if getattr(args, "mock_fixture", None) else None,
        skip_docx=getattr(args, "skip_docx", False),
        style_path=Path(args.style_path) if getattr(args, "style_path", None) else None,
    )
    try:
        if args.cmd == "phase1":
            sqlbot: Any
            if cfg.mock_fixture is not None:
                sqlbot = MockSQLBotClient(str(cfg.mock_fixture))
            else:
                sqlbot = RealSQLBotClient()
            orch = Orchestrator(cfg, sqlbot)
            fc = ForceContinue(
                skip_lint_checkpoint=args.skip_lint_checkpoint,
                skip_query_checkpoint=args.skip_query_checkpoint,
            )
            result = orch.run_phase_1(force_continue=fc)
        else:
            # Phase 2 doesn't invoke SQLBot (parsed + wide are read from disk).
            # Use a dummy client to satisfy the Orchestrator constructor.
            orch = Orchestrator(cfg, MockSQLBotClient(str(FIXTURE))) if False else Orchestrator(
                cfg, _NullSQLBotClient()
            )
            stem = cfg.md_path.stem
            parsed = json.loads(
                (cfg.out_dir / f"{stem}.parsed.json").read_text(encoding="utf-8")
            )
            wide = json.loads(
                (cfg.out_dir / f"{stem}.wide.json").read_text(encoding="utf-8")
            )
            descriptions_dir = args.descriptions_dir or str(cfg.out_dir)
            result = orch.run_phase_2(
                parsed=parsed,
                wide=wide,
                compute_sources=_parse_kv_list(args.compute_source),
                descriptions_dir=descriptions_dir,
                stem=stem,
            )
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    _emit_wire_format(result)
    return 0


class _NullSQLBotClient:
    """Placeholder for Phase 2 invocations — never called because phase 2
    reads parsed + wide from disk."""

    def query_report_info(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError(
            "_NullSQLBotClient.query_report_info should not be called — "
            "Phase 2 reads parsed + wide from disk and does not invoke SQLBot."
        )


if __name__ == "__main__":
    raise SystemExit(main())
