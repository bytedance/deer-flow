"""6 lifecycle tools for ``ai-report--custom`` (Phase 3 — §8.2 of the design).

Each tool is a ≤50-line thin shell over the repository + validator + permission
matrix. Runtime tools (``prepare_run`` / ``render_step`` etc.) are stubbed in
Phase 3 and implemented in Phase 4.

All tools return **structured JSON strings** rather than raw objects so that
LangGraph serialises them faithfully into ``ToolMessage.content``. Errors come
back as ``{"error": {"code": ..., "message": ...}}`` envelopes.

The 6 lifecycle tools:

  1. ``report_template_list``
  2. ``report_template_get``
  3. ``report_template_validate``
  4. ``report_template_save_draft``
  5. ``report_template_publish``
  6. ``report_template_fork``
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain.tools import tool
from langgraph.config import get_config

from deerflow.report_templates.permissions import check_permission
from deerflow.report_templates.records import (
    ReportTemplateRecord,
    validate_template_id,
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
    is_builtin_template_name,
)
from deerflow.report_templates.script_registry import get_registry
from deerflow.report_templates.service import (
    get_repository,
    principal_from_runnable_config,
)
from deerflow.report_templates.validator import validate_dsl

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error envelope helpers
# ---------------------------------------------------------------------------


def _err(code: str, message: str, **extra: Any) -> str:
    return json.dumps({"error": {"code": code, "message": message, **extra}}, ensure_ascii=False)


def _ok(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _scope_from_visibility(
    visibility: str, principal_user_id: str, principal_tenant_id: str
) -> Scope:
    if visibility == "private":
        return Scope.private(principal_user_id)
    if visibility == "tenant":
        return Scope.tenant(principal_tenant_id)
    if visibility == "builtin":
        return Scope.builtin()
    raise ValueError(f"unknown visibility {visibility!r}")


def _resolve_scope_for_template_id(
    repo: FileSystemReportTemplateRepository,
    template_id: str,
    principal_user_id: str,
    principal_tenant_id: str,
) -> tuple[Scope, ReportTemplateRecord]:
    """Look up a template by trying private → tenant → builtin in order.

    Returns the matching ``(scope, record)`` pair, or raises
    ``TemplateNotFoundError`` if no scope contains the id.
    """
    for scope_factory in (
        lambda: Scope.private(principal_user_id),
        lambda: Scope.tenant(principal_tenant_id),
        Scope.builtin,
    ):
        try:
            scope = scope_factory()
            rec = repo.get_template(scope, template_id)
            return scope, rec
        except (TemplateNotFoundError, BuiltinNotWritableError, ValueError):
            continue
    raise TemplateNotFoundError(template_id)


# ---------------------------------------------------------------------------
# Tool 1: list
# ---------------------------------------------------------------------------


@tool("report_template_list", parse_docstring=True)
def report_template_list_tool(visibility: str = "private") -> str:
    """List report templates visible to the current user.

    Args:
        visibility: One of "private", "tenant", "builtin". Defaults to "private"
            (the user's own templates). Cross-scope listing requires individual
            calls so the LLM can reason about provenance explicitly.

    Returns:
        JSON string ``{"templates": [...]}`` on success, or
        ``{"error": {"code", "message"}}`` on failure.
    """
    try:
        principal = principal_from_runnable_config(get_config())
        scope = _scope_from_visibility(visibility, principal.user_id, principal.tenant_id)
        repo = get_repository()
        entries = repo.list_templates(scope)
        return _ok({"templates": [e.model_dump() for e in entries]})
    except (ValueError, BuiltinNotWritableError) as e:
        return _err("INVALID_SCOPE", str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("report_template_list failed")
        return _err("INTERNAL", str(e))


# ---------------------------------------------------------------------------
# Tool 2: get
# ---------------------------------------------------------------------------


@tool("report_template_get", parse_docstring=True)
def report_template_get_tool(template_id: str, version: int | None = None) -> str:
    """Fetch a template's metadata and (optionally) one of its version snapshots.

    Args:
        template_id: ULID-style template id like ``tpl_...``.
        version: Optional version number to fetch. ``None`` returns metadata only;
            ``0`` returns the working draft; ``>=1`` returns an immutable
            published snapshot.

    Returns:
        JSON ``{"template": {...}, "version": {...} | null}`` or error envelope.
    """
    try:
        if is_builtin_template_name(template_id):
            # Builtin names (e.g. "daily-equipment") are not ULID IDs;
            # skip validate_template_id and go straight to builtin scope.
            principal = principal_from_runnable_config(get_config())
            repo = get_repository()
            scope = Scope.builtin()
            record = repo.get_template(scope, template_id)
        else:
            validate_template_id(template_id)
            principal = principal_from_runnable_config(get_config())
            repo = get_repository()
            scope, record = _resolve_scope_for_template_id(
                repo, template_id, principal.user_id, principal.tenant_id
            )
        decision = check_permission(principal=principal, operation="view", template=record)
        if not decision.allowed:
            return _err("PERMISSION_DENIED", decision.reason)
        version_payload = None
        if version is not None:
            version_payload = repo.get_version(scope, template_id, version).model_dump()
        return _ok(
            {
                "template": record.model_dump(),
                "version": version_payload,
                "scope": record.visibility,
            }
        )
    except TemplateNotFoundError as e:
        return _err("NOT_FOUND", str(e))
    except VersionNotFoundError as e:
        return _err("VERSION_NOT_FOUND", str(e))
    except ValueError as e:
        return _err("INVALID_ID", str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("report_template_get failed")
        return _err("INTERNAL", str(e))


# ---------------------------------------------------------------------------
# Tool 3: validate
# ---------------------------------------------------------------------------


@tool("report_template_validate", parse_docstring=True)
def report_template_validate_tool(dsl: dict) -> str:
    """Validate a DSL document against schema, registry and source-resolver rules.

    Args:
        dsl: The parsed DSL document (already YAML-decoded). The validator runs
            shape, cross-reference, registry-script, and section-type checks.

    Returns:
        JSON ``{"valid": bool, "errors": [...], "warnings": [...]}``. Always
        returns 200 — errors are structural and meant for direct user feedback.
    """
    try:
        registry = get_registry()
        report = validate_dsl(dsl, registry=registry)
        return _ok(report.to_dict())
    except Exception as e:  # noqa: BLE001
        logger.exception("report_template_validate crashed")
        return _err("INTERNAL", str(e))


# ---------------------------------------------------------------------------
# Tool 4: save_draft
# ---------------------------------------------------------------------------


@tool("report_template_save_draft", parse_docstring=True)
def report_template_save_draft_tool(
    template_id: str | None,
    dsl: dict,
    dsl_yaml: str,
    name: str | None = None,
    display_name: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    expected_etag: str | None = None,
) -> str:
    """Save (create-or-update) a draft template for the current user.

    Pass ``template_id=None`` to create a fresh template; the response includes
    the newly-allocated id. Pass an existing ``template_id`` + ``expected_etag``
    to update; mismatched etag returns ``ETAG_MISMATCH`` so the LLM can re-fetch.

    The DSL is validated **before** persistence. Validator errors are returned
    directly so the LLM can correct them without writing a malformed draft.

    Args:
        template_id: Existing template id to update, or ``None`` to create.
        dsl: Parsed DSL document.
        dsl_yaml: Original YAML text (preserves comments for round-trip editing).
        name: Optional template name (required on create, ignored on update).
        display_name: Optional display name (required on create).
        description: Optional description.
        tags: Optional list of tags.
        expected_etag: Required on update — the etag returned by the previous
            ``get``/``save_draft``/``publish``.

    Returns:
        JSON ``{"template": {...}}`` or error envelope.
    """
    try:
        # 1. Validate DSL before any write.
        registry = get_registry()
        report = validate_dsl(dsl, registry=registry)
        if not report.valid:
            return _err(
                "INVALID_DSL",
                "DSL validation failed",
                errors=[e.to_dict() for e in report.errors],
                warnings=[w.to_dict() for w in report.warnings],
            )

        principal = principal_from_runnable_config(get_config())
        repo = get_repository()
        scope = Scope.private(principal.user_id)

        # 2. Create vs update branch.
        if template_id is None:
            if not name or not display_name:
                return _err(
                    "MISSING_FIELD", "create requires 'name' and 'display_name'"
                )
            created = repo.create_template(
                scope=scope,
                name=name,
                display_name=display_name,
                owner_user_id=principal.user_id,
                tenant_id=principal.tenant_id,
                description=description or "",
                tags=tags,
            )
            updated = repo.save_draft(
                scope=scope,
                template_id=created.id,
                dsl=dsl,
                dsl_yaml=dsl_yaml,
                display_name=display_name,
                description=description,
                tags=tags,
                expected_etag=created.etag,
            )
            return _ok({"template": updated.model_dump()})

        # Update path requires etag.
        validate_template_id(template_id)
        if not expected_etag:
            return _err("MISSING_ETAG", "update requires expected_etag")
        current = repo.get_template(scope, template_id)
        decision = check_permission(
            principal=principal, operation="edit_draft", template=current
        )
        if not decision.allowed:
            return _err("PERMISSION_DENIED", decision.reason)
        updated = repo.save_draft(
            scope=scope,
            template_id=template_id,
            dsl=dsl,
            dsl_yaml=dsl_yaml,
            display_name=display_name,
            description=description,
            tags=tags,
            expected_etag=expected_etag,
        )
        return _ok({"template": updated.model_dump()})
    except EtagMismatchError as e:
        return _err("ETAG_MISMATCH", str(e))
    except ImmutablePublishedError as e:
        return _err("PUBLISHED_IMMUTABLE", str(e))
    except TemplateNotFoundError as e:
        return _err("NOT_FOUND", str(e))
    except (ValueError, PathTraversalError) as e:
        return _err("INVALID_INPUT", str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("report_template_save_draft failed")
        return _err("INTERNAL", str(e))


# ---------------------------------------------------------------------------
# Tool 5: publish
# ---------------------------------------------------------------------------


@tool("report_template_publish", parse_docstring=True)
def report_template_publish_tool(
    template_id: str,
    expected_current_version: int,
    changelog: str = "",
) -> str:
    """Promote the current working draft to a new immutable version.

    Args:
        template_id: The template to publish.
        expected_current_version: The ``current_version`` returned by the last
            read; concurrency-safety guard.
        changelog: Optional human-readable note recorded on the new version.

    Returns:
        JSON ``{"template": {...}}`` with status=published and the bumped
        current_version, or error envelope.
    """
    try:
        validate_template_id(template_id)
        principal = principal_from_runnable_config(get_config())
        repo = get_repository()
        scope = Scope.private(principal.user_id)
        current = repo.get_template(scope, template_id)
        decision = check_permission(
            principal=principal, operation="publish", template=current
        )
        if not decision.allowed:
            return _err("PERMISSION_DENIED", decision.reason)
        published = repo.publish(
            scope=scope,
            template_id=template_id,
            expected_current_version=expected_current_version,
            changelog=changelog,
        )
        return _ok({"template": published.model_dump()})
    except EtagMismatchError as e:
        return _err("VERSION_MISMATCH", str(e))
    except TemplateNotFoundError as e:
        return _err("NOT_FOUND", str(e))
    except RepositoryError as e:
        return _err("PUBLISH_FAILED", str(e))
    except ValueError as e:
        return _err("INVALID_ID", str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("report_template_publish failed")
        return _err("INTERNAL", str(e))


# ---------------------------------------------------------------------------
# Tool 6: fork
# ---------------------------------------------------------------------------


@tool("report_template_fork", parse_docstring=True)
def report_template_fork_tool(
    source_template_id: str,
    source_version: int,
    new_name: str,
    new_display_name: str,
) -> str:
    """Fork a readable template into a new private draft owned by the caller.

    Args:
        source_template_id: The template to copy. May be ``private`` (own only),
            ``tenant`` (same tenant), or ``builtin``.
        source_version: The published version to copy from. Working drafts (v0)
            cannot be forked.
        new_name: New template's machine-friendly name.
        new_display_name: New template's user-facing display name.

    Returns:
        JSON ``{"template": {...}}`` for the new draft, with v0 carrying
        ``source_template_id`` and ``source_template_version`` provenance.
    """
    try:
        validate_template_id(source_template_id)
        if source_version < 1:
            return _err("INVALID_VERSION", "source_version must be >= 1")
        principal = principal_from_runnable_config(get_config())
        repo = get_repository()
        source_scope, source_record = _resolve_scope_for_template_id(
            repo, source_template_id, principal.user_id, principal.tenant_id
        )
        decision = check_permission(
            principal=principal, operation="fork", template=source_record
        )
        if not decision.allowed:
            return _err("PERMISSION_DENIED", decision.reason)
        target_scope = Scope.private(principal.user_id)
        forked = repo.fork(
            source_scope=source_scope,
            source_template_id=source_template_id,
            source_version=source_version,
            target_scope=target_scope,
            target_owner_user_id=principal.user_id,
            target_tenant_id=principal.tenant_id,
            new_name=new_name,
            new_display_name=new_display_name,
        )
        return _ok({"template": forked.model_dump()})
    except TemplateNotFoundError as e:
        return _err("NOT_FOUND", str(e))
    except VersionNotFoundError as e:
        return _err("VERSION_NOT_FOUND", str(e))
    except ValueError as e:
        return _err("INVALID_INPUT", str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("report_template_fork failed")
        return _err("INTERNAL", str(e))


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------

REPORT_TEMPLATE_LIFECYCLE_TOOLS = [
    report_template_list_tool,
    report_template_get_tool,
    report_template_validate_tool,
    report_template_save_draft_tool,
    report_template_publish_tool,
    report_template_fork_tool,
]
