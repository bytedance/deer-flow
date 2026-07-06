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

        return Phase1Result(
            parsed=parsed.to_dict(),
            wide=[],
            ir=[],
            description_prompts=[],
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
        raise NotImplementedError
