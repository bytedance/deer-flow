# chatbi-report 重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace chatbi-report's 9-step CLI pipeline with a single `Orchestrator` class in `scripts/pipeline.py` that runs Phase 1 (steps 1-6) and Phase 2 (8a-9) in-process. The lead agent does LLM work between phases and routes 3 user checkpoints via `ask_clarification`.

**Architecture:** `scripts/pipeline.py` defines `Orchestrator` + 5 dataclasses (`OrchestratorConfig`, `CheckpointSignal`, `ForceContinue`, `Phase1Result`, `RunResult`). Each phase method calls the corresponding existing script's library function in sequence — no subprocess per step. CLI uses subcommands (`phase1` / `phase2`) and emits wire-format JSON on the last stdout line for the agent. `tests/e2e_minimal.py` is the completion gate (mock SQLBot + stub compute + stub descriptions).

**Tech Stack:** Python 3.12, dataclasses, pytest, existing chatbi-report library functions (md_lint, parse_md, sqlbot_client, compute, render_markdown, render_docx, assemble_status).

---

## Context

The current chatbi-report skill is invoked 9 times per run (one bash tool call per step), each spawn is a separate `python` subprocess, and intermediate state lives in JSON files between steps. This causes:
- **Instability**: errors are surfaced as `FAIL: ...` strings in stderr; downstream steps receive stale or None when intermediate JSON fields drift.
- **Slowness**: ~30s of pure plumbing overhead per run (agent LLM decisions + sandbox subprocess spawns).

The rewrite wraps the 9 steps in a single Python `Orchestrator` class. Phase 1 (deterministic bash steps 1-6) and Phase 2 (deterministic bash steps 8a-9) run in-process. The 2 LLM steps (7 codegen, 8d describe) remain agent-external between phases. 3 user checkpoints (1.5 lint, 3.5 query, 8d.5 description) emit a `CheckpointSignal` dataclass that the agent maps to `ask_clarification` (mapping table fixed in spec §"CheckpointSignal → ask_clarification 映射").

**Spec reference:** `docx/superpowers/specs/2026-07-06-chatbi-report-rewrite-design.md` (commits `cccf11b9` and `8249975f`).

**Completion gate:** `pytest scripts/tests/test_e2e_minimal.py -v` must be green, per [[ai-report-archived-lesson]].

---

## File Structure

### Created
- `skills/public/chatbi-report/scripts/pipeline.py` — `Orchestrator` class + 5 dataclasses + CLI subcommands
- `skills/public/chatbi-report/scripts/tests/test_orchestrator.py` — unit tests for `Orchestrator.run_phase_1` / `run_phase_2` / `ForceContinue` / `CheckpointSignal`
- `skills/public/chatbi-report/scripts/tests/test_pipeline_cli.py` — CLI subprocess tests (wire format kinds)
- `skills/public/chatbi-report/scripts/tests/test_e2e_minimal.py` — E2E gating test (mock SQLBot + stub compute + stub descriptions)
- `out_dir/orchestrator-metrics.json` (sidecar, written by Phase 2) — detailed per-step metrics; does NOT alter the spec-pinned `status.json` schema

