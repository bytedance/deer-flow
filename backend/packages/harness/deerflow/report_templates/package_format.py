"""`.template` package format — ZIP archive for template import/export.

Package structure:
    template.zip (or template.template)
    ├── template.yaml        DSL v1 document (required)
    ├── metadata.json        Template metadata (required)
    ├── blueprint.json       Blueprint origin info (optional)
    └── README.md            Human-readable description (optional)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Package file names
PACKAGE_TEMPLATE_YAML = "template.yaml"
PACKAGE_METADATA_JSON = "metadata.json"
PACKAGE_BLUEPRINT_JSON = "blueprint.json"
PACKAGE_README_MD = "README.md"

# Package file extension
PACKAGE_EXTENSION = ".template"


class PackageMetadata(BaseModel):
    """Metadata stored in metadata.json inside the package."""

    model_config = ConfigDict(extra="forbid")

    package_version: str = Field(default="1", description="Package format version")
    template_id: str = Field(description="Original template ID")
    template_version: int = Field(description="Version number this package was exported from")
    display_name: str = Field(description="Human-readable template name")
    description: str = Field(default="", description="Template description")
    visibility: str = Field(description="Visibility at export time: private/tenant/builtin")
    owner_user_id: str | None = Field(default=None, description="Owner user ID (if private)")
    tenant_id: str | None = Field(default=None, description="Tenant ID (if tenant-scoped)")
    tags: list[str] = Field(default_factory=list)
    exported_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    exported_by: str | None = Field(default=None, description="User ID who exported")
    dsl_version: str = Field(default="1", description="DSL schema version")


class PackageBlueprintOrigin(BaseModel):
    """Optional blueprint origin info stored in blueprint.json."""

    model_config = ConfigDict(extra="forbid")

    blueprint_id: str = Field(description="Blueprint ID this template was derived from")
    blueprint_version: str | None = Field(default=None, description="Blueprint version at derivation time")
    derived_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def validate_package_contents(files: dict[str, bytes]) -> list[str]:
    """Validate that a package ZIP contains required files.

    Returns list of error messages (empty = valid).
    """
    errors: list[str] = []

    if PACKAGE_TEMPLATE_YAML not in files:
        errors.append(f"missing required file: {PACKAGE_TEMPLATE_YAML}")

    if PACKAGE_METADATA_JSON not in files:
        errors.append(f"missing required file: {PACKAGE_METADATA_JSON}")

    return errors
