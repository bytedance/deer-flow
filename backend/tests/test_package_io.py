"""Tests for template package import/export functionality."""

import io
import json
import zipfile

import pytest
import yaml

from deerflow.report_templates.package_format import (
    PACKAGE_BLUEPRINT_JSON,
    PACKAGE_METADATA_JSON,
    PACKAGE_README_MD,
    PACKAGE_TEMPLATE_YAML,
    PackageBlueprintOrigin,
    PackageMetadata,
)
from deerflow.report_templates.package_io import (
    PackageExportResult,
    PackageImportResult,
    export_template_package,
    import_template_package,
)
from deerflow.report_templates.records import (
    ReportTemplateRecord,
    ReportTemplateVersionRecord,
)


@pytest.fixture
def sample_template() -> ReportTemplateRecord:
    """Create a sample template record for testing."""
    return ReportTemplateRecord(
        id="tpl_ABCDEFGHIJ0123456789",
        name="test-template",
        display_name="Test Template",
        description="A test template for unit tests",
        owner_user_id="test-user",
        tenant_id="test-tenant",
        visibility="private",
        status="published",
        current_version=1,
        dsl_version="1",
        tags=["test", "unit-test"],
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        etag="abc123",
    )


@pytest.fixture
def sample_version() -> ReportTemplateVersionRecord:
    """Create a sample version record for testing."""
    dsl = {
        "name": "test-report",
        "form_steps": [
            {
                "id": "step1",
                "title": "Step 1",
                "fields": [
                    {"name": "field1", "type": "text", "label": "Field 1"}
                ],
            }
        ],
        "sections": [
            {
                "id": "section1",
                "title": "Section 1",
                "component": "markdown",
                "source": "$.data.content",
            }
        ],
    }
    dsl_yaml = yaml.dump(dsl)

    return ReportTemplateVersionRecord(
        template_id="tpl_ABCDEFGHIJ0123456789",
        version=1,
        dsl=dsl,
        dsl_yaml=dsl_yaml,
        checksum="abc123def456",
        created_by="test-user",
        created_at="2026-01-01T00:00:00Z",
        changelog="Initial version",
    )


@pytest.fixture
def sample_blueprint_origin() -> PackageBlueprintOrigin:
    """Create a sample blueprint origin for testing."""
    return PackageBlueprintOrigin(
        blueprint_id="daily-equipment",
        blueprint_version="1.0",
        derived_at="2026-01-01T00:00:00Z",
    )


class TestExportTemplatePackage:
    """Tests for export_template_package function."""

    def test_export_basic_package(self, sample_template, sample_version):
        """Test exporting a basic template package."""
        result = export_template_package(sample_template, sample_version)

        assert isinstance(result, PackageExportResult)
        assert isinstance(result.data, bytes)
        assert result.filename == "test-template_v1.template"

        # Verify ZIP contents
        with zipfile.ZipFile(io.BytesIO(result.data), "r") as zf:
            names = zf.namelist()
            assert PACKAGE_TEMPLATE_YAML in names
            assert PACKAGE_METADATA_JSON in names

            # Verify template.yaml content
            dsl_yaml = zf.read(PACKAGE_TEMPLATE_YAML).decode("utf-8")
            assert "form_steps" in dsl_yaml

            # Verify metadata.json content
            metadata_json = zf.read(PACKAGE_METADATA_JSON).decode("utf-8")
            metadata = json.loads(metadata_json)
            assert metadata["template_id"] == "tpl_ABCDEFGHIJ0123456789"
            assert metadata["template_version"] == 1
            assert metadata["display_name"] == "Test Template"

    def test_export_with_blueprint_origin(
        self, sample_template, sample_version, sample_blueprint_origin
    ):
        """Test exporting a package with blueprint origin."""
        result = export_template_package(
            sample_template, sample_version, blueprint_origin=sample_blueprint_origin
        )

        with zipfile.ZipFile(io.BytesIO(result.data), "r") as zf:
            names = zf.namelist()
            assert PACKAGE_BLUEPRINT_JSON in names

            blueprint_json = zf.read(PACKAGE_BLUEPRINT_JSON).decode("utf-8")
            blueprint = json.loads(blueprint_json)
            assert blueprint["blueprint_id"] == "daily-equipment"
            assert blueprint["blueprint_version"] == "1.0"

    def test_export_with_exported_by(self, sample_template, sample_version):
        """Test exporting with exported_by user ID."""
        result = export_template_package(
            sample_template, sample_version, exported_by="admin-user"
        )

        with zipfile.ZipFile(io.BytesIO(result.data), "r") as zf:
            metadata_json = zf.read(PACKAGE_METADATA_JSON).decode("utf-8")
            metadata = json.loads(metadata_json)
            assert metadata["exported_by"] == "admin-user"

    def test_export_includes_readme(self, sample_template, sample_version):
        """Test that export includes README.md when description exists."""
        result = export_template_package(sample_template, sample_version)

        with zipfile.ZipFile(io.BytesIO(result.data), "r") as zf:
            names = zf.namelist()
            assert PACKAGE_README_MD in names

            readme = zf.read(PACKAGE_README_MD).decode("utf-8")
            assert "Test Template" in readme
            assert "A test template for unit tests" in readme


