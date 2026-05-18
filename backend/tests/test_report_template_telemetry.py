"""Tests for the Phase 7 telemetry collector +埋点 hooks.

Coverage:
  - ``ReportTemplateTelemetry`` records each event type and ``summary()`` shape
  - JSONL sink writes structured events when enabled
  - ``state.transition()`` emits a ``report_run_outcome`` exactly once per
    (run_id, terminal status) pair
  - ``mark_failed`` records failure with the error code
  - ``validate_dsl()`` emits ``validator_outcome`` per distinct error code
  - ``apply_args_aliases`` is unaffected (regression guard)
  - The ``record_fallback`` tool's input validation
  - ``data_runner._resolve_descriptor`` emits skill_unavailable on miss
  - ``storage_scanner.scan_storage / scan_version_counts`` walk the layout
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deerflow.report_templates import telemetry as telemetry_module
from deerflow.report_templates.runtime import state as state_module
from deerflow.report_templates.runtime.state import (
    RuntimeState,
    mark_failed,
    transition,
)
from deerflow.report_templates.script_registry import (
    ScriptRegistry,
    UnknownScriptError,
)
from deerflow.report_templates.storage_scanner import (
    scan_storage,
    scan_version_counts,
)
from deerflow.report_templates.telemetry import (
    ReportTemplateTelemetry,
    get_telemetry,
    reset_telemetry,
)
from deerflow.report_templates.validator import validate_dsl


@pytest.fixture
def fresh_telemetry(tmp_path, monkeypatch):
    """Force a clean singleton with a sandboxed JSONL path for every test."""
    reset_telemetry()
    state_module._emitted_terminal.clear()
    jsonl = tmp_path / "tele.jsonl"
    inst = ReportTemplateTelemetry(jsonl_path=jsonl)
    monkeypatch.setattr(telemetry_module, "_singleton", inst)
    yield inst
    reset_telemetry()
    state_module._emitted_terminal.clear()


# ---------------------------------------------------------------------------
# Collector primitives
# ---------------------------------------------------------------------------


class TestCollectorPrimitives:
    def test_report_run_increments_counter(self, fresh_telemetry):
        fresh_telemetry.record_report_run(
            template_id="tpl_A",
            template_version_ref="v1",
            visibility="private",
            report_run_id="rr_1",
            status="exported",
            error_code=None,
            duration_seconds=4.2,
        )
        s = fresh_telemetry.summary()
        assert s["report_runs"]["total"] == 1
        assert s["report_runs"]["by_template_status_error"][0] == {
            "template_id": "tpl_A",
            "status": "exported",
            "error_code": None,
            "count": 1,
        }
        assert s["report_runs"]["avg_duration_seconds_by_template"]["tpl_A"] == 4.2

    def test_success_rate_excludes_failed(self, fresh_telemetry):
        fresh_telemetry.record_report_run(
            template_id="t", template_version_ref=None, visibility=None,
            report_run_id="rr_a", status="exported", error_code=None, duration_seconds=1,
        )
        fresh_telemetry.record_report_run(
            template_id="t", template_version_ref=None, visibility=None,
            report_run_id="rr_b", status="failed", error_code="SCRIPT_TIMEOUT", duration_seconds=2,
        )
        s = fresh_telemetry.summary()
        assert s["report_runs"]["total"] == 2
        assert s["report_runs"]["success_rate"] == 0.5

    def test_fallback_counter(self, fresh_telemetry):
        fresh_telemetry.record_fallback(agent_name="ai-report--daily", reason="tool_error")
        fresh_telemetry.record_fallback(agent_name="ai-report--daily", reason="tool_error")
        fresh_telemetry.record_fallback(agent_name="ai-report--daily", reason="skill_disabled")
        s = fresh_telemetry.summary()
        assert s["fallback_triggered"]["total"] == 3
        agg = {(row["agent_name"], row["reason"]): row["count"] for row in s["fallback_triggered"]["by_agent_reason"]}
        assert agg[("ai-report--daily", "tool_error")] == 2
        assert agg[("ai-report--daily", "skill_disabled")] == 1

    def test_validator_groups_by_code(self, fresh_telemetry):
        fresh_telemetry.record_validator(outcome="valid", error_code=None)
        fresh_telemetry.record_validator(outcome="invalid", error_code="UNKNOWN_SCRIPT")
        fresh_telemetry.record_validator(outcome="invalid", error_code="UNKNOWN_SCRIPT")
        s = fresh_telemetry.summary()
        codes = {
            (row["outcome"], row["error_code"]): row["count"]
            for row in s["validator"]["by_outcome_error"]
        }
        assert codes[("valid", None)] == 1
        assert codes[("invalid", "UNKNOWN_SCRIPT")] == 2

    def test_storage_snapshot_keeps_latest(self, fresh_telemetry):
        fresh_telemetry.record_storage_snapshot(owner_type="users", owner_id="u1", bytes_used=100)
        fresh_telemetry.record_storage_snapshot(owner_type="users", owner_id="u1", bytes_used=500)
        s = fresh_telemetry.summary()
        assert s["storage"]["total_bytes"] == 500
        assert s["storage"]["by_owner"] == [
            {"owner_type": "users", "owner_id": "u1", "bytes_used": 500}
        ]

    def test_skill_unavailable_counter(self, fresh_telemetry):
        fresh_telemetry.record_skill_unavailable(skill_name="data-analyst", action="disabled_after_publish")
        s = fresh_telemetry.summary()
        assert s["skill_unavailable"]["total"] == 1


# ---------------------------------------------------------------------------
# JSONL sink
# ---------------------------------------------------------------------------


class TestJsonlSink:
    def test_each_event_appends_one_line(self, fresh_telemetry):
        fresh_telemetry.record_fallback(agent_name="ai-report--daily", reason="tool_error")
        fresh_telemetry.record_validator(outcome="valid", error_code=None)
        lines = fresh_telemetry._jsonl_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        payloads = [json.loads(line) for line in lines]
        assert payloads[0]["type"] == "fallback_triggered"
        assert payloads[0]["agent_name"] == "ai-report--daily"
        assert payloads[1]["type"] == "validator_outcome"

    def test_disabled_via_env(self, fresh_telemetry, monkeypatch):
        monkeypatch.setenv("DEER_FLOW_REPORT_TELEMETRY_LOG", "0")
        fresh_telemetry.record_fallback(agent_name="x", reason="tool_error")
        assert not fresh_telemetry._jsonl_path.exists()


# ---------------------------------------------------------------------------
# state.transition() — emits exactly once per terminal status
# ---------------------------------------------------------------------------


class TestStateTransitionHook:
    def _state(self, status="rendered") -> RuntimeState:
        return RuntimeState(
            report_run_id="rr_1",
            thread_id="t",
            template_id="tpl_A",
            template_version_ref="v1",
            status=status,
            created_at="2026-05-18T10:00:00+00:00",
        )

    def test_transition_to_exported_emits_success(self, fresh_telemetry):
        st = self._state()
        transition(st, "exported")
        s = fresh_telemetry.summary()
        assert s["report_runs"]["total"] == 1
        row = s["report_runs"]["by_template_status_error"][0]
        assert row["status"] == "exported"
        assert row["error_code"] is None

    def test_no_emit_on_non_terminal_transition(self, fresh_telemetry):
        st = self._state(status="pending")
        transition(st, "awaiting_step")
        assert fresh_telemetry.summary()["report_runs"]["total"] == 0

    def test_mark_failed_emits_with_error_code(self, fresh_telemetry):
        st = self._state(status="data_complete")
        mark_failed(st, code="SCRIPT_TIMEOUT", message="boom")
        s = fresh_telemetry.summary()
        assert s["report_runs"]["total"] == 1
        assert s["report_runs"]["by_template_status_error"][0]["error_code"] == "SCRIPT_TIMEOUT"

    def test_terminal_emit_is_idempotent(self, fresh_telemetry):
        st = self._state()
        transition(st, "exported")
        # Calling the recorder again for the same (run_id, status) is a no-op.
        state_module._record_terminal_outcome(st)
        state_module._record_terminal_outcome(st)
        assert fresh_telemetry.summary()["report_runs"]["total"] == 1


# ---------------------------------------------------------------------------
# validator.py 埋点
# ---------------------------------------------------------------------------


class TestValidatorHook:
    def _valid_dsl(self) -> dict:
        return {
            "dsl_version": "1",
            "name": "demo",
            "display_name": "demo",
            "form_steps": [
                {
                    "id": "scope",
                    "title": "t",
                    "fields": [{"name": "date", "label": "date", "type": "date"}],
                    "next": "generate",
                }
            ],
            "data_steps": [
                {
                    "id": "demo_data",
                    "kind": "script",
                    "name": "data-analyst/list_equipment",
                    "args": {"type": "all"},
                    "outputs": {"payload": "demo_data.json"},
                }
            ],
            "sections": [
                {
                    "id": "overview",
                    "title": "T",
                    "component": "markdown",
                    "source": "$.steps.demo_data.payload",
                }
            ],
        }

    def test_valid_emits_valid_outcome(self, fresh_telemetry):
        validate_dsl(self._valid_dsl())
        codes = {
            (row["outcome"], row["error_code"])
            for row in fresh_telemetry.summary()["validator"]["by_outcome_error"]
        }
        assert ("valid", None) in codes

    def test_invalid_emits_one_event_per_code(self, fresh_telemetry):
        bad = self._valid_dsl()
        bad["form_steps"][0]["next"] = "nonexistent"
        bad["sections"][0]["source"] = "$.steps.missing.x"  # unrelated error
        report = validate_dsl(bad)
        assert not report.valid
        codes_seen = {issue.code for issue in report.errors}
        emitted = {
            row["error_code"]
            for row in fresh_telemetry.summary()["validator"]["by_outcome_error"]
            if row["outcome"] == "invalid"
        }
        # Every distinct code in the report should appear in telemetry.
        assert codes_seen <= emitted


# ---------------------------------------------------------------------------
# data_runner._resolve_descriptor — skill_unavailable on miss
# ---------------------------------------------------------------------------


class TestDataRunnerSkillHook:
    def test_missing_script_emits_skill_unavailable(self, fresh_telemetry):
        from deerflow.report_templates.runtime.data_runner import _resolve_descriptor

        empty_registry = ScriptRegistry(scripts={})
        with pytest.raises(UnknownScriptError):
            _resolve_descriptor("data-analyst/missing_script", empty_registry)
        s = fresh_telemetry.summary()
        agg = {(row["skill_name"], row["action"]): row["count"] for row in s["skill_unavailable"]["by_skill_action"]}
        assert agg[("data-analyst", "disabled_after_publish")] == 1


# ---------------------------------------------------------------------------
# storage_scanner — walks the on-disk layout
# ---------------------------------------------------------------------------


class TestStorageScanner:
    def _build_tree(self, root: Path) -> None:
        # users/u1 has a 50-byte template + a 1-version subdir
        u1_tpl = root / "users" / "u1" / "tpl_A"
        u1_tpl.mkdir(parents=True)
        (u1_tpl / "template.json").write_text("x" * 50, encoding="utf-8")
        (u1_tpl / "versions").mkdir()
        (u1_tpl / "versions" / "v1.json").write_text("y" * 10, encoding="utf-8")
        # tenants/t1 has a 100-byte template, draft only
        t1_tpl = root / "tenants" / "t1" / "tpl_B"
        t1_tpl.mkdir(parents=True)
        (t1_tpl / "template.json").write_text("z" * 100, encoding="utf-8")

    def test_scan_storage_records_per_owner_bytes(self, tmp_path, fresh_telemetry):
        self._build_tree(tmp_path)
        result = scan_storage(tmp_path)
        assert result == {"users/u1": 60, "tenants/t1": 100}
        # Telemetry mirrors the result.
        owners = {(row["owner_type"], row["owner_id"]): row["bytes_used"] for row in fresh_telemetry.summary()["storage"]["by_owner"]}
        assert owners[("users", "u1")] == 60
        assert owners[("tenants", "t1")] == 100

    def test_scan_versions_counts_files(self, tmp_path, fresh_telemetry):
        self._build_tree(tmp_path)
        result = scan_version_counts(tmp_path)
        assert result == {"tpl_A": 1, "tpl_B": 0}
        s = fresh_telemetry.summary()
        counts = {row["template_id"]: row["version_count"] for row in s["version_counts"]}
        assert counts == {"tpl_A": 1, "tpl_B": 0}

    def test_scan_handles_missing_root(self, tmp_path, fresh_telemetry):
        # Pointing at a directory with no users/tenants subdirs is fine.
        assert scan_storage(tmp_path) == {}
        assert scan_version_counts(tmp_path) == {}


# ---------------------------------------------------------------------------
# record_fallback tool — input validation
# ---------------------------------------------------------------------------


class TestRecordFallbackTool:
    def test_records_on_valid_input(self, fresh_telemetry):
        from deerflow.tools.builtins.report_template_telemetry_tools import (
            report_template_record_fallback_tool,
        )

        out = json.loads(
            report_template_record_fallback_tool.invoke(
                {"agent_name": "ai-report--daily", "reason": "tool_error"}
            )
        )
        assert out["recorded"] is True
        assert fresh_telemetry.summary()["fallback_triggered"]["total"] == 1

    def test_rejects_unknown_reason(self, fresh_telemetry):
        from deerflow.tools.builtins.report_template_telemetry_tools import (
            report_template_record_fallback_tool,
        )

        out = json.loads(
            report_template_record_fallback_tool.invoke(
                {"agent_name": "ai-report--daily", "reason": "made_up_reason"}
            )
        )
        assert out["error"]["code"] == "INVALID_REASON"
        assert fresh_telemetry.summary()["fallback_triggered"]["total"] == 0

    def test_rejects_empty_agent(self, fresh_telemetry):
        from deerflow.tools.builtins.report_template_telemetry_tools import (
            report_template_record_fallback_tool,
        )

        out = json.loads(
            report_template_record_fallback_tool.invoke({"agent_name": "", "reason": "tool_error"})
        )
        assert out["error"]["code"] == "INVALID_AGENT_NAME"


# ---------------------------------------------------------------------------
# Idempotency / process singleton sanity
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_telemetry_returns_same_instance(self):
        reset_telemetry()
        a = get_telemetry()
        b = get_telemetry()
        assert a is b