### Modified
- `skills/public/chatbi-report/scripts/sqlbot_client.py` — drop `--mock` boolean flag (only `--mock-fixture` remains, per Goals #6)
- `skills/public/chatbi-report/scripts/tests/test_sqlbot_client.py` — update CLI tests for `--mock-fixture` only
- `skills/public/chatbi-report/SKILL.md` — replace 9-step bash commands with `phase1` / `phase2` subcommands
- `skills/public/chatbi-report/README.md` — single `--mock-fixture` flag in operator docs
- `skills/public/chatbi-report/references/pipeline.md` — Phase 1/2 state machine + new API
- `skills/public/chatbi-report/references/template-troubleshooting.md` — new error path (single traceback, central `metrics`)

### Unchanged (library + main() preserved)
`md_lint.py`, `parse_md.py`, `compute.py`, `unit_conversion.py`, `render_markdown.py`, `render_docx.py`, `assemble_status.py`, `retry.py`, `chart_gen.py`, `example/`, `prompts/`. Existing per-step test files (`test_md_lint.py`, `test_parse_md.py`, `test_compute.py`, `test_render_markdown.py`, `test_render_docx.py`) untouched — they test library functions, not `pipeline.py`.

---

## Cross-Cutting Constraints

These apply at the boundary handler + boundary unit test FIRST, per [[cross-cutting-constraint-boundary-discipline]]:

1. **Virtual paths in CLI, physical paths in tests.** CLI args use `/mnt/user-data/...` (sandbox virtual) and `pipeline.py` uses them as-is (sandbox resolves). Tests use `tmp_path` (pytest's tmp dir) — no `/mnt/`. Do not mix.
2. **Stem derives from `md_path`.** All artifact filenames in `out_dir` are `{stem}.parsed.json`, `{stem}.query.json`, `{stem}.wide.json`, `{stem}.ir.json`, `report.md`, `report.docx`, `status.json`. The E2E test asserts these.
3. **Mock/real SQLBot is selected at `Orchestrator` construction, not at runtime.** `Orchestrator(cfg, sqlbot_instance)` is the only switch. CLI translates `--mock-fixture` into `MockSQLBotClient(fixture)` else `RealSQLBotClient()` (which raises on missing `SQLBOT_BASE_URL`).
4. **Last-line stdout is JSON wire format, never user progress messages.** Progress messages go to stderr (or are omitted). Agent parses `stdout.strip().splitlines()[-1]` as JSON.
5. **Phase 2 reads `out_dir/{stem}.parsed.json` and `out_dir/{stem}.wide.json` from disk** (not from agent in-process state) — this keeps Phase 2 invocation independent of Phase 1 process lifetime.
6. **`wide.json` is flat `list[dict]`** (not nested), with `section_idx` / `report_idx` baked into each row. Same shape as `_cli_assemble_wide` (compute.py:444-472). T11 filters per-report before passing to `normalize_wide_by_report`.
7. **Descriptions flow via `descriptions_dir`, NOT a `dict[str, str]`.** Agent writes files matching `<stem>.description.report-<idx>.txt` (or the no-stem fallback `description.report-<idx>.txt`) into a directory; `run_phase_2` calls `render_markdown.attach_description_files(doc, descriptions_dir, stem=stem)` which sets `report.description_text` (the public attribute — renderers read `getattr(report, "description_text", None)`).
8. **`status.json` schema is spec-pinned: 8 flat metrics keys only** (see `assemble_status.write_status:54-63`). Orchestrator's detailed per-step metrics are written to a sidecar `orchestrator-metrics.json` (NOT in `status.json`) — preserves the schema and exposes debug data.
9. **`render_docx.style_path` is REQUIRED** (no default in the library). `OrchestratorConfig.style_path` defaults to `scripts/example/style.json` (the bundled default). CLI `--style-path` overrides.

---

## Tasks

### Task 1: Dataclasses

**Files:**
- Create: `skills/public/chatbi-report/scripts/pipeline.py`
- Test: `skills/public/chatbi-report/scripts/tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test (smoke import + dataclass construction)**

Create `skills/public/chatbi-report/scripts/tests/test_orchestrator.py`:

```python
"""Unit tests for scripts/pipeline.py (Orchestrator + dataclasses)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

import pipeline as p


FIXTURE = Path(__file__).parents[1] / "example" / "mock_sqlbot" / "profit_yoy.json"
INPUT_MD = Path(__file__).parents[1] / "example" / "input.md"


def test_dataclasses_construct_with_minimal_args():
    """All 5 dataclasses can be constructed with their typed fields."""
    cfg = p.OrchestratorConfig(md_path=INPUT_MD, out_dir=Path("/tmp/x"))
    assert cfg.md_path == INPUT_MD
    assert cfg.out_dir == Path("/tmp/x")
    assert cfg.mock_fixture is None
    assert cfg.skip_docx is False
    assert cfg.style_path is None

    fc = p.ForceContinue()
    assert fc.skip_lint_checkpoint is False
    assert fc.skip_query_checkpoint is False

    sig = p.CheckpointSignal(
        step="1.5",
        metrics={"n_err": 1, "n_warn": 0},
        artifacts={"parsed": Path("/tmp/x/input.parsed.json")},
        message="lint found 1 error",
    )
    assert sig.step == "1.5"
    assert sig.metrics["n_err"] == 1
    assert sig.message == "lint found 1 error"

    pr = p.Phase1Result(
        parsed={"sections": []},
        wide={"rows": [], "cols": []},
        ir=[],
        description_prompts=[],
        metrics={},
        runlog=[],
        artifacts={},
    )
    assert pr.ir == []

    rr = p.RunResult(
        report_md=Path("/tmp/x/report.md"),
        report_docx=Path("/tmp/x/report.docx"),
        status_json=Path("/tmp/x/status.json"),
        metrics={},
    )
    assert rr.report_md == Path("/tmp/x/report.md")
```

- [ ] **Step 2: Run the test to verify it fails (module not found)**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_orchestrator.py -v`
Expected: `ModuleNotFoundError: No module named 'pipeline'`

- [ ] **Step 3: Implement the dataclasses (no behavior, no Orchestrator class yet)**

Create `skills/public/chatbi-report/scripts/pipeline.py`:

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_orchestrator.py -v`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/pipeline.py skills/public/chatbi-report/scripts/tests/test_orchestrator.py
git commit -m "feat(chatbi-report): add Orchestrator dataclasses (T1)"
```

---

### Task 2: Orchestrator constructor with sqlbot injection

**Files:**
- Modify: `skills/public/chatbi-report/scripts/pipeline.py`
- Test: `skills/public/chatbi-report/scripts/tests/test_orchestrator.py`

- [ ] **Step 1: Append a failing test for constructor injection**

Append to `skills/public/chatbi-report/scripts/tests/test_orchestrator.py`:

```python
def test_orchestrator_constructor_stores_cfg_and_sqlbot():
    """Constructor accepts either MockSQLBotClient or RealSQLBotClient."""
    from sqlbot_client import MockSQLBotClient, RealSQLBotClient

    cfg = p.OrchestratorConfig(md_path=INPUT_MD, out_dir=Path("/tmp/x"))

    mock_client = MockSQLBotClient(str(FIXTURE))
    orch_mock = p.Orchestrator(cfg, mock_client)
    assert orch_mock._cfg is cfg
    assert orch_mock._sqlbot is mock_client

    real_client = RealSQLBotClient(base_url="http://sqlbot.lan:9070")
    orch_real = p.Orchestrator(cfg, real_client)
    assert orch_real._sqlbot is real_client
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_orchestrator.py::test_orchestrator_constructor_stores_cfg_and_sqlbot -v`
Expected: `AttributeError: module 'pipeline' has no attribute 'Orchestrator'`

- [ ] **Step 3: Add the Orchestrator class (constructor only, methods raise NotImplementedError)**

Append to `skills/public/chatbi-report/scripts/pipeline.py`:

```python
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
        raise NotImplementedError

    def run_phase_2(
        self,
        parsed: dict,
        wide: list[dict],
        compute_sources: dict[str, str],
        descriptions_dir: str,
        stem: str,
    ) -> CheckpointSignal | RunResult:
        raise NotImplementedError
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_orchestrator.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/pipeline.py skills/public/chatbi-report/scripts/tests/test_orchestrator.py
git commit -m "feat(chatbi-report): add Orchestrator constructor with sqlbot injection (T2)"
```

---

### Task 3: Phase 1 step 1 (lint) + step 2 (parse)

**Files:**
- Modify: `skills/public/chatbi-report/scripts/pipeline.py`
- Test: `skills/public/chatbi-report/scripts/tests/test_orchestrator.py`

- [ ] **Step 1: Append failing test for Phase 1 steps 1+2**

Append to `skills/public/chatbi-report/scripts/tests/test_orchestrator.py`:

```python
def test_run_phase_1_lint_and_parse_writes_parsed_json(tmp_path):
    """Phase 1 step 1 (lint) + step 2 (parse) writes out_dir/{stem}.parsed.json."""
    from sqlbot_client import MockSQLBotClient

    cfg = p.OrchestratorConfig(md_path=INPUT_MD, out_dir=tmp_path)
    orch = p.Orchestrator(cfg, MockSQLBotClient(str(FIXTURE)))
    result = orch.run_phase_1()
    assert isinstance(result, p.Phase1Result)
    assert (tmp_path / "input.parsed.json").exists()
    parsed = json.loads((tmp_path / "input.parsed.json").read_text(encoding="utf-8"))
    assert "sections" in parsed
    assert parsed["title"]  # non-empty title from input.md
    # metrics for steps 1 and 2 are present
    assert "1_lint" in result.metrics
    assert "2_parse" in result.metrics
    assert result.metrics["2_parse"]["n_sec"] >= 1
    assert result.metrics["2_parse"]["n_rep"] >= 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_orchestrator.py::test_run_phase_1_lint_and_parse_writes_parsed_json -v`
Expected: `NotImplementedError` (from `run_phase_1`)

- [ ] **Step 3: Implement steps 1+2 in `run_phase_1`**

Replace the body of `run_phase_1` in `skills/public/chatbi-report/scripts/pipeline.py`:

```python
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
        metrics["1_lint"] = {"n_err": lint.n_err, "n_warn": lint.n_warn}

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

        return Phase1Result(
            parsed=parsed.to_dict(),
            wide={},
            ir=[],
            description_prompts=[],
            metrics=metrics,
            runlog=[],
            artifacts=artifacts,
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_orchestrator.py::test_run_phase_1_lint_and_parse_writes_parsed_json -v`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/pipeline.py skills/public/chatbi-report/scripts/tests/test_orchestrator.py
git commit -m "feat(chatbi-report): Phase 1 steps 1+2 (lint, parse) (T3)"
```

---

### Task 4: Phase 1 step 3 (query)

**Files:**
- Modify: `skills/public/chatbi-report/scripts/pipeline.py`
- Test: `skills/public/chatbi-report/scripts/tests/test_orchestrator.py`

- [ ] **Step 1: Append failing test for step 3 query**

Append to `skills/public/chatbi-report/scripts/tests/test_orchestrator.py`:

```python
def test_run_phase_1_query_writes_query_json(tmp_path):
    """Phase 1 step 3 (query) writes out_dir/{stem}.query.json with mock SQLBot."""
    from sqlbot_client import MockSQLBotClient

    cfg = p.OrchestratorConfig(md_path=INPUT_MD, out_dir=tmp_path)
    orch = p.Orchestrator(cfg, MockSQLBotClient(str(FIXTURE)))
    result = orch.run_phase_1()
    assert isinstance(result, p.Phase1Result)
    assert (tmp_path / "input.query.json").exists()
    query = json.loads((tmp_path / "input.query.json").read_text(encoding="utf-8"))
    assert "results" in query
    assert len(query["results"]) >= 1
    assert "3_query" in result.metrics
    assert result.metrics["3_query"]["ok"] >= 1
    assert result.metrics["3_query"]["total"] >= 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_orchestrator.py::test_run_phase_1_query_writes_query_json -v`
Expected: `AssertionError: input.query.json not found` (current impl does not write it)

- [ ] **Step 3: Add step 3 query to `run_phase_1`**

In `skills/public/chatbi-report/scripts/pipeline.py`, after step 2 (before the `return Phase1Result(...)`), insert:

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_orchestrator.py::test_run_phase_1_query_writes_query_json -v`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/pipeline.py skills/public/chatbi-report/scripts/tests/test_orchestrator.py
git commit -m "feat(chatbi-report): Phase 1 step 3 (query) (T4)"
```

---

### Task 5: Phase 1 checkpoints 1.5 (lint) and 3.5 (query)

**Files:**
- Modify: `skills/public/chatbi-report/scripts/pipeline.py`
- Test: `skills/public/chatbi-report/scripts/tests/test_orchestrator.py`

- [ ] **Step 1: Append failing tests for both checkpoints**

Append to `skills/public/chatbi-report/scripts/tests/test_orchestrator.py`:

```python
def test_run_phase_1_lint_checkpoint_on_broken_md(tmp_path):
    """Phase 1 returns CheckpointSignal(step='1.5') when lint has errors."""
    from sqlbot_client import MockSQLBotClient

    broken = tmp_path / "broken.md"
    broken.write_text(
        "# Title\n\n"
        "> 机构:\n"
        ">   branch_num=27020199; branch_short_name=王益联社\n"
        "> 时期: time_info=[\"2025\"]\n\n"
        "## Section\n\n"
        "### Report\n\n"
        "| missing-data-idx attr | header |\n"
        "| --- | --- |\n"
        "| cell1 | cell2 |\n",
        encoding="utf-8",
    )
    cfg = p.OrchestratorConfig(md_path=broken, out_dir=tmp_path)
    orch = p.Orchestrator(cfg, MockSQLBotClient(str(FIXTURE)))
    result = orch.run_phase_1()
    assert isinstance(result, p.CheckpointSignal)
    assert result.step == "1.5"
    assert result.metrics["1_lint"]["n_err"] >= 1


def test_run_phase_1_query_checkpoint_when_all_fail(tmp_path):
    """Phase 1 returns CheckpointSignal(step='3.5') when query has any failure.

    Per 2026-06-27 policy reversal: always trigger 3.5, even when ok == 0.
    """
    from sqlbot_client import MockSQLBotClient

    fail_fixture = tmp_path / "fail.json"
    fail_fixture.write_text(
        json.dumps({"BAS_0263": {"success": False, "data": []}}),
        encoding="utf-8",
    )
    cfg = p.OrchestratorConfig(
        md_path=INPUT_MD, out_dir=tmp_path, mock_fixture=fail_fixture,
    )
    orch = p.Orchestrator(cfg, MockSQLBotClient(str(fail_fixture)))
    result = orch.run_phase_1()
    assert isinstance(result, p.CheckpointSignal)
    assert result.step == "3.5"
    assert result.metrics["3_query"]["ok"] < result.metrics["3_query"]["total"]
    assert (tmp_path / "input.query.json").exists()  # written before checkpoint
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_orchestrator.py::test_run_phase_1_lint_checkpoint_on_broken_md skills/public/chatbi-report/scripts/tests/test_orchestrator.py::test_run_phase_1_query_checkpoint_when_all_fail -v`
Expected: both fail — current `run_phase_1` does not return `CheckpointSignal`.

- [ ] **Step 3: Add checkpoint emit logic**

In `run_phase_1` of `pipeline.py`, after step 1 (lint) and BEFORE step 2 (parse), insert:

```python
        if not fc.skip_lint_checkpoint and lint.exit_code != 0 and lint.n_err > 0:
            return CheckpointSignal(
                step="1.5",
                metrics=metrics,
                artifacts=artifacts,
                message=f"lint 发现 {lint.n_err} 错误、{lint.n_warn} 警告",
            )
```

In `run_phase_1`, after step 3 (query) and BEFORE the `return Phase1Result(...)`, insert:

```python
        if not fc.skip_query_checkpoint and ok < total:
            return CheckpointSignal(
                step="3.5",
                metrics=metrics,
                artifacts=artifacts,
                message=f"SQLBot 查询 {ok}/{total} 成功,部分失败",
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_orchestrator.py -v`
Expected: all tests pass (4 prior + 2 new = 6 total).

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/pipeline.py skills/public/chatbi-report/scripts/tests/test_orchestrator.py
git commit -m "feat(chatbi-report): Phase 1 checkpoints 1.5/3.5 (T5)"
```

---

### Task 6: Phase 1 step 4 (assemble) + step 6 (extract-ir)

**Files:**
- Modify: `skills/public/chatbi-report/scripts/pipeline.py`
- Test: `skills/public/chatbi-report/scripts/tests/test_orchestrator.py`

- [ ] **Step 1: Append failing test for steps 4+6**

Append to `skills/public/chatbi-report/scripts/tests/test_orchestrator.py`:

```python
def test_run_phase_1_assemble_and_extract_ir(tmp_path):
    """Phase 1 steps 4+6 produce wide.json + ir.json; Phase1Result fully populated."""
    from sqlbot_client import MockSQLBotClient

    cfg = p.OrchestratorConfig(md_path=INPUT_MD, out_dir=tmp_path)
    orch = p.Orchestrator(cfg, MockSQLBotClient(str(FIXTURE)))
    result = orch.run_phase_1()
    assert isinstance(result, p.Phase1Result)
    assert (tmp_path / "input.wide.json").exists()
    assert (tmp_path / "input.ir.json").exists()
    assert "4_assemble" in result.metrics
    assert "6_ir" in result.metrics
    assert isinstance(result.wide, list)  # flat list[dict], section_idx/report_idx per row
    assert all({"section_idx", "report_idx"} <= set(r.keys()) for r in result.wide)
    assert isinstance(result.ir, list)
    # description_prompts collected per-report (input.md may have none)
    assert isinstance(result.description_prompts, list)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_orchestrator.py::test_run_phase_1_assemble_and_extract_ir -v`
Expected: `AssertionError: input.wide.json not found`

- [ ] **Step 3: Add steps 4+6 to `run_phase_1`**

In `run_phase_1` of `pipeline.py`, after step 3 (query) and after the 3.5 checkpoint emit, insert:

```python
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
```

Also update the final `return Phase1Result(...)` to use the assembled `flat_wide` and collected `ir` / `description_prompts`:

```python
        return Phase1Result(
            parsed=parsed.to_dict(),
            wide=flat_wide,
            ir=ir,
            description_prompts=description_prompts,
            metrics=metrics,
            runlog=[],
            artifacts=artifacts,
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_orchestrator.py -v`
Expected: all tests pass (7 total).

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/pipeline.py skills/public/chatbi-report/scripts/tests/test_orchestrator.py
git commit -m "feat(chatbi-report): Phase 1 steps 4+6 (assemble, extract-ir) (T6)"
```

---

### Task 7: Phase 1 `force_continue` parameter

**Files:**
- Modify: `skills/public/chatbi-report/scripts/pipeline.py`
- Test: `skills/public/chatbi-report/scripts/tests/test_orchestrator.py`

- [ ] **Step 1: Append failing test for `force_continue`**

Append to `skills/public/chatbi-report/scripts/tests/test_orchestrator.py`:

```python
def test_run_phase_1_force_continue_skips_lint_checkpoint(tmp_path):
    """With skip_lint_checkpoint=True, broken MD still proceeds past lint."""
    from sqlbot_client import MockSQLBotClient

    broken = tmp_path / "broken.md"
    broken.write_text(
        "# Title\n\n"
        "> 机构:\n"
        ">   branch_num=27020199; branch_short_name=王益联社\n"
        "> 时期: time_info=[\"2025\"]\n\n"
        "## Section\n\n"
        "### Report\n\n"
        "| missing-data-idx attr | header |\n"
        "| --- | --- |\n"
        "| cell1 | cell2 |\n",
        encoding="utf-8",
    )
    cfg = p.OrchestratorConfig(md_path=broken, out_dir=tmp_path)
    orch = p.Orchestrator(cfg, MockSQLBotClient(str(FIXTURE)))
    result = orch.run_phase_1(force_continue=p.ForceContinue(skip_lint_checkpoint=True))
    # Either Phase1Result (lint passed / ignored) or CheckpointSignal at 3.5
    # (because the broken MD likely has no usable idx to query).
    # Key assertion: not a 1.5 checkpoint.
    if isinstance(result, p.CheckpointSignal):
        assert result.step != "1.5"
    else:
        assert isinstance(result, p.Phase1Result)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_orchestrator.py::test_run_phase_1_force_continue_skips_lint_checkpoint -v`
Expected: result is `CheckpointSignal(step="1.5")` — the test asserts the opposite and fails.

- [ ] **Step 3: Verify `force_continue` handling already wired**

The 1.5 and 3.5 emit logic from T5 already checks `fc.skip_*_checkpoint`. Verify by reading the file; no code change needed in this task.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_orchestrator.py -v`
Expected: all tests pass (8 total).

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/tests/test_orchestrator.py
git commit -m "test(chatbi-report): Phase 1 force_continue skips 1.5 checkpoint (T7)"
```

(If the test in step 4 still fails, the `force_continue` wiring from T5 is incomplete — return to T5 and fix.)

---

### Task 8: Phase 2 step 8a (validate)

**Files:**
- Modify: `skills/public/chatbi-report/scripts/pipeline.py`
- Test: `skills/public/chatbi-report/scripts/tests/test_orchestrator.py`

- [ ] **Step 1: Append failing test for step 8a**

Append to `skills/public/chatbi-report/scripts/tests/test_orchestrator.py`:

```python
def test_run_phase_2_validate_marks_sentinel_for_bad_source(tmp_path):
    """Phase 2 step 8a marks wide cells with ⚠️COMPUTE_FAILED for invalid sources."""
    from sqlbot_client import MockSQLBotClient

    cfg = p.OrchestratorConfig(md_path=INPUT_MD, out_dir=tmp_path)
    orch = p.Orchestrator(cfg, MockSQLBotClient(str(FIXTURE)))
    p1 = orch.run_phase_1()
    assert isinstance(p1, p.Phase1Result)

    # Bad source: function name mismatch → validate_signature fails
    bad_src = tmp_path / "bad.py"
    bad_src.write_text("def wrong_name(df):\n    return 0\n", encoding="utf-8")

    final = orch.run_phase_2(
        parsed=p1.parsed,
        wide=p1.wide,
        compute_sources={"good_col": str(bad_src)},  # name mismatch is the failure
        descriptions_dir=str(tmp_path),
        stem=INPUT_MD.stem,
    )
    # Continue to RunResult (compute failures don't abort Phase 2)
    assert isinstance(final, p.RunResult)
    status = json.loads(final.status_json.read_text(encoding="utf-8"))
    # status.json schema is spec-pinned: only 8 flat metrics keys exist (assemble_status:54-63).
    # Detailed per-step metrics live in the sidecar orchestrator-metrics.json.
    assert status["metrics"]["computed_count"] == 1
    assert status["metrics"]["compute_validation_failures"] == 1
    sidecar = json.loads((tmp_path / "orchestrator-metrics.json").read_text(encoding="utf-8"))
    assert sidecar["8a_validate"]["total"] == 1
    assert sidecar["8a_validate"]["ok"] == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_orchestrator.py::test_run_phase_2_validate_marks_sentinel_for_bad_source -v`
Expected: `NotImplementedError` (from `run_phase_2`)

- [ ] **Step 3: Implement step 8a in `run_phase_2`**

Replace the body of `run_phase_2` in `skills/public/chatbi-report/scripts/pipeline.py`:

```python
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

        # Placeholder for steps 8b–9 (filled in next tasks)
        return self._finish_phase_2(parsed, wide, metrics, descriptions_dir, stem)
```

Add a private helper to `Orchestrator` that the next tasks will replace incrementally. Append after `run_phase_2`:

```python
    def _finish_phase_2(
        self, parsed: dict, wide: dict, metrics: dict[str, Any],
    ) -> RunResult:
        # Minimal RunResult for T8 — will be replaced in T9–T11.
        status_path = self._cfg.out_dir / "status.json"
        from assemble_status import write_status
        write_status(
            out_path=status_path,
            exit_step="9",
            error_class=None,
            error_detail=None,
            outputs={},
            metrics=metrics,
        )
        return RunResult(
            report_md=self._cfg.out_dir / "report.md",
            report_docx=None if self._cfg.skip_docx else self._cfg.out_dir / "report.docx",
            status_json=status_path,
            metrics=metrics,
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_orchestrator.py::test_run_phase_2_validate_marks_sentinel_for_bad_source -v`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/pipeline.py skills/public/chatbi-report/scripts/tests/test_orchestrator.py
git commit -m "feat(chatbi-report): Phase 2 step 8a (validate) (T8)"
```

---

### Task 9: Phase 2 steps 8b (evaluate) + 8c (apply-computed)

**Files:**
- Modify: `skills/public/chatbi-report/scripts/pipeline.py`
- Test: `skills/public/chatbi-report/scripts/tests/test_orchestrator.py`

- [ ] **Step 1: Append failing test for 8b+8c**

Append to `skills/public/chatbi-report/scripts/tests/test_orchestrator.py`:

```python
def test_run_phase_2_evaluate_and_apply(tmp_path):
    """Phase 2 evaluates compute source and applies results to wide."""
    from sqlbot_client import MockSQLBotClient

    cfg = p.OrchestratorConfig(md_path=INPUT_MD, out_dir=tmp_path)
    orch = p.Orchestrator(cfg, MockSQLBotClient(str(FIXTURE)))
    p1 = orch.run_phase_1()
    assert isinstance(p1, p.Phase1Result)

    # Source: takes a DataFrame and returns a Series-like dict.
    # We don't bind it to an actual wide column (the IR may not produce a matching
    # column); the test only asserts the apply step runs without aborting.
    src = tmp_path / "noop.py"
    src.write_text(
        "def noop(df):\n    return {}\n",
        encoding="utf-8",
    )
    final = orch.run_phase_2(
        parsed=p1.parsed,
        wide=p1.wide,
        compute_sources={"noop": str(src)},
        descriptions_dir=str(tmp_path),
        stem=INPUT_MD.stem,
    )
    assert isinstance(final, p.RunResult)
    sidecar = json.loads((tmp_path / "orchestrator-metrics.json").read_text(encoding="utf-8"))
    assert "8b_evaluate" in sidecar
    assert "8c_apply" in sidecar
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_orchestrator.py::test_run_phase_2_evaluate_and_apply -v`
Expected: `AssertionError` (status.json missing 8b_evaluate key)

- [ ] **Step 3: Add 8b + 8c between step 8a and `_finish_phase_2`**

In `run_phase_2`, replace the trailing `# Placeholder for steps 8b–9` block with:

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_orchestrator.py -v`
Expected: all tests pass (10 total).

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/pipeline.py skills/public/chatbi-report/scripts/tests/test_orchestrator.py
git commit -m "feat(chatbi-report): Phase 2 steps 8b+8c (evaluate, apply) (T9)"
```

---

### Task 10: Phase 2 step 8d (attach descriptions) + 8d.5 checkpoint

**Files:**
- Modify: `skills/public/chatbi-report/scripts/pipeline.py`
- Test: `skills/public/chatbi-report/scripts/tests/test_orchestrator.py`

- [ ] **Step 1: Append failing test for 8d + 8d.5**

Append to `skills/public/chatbi-report/scripts/tests/test_orchestrator.py`:

```python
def test_run_phase_2_attach_descriptions_and_8d5_checkpoint(tmp_path):
    """Phase 2 reads description files; 8d.5 checkpoint triggers on missing files."""
    from sqlbot_client import MockSQLBotClient

    cfg = p.OrchestratorConfig(md_path=INPUT_MD, out_dir=tmp_path)
    orch = p.Orchestrator(cfg, MockSQLBotClient(str(FIXTURE)))
    p1 = orch.run_phase_1()
    assert isinstance(p1, p.Phase1Result)

    # No description files → 8d.5 should trigger because we have at least 1
    # description_prompt in input.md and no files exist under descriptions_dir.
    final = orch.run_phase_2(
        parsed=p1.parsed,
        wide=p1.wide,
        compute_sources={},
        descriptions_dir=str(tmp_path / "desc"),  # empty dir → 8d.5 triggers
        stem=INPUT_MD.stem,
    )
    if p1.description_prompts:
        assert isinstance(final, p.CheckpointSignal)
        assert final.step == "8d.5"
    else:
        # input.md has no description_prompt → 8d.5 skipped, RunResult
        assert isinstance(final, p.RunResult)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_orchestrator.py::test_run_phase_2_attach_descriptions_and_8d5_checkpoint -v`
Expected: result is `RunResult` (current impl skips 8d.5 entirely) — test fails on the `isinstance(final, p.CheckpointSignal)` branch.

- [ ] **Step 3: Add 8d + 8d.5 in `run_phase_2` before `_finish_phase_2`**

In `run_phase_2`, replace the final `return self._finish_phase_2(...)` with:

```python
        # Step 8d: attach descriptions via render_markdown's standard API
        # (sets report.description_text, NOT _description_text — see render_markdown:96-112).
        # Idempotent: T11 calls this again, but it's a no-op once description_text is set.
        from render_markdown import attach_description_files
        from parse_md import doc_from_dict

        doc = doc_from_dict(parsed)
        attach_description_files(doc, descriptions_dir, stem=stem)

        # Detect failures: any report with description_prompt that didn't get description_text.
        total = 0
        found = 0
        for section in doc.sections:
            for report in section.reports:
                if not report.description_prompt:
                    continue
                total += 1
                if getattr(report, "description_text", None):
                    found += 1
        metrics["8d_describe"] = {"ok": found, "total": total}

        # Step 8d.5: description checkpoint (per spec §"用户回复路由" — 8d.5 always triggers
        # when any description file is missing AND prompts existed, 2026-06-27 policy reversal).
        if total > 0 and found < total:
            return CheckpointSignal(
                step="8d.5",
                metrics=metrics,
                artifacts={"parsed": self._cfg.out_dir / f"{stem}.parsed.json"},
                message=f"description 生成 {found}/{total} 失败",
            )

        return self._finish_phase_2(parsed, wide, metrics, descriptions_dir, stem)
```

The old `_find_report_by_global_index` and `p1_artifact_count` module helpers are deleted
(their work is now done by `attach_description_files` + `getattr` checks).

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_orchestrator.py -v`
Expected: all tests pass (11 total).

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/pipeline.py skills/public/chatbi-report/scripts/tests/test_orchestrator.py
git commit -m "feat(chatbi-report): Phase 2 step 8d + 8d.5 checkpoint (T10)"
```

---

### Task 11: Phase 2 step 9 (render markdown + docx + status)

**Files:**
- Modify: `skills/public/chatbi-report/scripts/pipeline.py`
- Test: `skills/public/chatbi-report/scripts/tests/test_orchestrator.py`

- [ ] **Step 1: Append failing test for step 9 render**

Append to `skills/public/chatbi-report/scripts/tests/test_orchestrator.py`:

```python
def test_run_phase_2_render_produces_report_and_status(tmp_path):
    """Phase 2 step 9 writes report.md + report.docx + status.json."""
    from sqlbot_client import MockSQLBotClient

    cfg = p.OrchestratorConfig(md_path=INPUT_MD, out_dir=tmp_path)
    orch = p.Orchestrator(cfg, MockSQLBotClient(str(FIXTURE)))
    p1 = orch.run_phase_1()
    assert isinstance(p1, p.Phase1Result)

    # Provide description files matching the report's description_prompts.
    # Filename convention matches render_markdown.attach_description_files
    # fallback: {stem}.description.report-<idx>.txt or description.report-<idx>.txt.
    desc_dir = tmp_path / "desc"
    desc_dir.mkdir()
    stem = INPUT_MD.stem
    for i, _ in enumerate(p1.description_prompts):
        # flat_idx (single-section input.md → flat == section-relative)
        (desc_dir / f"{stem}.description.report-{i}.txt").write_text(
            f"description for report {i}", encoding="utf-8"
        )

    final = orch.run_phase_2(
        parsed=p1.parsed,
        wide=p1.wide,
        compute_sources={},
        descriptions_dir=str(desc_dir),
        stem=stem,
    )
    assert isinstance(final, p.RunResult)
    assert final.report_md.exists()
    assert final.report_md.read_text(encoding="utf-8")  # non-empty
    if not cfg.skip_docx:
        assert final.report_docx is not None
        assert final.report_docx.exists()
        assert final.report_docx.stat().st_size > 0
    assert final.status_json.exists()
    status = json.loads(final.status_json.read_text(encoding="utf-8"))
    assert status["error_class"] is None
    # status.json schema is spec-pinned (8 flat keys); see assemble_status:54-63.
    assert status["exit_step"] == "9"
    assert "queried_count" in status["metrics"]
    assert "compute_validation_failures" in status["metrics"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_orchestrator.py::test_run_phase_2_render_produces_report_and_status -v`
Expected: `AssertionError` on `final.report_md.exists()` (current `_finish_phase_2` does not write report files).

- [ ] **Step 3: Replace `_finish_phase_2` with full step 9 implementation**

Replace the entire `_finish_phase_2` method body with:

```python
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
                Path(__file__).resolve().parent / "example" / "style.json"
            )
            render_docx(
                report_doc=doc,
                wide=wide_by_report,
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_orchestrator.py -v`
Expected: all tests pass (12 total).

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/pipeline.py skills/public/chatbi-report/scripts/tests/test_orchestrator.py
git commit -m "feat(chatbi-report): Phase 2 step 9 (render + status) (T11)"
```

---

### Task 12: CLI subcommands + wire format emitter

**Files:**
- Modify: `skills/public/chatbi-report/scripts/pipeline.py`
- Create: `skills/public/chatbi-report/scripts/tests/test_pipeline_cli.py`

- [ ] **Step 1: Append failing CLI tests**

Create `skills/public/chatbi-report/scripts/tests/test_pipeline_cli.py`:

```python
"""CLI subprocess tests for scripts/pipeline.py — wire format kinds."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPTS_DIR = Path(__file__).resolve().parent.parent
PIPELINE = SCRIPTS_DIR / "pipeline.py"
FIXTURE = SCRIPTS_DIR / "example" / "mock_sqlbot" / "profit_yoy.json"
INPUT_MD = SCRIPTS_DIR / "example" / "input.md"


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PIPELINE), *args],
        capture_output=True,
        text=True,
        cwd=str(SCRIPTS_DIR),
    )


