"""E2E traceability verification — template → version → run → payload → artifact.

Validates the complete chain defined by ``establish-report-template-to-artifact-traceability``:
- Run record references correct template version
- Payload contains template and run metadata
- Artifact paths point to existing files
- Data step outputs are discoverable
"""

from __future__ import annotations

import json
from pathlib import Path

from deerflow.report_templates.records import (
    ReportRunErrorCode,
    ReportRunRecord,
    new_report_run_id,
    now_iso,
)
from deerflow.report_templates.runtime.exporter import export_report
from deerflow.report_templates.runtime.payload_builder import assemble_payload
from deerflow.report_templates.runtime.state import (
    RuntimeState,
    mark_cancelled,
    mark_failed,
    read_state,
    write_state,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state(**overrides) -> RuntimeState:
    base = {
        "report_run_id": "rr_AAAAAAAAAAAAAAAAAAAAAAAA",
        "thread_id": "thread-trace-1",
        "template_id": "tpl_BBBBBBBBBBBBBBBBBBBBBBBB",
        "template_version": 3,
        "template_version_ref": "v3",
        "status": "data_complete",
        "nonce": "n1",
        "created_at": "2026-05-22T00:00:00+00:00",
        "step_outputs": {
            "k": {
                "daily_kpi": {
                    "summary": "Equipment status normal",
                    "alarms": [{"id": 1, "device": "Pump-A", "severity": "high"}],
                    "trend_chart": {"series": [{"type": "line", "data": [1, 2, 3]}]},
                    "kpis": [{"title": "Runtime", "value": "99.7%"}],
                }
            }
        },
        "form_state": {
            "scope": {"report_date": "2026-05-22", "equipment_ids": ["P-001", "P-002"]},
        },
    }
    base.update(overrides)
    return RuntimeState(**base)


MINIMAL_DSL: dict = {
    "name": "traceability-demo",
    "display_name": "Traceability Demo",
    "sections": [
        {
            "id": "s1",
            "title": "Overview",
            "component": "markdown",
            "source": "$.steps.k.daily_kpi.summary",
        },
        {
            "id": "s2",
            "title": "Alarms",
            "component": "table",
            "source": "$.steps.k.daily_kpi.alarms",
        },
    ],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFullChainTraceability:
    """Verify the complete chain: template version → run record → payload → artifacts."""

    def test_run_record_references_template_version(self):
        """A ReportRunRecord must carry template_id + template_version for traceability."""
        record = ReportRunRecord(
            id=new_report_run_id(),
            template_id="tpl_BBBBBBBBBBBBBBBBBBBBBBBB",
            template_version=3,
            template_version_ref="v3",
            thread_id="thread-trace-1",
            run_id="run-1",
            user_id="alice",
            tenant_id="tenant-a",
            status="success",
            created_at=now_iso(),
        )
        assert record.template_id == "tpl_BBBBBBBBBBBBBBBBBBBBBBBB"
        assert record.template_version == 3
        assert record.template_version_ref == "v3"

    def test_payload_contains_template_metadata(self):
        """The assembled payload must embed template id, version, and name."""
        st = _state()
        payload = assemble_payload(dsl=MINIMAL_DSL, state=st)

        assert payload["template"]["id"] == st.template_id
        assert payload["template"]["version"] == st.template_version
        assert payload["template"]["name"] == "traceability-demo"

    def test_payload_contains_run_metadata(self):
        """The assembled payload must embed run id and thread id."""
        st = _state()
        payload = assemble_payload(dsl=MINIMAL_DSL, state=st)

        assert payload["run"]["id"] == st.report_run_id
        assert payload["run"]["thread_id"] == st.thread_id
        assert "generated_at" in payload["run"]

    def test_payload_contains_parameters(self):
        """The assembled payload must flatten form state into parameters."""
        st = _state()
        payload = assemble_payload(dsl=MINIMAL_DSL, state=st)

        assert payload["parameters"]["report_date"] == "2026-05-22"
        assert payload["parameters"]["equipment_ids"] == ["P-001", "P-002"]

    def test_artifact_export_produces_existing_files(self, tmp_path: Path):
        """Export must produce md_path that points to an existing file."""
        st = _state()
        payload = assemble_payload(dsl=MINIMAL_DSL, state=st)

        run_dir = tmp_path / "run"
        run_dir.mkdir()
        exports_dir = run_dir / "exports"
        exports_dir.mkdir(parents=True)

        result = export_report(payload=payload, run_output_dir=run_dir, pdf=False)

        md_path = Path(result.md_path)
        assert md_path.exists()
        content = md_path.read_text(encoding="utf-8")
        assert "Equipment status normal" in content

    def test_data_files_are_discoverable(self, tmp_path: Path):
        """Data step outputs under data/ must be listable for traceability."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "daily_kpi.json").write_text('{"summary": "ok"}', encoding="utf-8")
        (data_dir / "alarms.json").write_text('[{"id": 1}]', encoding="utf-8")

        json_files = sorted(
            f.name for f in data_dir.iterdir() if f.suffix == ".json"
        )
        assert json_files == ["alarms.json", "daily_kpi.json"]

    def test_mark_failed_sets_error_code(self):
        """mark_failed must store error_code for traceability of failure reasons."""
        st = _state(status="data_complete")
        mark_failed(st, code=ReportRunErrorCode.DATA_STEP_FAILED, message="[data1] script timeout")

        assert st.status == "failed"
        assert st.error_code == ReportRunErrorCode.DATA_STEP_FAILED
        assert "data1" in st.error_message

    def test_mark_cancelled_sets_run_interrupted(self):
        """mark_cancelled must set RUN_INTERRUPTED error code."""
        st = _state(status="awaiting_step")
        mark_cancelled(st, code=ReportRunErrorCode.RUN_INTERRUPTED)

        assert st.status == "cancelled"
        assert st.error_code == ReportRunErrorCode.RUN_INTERRUPTED

    def test_state_round_trip_preserves_traceability_fields(self, tmp_path: Path):
        """After write_state + read_state, template version fields must survive."""
        st = _state()
        write_state(tmp_path, st)
        loaded = read_state(tmp_path)

        assert loaded.template_id == st.template_id
        assert loaded.template_version == st.template_version
        assert loaded.template_version_ref == st.template_version_ref
        assert loaded.report_run_id == st.report_run_id
        assert loaded.thread_id == st.thread_id

    def test_mini_pipeline_produces_traceable_artifacts(self, tmp_path: Path):
        """Full pipeline: assemble → export → verify all chain links."""
        st = _state()
        payload = assemble_payload(dsl=MINIMAL_DSL, state=st)

        run_dir = tmp_path / "run"
        run_dir.mkdir()

        # Write payload to disk (simulating assemble_payload tool)
        payload_path = run_dir / "report_payload.json"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        # Export
        result = export_report(payload=payload, run_output_dir=run_dir, pdf=False)

        # Chain verification
        md_path = Path(result.md_path)
        assert md_path.exists(), "Markdown artifact must exist"

        # Payload → template traceability
        assert payload["template"]["id"] == st.template_id
        assert payload["template"]["version"] == st.template_version

        # Payload → run traceability
        assert payload["run"]["id"] == st.report_run_id
        assert payload["run"]["thread_id"] == st.thread_id

        # Parameters carry input traceability
        assert "report_date" in payload["parameters"]

        # Artifact path is within the expected run directory
        assert str(run_dir) in str(md_path)


class TestKnowledgeSourcesRecording:
    """Verify knowledge_sources are captured and persisted through the chain."""

    def test_runtime_state_stores_knowledge_sources(self):
        st = _state(knowledge_sources=[{"selected_ids": ["kb-1", "kb-2"], "source": "runtime"}])
        assert len(st.knowledge_sources) == 1
        assert st.knowledge_sources[0]["selected_ids"] == ["kb-1", "kb-2"]
        assert st.knowledge_sources[0]["source"] == "runtime"

    def test_state_round_trip_preserves_knowledge_sources(self, tmp_path: Path):
        st = _state(knowledge_sources=[{"selected_ids": ["kb-1"], "source": "runtime"}])
        write_state(tmp_path, st)
        loaded = read_state(tmp_path)
        assert loaded.knowledge_sources == st.knowledge_sources

    def test_state_round_trip_preserves_empty_knowledge_sources(self, tmp_path: Path):
        st = _state(knowledge_sources=[])
        write_state(tmp_path, st)
        loaded = read_state(tmp_path)
        assert loaded.knowledge_sources == []

    def test_report_run_record_stores_trigger_type(self):
        record = ReportRunRecord(
            id=new_report_run_id(),
            template_id="tpl_BBBBBBBBBBBBBBBBBBBBBBBB",
            template_version=3,
            thread_id="thread-1",
            run_id="run-1",
            user_id="alice",
            tenant_id="tenant-a",
            status="pending",
            trigger_type="manual",
            created_at=now_iso(),
        )
        assert record.trigger_type == "manual"

    def test_report_run_record_stores_knowledge_sources(self):
        record = ReportRunRecord(
            id=new_report_run_id(),
            template_id="tpl_BBBBBBBBBBBBBBBBBBBBBBBB",
            template_version=3,
            thread_id="thread-1",
            run_id="run-1",
            user_id="alice",
            tenant_id="tenant-a",
            status="pending",
            knowledge_sources=[{"selected_ids": ["kb-1"], "source": "runtime"}],
            created_at=now_iso(),
        )
        assert len(record.knowledge_sources) == 1
        assert record.knowledge_sources[0]["selected_ids"] == ["kb-1"]

    def test_report_run_record_serializes_knowledge_sources(self):
        record = ReportRunRecord(
            id=new_report_run_id(),
            template_id="tpl_BBBBBBBBBBBBBBBBBBBBBBBB",
            template_version=3,
            thread_id="thread-1",
            run_id="run-1",
            user_id="alice",
            tenant_id="tenant-a",
            status="pending",
            knowledge_sources=[{"selected_ids": ["kb-1"], "source": "runtime"}],
            trigger_type="manual",
            created_at=now_iso(),
        )
        data = record.model_dump()
        assert data["knowledge_sources"] == [{"selected_ids": ["kb-1"], "source": "runtime"}]
        assert data["trigger_type"] == "manual"

    def test_report_run_record_defaults(self):
        record = ReportRunRecord(
            id=new_report_run_id(),
            template_id="tpl_BBBBBBBBBBBBBBBBBBBBBBBB",
            thread_id="thread-1",
            run_id="run-1",
            user_id="alice",
            tenant_id="tenant-a",
            created_at=now_iso(),
        )
        assert record.knowledge_sources == []
        assert record.trigger_type == "manual"


class TestArtifactLineageRecording:
    """Verify artifact paths are recorded in the run record."""

    def test_run_record_stores_artifact_paths(self):
        record = ReportRunRecord(
            id=new_report_run_id(),
            template_id="tpl_BBBBBBBBBBBBBBBBBBBBBBBB",
            template_version=3,
            thread_id="thread-1",
            run_id="run-1",
            user_id="alice",
            tenant_id="tenant-a",
            status="success",
            artifact_paths={"md": "/tmp/report.md", "pdf": None},
            pdf_skipped_reason="weasyprint_unavailable",
            created_at=now_iso(),
        )
        assert record.artifact_paths["md"] == "/tmp/report.md"
        assert record.artifact_paths["pdf"] is None
        assert record.pdf_skipped_reason == "weasyprint_unavailable"

    def test_run_record_stores_report_payload_path(self):
        record = ReportRunRecord(
            id=new_report_run_id(),
            template_id="tpl_BBBBBBBBBBBBBBBBBBBBBBBB",
            template_version=3,
            thread_id="thread-1",
            run_id="run-1",
            user_id="alice",
            tenant_id="tenant-a",
            status="pending",
            report_payload_path="/tmp/report_payload.json",
            created_at=now_iso(),
        )
        assert record.report_payload_path == "/tmp/report_payload.json"


class TestFailureSemantics:
    """Verify the three error categories have clear semantics."""

    def test_template_unavailable_error_code(self):
        """TEMPLATE_UNAVAILABLE must be a distinct error code constant."""
        assert ReportRunErrorCode.TEMPLATE_UNAVAILABLE == "TEMPLATE_UNAVAILABLE"

    def test_kb_unavailable_error_code(self):
        """KB_UNAVAILABLE must be a distinct error code constant."""
        assert ReportRunErrorCode.KB_UNAVAILABLE == "KB_UNAVAILABLE"

    def test_run_interrupted_error_code(self):
        """RUN_INTERRUPTED must be a distinct error code constant."""
        assert ReportRunErrorCode.RUN_INTERRUPTED == "RUN_INTERRUPTED"

    def test_mark_failed_with_template_unavailable(self):
        """mark_failed must accept TEMPLATE_UNAVAILABLE error code."""
        st = _state(status="pending")
        mark_failed(st, code=ReportRunErrorCode.TEMPLATE_UNAVAILABLE, message="template is archived")
        assert st.status == "failed"
        assert st.error_code == "TEMPLATE_UNAVAILABLE"

    def test_mark_failed_with_kb_unavailable(self):
        """mark_failed must accept KB_UNAVAILABLE error code."""
        st = _state(status="ready_for_data")
        mark_failed(st, code=ReportRunErrorCode.KB_UNAVAILABLE, message="knowledge base kb-1 not found")
        assert st.status == "failed"
        assert st.error_code == "KB_UNAVAILABLE"

    def test_mark_cancelled_defaults_to_run_interrupted(self):
        """mark_cancelled must default to RUN_INTERRUPTED code."""
        st = _state(status="awaiting_step")
        mark_cancelled(st)
        assert st.status == "cancelled"
        assert st.error_code == "RUN_INTERRUPTED"
        assert st.error_message == "Report run was cancelled"

    def test_error_messages_are_preserved_in_state_round_trip(self, tmp_path: Path):
        """Error code and message must survive write+read."""
        st = _state(status="failed", error_code="KB_UNAVAILABLE", error_message="kb-1 deleted")
        write_state(tmp_path, st)
        loaded = read_state(tmp_path)
        assert loaded.error_code == "KB_UNAVAILABLE"
        assert loaded.error_message == "kb-1 deleted"
        assert loaded.status == "failed"

    def test_run_record_preserves_error_semantics(self):
        """ReportRunRecord must carry error_code for traceability."""
        record = ReportRunRecord(
            id=new_report_run_id(),
            template_id="tpl_BBBBBBBBBBBBBBBBBBBBBBBB",
            template_version=3,
            thread_id="thread-1",
            run_id="run-1",
            user_id="alice",
            tenant_id="tenant-a",
            status="failed",
            error_code="TEMPLATE_UNAVAILABLE",
            error_message="template is archived and cannot be run",
            created_at=now_iso(),
        )
        assert record.error_code == "TEMPLATE_UNAVAILABLE"
        assert "archived" in record.error_message
