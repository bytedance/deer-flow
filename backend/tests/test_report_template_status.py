"""ISSUE-02 regression: report template status uses shared RunStatus, "cancelled" spelling."""

from __future__ import annotations

from deerflow.shared.status import RunStatus


class TestReportTemplateRunStatus:
    """ReportRunRecord.status must be shared RunStatus, not ad-hoc Literal."""

    def test_records_run_status_is_shared(self):
        """records.py RunStatus must be the shared enum, not a separate Literal."""
        from deerflow.report_templates.records import RunStatus as RecordsRunStatus

        assert RecordsRunStatus is RunStatus, (
            "report_templates.records.RunStatus must be the shared deerflow.shared.status.RunStatus enum"
        )

    def test_records_uses_cancelled(self):
        """records RunStatus must use 'cancelled' (double-l)."""
        assert RunStatus.cancelled.value == "cancelled"
        assert "cancelled" in {m.value for m in RunStatus}


class TestRuntimeStateStepStatus:
    """Runtime state step-level status uses StepStatus with 'cancelled'."""

    def test_step_status_uses_cancelled(self):
        from deerflow.report_templates.runtime.state import StepStatus

        assert "cancelled" in set(StepStatus.__args__), (
            "StepStatus must include 'cancelled' (double-l), not 'canceled'"
        )
        assert "canceled" not in set(StepStatus.__args__), (
            "StepStatus must NOT include 'canceled' (single-l)"
        )

    def test_read_state_maps_canceled(self, tmp_path):
        """read_state must map old 'canceled' to 'cancelled'."""
        import json

        from deerflow.report_templates.runtime.state import read_state

        status_path = tmp_path / "status.json"
        old_state = {
            "schema_version": "1",
            "report_run_id": "rr_test123",
            "thread_id": "th_test123",
            "template_id": "tpl_test123",
            "status": "canceled",
            "nonce": "abc",
            "expected_step": None,
            "completed_steps": [],
            "form_state": {},
            "step_outputs": {},
            "parameters_summary": {},
            "error_code": None,
            "error_message": None,
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-01T00:00:00+00:00",
        }
        status_path.write_text(json.dumps(old_state), encoding="utf-8")

        state = read_state(tmp_path)
        assert state.status == "cancelled", (
            f"Expected 'cancelled' after migration, got {state.status!r}"
        )

    def test_mark_cancelled_sets_cancelled(self):
        """mark_cancelled must set status to 'cancelled'."""
        from deerflow.report_templates.runtime.state import RuntimeState, mark_cancelled

        st = RuntimeState(status="awaiting_step")
        mark_cancelled(st)
        assert st.status == "cancelled"


class TestNoCanceledLiteral:
    """'canceled' (single-l) must not appear in report_templates code."""

    def test_no_canceled_in_step_status(self):
        from deerflow.report_templates.runtime.state import StepStatus

        values = set(StepStatus.__args__)
        assert "canceled" not in values