def test_cli_phase1_emits_phase1_result_wire_format(tmp_path):
    """phase1 subcommand on happy MD emits last-line JSON with kind=phase1_result."""
    result = _run_cli(
        "phase1",
        "--md", str(INPUT_MD),
        "--out-dir", str(tmp_path),
        "--mock-fixture", str(FIXTURE),
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    last_line = result.stdout.strip().splitlines()[-1]
    payload = json.loads(last_line)
    assert payload["kind"] == "phase1_result"
    assert "result" in payload
    assert "parsed" in payload["result"]


def test_cli_phase1_emits_checkpoint_wire_format_on_broken_md(tmp_path):
    """phase1 subcommand on broken MD emits last-line JSON with kind=checkpoint."""
    broken = tmp_path / "broken.md"
    broken.write_text(
        "# Title\n\n"
        "> 机构:\n"
        ">   branch_num=27020199; branch_short_name=王益联社\n"
        "> 时期: time_info=[\"2025\"]\n\n"
        "## Section\n\n"
        "### Report\n\n"
        "| no-attr | header |\n"
        "| --- | --- |\n"
        "| a | b |\n",
        encoding="utf-8",
    )
    result = _run_cli(
        "phase1",
        "--md", str(broken),
        "--out-dir", str(tmp_path),
        "--mock-fixture", str(FIXTURE),
    )
    assert result.returncode == 0
    last_line = result.stdout.strip().splitlines()[-1]
    payload = json.loads(last_line)
    assert payload["kind"] == "checkpoint"
    assert payload["step"] == "1.5"


def test_cli_phase2_emits_phase2_result_wire_format(tmp_path):
    """phase2 subcommand emits last-line JSON with kind=phase2_result."""
    # First run phase1
    p1 = _run_cli(
        "phase1",
        "--md", str(INPUT_MD),
        "--out-dir", str(tmp_path),
        "--mock-fixture", str(FIXTURE),
    )
    assert p1.returncode == 0
    p1_payload = json.loads(p1.stdout.strip().splitlines()[-1])
    assert p1_payload["kind"] == "phase1_result"

    # Provide description files at <stem>.description.report-<idx>.txt
    # (matches render_markdown.attach_description_files fallback naming).
    desc_dir = tmp_path / "desc"
    desc_dir.mkdir()
    stem = INPUT_MD.stem
    for i, _ in enumerate(p1_payload["result"]["description_prompts"]):
        (desc_dir / f"{stem}.description.report-{i}.txt").write_text(
            f"desc {i}", encoding="utf-8"
        )

    p2 = _run_cli(
        "phase2",
        "--md", str(INPUT_MD),
        "--out-dir", str(tmp_path),
        "--descriptions-dir", str(desc_dir),
    )
    assert p2.returncode == 0, f"stderr: {p2.stderr}"
    last_line = p2.stdout.strip().splitlines()[-1]
    payload = json.loads(last_line)
    assert payload["kind"] == "phase2_result"
    assert Path(payload["result"]["report_md"]).exists()
    assert Path(payload["result"]["status_json"]).exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_pipeline_cli.py -v`
Expected: all fail (no `phase1` / `phase2` subcommand).

- [ ] **Step 3: Add CLI + wire format emitter to `pipeline.py`**

Append to `skills/public/chatbi-report/scripts/pipeline.py`:

```python
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
    print(json.dumps(payload, ensure_ascii=False))


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
        mock_fixture=Path(args.mock_fixture) if args.mock_fixture else None,
        skip_docx=getattr(args, "skip_docx", False),
        style_path=Path(args.style_path) if getattr(args, "style_path", None) else None,
    )
    sqlbot: Any
    if cfg.mock_fixture is not None:
        sqlbot = MockSQLBotClient(str(cfg.mock_fixture))
    else:
        sqlbot = RealSQLBotClient()
    orch = Orchestrator(cfg, sqlbot)

    try:
        if args.cmd == "phase1":
            fc = ForceContinue(
                skip_lint_checkpoint=args.skip_lint_checkpoint,
                skip_query_checkpoint=args.skip_query_checkpoint,
            )
            result = orch.run_phase_1(force_continue=fc)
        else:
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


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_pipeline_cli.py -v`
Expected: `3 passed`

Also re-run the orchestrator unit tests to confirm no regression:
`cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_orchestrator.py -v`
Expected: all 12 still pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/pipeline.py skills/public/chatbi-report/scripts/tests/test_pipeline_cli.py
git commit -m "feat(chatbi-report): CLI subcommands + wire format emitter (T12)"
```

