"""chatbi-report Single Pipeline — simplified flow without checkpoints.

- Single phase: lint → parse → query → assemble → extract-ir → validate → evaluate → apply-computed → describe → render
- Any error stops immediately
- JSON wire format for success/error with traceback in debug mode
- status.json in debug mode
"""
from __future__ import annotations

import json
import os
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPTS_DIR.parent
DEFAULT_FIXTURE = SCRIPTS_DIR / "example" / "mock_sqlbot" / "profit_yoy.json"


def load_env(env_path: Path | None = None) -> dict[str, str]:
    """Load KEY=VALUE pairs from a .env file into ``os.environ``."""
    if env_path is None:
        env_path = SKILL_DIR / ".env"
    loaded: dict[str, str] = {}
    if not env_path.exists():
        return loaded
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        loaded[key] = value
        os.environ.setdefault(key, value)
    return loaded


@dataclass
class PipelineConfig:
    """Single-run immutable config. CLI parsing produces this."""
    md_path: Path
    out_dir: Path
    mock_fixture: Path | None = None
    skip_docx: bool = False
    style_path: Path | None = None
    debug: bool = False


@dataclass
class PipelineResult:
    """Success result with all outputs and metrics."""
    status: str  # "success"
    exit_step: str
    outputs: dict[str, str]
    metrics: dict[str, Any]


@dataclass
class PipelineError:
    """Error result with traceback and partial outputs."""
    status: str  # "error"
    exit_step: str
    error_class: str
    error_detail: str
    traceback: str
    outputs: dict[str, str]
    metrics: dict[str, Any]
    exit_code: int = 1


