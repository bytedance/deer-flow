"""Tests for ai-report--custom SOUL.md contract (2-lane structure).

After Task 3 rewrite — verifies:
- All 8 runtime tools are referenced (sprint plan: must surface the full
  prepare → render_step → submit → run_data_steps → assemble → render →
  export flow + resume).
- All 6 lifecycle tools are still referenced (Lane B preserved).
- All 8 builtin DSL templates are mentioned by name (so users know what's
  available without re-querying).
- The lane-router language exists (entry-point guidance).
- §13.2 human_review_required reminder mandate present.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SOUL_PATH = (
    Path(__file__).resolve().parents[2]
    / "agents"
    / "builtin"
    / "ai-report--custom"
    / "SOUL.md"
)


@pytest.fixture(scope="module")
def soul_text() -> str:
    return SOUL_PATH.read_text(encoding="utf-8")


# --- 2-lane routing ----------------------------------------------------------

def test_soul_mentions_two_lanes(soul_text):
    """Entry-point lane router must be explicit (Lane A run / Lane B author)."""
    assert "Lane A" in soul_text
    assert "Lane B" in soul_text


def test_soul_has_intent_router(soul_text):
    """An '入口判断' or 'entry router' table that decides between lanes."""
    assert "入口判断" in soul_text or "走哪条 Lane" in soul_text


# --- Lane A: 8 runtime tools must be present ---------------------------------

@pytest.mark.parametrize(
    "tool_name",
    [
        "report_template_prepare_run",
        "report_template_render_step",
        "report_template_submit_step",
        "report_template_run_data_steps",
        "report_template_assemble_payload",
        "report_template_render_report",
        "report_template_export",
        "report_template_resume_run",
    ],
)
def test_runtime_tools_referenced(soul_text, tool_name):
    """All 8 runtime tools shipped in Phase 4 must be documented."""
    assert tool_name in soul_text, f"Lane A runtime tool {tool_name} not in SOUL.md"


# --- Lane B: 6 lifecycle tools preserved -------------------------------------

@pytest.mark.parametrize(
    "tool_name",
    [
        "report_template_list",
        "report_template_get",
        "report_template_validate",
        "report_template_save_draft",
        "report_template_publish",
        "report_template_fork",
    ],
)
def test_lifecycle_tools_preserved(soul_text, tool_name):
    """All 6 Lane B (authoring) tools must still be documented."""
    assert tool_name in soul_text, f"Lane B lifecycle tool {tool_name} missing"


# --- 8 builtin DSL templates must be discoverable ----------------------------

@pytest.mark.parametrize(
    "template_name",
    [
        "daily-equipment",
        "weekly-equipment",
        "monthly-equipment",
        "trend-equipment",
        "diagnosis-fault",
        "failure-analysis",
        "closure-summary",
        "inspection",
    ],
)
def test_builtin_templates_listed(soul_text, template_name):
    """User should learn which builtin templates exist without re-querying."""
    assert template_name in soul_text, f"builtin template {template_name} not mentioned in SOUL.md"


# --- State machine documented ------------------------------------------------

@pytest.mark.parametrize(
    "state",
    ["pending", "awaiting_step", "ready_for_data", "data_complete", "payload_ready", "rendered", "exported"],
)
def test_state_machine_documented(soul_text, state):
    """Every state in the runtime state machine must be named in SOUL."""
    assert state in soul_text, f"state {state!r} not documented"


# --- Lane A runtime error codes ----------------------------------------------

@pytest.mark.parametrize(
    "code",
    [
        "STATE_NOT_FOUND",
        "STATE_MISMATCH",
        "STEP_MISMATCH",
        "SCRIPT_TIMEOUT",
        "ASSEMBLE_FAILED",
        "NO_ACTIVE_RUN",
    ],
)
def test_lane_a_error_codes_documented(soul_text, code):
    assert code in soul_text, f"Lane A error code {code} missing"


# --- §13.2 interpretive report reminder mandate -------------------------------

def test_human_review_reminder_documented(soul_text):
    """SOUL must instruct LLM to remind users about human_review_required
    for §13.2 interpretive reports (trend / diagnosis / failure-analysis)."""
    # Look for ANY of: human_review_required mention, "人工复核" reminder, §13.2 callout
    has_reminder = (
        "human_review_required" in soul_text
        or "人工复核" in soul_text
        or "§13.2" in soul_text
    )
    assert has_reminder, "SOUL must mention §13.2 / human_review_required reminder"


def test_interpretive_reports_called_out(soul_text):
    """All 3 §13.2 interpretive reports should be flagged as needing
    human review (trend / diagnosis / failure-analysis)."""
    # At least one occurrence each
    for report in ("trend", "diagnosis", "failure-analysis"):
        assert report in soul_text, f"§13.2 interpretive report '{report}' not mentioned"


# --- Forbidden anti-patterns -------------------------------------------------

def test_no_stale_phase4_disclaimer(soul_text):
    """The old 'Phase 4 暂未上线' disclaimer must NOT survive — runtime is live."""
    forbidden_phrases = [
        "Phase 3 交付",  # old "Phase 3 仅支持生命周期管理" line
        "暂未在 Phase 3",  # variations of the same
        "Phase 4 的 report_template_prepare_run",  # treating it as future work
    ]
    for phrase in forbidden_phrases:
        assert phrase not in soul_text, (
            f"stale Phase 4 disclaimer survived: {phrase!r} — runtime is shipped, "
            f"the SOUL must NOT tell users it's unavailable"
        )


def test_no_bash_fallback_advised(soul_text):
    """The SOUL must NOT advise bash as a fallback for template ops."""
    # Sanity: doc still mentions "禁止用 bash" (the prohibition).
    assert "禁止用 `bash`" in soul_text or "没有 bash 兜底" in soul_text


def test_no_structured_session_summary_output(soul_text):
    """SOUL must instruct LLM NOT to output SESSION INTENT / SUMMARY blocks
    (recurring rule across daily/weekly/monthly SOULs)."""
    assert "严禁输出结构化会话摘要" in soul_text or "SESSION INTENT" in soul_text


# --- Sanity ------------------------------------------------------------------

def test_soul_file_exists_and_not_empty(soul_text):
    assert len(soul_text) > 500, "SOUL.md unexpectedly small"


def test_soul_is_a_meaningful_rewrite(soul_text):
    """Old SOUL was 182 lines and lacked Lane A runtime tools entirely;
    the rewrite must be substantially larger AND introduce the lane router."""
    line_count = soul_text.count("\n")
    assert line_count > 300, f"SOUL.md should be a substantial rewrite, got only {line_count} lines"