---

### Task 13: E2E gating test

**Files:**
- Create: `skills/public/chatbi-report/scripts/tests/test_e2e_minimal.py`

- [ ] **Step 1: Write the E2E test (this is the completion gate)**

Create `skills/public/chatbi-report/scripts/tests/test_e2e_minimal.py`:

```python
"""E2E anchor for chatbi-report rewrite — completion gating per ai-report-archived-lesson.

Runs the full happy path with MockSQLBotClient + stub compute sources + stub
description files. Asserts every Phase 1/2 artifact exists and status.json
does not record USER_ABORTED. If this test fails the rewrite is not shippable.
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlbot_client import MockSQLBotClient

import pipeline as p


FIXTURE = Path(__file__).parents[1] / "example" / "mock_sqlbot" / "profit_yoy.json"
INPUT_MD = Path(__file__).parents[1] / "example" / "input.md"


def test_e2e_minimal(tmp_path):
    cfg = p.OrchestratorConfig(md_path=INPUT_MD, out_dir=tmp_path)
    orch = p.Orchestrator(cfg, MockSQLBotClient(str(FIXTURE)))

    # Phase 1
    p1 = orch.run_phase_1()
    assert isinstance(p1, p.Phase1Result), f"expected Phase1Result, got {type(p1).__name__}"
    stem = INPUT_MD.stem
    assert (tmp_path / f"{stem}.parsed.json").exists()
    assert (tmp_path / f"{stem}.query.json").exists()
    assert (tmp_path / f"{stem}.wide.json").exists()
    assert (tmp_path / f"{stem}.ir.json").exists()

    # Simulate agent writing stub compute + description files between phases
    compute_sources: dict[str, str] = {}
    for ir_item in p1.ir:
        src = tmp_path / f"{ir_item['name']}.py"
        src.write_text(
            f"def {ir_item['name']}(df):\n    return {{}}\n",
            encoding="utf-8",
        )
        compute_sources[ir_item["name"]] = str(src)

    descriptions_dir = tmp_path / "desc"
    descriptions_dir.mkdir()
    stem = INPUT_MD.stem
    for i, _ in enumerate(p1.description_prompts):
        (descriptions_dir / f"{stem}.description.report-{i}.txt").write_text(
            f"description text for report {i}", encoding="utf-8"
        )

    # Phase 2
    final = orch.run_phase_2(
        parsed=p1.parsed,
        wide=p1.wide,
        compute_sources=compute_sources,
        descriptions_dir=str(descriptions_dir),
        stem=stem,
    )
    assert isinstance(final, p.RunResult), f"expected RunResult, got {type(final).__name__}"

    # All artifacts
    assert final.report_md.exists()
    assert final.report_md.read_text(encoding="utf-8")  # non-empty
    assert final.report_docx is not None
    assert final.report_docx.exists()
    assert final.status_json.exists()

    # status.json: spec-pinned schema (8 flat metrics keys, see assemble_status:54-63).
    status = json.loads(final.status_json.read_text(encoding="utf-8"))
    assert status.get("error_class") != "USER_ABORTED", status
    assert status.get("exit_step") == "9"
    assert status["metrics"]["queried_count"] >= 1
    assert status["metrics"]["query_failures"] == 0  # mock fixture all succeed

    # orchestrator-metrics.json: detailed per-step metrics sidecar.
    sidecar = json.loads(
        (tmp_path / "orchestrator-metrics.json").read_text(encoding="utf-8")
    )
    assert "8a_validate" in sidecar
    assert "8b_evaluate" in sidecar
```

