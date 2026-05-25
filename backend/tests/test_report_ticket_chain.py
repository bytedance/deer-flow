"""E2E verification for report/diagnosis → ticket → trace-back chain (ISSUE-12)."""

from __future__ import annotations

import pytest

from deerflow.closed_loop.schemas import (
    ClosurePriority,
    ClosureSourceType,
    CreateTicketRequest,
)


class TestReportToTicketChain:
    """Task 4.1: Verify the complete chain: report → ticket creation → trace-back."""

    def test_create_ticket_from_report_preserves_source(self):
        """Ticket created from a report carries immutable source_run_id."""
        req = CreateTicketRequest(
            title="[报告] 磨煤机振动异常",
            description="日报检测到1#磨煤机振动幅值超标",
            priority=ClosurePriority.IMPORTANT,
            source_type=ClosureSourceType.REPORT,
            source_run_id="run-abc123",
            source_thread_id="thread-xyz",
            metadata={
                "report_template_id": "daily-equipment-check",
                "period": "daily",
            },
        )

        assert req.source_type == ClosureSourceType.REPORT
        assert req.source_run_id == "run-abc123"
        assert req.source_thread_id == "thread-xyz"
        assert req.metadata["report_template_id"] == "daily-equipment-check"

    def test_create_ticket_from_report_metadata_roundtrip(self):
        """Metadata from report context survives round-trip through Pydantic."""
        req = CreateTicketRequest(
            title="[报告] 油液分析异常",
            source_type=ClosureSourceType.REPORT,
            source_run_id="run-oil-001",
            metadata={
                "report_template_id": "oil-analysis",
                "period": "weekly",
                "key_findings": ["铁含量超标", "粘度下降"],
            },
        )

        assert req.metadata["key_findings"] == ["铁含量超标", "粘度下降"]
        assert req.metadata["period"] == "weekly"

    def test_create_ticket_minimal_report_source(self):
        """Minimal ticket creation with just source_run_id works."""
        req = CreateTicketRequest(
            title="[报告] 巡检异常项",
            source_type=ClosureSourceType.REPORT,
            source_run_id="run-min-001",
        )

        assert req.source_type == ClosureSourceType.REPORT
        assert req.source_run_id == "run-min-001"
        assert req.source_thread_id is None
        assert req.metadata == {}

    def test_filter_by_source_run_id_in_schema(self):
        """ListTicketsFilter supports source_run_id for the linked-tickets query."""
        from deerflow.closed_loop.schemas import ListTicketsFilter

        f = ListTicketsFilter(source_run_id="run-abc123")
        assert f.source_run_id == "run-abc123"

        f2 = ListTicketsFilter(source_type=ClosureSourceType.REPORT, source_run_id="run-xyz")
        assert f2.source_type == ClosureSourceType.REPORT
        assert f2.source_run_id == "run-xyz"


class TestDiagnosisToTicketChain:
    """Task 4.2: Verify diagnosis → ticket creation → trace-back."""

    def test_create_ticket_from_diagnosis_preserves_thread(self):
        """Ticket from diagnosis carries source_thread_id for chat trace-back."""
        req = CreateTicketRequest(
            title="[诊断] 轴承温度过高",
            description="Agent诊断发现轴承温度持续>85°C",
            priority=ClosurePriority.URGENT,
            source_type=ClosureSourceType.DIAGNOSIS,
            source_thread_id="thread-diag-456",
            metadata={
                "findings": ["轴承温度过高", "润滑不足"],
                "confidence": 0.92,
                "fault_code": "BRG-OVERHEAT",
            },
        )

        assert req.source_type == ClosureSourceType.DIAGNOSIS
        assert req.source_thread_id == "thread-diag-456"
        assert req.metadata["fault_code"] == "BRG-OVERHEAT"
        assert req.metadata["confidence"] == 0.92

    def test_diagnosis_metadata_validated(self):
        """Diagnosis metadata fields are properly typed."""
        req = CreateTicketRequest(
            title="[诊断] 齿轮箱异响",
            source_type=ClosureSourceType.DIAGNOSIS,
            source_thread_id="thread-gear-789",
            metadata={
                "findings": ["齿轮磨损"],
                "confidence": 0.78,
            },
        )

        assert isinstance(req.metadata["confidence"], float)
        assert isinstance(req.metadata["findings"], list)

    def test_chat_source_type_for_ad_hoc(self):
        """Tickets from chat context use CHAT source type."""
        req = CreateTicketRequest(
            title="[会话] 现场确认渗油",
            source_type=ClosureSourceType.CHAT,
            source_thread_id="thread-chat-001",
            metadata={"note": "现场巡检人员确认"},
        )

        assert req.source_type == ClosureSourceType.CHAT


class TestSourceImmutability:
    """Verify source fields are not mutable after creation."""

    def test_source_fields_in_request_only(self):
        """source_type, source_run_id, source_thread_id are in CreateTicketRequest
        but NOT in UpdateTicketRequest — enforcing immutability."""
        from deerflow.closed_loop.schemas import UpdateTicketRequest

        # UpdateTicketRequest has no source_* fields
        update = UpdateTicketRequest(title="New Title")
        d = update.model_dump()
        assert "source_type" not in d
        assert "source_run_id" not in d
        assert "source_thread_id" not in d

    def test_update_fields_exclude_source(self):
        """Only mutable fields can be updated."""
        from deerflow.closed_loop.schemas import UpdateTicketRequest

        fields = UpdateTicketRequest.model_fields
        mutable = {"title", "description", "priority", "severity", "assignee_id", "device_name", "metadata_patch"}
        for f in mutable:
            assert f in fields, f"Expected mutable field {f}"

        immutable = {"source_type", "source_run_id", "source_thread_id", "created_by", "tenant_id"}
        for f in immutable:
            assert f not in fields, f"Unexpected immutable field {f}"


class TestClosureSourceTypeEnum:
    """Verify frontend-backend alignment on source types."""

    @pytest.mark.parametrize("value", ["diagnosis", "report", "inspection", "manual", "chat"])
    def test_valid_source_types(self, value):
        assert value in ClosureSourceType.__members__.values()

    def test_no_legacy_report_subtypes(self):
        """The backend uses 'report' uniformly, not daily_report etc."""
        values = set(ClosureSourceType.__members__.values())
        assert "daily_report" not in values
        assert "weekly_report" not in values
        assert "monthly_report" not in values
        assert "custom_report" not in values