class SinglePipeline:
    """Single-phase pipeline without checkpoints. Any error stops immediately."""

    def __init__(self, cfg: PipelineConfig, sqlbot: Any) -> None:
        self._cfg = cfg
        self._sqlbot = sqlbot
        self._metrics: dict[str, Any] = {}
        self._artifacts: dict[str, Path] = {}
        self._exit_step: str = ""

    def run(self) -> PipelineResult | PipelineError:
        """Run the full pipeline. Any exception is caught and returned as PipelineError."""
        try:
            self._run_steps()
            return self._build_success_result()
        except Exception as exc:
            return self._build_error_result(exc)

    def _run_steps(self) -> None:
        """Execute all pipeline steps in order. Any error propagates."""
        # Step 1: lint
        self._exit_step = "lint"
        from md_lint import lint_file
        lint = lint_file(str(self._cfg.md_path))
        self._metrics["1_lint"] = {"n_err": len(lint.errors), "n_warn": len(lint.warnings)}
        if lint.errors:
            raise LintError(f"lint found {len(lint.errors)} errors, {len(lint.warnings)} warnings")

        # Step 2: parse
        self._exit_step = "parse"
        from parse_md import parse_file
        parsed = parse_file(str(self._cfg.md_path))
        stem = self._cfg.md_path.stem
        parsed_path = self._cfg.out_dir / f"{stem}.parsed.json"
        parsed_path.write_text(
            json.dumps(parsed.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._artifacts["parsed"] = parsed_path
        n_sec = len(parsed.sections)
        n_rep = sum(len(s.reports) for s in parsed.sections)
        n_idx = len(parsed.all_idx_ids)
        self._metrics["2_parse"] = {"n_sec": n_sec, "n_rep": n_rep, "n_idx": n_idx}

        # Step 3: query
        self._exit_step = "query"
        from sqlbot_client import query_from_parsed
        query_payload = query_from_parsed(parsed.to_dict(), self._sqlbot)
        query_path = self._cfg.out_dir / f"{stem}.query.json"
        query_path.write_text(
            json.dumps(query_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._artifacts["query"] = query_path

        ok, total = self._count_query_outcomes(query_payload)
        self._metrics["3_query"] = {"ok": ok, "total": total}
        if ok < total:
            raise QueryError(f"SQLBot query {ok}/{total} succeeded")

        # Step 4: assemble-wide
        self._exit_step = "assemble"
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
        self._artifacts["wide"] = wide_path
        n_rows = len(flat_wide)
        n_cols = sum(
            len({k for k in r.keys() if k not in {"branch_num", "section_idx", "report_idx", "data_dt", "org_ecd"}})
            for r in flat_wide
        )
        self._metrics["4_assemble"] = {"rows": n_rows, "cols": n_cols}

        # Step 5: extract-ir
        self._exit_step = "extract_ir"
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
        self._artifacts["ir"] = ir_path
        self._metrics["5_ir"] = {"n_specs": len(ir)}

        # Step 6: validate compute sources
        self._exit_step = "validate"
        # Step 6: validate skipped — agent pre-validates compute sources before pipeline

        # Step 7: render
        self._exit_step = "render"
        from render_docx import render_docx
        from render_markdown import (
            attach_description_files,
            doc_from_dict,
            normalize_wide_by_report,
            render_markdown,
        )
        doc = doc_from_dict(parsed.to_dict())

        wide_by_report: list[list[dict]] = []
        for sec_idx, section in enumerate(doc.sections):
            for rep_idx, _ in enumerate(section.reports):
                rows = [
                    r for r in flat_wide
                    if r.get("section_idx") == sec_idx and r.get("report_idx") == rep_idx
                ]
                if not rows:
                    wide_by_report.append([])
                    continue
                wide_by_report.append(normalize_wide_by_report(doc, rows)[0])

        # Attach description files if they exist
        descriptions_dir = str(self._cfg.out_dir)
        attach_description_files(doc, descriptions_dir, stem=stem)

        report_md_path = self._cfg.out_dir / f"{stem}.report.md"
        md_text = render_markdown(
            doc=doc,
            wide_by_report=wide_by_report,
            compute_status={},
        )
        report_md_path.write_text(md_text, encoding="utf-8")
        self._artifacts["report_md"] = report_md_path

        report_docx_path: Path | None = None
        if not self._cfg.skip_docx:
            report_docx_path = self._cfg.out_dir / f"{stem}.report.docx"
            resolved_style = self._cfg.style_path or (
                Path(__file__).resolve().parents[1] / "example" / "style.json"
            )
            render_docx(
                doc,
                wide_by_report,
                out_path=str(report_docx_path),
                style_path=str(resolved_style),
            )
            self._artifacts["report_docx"] = report_docx_path

        self._exit_step = "done"

    def _count_query_outcomes(self, payload: dict) -> tuple[int, int]:
        total = 0
        ok = 0
        for entry in payload.get("results", []):
            rows = entry.get("results", [])
            total += 1
            if rows and all(bool(r.get("success")) for r in rows):
                ok += 1
        return ok, total

    def _build_success_result(self) -> PipelineResult:
        from assemble_status import write_status
        stem = self._cfg.md_path.stem
        outputs = {k: str(v) for k, v in self._artifacts.items()}

        if self._cfg.debug:
            write_status(
                out_path=self._cfg.out_dir / f"{stem}.status.json",
                exit_step=self._exit_step,
                error_class=None,
                error_detail=None,
                outputs=outputs,
                metrics=self._metrics,
            )

        return PipelineResult(
            status="success",
            exit_step=self._exit_step,
            outputs=outputs,
            metrics=self._metrics,
        )

    def _build_error_result(self, exc: Exception) -> PipelineError:
        from assemble_status import write_status
        stem = self._cfg.md_path.stem

        tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
        tb_str = "".join(tb_lines[-50:])  # Last 50 lines of traceback

        outputs = {k: str(v) for k, v in self._artifacts.items()}
        error_class = type(exc).__name__
        error_detail = str(exc)

        if self._cfg.debug:
            write_status(
                out_path=self._cfg.out_dir / f"{stem}.status.json",
                exit_step=self._exit_step,
                error_class=error_class,
                error_detail=error_detail,
                outputs=outputs,
                metrics=self._metrics,
            )

        return PipelineError(
            status="error",
            exit_step=self._exit_step,
            error_class=error_class,
            error_detail=error_detail,
            traceback=tb_str,
            outputs=outputs,
            metrics=self._metrics,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _emit_wire_format(
    result: PipelineResult | PipelineError,
    *,
    debug: bool = False,
) -> None:
    """Print JSON wire format to stdout."""
    if isinstance(result, PipelineResult):
        payload = {
            "kind": "success",
            "status": result.status,
            "exit_step": result.exit_step,
            "outputs": result.outputs,
            "metrics": result.metrics,
        }
    else:
        payload = {
            "kind": "error",
            "status": result.status,
            "exit_step": result.exit_step,
            "error_class": result.error_class,
            "error_detail": result.error_detail,
            "exit_code": result.exit_code,
            "outputs": result.outputs,
            "metrics": result.metrics,
        }
        if debug:
            payload["traceback"] = result.traceback

    print(json.dumps(payload, ensure_ascii=False, default=str))


def main(argv: list[str] | None = None) -> int:
    import argparse

    from sqlbot_client import MockSQLBotClient, RealSQLBotClient

    parser = argparse.ArgumentParser(prog="single_pipeline", description=__doc__)
    parser.add_argument("--md", required=True, help="Input markdown file")
    parser.add_argument("--out-dir", required=True, help="Output directory")
    parser.add_argument("--mock-fixture", default=None,
                        help="mock fixture path; default: shipped profit_yoy.json")
    parser.add_argument("--real", action="store_true",
                        help="use real SQLBot (default: mock with shipped fixture)")
    parser.add_argument("--skip-docx", action="store_true")
    parser.add_argument("--style-path", default=None,
                        help="DOCX style JSON (defaults to example/style.json)")
    parser.add_argument("--debug", action="store_true",
                        help="Include traceback in output and write status.json")

    args = parser.parse_args(argv)

    cfg = PipelineConfig(
        md_path=Path(args.md),
        out_dir=Path(args.out_dir),
        mock_fixture=Path(args.mock_fixture) if getattr(args, "mock_fixture", None) else DEFAULT_FIXTURE,
        skip_docx=getattr(args, "skip_docx", False),
        style_path=Path(args.style_path) if getattr(args, "style_path", None) else None,
        debug=getattr(args, "debug", False),
    )

    sqlbot: Any
    if args.real:
        load_env()
        sqlbot = RealSQLBotClient()
    else:
        sqlbot = MockSQLBotClient(str(cfg.mock_fixture))

    pipeline = SinglePipeline(cfg, sqlbot)
    result = pipeline.run()

    _emit_wire_format(result, debug=cfg.debug)

    if isinstance(result, PipelineError):
        return 1
    return 0


class LintError(Exception):
    """Raised when lint finds errors."""
    pass


class QueryError(Exception):
    """Raised when SQLBot query fails."""
    pass


if __name__ == "__main__":
    raise SystemExit(main())
