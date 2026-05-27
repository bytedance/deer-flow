"""Tests for industrial template marketplace: featured category, search boost, and usage tracking.

Covers tasks from the industrial-intelligence-primary-track change:
- is_featured field on template metadata
- Auto-set is_featured for industrial category
- Search boost for featured templates
- Usage tracking (install_count, run_count)
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from deerflow.report_templates.records import (
    ReportTemplateRecord,
    IndexEntry,
)
from deerflow.report_templates.repository import (
    FileSystemReportTemplateRepository,
    Scope,
)


@pytest.fixture
def temp_repo():
    """Create a temporary repository for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = FileSystemReportTemplateRepository(base_dir=Path(tmpdir))
        yield repo


class TestFeaturedField:
    """Tests for is_featured field on template metadata."""

    def test_template_record_has_is_featured_field(self):
        """ReportTemplateRecord should have is_featured boolean field."""
        from deerflow.report_templates.records import now_iso
        import uuid

        record = ReportTemplateRecord(
            id="tpl_TEST000000000000000001",
            name="test",
            display_name="Test Template",
            owner_user_id="user-1",
            tenant_id="tenant-1",
            created_at=now_iso(),
            updated_at=now_iso(),
            etag=uuid.uuid4().hex,
            is_featured=True,
        )
        assert record.is_featured is True

    def test_template_record_default_not_featured(self):
        """Templates are not featured by default."""
        from deerflow.report_templates.records import now_iso
        import uuid

        record = ReportTemplateRecord(
            id="tpl_TEST000000000000000002",
            name="test",
            display_name="Test Template",
            owner_user_id="user-1",
            tenant_id="tenant-1",
            created_at=now_iso(),
            updated_at=now_iso(),
            etag=uuid.uuid4().hex,
        )
        assert record.is_featured is False

    def test_index_entry_has_is_featured_field(self):
        """IndexEntry should have is_featured field for marketplace listing."""
        from deerflow.report_templates.records import now_iso

        entry = IndexEntry(
            id="tpl_TEST000000000000000003",
            name="test",
            display_name="Test Template",
            visibility="tenant",
            status="published",
            current_version=1,
            updated_at=now_iso(),
            is_featured=True,
            category="industrial",
        )
        assert entry.is_featured is True
        assert entry.category == "industrial"


class TestAutoFeatureIndustrial:
    """Tests for auto-setting is_featured on industrial templates."""

    def test_create_industrial_template_auto_featured(self, temp_repo):
        """Creating a template with category='industrial' should auto-set is_featured=True."""
        scope = Scope.tenant("tenant-1")
        record = temp_repo.create_template(
            scope=scope,
            name="industrial-report",
            display_name="Industrial Report",
            owner_user_id="user-1",
            tenant_id="tenant-1",
            category="industrial",
        )
        assert record.category == "industrial"
        assert record.is_featured is True

    def test_create_non_industrial_template_not_featured(self, temp_repo):
        """Creating a template with other category should not auto-set is_featured."""
        scope = Scope.tenant("tenant-1")
        record = temp_repo.create_template(
            scope=scope,
            name="general-report",
            display_name="General Report",
            owner_user_id="user-1",
            tenant_id="tenant-1",
            category="general",
        )
        assert record.category == "general"
        assert record.is_featured is False

    def test_create_template_without_category_not_featured(self, temp_repo):
        """Creating a template without category should not auto-set is_featured."""
        scope = Scope.tenant("tenant-1")
        record = temp_repo.create_template(
            scope=scope,
            name="basic-report",
            display_name="Basic Report",
            owner_user_id="user-1",
            tenant_id="tenant-1",
        )
        assert record.category is None
        assert record.is_featured is False


class TestUsageTracking:
    """Tests for install_count and run_count tracking."""

    def test_template_record_has_usage_fields(self):
        """ReportTemplateRecord should have install_count and run_count."""
        from deerflow.report_templates.records import now_iso
        import uuid

        record = ReportTemplateRecord(
            id="tpl_TEST000000000000000004",
            name="test",
            display_name="Test Template",
            owner_user_id="user-1",
            tenant_id="tenant-1",
            created_at=now_iso(),
            updated_at=now_iso(),
            etag=uuid.uuid4().hex,
            install_count=10,
            run_count=25,
        )
        assert record.install_count == 10
        assert record.run_count == 25

    def test_template_record_default_usage_zero(self):
        """Usage counters should default to zero."""
        from deerflow.report_templates.records import now_iso
        import uuid

        record = ReportTemplateRecord(
            id="tpl_TEST000000000000000005",
            name="test",
            display_name="Test Template",
            owner_user_id="user-1",
            tenant_id="tenant-1",
            created_at=now_iso(),
            updated_at=now_iso(),
            etag=uuid.uuid4().hex,
        )
        assert record.install_count == 0
        assert record.run_count == 0

    def test_index_entry_has_usage_fields(self):
        """IndexEntry should have usage tracking fields."""
        from deerflow.report_templates.records import now_iso

        entry = IndexEntry(
            id="tpl_TEST000000000000000006",
            name="test",
            display_name="Test Template",
            visibility="tenant",
            status="published",
            current_version=1,
            updated_at=now_iso(),
            install_count=5,
            run_count=15,
        )
        assert entry.install_count == 5
        assert entry.run_count == 15


class TestSearchBoost:
    """Tests for search result ordering with featured templates."""

    def test_featured_templates_appear_first(self, temp_repo):
        """Featured templates should appear before non-featured in listings."""
        scope = Scope.tenant("tenant-1")

        # Create non-featured template
        temp_repo.create_template(
            scope=scope,
            name="general-report",
            display_name="General Report",
            owner_user_id="user-1",
            tenant_id="tenant-1",
            category="general",
        )

        # Create featured industrial template
        temp_repo.create_template(
            scope=scope,
            name="industrial-report",
            display_name="Industrial Report",
            owner_user_id="user-1",
            tenant_id="tenant-1",
            category="industrial",
        )

        # List templates
        templates = temp_repo.list_templates(scope)

        # Featured should appear first
        assert len(templates) == 2
        assert templates[0].is_featured is True
        assert templates[1].is_featured is False
