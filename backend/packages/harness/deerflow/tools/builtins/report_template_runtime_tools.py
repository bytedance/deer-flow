"""8 runtime tools that drive a ReportRun (Phase 4 — §8.2 of the design).

Each tool is a thin shell over the ``runtime/`` modules. The LLM (under
``ai-report--custom`` SOUL.md) invokes them in sequence:

    prepare_run
        → render_step  ⟷  submit_step      (loop while form_steps remain)
        → run_data_steps
        → assemble_payload
        → render_report
        → export

``resume_run`` is the recovery entry point: it inspects the latest
``status.json`` for the current thread and tells the LLM where to continue.

Each tool returns a JSON string ``{...}`` on success or
``{"error": {code, message, ...}}`` on failure.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from langchain.tools import tool
from langgraph.config import get_config

from deerflow.config.paths import get_paths
from deerflow.report_templates.records import (
    ReportRunRecord,
    builtin_version_ref,
    new_report_run_id,
    now_iso,
    validate_report_run_id,
    validate_template_id,
)
from deerflow.report_templates.repository import (
    Scope,
    TemplateNotFoundError,
    VersionNotFoundError,
)
from deerflow.report_templates.runtime.data_runner import (
    DataRunnerError,
    ScriptExecutionError,
    ScriptTimeoutError,
    run_data_steps_and_transforms,
)
from deerflow.report_templates.runtime.exporter import ExportError, export_report
from deerflow.report_templates.runtime.payload_builder import (
    PayloadBuildError,
    assemble_payload,
)
from deerflow.report_templates.runtime.report_renderer import (
    RenderReportError,
    render_report_blocks,
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
from deerflow.report_templates.runtime.step_renderer import (
    StepRenderError,
    build_context,
    build_device_selector_props,
    build_form_props,
    find_step,
    maybe_run_before_step,
)
from deerflow.report_templates.runtime.step_submitter import (
    SubmitStepError,
    submit_step as _submit_step,
)
from deerflow.report_templates.script_registry import (
    UnknownScriptError,
    get_registry,
)
from deerflow.report_templates.service import (
    get_repository,
    principal_from_runnable_config,
)
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error envelope helpers
# ---------------------------------------------------------------------------


def _err(code: str, message: str, **extra: Any) -> str:
    return json.dumps({"error": {"code": code, "message": message, **extra}}, ensure_ascii=False)


def _ok(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _thread_id_from_config() -> str:
    cfg = (get_config() or {}).get("configurable", {}) or {}
    thread_id = cfg.get("thread_id")
    if not thread_id:
        raise RuntimeError("thread_id missing from RunnableConfig.configurable")
    return str(thread_id)


def _run_output_dir(thread_id: str, report_run_id: str) -> Path:
    validate_report_run_id(report_run_id)
    paths = get_paths()
    outputs_dir = paths.sandbox_outputs_dir(thread_id, user_id=get_effective_user_id())
    run_dir = (outputs_dir / "report-runs" / report_run_id).resolve()
    try:
        run_dir.relative_to(outputs_dir.resolve())
    except ValueError as e:
        raise RuntimeError(f"run dir escapes outputs root: {run_dir}") from e
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _locate_active_run_dir(thread_id: str) -> Path | None:
    """Find the most recently updated run dir under the thread's outputs."""
    paths = get_paths()
    outputs_dir = paths.sandbox_outputs_dir(thread_id, user_id=get_effective_user_id())
    runs_root = outputs_dir / "report-runs"
    if not runs_root.exists():
        return None
    candidates = [p for p in runs_root.iterdir() if (p / "status.json").exists()]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p / "status.json").stat().st_mtime, reverse=True)
    return candidates[0]


def _load_dsl_for(state: RuntimeState) -> dict[str, Any]:
    """Read the version of the DSL bound to this run."""
    repo = get_repository()
    if state.template_version is None:
        # Builtin templates: use current pointer (no per-version files).
        return repo.get_template(Scope.builtin(), state.template_id).model_dump() and {}  # placeholder
    # For private/tenant we use the version we recorded.
    principal = principal_from_runnable_config(get_config())
    scope = Scope.private(principal.user_id)
    try:
        version = repo.get_version(scope, state.template_id, state.template_version)
        return version.dsl
    except (TemplateNotFoundError, VersionNotFoundError):
        # Fallback to tenant scope.
        scope = Scope.tenant(principal.tenant_id)
        version = repo.get_version(scope, state.template_id, state.template_version)
        return version.dsl


