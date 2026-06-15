"""Phase 4 runtime tests — state machine, payload builder, submit_step, exporter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from deerflow.report_templates.runtime.exporter import (
    ExportResult,
    export_report,
)
from deerflow.report_templates.runtime.payload_builder import (
    PayloadBuildError,
    assemble_payload,
)
from deerflow.report_templates.runtime.state import (
    RuntimeState,
    StateNotFoundError,
    StateTransitionError,
    expect_status,
    mark_failed,
    read_state,
    transition,
    write_state,
)
from deerflow.report_templates.runtime.step_renderer import build_form_props
from deerflow.report_templates.runtime.step_submitter import (
    SubmitStepError,
    submit_step,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    d = tmp_path / "run"
    d.mkdir()
    return d


def _state(**overrides) -> RuntimeState:
    base = {
        "report_run_id": "rr_AAAAAAAAAAAAAAAAAAAAAAAA",
        "thread_id": "thread-1",
        "template_id": "tpl_BBBBBBBBBBBBBBBBBBBBBBBB",
        "template_version": 1,
        "status": "pending",
        "nonce": "n1",
        "expected_step": "scope",
        "created_at": "2026-05-18T00:00:00+00:00",
    }
    base.update(overrides)
    return RuntimeState(**base)


# ---------------------------------------------------------------------------
# state.py
# ---------------------------------------------------------------------------


class TestStateRoundTrip:
    def test_write_and_read(self, run_dir):
        st = _state()
        write_state(run_dir, st)
        loaded = read_state(run_dir)
        assert loaded.report_run_id == st.report_run_id
        assert loaded.thread_id == st.thread_id
        assert loaded.status == "pending"

    def test_read_missing_raises(self, run_dir):
        with pytest.raises(StateNotFoundError):
            read_state(run_dir)

    def test_expect_status_allows(self):
        st = _state(status="awaiting_step")
        expect_status(st, "awaiting_step", "pending")  # no raise

    def test_expect_status_rejects(self):
        st = _state(status="exported")
        with pytest.raises(StateTransitionError):
            expect_status(st, "pending")

    def test_transition_allowed(self):
        st = _state(status="pending")
        transition(st, "awaiting_step")
        assert st.status == "awaiting_step"

    def test_transition_disallowed(self):
        st = _state(status="exported")
        with pytest.raises(StateTransitionError):
            transition(st, "pending")

    def test_mark_failed_overrides(self):
        st = _state(status="payload_ready")
        mark_failed(st, code="X", message="boom")
        assert st.status == "failed"
        assert st.error_code == "X"


# ---------------------------------------------------------------------------
# step_submitter.py
# ---------------------------------------------------------------------------


DSL_TWO_STEPS = {
    "form_steps": [
        {
            "id": "scope",
            "title": "Scope",
            "fields": [
                {"name": "report_date", "label": "Date", "type": "date", "required": True}
            ],
            "next": "equipment",
        },
        {
            "id": "equipment",
            "title": "Equipment",
            "fields": [{"name": "equipment_ids", "label": "IDs", "type": "text"}],
            "next": "generate",
        },
    ],
    "sections": [],
}


class TestSubmitStep:
    def test_submit_first_step_advances_to_second(self):
        st = _state(status="pending", expected_step="scope")
        next_id = submit_step(
            dsl=DSL_TWO_STEPS,
            state=st,
            submitted_step_id="scope",
            payload={"report_date": "2026-05-18"},
        )
        assert next_id == "equipment"
        assert st.status == "awaiting_step"
        assert st.expected_step == "equipment"
        assert st.form_state["scope"] == {"report_date": "2026-05-18"}
        assert "scope" in st.completed_steps

    def test_submit_final_step_transitions_to_ready_for_data(self):
        st = _state(
            status="awaiting_step", expected_step="equipment",
            completed_steps=["scope"], form_state={"scope": {"report_date": "x"}},
        )
        next_id = submit_step(
            dsl=DSL_TWO_STEPS,
            state=st,
            submitted_step_id="equipment",
            payload={"equipment_ids": "P-001"},
        )
        assert next_id == "__generate__"
        assert st.status == "ready_for_data"
        assert st.expected_step is None

    def test_wrong_step_id_rejected(self):
        st = _state(status="awaiting_step", expected_step="equipment")
        with pytest.raises(SubmitStepError, match="step mismatch"):
            submit_step(
                dsl=DSL_TWO_STEPS,
                state=st,
                submitted_step_id="scope",
                payload={},
            )

    def test_missing_required_field_rejected(self):
        st = _state(status="pending", expected_step="scope")
        with pytest.raises(SubmitStepError, match="missing required"):
            submit_step(
                dsl=DSL_TWO_STEPS,
                state=st,
                submitted_step_id="scope",
                payload={},
            )

    def test_unknown_step_rejected(self):
        st = _state(status="awaiting_step", expected_step="ghost")
        with pytest.raises(SubmitStepError):
            submit_step(
                dsl=DSL_TWO_STEPS,
                state=st,
                submitted_step_id="ghost",
                payload={},
            )


# ---------------------------------------------------------------------------
# payload_builder.py
# ---------------------------------------------------------------------------


DSL_WITH_SECTIONS = {
    "name": "demo",
    "display_name": "Demo",
    "sections": [
        {"id": "s1", "title": "Overview", "component": "markdown",
         "source": "$.steps.k.daily_kpi.summary"},
        {"id": "s2", "title": "Table", "component": "table",
         "source": "$.steps.k.daily_kpi.alarms"},
        {"id": "s3", "title": "Chart", "component": "echart",
         "source": "$.steps.k.daily_kpi.trend_chart"},
        {"id": "s4", "title": "Cards", "component": "card_group",
         "source": "$.steps.k.daily_kpi.kpis"},
    ],
}


def _state_with_outputs() -> RuntimeState:
    return _state(
        status="data_complete",
        step_outputs={
            "k": {
                "daily_kpi": {
                    "summary": "all good",
                    "alarms": [{"id": 1}, {"id": 2}],
                    "trend_chart": {"series": [{"type": "line", "data": [1, 2]}]},
                    "kpis": [{"title": "runtime", "value": "99%"}],
                }
            }
        },
    )


class TestPayloadBuilder:
    def test_assembles_all_section_types(self):
        st = _state_with_outputs()
        payload = assemble_payload(dsl=DSL_WITH_SECTIONS, state=st)
        assert payload["schema_version"] == "1"
        ids = [s["id"] for s in payload["sections"]]
        assert ids == ["s1", "s2", "s3", "s4"]
        assert payload["sections"][0]["props"]["content"] == "all good"
        assert payload["sections"][1]["props"]["rows"] == [{"id": 1}, {"id": 2}]
        assert payload["sections"][2]["props"]["option"] == {
            "series": [{"type": "line", "data": [1, 2]}]
        }
        assert payload["sections"][3]["props"]["items"] == [
            {"title": "runtime", "value": "99%"}
        ]

    def test_section_with_short_form_source(self):
        st = _state_with_outputs()
        dsl = {
            "name": "demo",
            "sections": [
                {"id": "s1", "title": "X", "component": "markdown",
                 "source": "k.daily_kpi.summary"},
            ],
        }
        payload = assemble_payload(dsl=dsl, state=st)
        assert payload["sections"][0]["props"]["content"] == "all good"

    def test_missing_step_raises(self):
        st = _state_with_outputs()
        dsl = {
            "name": "demo",
            "sections": [
                {"id": "s1", "title": "X", "component": "markdown",
                 "source": "$.steps.nope.foo"},
            ],
        }
        with pytest.raises(PayloadBuildError):
            assemble_payload(dsl=dsl, state=st)

    def test_wrong_type_for_component_raises(self):
        st = _state_with_outputs()
        dsl = {
            "name": "demo",
            "sections": [
                {"id": "s1", "title": "X", "component": "echart",
                 "source": "$.steps.k.daily_kpi.summary"},  # string, not dict
            ],
        }
        with pytest.raises(PayloadBuildError, match="echart"):
            assemble_payload(dsl=dsl, state=st)

    def test_flattens_form_state_into_parameters(self):
        st = _state_with_outputs()
        st.form_state = {
            "scope": {"report_date": "2026-05-18"},
            "kpis": {"kpi_keys": ["a", "b"]},
        }
        payload = assemble_payload(dsl=DSL_WITH_SECTIONS, state=st)
        assert payload["parameters"] == {
            "report_date": "2026-05-18",
            "kpi_keys": ["a", "b"],
        }


# ---------------------------------------------------------------------------
# step_renderer.py
# ---------------------------------------------------------------------------


class TestStepRenderer:
    def test_build_form_props_supports_nested_output_id_path(self):
        st = _state(
            step_outputs={
                "kpi_catalog": {
                    "list_equipment": {
                        "available_kpis": [
                            {
                                "key": "runtime_rate",
                                "label": "Runtime Rate",
                                "description": "Equipment runtime rate",
                            }
                        ]
                    }
                }
            }
        )
        step = {
            "id": "kpis",
            "title": "Select KPI",
            "fields": [
                {
                    "name": "kpi_keys",
                    "label": "KPI",
                    "type": "multi-select",
                    "options_source": {
                        "step": "kpi_catalog",
                        "path": "list_equipment.available_kpis",
                        "label": "label",
                        "value": "key",
                        "description": "description",
                    },
                }
            ],
            "next": "generate",
        }

        props = build_form_props(step=step, state=st, callback_id="cb-1")

        assert props["fields"][0]["options"] == [
            {
                "label": "Runtime Rate",
                "value": "runtime_rate",
                "description": "Equipment runtime rate",
            }
        ]

    def test_build_form_props_allows_single_output_shorthand_path(self):
        st = _state(
            step_outputs={
                "kpi_catalog": {
                    "list_equipment": {
                        "available_kpis": [
                            {
                                "key": "alarm_count",
                                "label": "Alarm Count",
                            }
                        ]
                    }
                }
            }
        )
        step = {
            "id": "kpis",
            "title": "Select KPI",
            "fields": [
                {
                    "name": "kpi_keys",
                    "label": "KPI",
                    "type": "multi-select",
                    "options_source": {
                        "step": "kpi_catalog",
                        "path": "available_kpis",
                        "label": "label",
                        "value": "key",
                    },
                }
            ],
            "next": "generate",
        }

        props = build_form_props(step=step, state=st, callback_id="cb-2")

        assert props["fields"][0]["options"] == [
            {
                "label": "Alarm Count",
                "value": "alarm_count",
            }
        ]


# ---------------------------------------------------------------------------
# exporter.py
# ---------------------------------------------------------------------------


def _simple_payload() -> dict[str, Any]:
    return {
        "schema_version": "1",
        "title": "Demo",
        "template": {"id": "tpl_x", "version": 1, "name": "demo"},
        "run": {"id": "rr_x", "thread_id": "t", "run_id": "", "generated_at": "now"},
        "parameters": {"date": "2026-05-18"},
        "sections": [
            {"id": "s1", "title": "Overview", "component": "markdown",
             "props": {"content": "hello"}},
            {"id": "s2", "title": "Table", "component": "table",
             "props": {"columns": ["a"], "data": [["1"]]}},
        ],
    }


class TestExporter:
    def test_markdown_required_and_succeeds(self, run_dir):
        result = export_report(payload=_simple_payload(), run_output_dir=run_dir, pdf=False)
        assert isinstance(result, ExportResult)
        assert result.pdf_path is None
        assert result.pdf_skipped_reason is None
        # File on disk.
        md_path = Path(result.md_path)
        assert md_path.exists()
        content = md_path.read_text(encoding="utf-8")
        assert "hello" in content
        assert "| a |" in content

    def test_pdf_attempt_degrades_when_unavailable(self, run_dir, monkeypatch):
        # Simulate weasyprint not installed by hiding it from sys.modules.
        import sys

        had = sys.modules.pop("weasyprint", None)
        try:
            # Inject a fake import error.
            monkeypatch.setitem(sys.modules, "weasyprint", None)  # type: ignore[arg-type]
            result = export_report(payload=_simple_payload(), run_output_dir=run_dir, pdf=True)
            assert result.pdf_path is None
            assert result.pdf_skipped_reason in {"weasyprint_unavailable", "render_error"}
        finally:
            if had is not None:
                sys.modules["weasyprint"] = had

    def test_pdf_skipped_when_pdf_false(self, run_dir):
        result = export_report(payload=_simple_payload(), run_output_dir=run_dir, pdf=False)
        assert result.pdf_path is None
        assert result.pdf_skipped_reason is None


# ---------------------------------------------------------------------------
# Mini integration: submit_step → assemble_payload → export
# ---------------------------------------------------------------------------


class TestMiniPipeline:
    def test_two_step_form_then_payload_assembly(self):
        st = _state(status="pending", expected_step="scope")
        # Submit step 1.
        submit_step(
            dsl=DSL_TWO_STEPS, state=st, submitted_step_id="scope",
            payload={"report_date": "2026-05-18"},
        )
        assert st.status == "awaiting_step"
        # Submit final step.
        submit_step(
            dsl=DSL_TWO_STEPS, state=st, submitted_step_id="equipment",
            payload={"equipment_ids": "P-001"},
        )
        assert st.status == "ready_for_data"
        # Pretend data steps ran and store outputs.
        st.step_outputs["k"] = {
            "daily_kpi": {"summary": "ok", "alarms": [], "trend_chart": {"series": [{"type": "line"}]},
                          "kpis": [{"title": "x", "value": "1"}]}
        }
        st.status = "data_complete"
        # Assemble.
        payload = assemble_payload(dsl={**DSL_TWO_STEPS, **DSL_WITH_SECTIONS, "form_steps": DSL_TWO_STEPS["form_steps"]}, state=st)
        assert payload["title"] == "Demo"
        assert payload["parameters"]["report_date"] == "2026-05-18"
