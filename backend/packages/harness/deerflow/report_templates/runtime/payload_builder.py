"""Payload assembler — turn DSL sections + step_outputs into ``report_payload.json``.

Pipeline:
    sections[]:
        - source: JSONPath/dotted ref into the runtime context
        - component: "markdown" | "card" | "card_group" | "echart" | "table"
                     | "image" | "closure_section"

For each section, the assembler:
  1. Resolves ``source`` against the context (form / steps / run / template),
     OR — for ``closure_section`` — calls
     ``closed_loop.service.list_for_report`` with the section's ``filters``
     (placeholders pre-resolved against the runtime context).
  2. Wraps the resolved value into the correct ``props`` dict for the
     downstream renderer:
       - markdown        → ``{content: str|list[str]}``
       - card            → object with title/value/description
       - card_group      → ``{items: [...]}``
       - echart          → ``{option: {...}}`` (raw ECharts option)
       - table           → ``{columns: [...], data: [...]}`` or ``{rows: [...]}``
       - image           → ``{src, alt}``
       - closure_section → ``{columns, data, summary}`` table-shaped payload
  3. Emits one section dict matching the §12.1 payload schema.

The output is JSON-safe (i.e. ``json.dumps()`` works) — runtime tools just
``json.dump()`` the payload to disk.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from deerflow.report_templates.records import now_iso
from deerflow.report_templates.runtime.echart_sanitizer import (
    EchartsSanitizeError,
    sanitize_echart_option,
)
from deerflow.report_templates.runtime.state import RuntimeState
from deerflow.report_templates.source_resolver import (
    JSONPathError,
    PathNotFoundError,
    evaluate,
    extract_expressions,
    parse,
)

logger = logging.getLogger(__name__)

REPORT_PAYLOAD_SCHEMA_VERSION = "1"


class PayloadBuildError(Exception):
    """Raised when a section cannot be assembled."""


def assemble_payload(
    *,
    dsl: dict[str, Any],
    state: RuntimeState,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Build the ``report_payload.json`` dict for a finished run.

    ``tenant_id`` is required when any section uses ``closure_section`` — the
    closure service is tenant-scoped. Other components ignore it.
    """
    sections_out: list[dict[str, Any]] = []
    context = _context(state)

    for section in dsl.get("sections", []) or []:
        try:
            sections_out.append(_assemble_section(section, context, tenant_id=tenant_id))
        except (JSONPathError, PathNotFoundError) as e:
            raise PayloadBuildError(
                f"section {section.get('id')!r} failed to resolve source {section.get('source')!r}: {e}"
            ) from e

    return {
        "schema_version": REPORT_PAYLOAD_SCHEMA_VERSION,
        "title": dsl.get("display_name") or dsl.get("name", ""),
        "template": {
            "id": state.template_id,
            "version": state.template_version,
            "name": dsl.get("name", ""),
        },
        "run": {
            "id": state.report_run_id,
            "thread_id": state.thread_id,
            "run_id": "",  # filled by tools layer (LangGraph run id)
            "generated_at": now_iso(),
        },
        "parameters": _flatten_form_state(state.form_state),
        "sections": sections_out,
    }


