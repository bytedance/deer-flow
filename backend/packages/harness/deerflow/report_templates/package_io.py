"""Template package import/export — ZIP archive I/O.

Exports a template (DSL + metadata) to a `.template` ZIP archive and imports
it back with validation.
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

import yaml
from pydantic import ValidationError

from deerflow.report_templates.package_format import (
    PACKAGE_BLUEPRINT_JSON,
    PACKAGE_METADATA_JSON,
    PACKAGE_README_MD,
    PACKAGE_TEMPLATE_YAML,
    PackageBlueprintOrigin,
    PackageMetadata,
    validate_package_contents,
)
from deerflow.report_templates.records import (
    ReportTemplateRecord,
    ReportTemplateVersionRecord,
)


class PackageExportResult:
    """Result of exporting a template to a package."""

    def __init__(self, data: bytes, filename: str):
        self.data = data
        self.filename = filename


class PackageImportResult:
    """Result of importing a template from a package."""

    def __init__(
        self,
        dsl: dict[str, Any],
        dsl_yaml: str,
        metadata: PackageMetadata,
        blueprint_origin: PackageBlueprintOrigin | None = None,
        readme: str | None = None,
    ):
        self.dsl = dsl
        self.dsl_yaml = dsl_yaml
        self.metadata = metadata
        self.blueprint_origin = blueprint_origin
        self.readme = readme


def export_template_package(
    template: ReportTemplateRecord,
    version: ReportTemplateVersionRecord,
    blueprint_origin: PackageBlueprintOrigin | None = None,
    exported_by: str | None = None,
) -> PackageExportResult:
    """Export a template version to a .template ZIP archive.

    Args:
        template: Template metadata record
        version: Template version record containing DSL
        blueprint_origin: Optional blueprint origin info
        exported_by: User ID performing the export

    Returns:
        PackageExportResult with ZIP bytes and suggested filename
    """
    buf = io.BytesIO()

    metadata = PackageMetadata(
        template_id=template.id,
        template_version=version.version,
        display_name=template.display_name,
        description=template.description,
        visibility=template.visibility,
        owner_user_id=template.owner_user_id if template.visibility == "private" else None,
        tenant_id=template.tenant_id if template.visibility in ("tenant", "builtin") else None,
        tags=template.tags,
        exported_by=exported_by,
        dsl_version=template.dsl_version,
    )

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(PACKAGE_TEMPLATE_YAML, version.dsl_yaml)
        zf.writestr(PACKAGE_METADATA_JSON, metadata.model_dump_json(indent=2))

        if blueprint_origin is not None:
            zf.writestr(PACKAGE_BLUEPRINT_JSON, blueprint_origin.model_dump_json(indent=2))

        if template.description:
            readme = f"# {template.display_name}\n\n{template.description}\n"
            zf.writestr(PACKAGE_README_MD, readme)

    filename = f"{template.name}_v{version.version}.template"
    return PackageExportResult(data=buf.getvalue(), filename=filename)


def import_template_package(data: bytes) -> PackageImportResult:
    """Import a template from a .template ZIP archive.

    Args:
        data: ZIP file bytes

    Returns:
        PackageImportResult with extracted DSL and metadata

    Raises:
        ValueError: If package is invalid or malformed
    """
    try:
        buf = io.BytesIO(data)
        with zipfile.ZipFile(buf, "r") as zf:
            files = {name: zf.read(name) for name in zf.namelist()}
    except zipfile.BadZipFile as e:
        raise ValueError(f"invalid ZIP archive: {e}") from e

    errors = validate_package_contents(files)
    if errors:
        raise ValueError(f"invalid package: {'; '.join(errors)}")

    try:
        dsl_yaml = files[PACKAGE_TEMPLATE_YAML].decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"template.yaml is not valid UTF-8: {e}") from e

    try:
        dsl = yaml.safe_load(dsl_yaml)
    except yaml.YAMLError as e:
        raise ValueError(f"template.yaml is not valid YAML: {e}") from e

    if not isinstance(dsl, dict):
        raise ValueError("template.yaml must contain a YAML mapping (not a list or scalar)")

    try:
        metadata_json = files[PACKAGE_METADATA_JSON].decode("utf-8")
        metadata = PackageMetadata.model_validate_json(metadata_json)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as e:
        raise ValueError(f"metadata.json is not valid JSON: {e}") from e
    except Exception as e:
        raise ValueError(f"metadata.json is not valid: {e}") from e

    blueprint_origin = None
    if PACKAGE_BLUEPRINT_JSON in files:
        try:
            blueprint_json = files[PACKAGE_BLUEPRINT_JSON].decode("utf-8")
            blueprint_origin = PackageBlueprintOrigin.model_validate_json(blueprint_json)
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as e:
            raise ValueError(f"blueprint.json is not valid JSON: {e}") from e
        except Exception as e:
            raise ValueError(f"blueprint.json is not valid: {e}") from e

    readme = None
    if PACKAGE_README_MD in files:
        try:
            readme = files[PACKAGE_README_MD].decode("utf-8")
        except UnicodeDecodeError:
            pass

    return PackageImportResult(
        dsl=dsl,
        dsl_yaml=dsl_yaml,
        metadata=metadata,
        blueprint_origin=blueprint_origin,
        readme=readme,
    )
