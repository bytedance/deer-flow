"""chatbi-report Orchestrator — Phase 1 / Phase 2 in-process pipeline.

Replaces 9-step CLI pattern. See
docx/superpowers/specs/2026-07-06-chatbi-report-rewrite-design.md.
"""
from __future__ import annotations

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