def _assemble_section(
    section: dict[str, Any],
    context: dict[str, Any],
    *,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    component = section["component"]
    if component == "closure_section":
        props = _build_closure_props(
            section_id=section["id"],
            filters=section.get("filters") or {},
            extra_props=section.get("props"),
            context=context,
            tenant_id=tenant_id,
        )
    else:
        source = (section.get("source") or "").strip()
        if not source:
            raise PayloadBuildError(
                f"section {section['id']!r}: component {component!r} requires 'source'"
            )
        # Auto-prefix short form ``step.output.path``.
        expr = source if source.startswith("$.") else f"$.steps.{source}"
        ast = parse(expr)
        value = evaluate(ast, context)
        props = _wrap_props(component, value, section.get("props"))
    return {
        "id": section["id"],
        "component": component,
        "title": section.get("title", section["id"]),
        "props": props,
    }


def _wrap_props(component: str, value: Any, extra_props: dict | None) -> dict[str, Any]:
    """Convert a resolved source value into the renderer-friendly props dict."""
    base: dict[str, Any] = dict(extra_props or {})
    if component == "markdown":
        if not isinstance(value, (str, list)):
            raise PayloadBuildError(
                f"markdown source must be a string or list of strings, got {type(value).__name__}"
            )
        base["content"] = value
        return base
    if component == "card":
        # Standard form: card source resolves to {title, value, ...} dict.
        if isinstance(value, dict):
            base.update(value)
            return base
        # Banner / confidence-badge form: card source resolves to a scalar
        # (bool/str/int/float) and DSL author-supplied ``props`` carry the
        # banner ``style`` + ``template`` text. The scalar becomes ``value`` so
        # generic_renderer can fall back to ``template`` or display the value
        # (e.g. ``confidence: high`` → 🟢 High badge).
        if isinstance(value, (bool, str, int, float)):
            base.setdefault("value", value)
            return base
        raise PayloadBuildError(
            f"card source must be an object or scalar, got {type(value).__name__}"
        )
    if component == "card_group":
        if not isinstance(value, list):
            raise PayloadBuildError(
                f"card_group source must be a list of objects, got {type(value).__name__}"
            )
        base["items"] = value
        return base
    if component == "echart":
        if not isinstance(value, dict):
            raise PayloadBuildError(
                f"echart source must be an ECharts option object, got {type(value).__name__}"
            )
        # §11.3 — reject function bodies / HTML / external URLs before shipping.
        try:
            sanitize_echart_option(value)
        except EchartsSanitizeError as exc:
            raise PayloadBuildError(
                f"echart option failed safety scan: {exc.reason} at {exc.path}"
            ) from exc
        base["option"] = value
        return base
    if component == "table":
        if isinstance(value, dict) and "columns" in value and "data" in value:
            base["columns"] = value["columns"]
            base["data"] = value["data"]
            return base
        if isinstance(value, list):
            base["rows"] = value
            return base
        raise PayloadBuildError(
            "table source must be {columns, data} or a list of row dicts"
        )
    if component == "image":
        if not isinstance(value, dict):
            raise PayloadBuildError("image source must be {src, alt} dict")
        base.update(value)
        return base
    if component == "closure_section":
        # closure_section never reaches _wrap_props -- handled separately.
        raise PayloadBuildError(
            "closure_section sections must be assembled via _build_closure_props"
        )
    raise PayloadBuildError(f"unsupported section component {component!r}")


# ---------------------------------------------------------------------------
# closure_section assembly
# ---------------------------------------------------------------------------


CLOSURE_SECTION_COLUMNS: list[dict[str, str]] = [
    {"key": "id", "label": "工单"},
    {"key": "title", "label": "标题"},
    {"key": "device_name", "label": "设备"},
    {"key": "status", "label": "状态"},
    {"key": "priority", "label": "优先级"},
    {"key": "assignee_id", "label": "负责人"},
    {"key": "due_at", "label": "应办结时间"},
    {"key": "is_overdue", "label": "是否超期"},
    {"key": "closed_at", "label": "关闭时间"},
    {"key": "source_type", "label": "来源"},
]
CLOSURE_SECTION_EMPTY_PLACEHOLDER = "本期无相关闭环单据。"


def _build_closure_props(
    *,
    section_id: str,
    filters: dict[str, Any],
    extra_props: dict[str, Any] | None,
    context: dict[str, Any],
    tenant_id: str | None,
) -> dict[str, Any]:
    """Pull rows from ``closed_loop.service.list_for_report`` and shape them as a table-like payload.

    Empty result: emit a placeholder row so the renderer outputs a "no data"
    note rather than an empty table — this is the §6.3 requirement.
    """
    if not tenant_id:
        raise PayloadBuildError(
            f"section {section_id!r}: closure_section requires tenant_id but none was provided"
        )

    resolved = _resolve_closure_filters(filters, context, section_id=section_id)

    try:
        from deerflow.closed_loop.service_factory import get_default_service
    except ImportError as e:  # pragma: no cover -- module is part of harness
        raise PayloadBuildError(
            f"closure_section unavailable: closed_loop module is not installed ({e})"
        ) from e

    service = get_default_service()
    if service is None:
        raise PayloadBuildError(
            f"section {section_id!r}: closure_section requires the closure service "
            "(no DB engine wired up)"
        )

    rows = _run_async(
        service.list_for_report(
            tenant_id=tenant_id,
            period_start=resolved["period_start"],
            period_end=resolved["period_end"],
            device_ids=resolved["device_ids"],
            statuses=resolved["statuses"],
            page_size=resolved["page_size"],
        )
    )

    if resolved["include_overdue_only"]:
        rows = [r for r in rows if r.get("is_overdue")]

    base: dict[str, Any] = dict(extra_props or {})
    base.setdefault("columns", CLOSURE_SECTION_COLUMNS)

    if not rows:
        base["data"] = []
        base["empty_text"] = base.get("empty_text") or CLOSURE_SECTION_EMPTY_PLACEHOLDER
        base["summary"] = {
            "total": 0,
            "open": 0,
            "closed": 0,
            "overdue": 0,
        }
        return base

    base["data"] = rows
    base["summary"] = _summarize_closure_rows(rows)
    return base


def _resolve_closure_filters(
    raw: dict[str, Any],
    context: dict[str, Any],
    *,
    section_id: str,
) -> dict[str, Any]:
    """Resolve placeholders in filters and turn ISO strings into datetimes."""
    device_ids = _resolve_string_list(raw.get("device_ids"), context, section_id=section_id, field="device_ids")
    statuses = raw.get("statuses") or None
    if statuses is not None and not isinstance(statuses, list):
        raise PayloadBuildError(
            f"section {section_id!r}: filters.statuses must be a list or null"
        )
    period_start = _resolve_iso_datetime(raw.get("period_start"), context, section_id=section_id, field="period_start")
    period_end = _resolve_iso_datetime(raw.get("period_end"), context, section_id=section_id, field="period_end")
    page_size = int(raw.get("page_size") or 200)
    include_overdue_only = bool(raw.get("include_overdue_only", False))
    return {
        "device_ids": device_ids,
        "statuses": statuses,
        "period_start": period_start,
        "period_end": period_end,
        "page_size": page_size,
        "include_overdue_only": include_overdue_only,
    }


def _resolve_string_list(
    value: Any,
    context: dict[str, Any],
    *,
    section_id: str,
    field: str,
) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        # Single placeholder string e.g. "{{ $.form.scope.equipment_ids }}".
        resolved = _resolve_value(value, context, section_id=section_id, field=field)
        if resolved is None:
            return None
        if isinstance(resolved, list):
            return [str(v) for v in resolved if v is not None]
        return [str(resolved)]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and "{{" in item:
                resolved = _resolve_value(item, context, section_id=section_id, field=field)
                if resolved is None:
                    continue
                if isinstance(resolved, list):
                    out.extend(str(v) for v in resolved if v is not None)
                else:
                    out.append(str(resolved))
            elif item is not None:
                out.append(str(item))
        return out or None
    raise PayloadBuildError(
        f"section {section_id!r}: filters.{field} must be a list of strings, got {type(value).__name__}"
    )


def _resolve_iso_datetime(
    value: Any,
    context: dict[str, Any],
    *,
    section_id: str,
    field: str,
) -> datetime | None:
    if value is None:
        return None
    resolved = _resolve_value(value, context, section_id=section_id, field=field) if isinstance(value, str) else value
    if resolved is None:
        return None
    if isinstance(resolved, datetime):
        return resolved
    if not isinstance(resolved, str):
        raise PayloadBuildError(
            f"section {section_id!r}: filters.{field} must be an ISO-8601 string, got {type(resolved).__name__}"
        )
    try:
        # Accept bare dates (``2026-05-01``) too — Python's fromisoformat is happy.
        return datetime.fromisoformat(resolved)
    except ValueError as e:
        raise PayloadBuildError(
            f"section {section_id!r}: filters.{field}={resolved!r} is not a valid ISO-8601 datetime ({e})"
        ) from e


def _resolve_value(
    value: str,
    context: dict[str, Any],
    *,
    section_id: str,
    field: str,
) -> Any:
    """Resolve a single ``{{ $.path }}`` placeholder; pass plain strings through."""
    exprs = list(extract_expressions(value))
    if not exprs:
        return value
    if len(exprs) == 1 and value.strip() == f"{{{{ {exprs[0]} }}}}":
        # Pure-placeholder shape — return the resolved value as-is.
        try:
            ast = parse(exprs[0])
            return evaluate(ast, context)
        except (JSONPathError, PathNotFoundError):
            return None
    # Mixed text+placeholders — return the literal string (no inline interpolation
    # for filter values; the DSL author should use a pure placeholder).
    raise PayloadBuildError(
        f"section {section_id!r}: filters.{field} only supports pure ``{{{{ $.path }}}}`` placeholders"
    )


def _summarize_closure_rows(rows: list[dict[str, Any]]) -> dict[str, int]:
    total = len(rows)
    closed = sum(1 for r in rows if r.get("status") in ("closed", "rejected"))
    overdue = sum(1 for r in rows if r.get("is_overdue"))
    return {"total": total, "open": total - closed, "closed": closed, "overdue": overdue}


def _run_async(coro: Any) -> Any:
    """Run an async coroutine from a sync caller, even if a loop is already running.

    The payload builder is invoked from sync code (the runtime tool layer) but
    ``ClosureService.list_for_report`` is async. When called from inside an
    already-running event loop (e.g. tests), we delegate to a worker thread.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, coro)
        return future.result()


def _context(state: RuntimeState) -> dict[str, Any]:
    return {
        "form": state.form_state,
        "steps": state.step_outputs,
        "run": {
            "report_run_id": state.report_run_id,
            "thread_id": state.thread_id,
            "generated_at": state.created_at,
        },
        "template": {
            "id": state.template_id,
            "version": state.template_version,
            "name": "",
        },
    }


def _flatten_form_state(form_state: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Flatten ``{step_id: {field: value}}`` into a single dict for the payload.

    Field collisions across steps keep the last one. Used as a friendly summary
    on the report payload — not for downstream resolution (which reads
    ``state.form_state`` directly).
    """
    out: dict[str, Any] = {}
    for fields in form_state.values():
        out.update(fields)
    return out