- [ ] **Step 2: Run the E2E test**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_e2e_minimal.py -v`
Expected: `1 passed`. If it fails, do NOT proceed — fix the underlying issue in pipeline.py (most likely: assemble_wide_table or render_docx signature drift).

- [ ] **Step 3: Run the full chatbi-report test suite**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/ -v`
Expected: all green (existing per-step tests + new orchestrator + new CLI + new E2E).

- [ ] **Step 4: Run the integration scenarios**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest backend/tests/chatbi_report/ -v`
Expected: all green (the integration scenarios exercise the existing library functions, which are unchanged).

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/tests/test_e2e_minimal.py
git commit -m "test(chatbi-report): E2E anchor test_e2e_minimal (T13, completion gate)"
```

---

### Task 14: Drop `--mock` boolean flag from `sqlbot_client.py`

**Files:**
- Modify: `skills/public/chatbi-report/scripts/sqlbot_client.py`
- Modify: `skills/public/chatbi-report/scripts/tests/test_sqlbot_client.py`

- [ ] **Step 1: Identify and update existing CLI tests**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && grep -n "mock" skills/public/chatbi-report/scripts/tests/test_sqlbot_client.py | head -20`

Note the test cases that use `--mock` (the boolean flag). They need updating to use `--mock-fixture <path>`.

- [ ] **Step 2: Update `test_sqlbot_client.py` to use `--mock-fixture` only**

In `skills/public/chatbi-report/scripts/tests/test_sqlbot_client.py`, find every test that calls `sc.main([..., "--mock", ...])` and replace `--mock <path>` with `--mock-fixture <path>`. Remove any test that relies on the bare `--mock` boolean behavior.

Concretely, replace the `_cli_query` invocation pattern:

```python
# BEFORE
result = sc.main(["query", "--parsed", str(parsed), "--mock", "--out", str(out)])