class TestImportTemplatePackage:
    """Tests for import_template_package function."""

    def test_import_basic_package(self, sample_template, sample_version):
        """Test importing a basic template package."""
        export_result = export_template_package(sample_template, sample_version)
        import_result = import_template_package(export_result.data)

        assert isinstance(import_result, PackageImportResult)
        assert isinstance(import_result.dsl, dict)
        assert "form_steps" in import_result.dsl
        assert isinstance(import_result.dsl_yaml, str)
        assert isinstance(import_result.metadata, PackageMetadata)
        assert import_result.metadata.template_id == "tpl_ABCDEFGHIJ0123456789"
        assert import_result.metadata.template_version == 1
        assert import_result.blueprint_origin is None

    def test_import_with_blueprint_origin(
        self, sample_template, sample_version, sample_blueprint_origin
    ):
        """Test importing a package with blueprint origin."""
        export_result = export_template_package(
            sample_template, sample_version, blueprint_origin=sample_blueprint_origin
        )
        import_result = import_template_package(export_result.data)

        assert import_result.blueprint_origin is not None
        assert import_result.blueprint_origin.blueprint_id == "daily-equipment"
        assert import_result.blueprint_origin.blueprint_version == "1.0"

    def test_roundtrip_preserves_data(self, sample_template, sample_version):
        """Test that export/import roundtrip preserves all data."""
        export_result = export_template_package(sample_template, sample_version)
        import_result = import_template_package(export_result.data)

        # DSL should be preserved
        assert import_result.dsl == sample_version.dsl

        # Metadata should be preserved
        assert import_result.metadata.template_id == sample_template.id
        assert import_result.metadata.template_version == sample_version.version
        assert import_result.metadata.display_name == sample_template.display_name
        assert import_result.metadata.description == sample_template.description
        assert import_result.metadata.tags == sample_template.tags


class TestImportValidation:
    """Tests for package validation during import."""

    def test_import_invalid_zip(self):
        """Test importing invalid ZIP data raises ValueError."""
        with pytest.raises(ValueError, match="invalid ZIP archive"):
            import_template_package(b"not a zip file")

    def test_import_missing_template_yaml(self):
        """Test importing package without template.yaml."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            metadata = PackageMetadata(
                template_id="tpl_ABCDEFGHIJ0123456789",
                template_version=1,
                display_name="Test",
                visibility="private",
            )
            zf.writestr(PACKAGE_METADATA_JSON, metadata.model_dump_json())

        with pytest.raises(ValueError, match="missing required file: template.yaml"):
            import_template_package(buf.getvalue())

    def test_import_missing_metadata_json(self):
        """Test importing package without metadata.json."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(PACKAGE_TEMPLATE_YAML, "name: test")

        with pytest.raises(ValueError, match="missing required file: metadata.json"):
            import_template_package(buf.getvalue())

    def test_import_invalid_yaml(self):
        """Test importing package with invalid YAML."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(PACKAGE_TEMPLATE_YAML, "not: valid: yaml: [")
            metadata = PackageMetadata(
                template_id="tpl_ABCDEFGHIJ0123456789",
                template_version=1,
                display_name="Test",
                visibility="private",
            )
            zf.writestr(PACKAGE_METADATA_JSON, metadata.model_dump_json())

        with pytest.raises(ValueError, match="template.yaml is not valid YAML"):
            import_template_package(buf.getvalue())

    def test_import_yaml_not_mapping(self):
        """Test importing package where YAML is not a mapping."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(PACKAGE_TEMPLATE_YAML, "- item1\n- item2")
            metadata = PackageMetadata(
                template_id="tpl_ABCDEFGHIJ0123456789",
                template_version=1,
                display_name="Test",
                visibility="private",
            )
            zf.writestr(PACKAGE_METADATA_JSON, metadata.model_dump_json())

        with pytest.raises(ValueError, match="must contain a YAML mapping"):
            import_template_package(buf.getvalue())

    def test_import_invalid_metadata_json(self):
        """Test importing package with invalid metadata JSON."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(PACKAGE_TEMPLATE_YAML, "name: test")
            zf.writestr(PACKAGE_METADATA_JSON, "not valid json")

        with pytest.raises(ValueError, match="metadata.json is not valid JSON"):
            import_template_package(buf.getvalue())

    def test_import_invalid_blueprint_json(self):
        """Test importing package with invalid blueprint JSON."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(PACKAGE_TEMPLATE_YAML, "name: test")
            metadata = PackageMetadata(
                template_id="tpl_ABCDEFGHIJ0123456789",
                template_version=1,
                display_name="Test",
                visibility="private",
            )
            zf.writestr(PACKAGE_METADATA_JSON, metadata.model_dump_json())
            zf.writestr(PACKAGE_BLUEPRINT_JSON, "not valid json")

        with pytest.raises(ValueError, match="blueprint.json is not valid JSON"):
            import_template_package(buf.getvalue())