# ---------------------------------------------------------------------------
# Tool 1: prepare_run
# ---------------------------------------------------------------------------


@tool("report_template_prepare_run", parse_docstring=True)
def report_template_prepare_run_tool(
    template_id: str,
    template_version: int,
    idempotency_key: str | None = None,
) -> str:
    """Allocate a new ReportRun + initialise status.json.

    Args:
        template_id: ``tpl_...`` id of the template to run. The template must
            already be readable to the current user.
        template_version: Specific published version to bind this run to
            (>= 1). Builtin templates pass ``-1`` to indicate "current builtin".
        idempotency_key: Optional client-supplied key. The runtime does not
            currently dedupe, but the value is persisted for traceability.

    Returns:
        JSON ``{"report_run_id", "nonce", "first_step_id", "run_output_dir"}``.
    """
    try:
        validate_template_id(template_id)
        principal = principal_from_runnable_config(get_config())
        repo = get_repository()
        # Resolve template + version for DSL retrieval.
        dsl: dict[str, Any]
        version_to_record: int | None
        version_ref: str | None
        if template_version <= 0:
            scope, rec = Scope.builtin(), repo.get_template(Scope.builtin(), template_id)
            # builtin templates expose a current DSL view (no v-number versioning here).
            version_to_record = None
            version_ref = builtin_version_ref(rec.dsl_version)
            # builtin DSL location: repository keeps it inline via version 1 if loaded
            # (Phase 2 fork test demonstrates this). For MVP we read v1.
            version = repo.get_version(scope, template_id, 1)
            dsl = version.dsl
        else:
            scope = Scope.private(principal.user_id)
            try:
                version = repo.get_version(scope, template_id, template_version)
            except (TemplateNotFoundError, VersionNotFoundError):
                scope = Scope.tenant(principal.tenant_id)
                version = repo.get_version(scope, template_id, template_version)
            dsl = version.dsl
            version_to_record = template_version
            version_ref = f"v{template_version}"

        thread_id = _thread_id_from_config()
        report_run_id = new_report_run_id()
        run_dir = _run_output_dir(thread_id, report_run_id)
        nonce = uuid.uuid4().hex
        first_step_id = (dsl.get("form_steps") or [{}])[0].get("id")

        state = RuntimeState(
            report_run_id=report_run_id,
            thread_id=thread_id,
            template_id=template_id,
            template_version=version_to_record,
            template_version_ref=version_ref,
            status="pending",
            nonce=nonce,
            expected_step=first_step_id,
            created_at=now_iso(),
        )
        write_state(run_dir, state)

        # Snapshot DSL alongside status.json for traceability + resume.
        (run_dir / "template_version.json").write_text(
            json.dumps(
                {
                    "template_id": template_id,
                    "template_version": version_to_record,
                    "template_version_ref": version_ref,
                    "dsl": dsl,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        # Record an empty ReportRun index entry in the repository.
        try:
            run_record = ReportRunRecord(
                id=report_run_id,
                template_id=template_id,
                template_version=version_to_record,
                template_version_ref=version_ref,
                thread_id=thread_id,
                run_id="",
                user_id=principal.user_id,
                tenant_id=principal.tenant_id,
                idempotency_key=idempotency_key,
                status="pending",
                created_at=state.created_at,
            )
            repo.create_report_run(scope=scope, record=run_record)
        except Exception:  # noqa: BLE001
            logger.warning("ReportRun index create failed (non-fatal)", exc_info=True)

        return _ok(
            {
                "report_run_id": report_run_id,
                "nonce": nonce,
                "first_step_id": first_step_id,
                "run_output_dir": str(run_dir),
            }
        )
    except (TemplateNotFoundError, VersionNotFoundError) as e:
        return _err("TEMPLATE_NOT_FOUND", str(e))
    except ValueError as e:
        return _err("INVALID_INPUT", str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("prepare_run failed")
        return _err("INTERNAL", str(e))


# ---------------------------------------------------------------------------
# Tool 2: render_step
# ---------------------------------------------------------------------------


@tool("report_template_render_step", parse_docstring=True)
def report_template_render_step_tool(report_run_id: str, step_id: str) -> str:
    """Resolve the requested form_step and return its rendered props.

    Runs ``before_step`` if declared and not yet cached. Returns the props for
    a ``render_ui(component="form")`` block that the LLM should emit next. The
    LLM (not this tool) issues the actual ``render_ui`` call so the existing
    interrupt middleware handles the form submission.

    Args:
        report_run_id: The ``rr_...`` id returned by ``prepare_run``.
        step_id: The form step to render. Must match ``state.expected_step``.

    Returns:
        JSON ``{"callback_id": ..., "form_props": {...}, "state_summary": {...}}``.
    """
    try:
        thread_id = _thread_id_from_config()
        run_dir = _run_output_dir(thread_id, report_run_id)
        state = read_state(run_dir)
        expect_status(state, "pending", "awaiting_step")

        if state.expected_step and step_id != state.expected_step:
            return _err(
                "STEP_MISMATCH",
                f"expected {state.expected_step!r}, got {step_id!r}",
            )

        dsl = _load_dsl_for(state)
        step = find_step(dsl, step_id)

        # Run before_step if needed and stash its outputs.
        before_result = maybe_run_before_step(
            step=step,
            state=state,
            registry=get_registry(),
            run_output_dir=run_dir,
        )
        if before_result is not None:
            state.step_outputs[before_result.step_id] = before_result.outputs

        callback_id = f"custom-report:{state.template_id}:{state.report_run_id}:{step_id}"
        component = step.get("component", "form")
        try:
            if component == "device-selector-multi":
                props = build_device_selector_props(step=step, state=state, callback_id=callback_id)
            else:
                props = build_form_props(step=step, state=state, callback_id=callback_id)
        except StepRenderError as e:
            mark_failed(state, code="RENDER_FAILED", message=str(e))
            write_state(run_dir, state)
            return _err("RENDER_FAILED", str(e))

        # Reflect that the form is now awaiting a submission.
        state.expected_step = step_id
        if state.status == "pending":
            transition(state, "awaiting_step")
        write_state(run_dir, state)
        return _ok(
            {
                "callback_id": callback_id,
                "component": component,
                "props": props,
                "completed_steps": list(state.completed_steps),
                "status": state.status,
            }
        )
    except StateNotFoundError as e:
        return _err("RUN_NOT_FOUND", str(e))
    except (DataRunnerError, ScriptExecutionError, ScriptTimeoutError, UnknownScriptError) as e:
        return _err("BEFORE_STEP_FAILED", str(e))
    except StateTransitionError as e:
        return _err("STATE_MISMATCH", str(e))
    except ValueError as e:
        return _err("INVALID_INPUT", str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("render_step failed")
        return _err("INTERNAL", str(e))


# ---------------------------------------------------------------------------
# Tool 3: submit_step
# ---------------------------------------------------------------------------


@tool("report_template_submit_step", parse_docstring=True)
def report_template_submit_step_tool(
    report_run_id: str, step_id: str, payload: dict
) -> str:
    """Apply a user-submitted form payload and advance the state machine.

    Args:
        report_run_id: ``rr_...``.
        step_id: The step the user just submitted. Must equal ``expected_step``.
        payload: ``{field_name: value}`` from the user's GenUI form submission.

    Returns:
        JSON ``{"next_step_id": "..."|"__generate__", "status": "..."}``.
    """
    try:
        thread_id = _thread_id_from_config()
        run_dir = _run_output_dir(thread_id, report_run_id)
        state = read_state(run_dir)
        dsl = _load_dsl_for(state)
        next_id = _submit_step(
            dsl=dsl, state=state, submitted_step_id=step_id, payload=payload
        )
        # Persist the parameters_summary for the eventual ReportRun record.
        state.parameters_summary = {**state.parameters_summary, **payload}
        write_state(run_dir, state)
        return _ok({"next_step_id": next_id, "status": state.status})
    except StateNotFoundError as e:
        return _err("RUN_NOT_FOUND", str(e))
    except SubmitStepError as e:
        return _err("SUBMIT_REJECTED", str(e))
    except StateTransitionError as e:
        return _err("STATE_MISMATCH", str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("submit_step failed")
        return _err("INTERNAL", str(e))


# ---------------------------------------------------------------------------
# Tool 4: run_data_steps
# ---------------------------------------------------------------------------


@tool("report_template_run_data_steps", parse_docstring=True)
def report_template_run_data_steps_tool(report_run_id: str) -> str:
    """Execute every ``data_steps`` and ``transforms`` declared in the DSL.

    Args:
        report_run_id: ``rr_...`` of the run to advance.

    Returns:
        JSON ``{"completed": [step_id, ...], "status": "data_complete"}``.
    """
    try:
        thread_id = _thread_id_from_config()
        run_dir = _run_output_dir(thread_id, report_run_id)
        state = read_state(run_dir)
        expect_status(state, "ready_for_data")

        dsl = _load_dsl_for(state)
        context = build_context(state)
        try:
            new_outputs = run_data_steps_and_transforms(
                dsl=dsl,
                registry=get_registry(),
                run_output_dir=run_dir,
                context=context,
            )
        except (DataRunnerError, ScriptExecutionError, ScriptTimeoutError, UnknownScriptError) as e:
            mark_failed(state, code="DATA_STEP_FAILED", message=str(e))
            write_state(run_dir, state)
            return _err("DATA_STEP_FAILED", str(e))

        state.step_outputs.update(new_outputs)
        transition(state, "data_complete")
        write_state(run_dir, state)
        return _ok(
            {
                "completed": [s["id"] for s in dsl.get("data_steps", []) or []]
                + [s["id"] for s in dsl.get("transforms", []) or []],
                "status": state.status,
            }
        )
    except StateNotFoundError as e:
        return _err("RUN_NOT_FOUND", str(e))
    except StateTransitionError as e:
        return _err("STATE_MISMATCH", str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("run_data_steps failed")
        return _err("INTERNAL", str(e))


# ---------------------------------------------------------------------------
# Tool 5: assemble_payload
# ---------------------------------------------------------------------------


@tool("report_template_assemble_payload", parse_docstring=True)
def report_template_assemble_payload_tool(report_run_id: str) -> str:
    """Assemble ``report_payload.json`` from the DSL sections + step_outputs.

    Args:
        report_run_id: ``rr_...``.

    Returns:
        JSON ``{"payload_path": ..., "section_count": N, "status": "payload_ready"}``.
    """
    try:
        thread_id = _thread_id_from_config()
        run_dir = _run_output_dir(thread_id, report_run_id)
        state = read_state(run_dir)
        expect_status(state, "data_complete")
        dsl = _load_dsl_for(state)
        try:
            principal = principal_from_runnable_config(get_config())
            payload = assemble_payload(
                dsl=dsl, state=state, tenant_id=principal.tenant_id
            )
        except PayloadBuildError as e:
            mark_failed(state, code="ASSEMBLE_FAILED", message=str(e))
            write_state(run_dir, state)
            return _err("ASSEMBLE_FAILED", str(e))

        payload_path = run_dir / "report_payload.json"
        payload_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        transition(state, "payload_ready")
        write_state(run_dir, state)
        return _ok(
            {
                "payload_path": str(payload_path),
                "section_count": len(payload.get("sections", [])),
                "status": state.status,
            }
        )
    except StateNotFoundError as e:
        return _err("RUN_NOT_FOUND", str(e))
    except StateTransitionError as e:
        return _err("STATE_MISMATCH", str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("assemble_payload failed")
        return _err("INTERNAL", str(e))


# ---------------------------------------------------------------------------
# Tool 6: render_report
# ---------------------------------------------------------------------------


@tool("report_template_render_report", parse_docstring=True)
def report_template_render_report_tool(report_run_id: str) -> str:
    """Push one GenUI block per ``report_payload.sections[]`` to the SSE stream.

    Args:
        report_run_id: ``rr_...``.

    Returns:
        JSON ``{"blocks_pushed": N, "status": "rendered"}``.
    """
    try:
        thread_id = _thread_id_from_config()
        run_dir = _run_output_dir(thread_id, report_run_id)
        state = read_state(run_dir)
        expect_status(state, "payload_ready")
        payload = json.loads((run_dir / "report_payload.json").read_text(encoding="utf-8"))
        try:
            blocks = render_report_blocks(payload=payload, base_sequence=10)
        except RenderReportError as e:
            mark_failed(state, code="RENDER_REPORT_FAILED", message=str(e))
            write_state(run_dir, state)
            return _err("RENDER_REPORT_FAILED", str(e))
        transition(state, "rendered")
        write_state(run_dir, state)
        return _ok({"blocks_pushed": len(blocks), "status": state.status})
    except StateNotFoundError as e:
        return _err("RUN_NOT_FOUND", str(e))
    except StateTransitionError as e:
        return _err("STATE_MISMATCH", str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("render_report failed")
        return _err("INTERNAL", str(e))


# ---------------------------------------------------------------------------
# Tool 7: export
# ---------------------------------------------------------------------------


@tool("report_template_export", parse_docstring=True)
def report_template_export_tool(report_run_id: str, pdf: bool = True) -> str:
    """Export the rendered payload as Markdown (required) and PDF (best-effort).

    Args:
        report_run_id: ``rr_...``.
        pdf: When False, skip PDF entirely. When True, attempt and degrade
            gracefully on missing weasyprint/render error.

    Returns:
        JSON ``{"md_path", "pdf_path"?, "pdf_skipped_reason"?, "status": "exported"}``.
    """
    try:
        thread_id = _thread_id_from_config()
        run_dir = _run_output_dir(thread_id, report_run_id)
        state = read_state(run_dir)
        expect_status(state, "rendered")
        payload = json.loads((run_dir / "report_payload.json").read_text(encoding="utf-8"))
        try:
            result = export_report(payload=payload, run_output_dir=run_dir, pdf=pdf)
        except ExportError as e:
            mark_failed(state, code="EXPORT_FAILED", message=str(e))
            write_state(run_dir, state)
            return _err("EXPORT_FAILED", str(e))
        transition(state, "exported")
        write_state(run_dir, state)
        return _ok(
            {
                "md_path": result.md_path,
                "pdf_path": result.pdf_path,
                "pdf_skipped_reason": result.pdf_skipped_reason,
                "status": state.status,
            }
        )
    except StateNotFoundError as e:
        return _err("RUN_NOT_FOUND", str(e))
    except StateTransitionError as e:
        return _err("STATE_MISMATCH", str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("export failed")
        return _err("INTERNAL", str(e))


# ---------------------------------------------------------------------------
# Tool 8: resume_run
# ---------------------------------------------------------------------------


@tool("report_template_resume_run", parse_docstring=True)
def report_template_resume_run_tool() -> str:
    """Find the latest unfinished ReportRun in the current thread.

    Returns:
        JSON snapshot of the latest ``status.json`` (or ``{"error": ...}``).
        The LLM uses the ``status`` + ``expected_step`` fields to pick the
        next tool to call.
    """
    try:
        thread_id = _thread_id_from_config()
        latest = _locate_active_run_dir(thread_id)
        if latest is None:
            return _err("NO_ACTIVE_RUN", "no ReportRun found in this thread")
        state = read_state(latest)
        return _ok(
            {
                "report_run_id": state.report_run_id,
                "template_id": state.template_id,
                "template_version": state.template_version,
                "status": state.status,
                "expected_step": state.expected_step,
                "completed_steps": list(state.completed_steps),
                "error_code": state.error_code,
                "error_message": state.error_message,
                "run_output_dir": str(latest),
            }
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("resume_run failed")
        return _err("INTERNAL", str(e))


# ---------------------------------------------------------------------------
# Exported list (for tools/tools.py registration)
# ---------------------------------------------------------------------------


REPORT_TEMPLATE_RUNTIME_TOOLS = [
    report_template_prepare_run_tool,
    report_template_render_step_tool,
    report_template_submit_step_tool,
    report_template_run_data_steps_tool,
    report_template_assemble_payload_tool,
    report_template_render_report_tool,
    report_template_export_tool,
    report_template_resume_run_tool,
]