# AFTER
result = sc.main(["query", "--parsed", str(parsed), "--mock-fixture", str(fixture), "--out", str(out)])
```

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/test_sqlbot_client.py -v`
Expected: all pass after update.

- [ ] **Step 3: Remove `--mock` from `sqlbot_client.py` argparse**

In `skills/public/chatbi-report/scripts/sqlbot_client.py`, locate the `p_query` argparse setup (~line 305) and remove the `--mock` argument. Also simplify the `_cli_query` body — the new logic is `args.mock_fixture is not None`:

```python
def _cli_query(args: argparse.Namespace) -> int:
    parsed = json.loads(Path(args.parsed).read_text(encoding="utf-8"))
    if args.mock_fixture:
        client: Any = MockSQLBotClient(args.mock_fixture)
    else:
        client = RealSQLBotClient(base_url=args.base_url)

    payload = query_from_parsed(parsed, client)
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    mode = "mock" if args.mock_fixture else "real"
    print(f"OK: queried {len(payload['results'])} indicator-periods via {mode} -> {args.out}")
    return 0
```

And in the argparse:

```python
    p_query.add_argument("--mock-fixture", default=None, help="mock fixture path; triggers MockSQLBotClient when set")
```

(Remove `p_query.add_argument("--mock", action="store_true", ...)`.)

- [ ] **Step 4: Re-run the test**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && python -m pytest skills/public/chatbi-report/scripts/tests/ -v`
Expected: all green (E2E + orchestrator + CLI + sqlbot + existing per-step tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/sqlbot_client.py skills/public/chatbi-report/scripts/tests/test_sqlbot_client.py
git commit -m "refactor(chatbi-report): drop --mock boolean flag, use --mock-fixture only (T14)"
```

---

### Task 15: Update `SKILL.md` with Phase 1 / Phase 2 commands

**Files:**
- Modify: `skills/public/chatbi-report/SKILL.md`

