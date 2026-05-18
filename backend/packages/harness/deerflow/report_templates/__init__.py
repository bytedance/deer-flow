"""Report template platform — DSL, validator, registry, runtime.

This module hosts the report template platform described in
docs/plans/2026-05-14-ai-report-custom-template-design.md.

MVP layout (Phase 0+1+2 ship the JSONPath subset parser, the SSE push helper,
the generic Markdown renderer prototype, the DSL schema/validator/registry,
the file-system repository and the permission matrix; Phase 3-4 add tools
and runtime):

    schema.py            # DSL Pydantic schema           (Phase 1 ✓)
    validator.py         # DSL whole-document validator  (Phase 1 ✓)
    records.py           # persisted record models       (Phase 2 ✓)
    repository.py        # template/version/run storage  (Phase 2 ✓)
    permissions.py       # §11.1 permission matrix       (Phase 2 ✓)
    script_registry.py   # skill-contributed registry    (Phase 1 ✓)
    source_resolver.py   # JSONPath subset parser        (Phase 0 ✓)
    push_block.py        # SSE push helper for runtime   (Phase 0 ✓)
    generic_renderer.py  # render_markdown_generic       (Phase 0 ✓)
    runtime/             # per-tool runtime helpers      (Phase 4)
"""

from deerflow.report_templates.generic_renderer import (
    REPORT_PAYLOAD_SCHEMA_VERSION,
    RenderError,
    render_markdown_generic,
)
from deerflow.report_templates.permissions import (
    Decision,
    Operation,
    Principal,
    check_permission,
)
from deerflow.report_templates.push_block import (
    PushBlockError,
    push_block_to_sse,
)
from deerflow.report_templates.records import (
    IndexEntry,
    ReportRunRecord,
    ReportTemplateRecord,
    ReportTemplateVersionRecord,
    RunStatus,
    TemplateIndex,
    TemplateStatus,
    Visibility,
    new_report_run_id,
    new_template_id,
    now_iso,
    validate_report_run_id,
    validate_template_id,
    validate_user_tenant_id,
)
from deerflow.report_templates.repository import (
    BuiltinNotWritableError,
    EtagMismatchError,
    FileSystemReportTemplateRepository,
    ImmutablePublishedError,
    PathTraversalError,
    RepositoryError,
    Scope,
    TemplateNotFoundError,
    VersionNotFoundError,
)
from deerflow.report_templates.schema import (
    DSL_SCHEMA_VERSION,
    DataStep,
    DataStepRef,
    ExportConfig,
    FieldValidation,
    FormField,
    FormFieldOption,
    FormStep,
    OptionsSource,
    ReportTemplateDSL,
    Section,
    TransformStep,
)
from deerflow.report_templates.script_registry import (
    REGISTRY_SCHEMA_VERSION,
    REPORT_SCRIPTS_FILE,
    RegistryConflictError,
    RegistryError,
    RegistryLoadError,
    ScriptDescriptor,
    ScriptRegistry,
    UnknownScriptError,
    get_registry,
    load_registry,
    reset_registry,
)
from deerflow.report_templates.source_resolver import (
    ArrayAll,
    FieldAccess,
    JSONPathError,
    PathNotFoundError,
    PathSyntaxError,
    Root,
    evaluate,
    extract_expressions,
    parse,
    render,
)
from deerflow.report_templates.validator import (
    ValidationIssue,
    ValidationReport,
    validate_dsl,
)

__all__ = [
    "DSL_SCHEMA_VERSION",
    "REGISTRY_SCHEMA_VERSION",
    "REPORT_PAYLOAD_SCHEMA_VERSION",
    "REPORT_SCRIPTS_FILE",
    "ArrayAll",
    "BuiltinNotWritableError",
    "DataStep",
    "DataStepRef",
    "Decision",
    "EtagMismatchError",
    "ExportConfig",
    "FieldAccess",
    "FieldValidation",
    "FileSystemReportTemplateRepository",
    "FormField",
    "FormFieldOption",
    "FormStep",
    "ImmutablePublishedError",
    "IndexEntry",
    "JSONPathError",
    "Operation",
    "OptionsSource",
    "PathNotFoundError",
    "PathSyntaxError",
    "PathTraversalError",
    "Principal",
    "PushBlockError",
    "RegistryConflictError",
    "RegistryError",
    "RegistryLoadError",
    "RenderError",
    "ReportRunRecord",
    "ReportTemplateDSL",
    "ReportTemplateRecord",
    "ReportTemplateVersionRecord",
    "RepositoryError",
    "Root",
    "RunStatus",
    "Scope",
    "ScriptDescriptor",
    "ScriptRegistry",
    "Section",
    "TemplateIndex",
    "TemplateNotFoundError",
    "TemplateStatus",
    "TransformStep",
    "UnknownScriptError",
    "ValidationIssue",
    "ValidationReport",
    "VersionNotFoundError",
    "Visibility",
    "check_permission",
    "evaluate",
    "extract_expressions",
    "get_registry",
    "load_registry",
    "new_report_run_id",
    "new_template_id",
    "now_iso",
    "parse",
    "push_block_to_sse",
    "render",
    "render_markdown_generic",
    "reset_registry",
    "validate_dsl",
    "validate_report_run_id",
    "validate_template_id",
    "validate_user_tenant_id",
]