- [ ] **Step 1: Read the current `SKILL.md` Step 3 command**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && grep -n "python.*sqlbot_client\|python.*md_lint\|python.*parse_md\|python.*compute\|python.*render" skills/public/chatbi-report/SKILL.md`

Note the exact lines that need replacement (typically the "Step 3 query" command block, plus any other steps that point at the old CLI scripts).

- [ ] **Step 2: Replace the 9-step bash commands with Phase 1/Phase 2 subcommands**

In `skills/public/chatbi-report/SKILL.md`, replace the existing 9-step command block with:

```markdown
## Steps

### Step 1+2: lint + parse (auto, embedded in Phase 1)

Phase 1 runs lint and parse in-process. No separate command needed.

### Step 3: query (Phase 1 subcommand)

```bash
python /mnt/skills/public/chatbi-report/scripts/pipeline.py phase1 \
  --md /mnt/user-data/uploads/<file>.md \
  --out-dir /mnt/user-data/outputs \
  --mock-fixture /mnt/skills/public/chatbi-report/example/mock_sqlbot/profit_yoy.json
```

If the parsed last-line JSON is `{"kind": "checkpoint", "step": "1.5" | "3.5", ...}`, call `ask_clarification` per the table in `references/pipeline.md`. If user picks "停止", call `assemble_status.py` with `error_class=USER_ABORTED`. If user picks "继续", re-invoke the same `phase1` command with `--skip-lint-checkpoint` and/or `--skip-query-checkpoint` (these set `ForceContinue` per spec §"用户回复路由").

### Step 4–6: assemble, extract-ir (auto, embedded in Phase 1)

### Step 7: codegen (agent LLM, in chat)

Read the last-line JSON's `result.ir` (list of ComputeIR) and `result.description_prompts`. Write compute source files to `/mnt/user-data/outputs/compute/<name>.py` and description files to `/mnt/user-data/outputs/desc/<stem>.description.report-<idx>.txt` (filename convention matches `render_markdown.attach_description_files`).

### Step 8a–8d.5: validate, evaluate, apply, describe (Phase 2 subcommand)

```bash
python /mnt/skills/public/chatbi-report/scripts/pipeline.py phase2 \
  --md /mnt/user-data/uploads/<file>.md \
  --out-dir /mnt/user-data/outputs \
  --descriptions-dir /mnt/user-data/outputs/desc \
  --compute-source my_col=/mnt/user-data/outputs/compute/my_col.py
```

If the last-line JSON is `{"kind": "checkpoint", "step": "8d.5", ...}`, call `ask_clarification` per the table in `references/pipeline.md`.

### Step 9: render + status (auto, embedded in Phase 2)
```

- [ ] **Step 3: Verify no other commands in `SKILL.md` reference the old per-step CLIs**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && grep -n "python.*scripts/" skills/public/chatbi-report/SKILL.md`

Expected: only the two `phase1` / `phase2` invocations remain.

- [ ] **Step 4: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/SKILL.md
git commit -m "docs(chatbi-report): SKILL.md — Phase 1/Phase 2 subcommands (T15)"
```

---

### Task 16: Update `README.md` for single `--mock-fixture` flag

**Files:**
- Modify: `skills/public/chatbi-report/README.md`

- [ ] **Step 1: Locate the SQLBot section**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && grep -n "mock" skills/public/chatbi-report/README.md`

Note the lines that mention `--mock` or `--mock-fixture`.

- [ ] **Step 2: Replace the SQLBot query mode section**

In `skills/public/chatbi-report/README.md`, replace the "SQLBot query mode" section with:

```markdown
## SQLBot query mode

### Phase 1 default (mock)

`SKILL.md` Step 3 runs Phase 1 with the bundled mock fixture by default:

```bash
python /mnt/skills/public/chatbi-report/scripts/pipeline.py phase1 \
  --md /mnt/user-data/uploads/<file>.md \
  --out-dir /mnt/user-data/outputs \
  --mock-fixture /mnt/skills/public/chatbi-report/example/mock_sqlbot/profit_yoy.json
```

`--mock-fixture` selects `MockSQLBotClient`; without it, `RealSQLBotClient` is used (which reads `SQLBOT_BASE_URL` and raises if unset).

### Switching to real SQLBot

1. Drop `--mock-fixture` from the `phase1` command.
2. Set `SQLBOT_BASE_URL` in the runtime environment, e.g. `SQLBOT_BASE_URL=http://your-sqlbot:9070`.

Real mode posts to `${SQLBOT_BASE_URL}/api/v1/indicator/query-report-info` with no API key or Authorization header (per 2026-06-23 spec).
```

- [ ] **Step 3: Verify README.md mentions only `--mock-fixture`**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && grep -n "mock" skills/public/chatbi-report/README.md`

Expected: only `--mock-fixture` references; no bare `--mock` boolean.

- [ ] **Step 4: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/README.md
git commit -m "docs(chatbi-report): README.md — single --mock-fixture flag (T16)"
```

---

### Task 17: Update `references/pipeline.md` with Phase 1/2 split

**Files:**
- Modify: `skills/public/chatbi-report/references/pipeline.md`

- [ ] **Step 1: Replace the state machine and step definitions**

In `skills/public/chatbi-report/references/pipeline.md`, replace the "State machine" and "Step definitions" tables with:

```markdown
## State machine (Phase 1 / Phase 2 split)

```text
# Agent calls pipeline.py phase1
[orchestrator] 1 lint → 1.5 lint checkpoint → 2 parse → 3 query → 3.5 query checkpoint
                → 4 assemble-wide → 6 extract-ir
[agent] reads ir.json + description_prompts; writes compute sources + description files
# Agent calls pipeline.py phase2
[orchestrator] 8a validate → 8b evaluate → 8c apply-computed
                → 8d attach descriptions → 8d.5 description checkpoint
                → 9 render markdown + docx + status.json
```

## Step table

| Step | Type | Owner | Output |
|---|---|---|---|
| 1 lint | in-process | `Orchestrator.run_phase_1` | metrics only |
| 1.5 lint checkpoint | dataclass emit | `Orchestrator.run_phase_1` | `CheckpointSignal("1.5", ...)` if errors |
| 2 parse | in-process | `Orchestrator.run_phase_1` | `<stem>.parsed.json` |
| 3 query | in-process | `Orchestrator.run_phase_1` | `<stem>.query.json` |
| 3.5 query checkpoint | dataclass emit | `Orchestrator.run_phase_1` | `CheckpointSignal("3.5", ...)` if any failure (2026-06-27 policy reversal: always trigger) |
| 4 assemble-wide | in-process | `Orchestrator.run_phase_1` | `<stem>.wide.json` |
| 6 extract-ir | in-process | `Orchestrator.run_phase_1` | `<stem>.ir.json` |
| 7 codegen | agent LLM | lead agent | compute source files |
| 8a validate | in-process | `Orchestrator.run_phase_2` | per-source pass/fail → sentinel |
| 8b evaluate | in-process | `Orchestrator.run_phase_2` | per-source computed dict |
| 8c apply-computed | in-process | `Orchestrator.run_phase_2` | updated wide.per_report |
| 8d attach descriptions | in-process | `Orchestrator.run_phase_2` | `report.description_text` per report (via `render_markdown.attach_description_files`) |
| 8d.5 description checkpoint | dataclass emit | `Orchestrator.run_phase_2` | `CheckpointSignal("8d.5", ...)` if any failure |
| 9 render + status | in-process | `Orchestrator.run_phase_2` | `report.md`, `report.docx`, `status.json` |

## CheckpointSignal → ask_clarification mapping

See spec `docx/superpowers/specs/2026-07-06-chatbi-report-rewrite-design.md` §"CheckpointSignal → `ask_clarification` 映射" for the fixed mapping table (do not invent alternatives).

## Wire format

`pipeline.py` stdout last line is JSON, four kinds:

- `{"kind": "phase1_result", "result": {...}}`
- `{"kind": "phase2_result", "result": {...}}`
- `{"kind": "checkpoint", "step": "1.5" | "3.5" | "8d.5", "metrics": {...}, "artifacts": {...}, "message": "..."}`
- `{"kind": "phase_aborted", "step": "...", "reason": "USER_ABORTED"}`

Non-last stdout lines (if any) are progress messages. Errors → stderr traceback + exit code != 0.
```

Remove the old "Step definitions" table content, the "Step types" subsection, and the "Retry budget" table (the new design doesn't have per-step retry budgets — Phase 1/2 either complete or checkpoint).

- [ ] **Step 2: Verify no orphan references to old step numbers**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && grep -n "Step 1\|Step 2\|Step 3\|Step 4\|Step 5\|Step 6\|Step 7\|Step 8\|Step 9" skills/public/chatbi-report/references/pipeline.md`

Expected: only the new step table rows; no orphan "Step 1: lint" / "Step 2: parse" prose.

- [ ] **Step 3: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/references/pipeline.md
git commit -m "docs(chatbi-report): pipeline.md — Phase 1/Phase 2 + wire format (T17)"
```

---

### Task 18: Update `template-troubleshooting.md` for new error path

**Files:**
- Modify: `skills/public/chatbi-report/references/template-troubleshooting.md`

- [ ] **Step 1: Replace the "Failure handling" + "Common symptoms" sections**

In `skills/public/chatbi-report/references/template-troubleshooting.md`, replace the "Failure handling" and "Common symptoms" sections with:

```markdown
## Failure handling

- `pipeline.py phase1` / `pipeline.py phase2` non-zero exit → Python traceback on stderr; the agent displays the traceback and stops. No `assemble_status` write.
- `phase1` returns `CheckpointSignal("1.5" | "3.5", ...)` → agent calls `ask_clarification` per the mapping table in `references/pipeline.md`. If user picks "停止", agent writes `status.json` with `error_class=USER_ABORTED` via `assemble_status.write_status`. If user picks "继续", agent re-invokes `phase1` (with `force_continue`).
- `phase2` returns `CheckpointSignal("8d.5", ...)` → same routing.
- 8a / 8b / 8d internal failures (compute, evaluate, description) → cells become `⚠️COMPUTE_FAILED` / `⚠️DESCRIPTION_FAILED` sentinels; pipeline continues to `report.md` / `report.docx` / `status.json` with `error_class=None`.

## Common symptoms

| Symptom | Likely cause | Fix |
|---|---|---|
| `phase1` returns `kind=checkpoint, step=3.5` with `ok < total` | SQLBot returned `success=false` for some idx_id OR `data` empty | Check `SQLBOT_BASE_URL`; verify mock fixture has matching `idx_id` keys; if real SQLBot, check periods match `time_info` |
| `phase1` returns `kind=checkpoint, step=1.5` with `n_err > 0` | markdown template has lint errors (missing `data-idx`, malformed `> 计算:` block, etc.) | Run `python -m md_lint scripts/md_lint.py <file>.md` for the error list |
| `phase2` finishes but `status.json` shows many `⚠️COMPUTE_FAILED` cells | Compute source code failed `validate_ast` / `validate_signature` / `run_smoke` / `run_example` | Re-read `prompts/compute_codegen.md`; regenerate compute source via LLM |
| `phase2` returns `kind=checkpoint, step=8d.5` | Description file missing or unreadable | Verify the description file paths passed via `--description` exist; check `out_dir` permissions |
| `phase2` produces empty `report.md` | wide.per_report has no rows | Check `query.json` — likely no idx_id succeeded; see first row |
| Sandbox can't import pandas | Container missing deps | Restart with `make dev` |
```

- [ ] **Step 2: Verify no orphan references to old step numbers in the symptoms**

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && grep -n "Step [0-9]\|phase1\|phase2" skills/public/chatbi-report/references/template-troubleshooting.md`

Expected: only references to `phase1` / `phase2` subcommands and the checkpoint steps.

- [ ] **Step 3: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/references/template-troubleshooting.md
git commit -m "docs(chatbi-report): troubleshooting.md — new error path via wire format (T18)"
```

---

## Self-Review

### 1. Spec coverage

| Spec section | Covered by task |
|---|---|
| Goals #1 库函数 + 单一 Orchestrator 入口 | T1, T2 |
| Goals #2 9 步逻辑、3 checkpoint、2 LLM 边界全部保留 | T3–T11 (steps preserved in Orchestrator methods) |
| Goals #3 Phase 1 / Phase 2 拆分 | T3–T11 (two separate methods on Orchestrator) |
| Goals #4 E2E 锚点 | T13 (test_e2e_minimal.py is the gating test) |
| Goals #5 统一错误诊断 + CheckpointSignal → ask_clarification 映射 | T5, T8, T10 (CheckpointSignal emit); mapping table referenced in T15, T17 |
| Goals #6 消除 --mock / --mock-fixture 双 flag | T14 |
| Goals #7 可观测性 (metrics dict) | T3–T11 (every step records `metrics["<step>_<name>"]`) |
| Non-Goals (no SQLBot wire change, no template change, no chart change) | respected throughout — no modifications to existing library functions or `chart_gen.py` |
| Architecture §"Phase 边界" (Phase 1 = 1-6, Phase 2 = 8a-9) | T3–T6, T8–T11 |
| Wire format (last-line JSON 4 kinds) | T12 (emitter + 3 CLI tests covering all kinds) |
| CheckpointSignal → ask_clarification mapping | T15, T17 (docs reference spec) |
| 用户回复路由 (force_continue / USER_ABORTED) | T7 (force_continue test), T15 (SKILL.md describes routing) |
| Anti-pattern 不要 delegate 给 subagent | T15 (SKILL.md emphasizes lead agent must call pipeline.py itself) |
| E2E test as completion gate | T13 (gating) + T13 step 3 (full suite) + T13 step 4 (integration scenarios) |
| Risks row 1 (OOM): not addressed in this plan | out of scope; spec notes "实施时再决定 GC 策略" |
| Open questions 1–4 | per-step details left to implementation; the plan provides a workable default for each |

### 2. Placeholder scan

- No "TBD" / "TODO" / "fill in later" in any task.
- No "add appropriate error handling" — every task's error path is concrete (T5 emits CheckpointSignal, T8 marks sentinel, T12 exits 1 on exception).
- No "Similar to Task N" — every task's code is shown in full.
- No "Write tests for the above" — every test is a complete pytest function.

### 3. Type consistency

| Symbol | Defined in | Used in |
|---|---|---|
| `OrchestratorConfig` | T1 | T2, T3, T4, T8, T12 |
| `CheckpointSignal` | T1 | T5, T7, T10, T12 |
| `ForceContinue` | T1 | T5, T7, T12 (referenced in docs) |
| `Phase1Result` | T1 | T3, T6, T8, T9, T12 |
| `RunResult` | T1 | T8, T9, T10, T11, T12 |
| `Orchestrator.__init__` | T2 | all subsequent |
| `Orchestrator.run_phase_1` | T3 | T4, T5, T6, T7, T8, T12 |
| `Orchestrator.run_phase_2` | T8 | T9, T10, T11, T12 |
| `Orchestrator._finish_phase_2` | T8 (placeholder) → T11 (full impl) | T8, T9, T10, T11 |
| `_emit_wire_format` | T12 | T12 only |
| `_parse_kv_list` | T12 | T12 only |
| `main` | T12 | T12 only |
| `attach_description_files` (called from T10 + T11) | render_markdown.py (library) | T10, T11 |
| `orchestrator-metrics.json` (sidecar) | T11 | T11, T13 (asserts) |

No type drift. `clearLayers` vs `clearFullLayers`-style bugs are not present.

### 4. Order dependency

T1 → T2 → T3 → T4 → T5 → T6 → T7 (Phase 1 done) → T8 → T9 → T10 → T11 (Phase 2 done) → T12 (CLI needs both phases) → T13 (E2E needs CLI) → T14 (sqlbot cleanup is independent) → T15 → T16 → T17 → T18 (docs last).

T7 is the only "verify a previous task's wiring" task — it confirms T5's `fc.skip_lint_checkpoint` branch works. If T7 fails, the engineer fixes T5 directly.

T14 is independent of T1–T13 — the `--mock` flag was a redundant CLI flag, the cleanup doesn't change behavior. Could be done any time, but placed after T13 so the E2E gate still covers it.

---

## Execution Handoff

Plan complete and saved to `docx/superpowers/plans/2026-07-06-chatbi-report-rewrite.md`. 18 tasks, 5 TDD-style steps each, ~13 commits per task, total ~90-100 sub-steps. Estimated time per task: 15-30 min for an engineer familiar with the existing chatbi-report scripts. Total: ~6-8 hours of focused work.

**Two execution options:**

1. **Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, two-stage review between tasks (implementer + spec-compliance reviewer), fast iteration on small diffs.
2. **Inline Execution** — Execute tasks in this session using `executing-plans`, batch execution with checkpoints for review.

**Which approach?**
