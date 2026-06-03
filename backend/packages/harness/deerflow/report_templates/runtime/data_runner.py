"""Data step runner — execute a script descriptor with sanitized args.

Used by:
  - ``runtime/step_renderer.py``  for form_step.before_step (form_options scripts)
  - ``runtime/data_runner.py``    for top-level data_steps + transforms

Security (§9.2):
    - No ``shell=True``; arguments built as a list and passed to ``subprocess.run``.
    - Per-script timeout + max output bytes enforced.
    - Output paths are pre-resolved from the registry descriptor with
      ``{run_output_dir}`` substituted — the script cannot redirect output.
    - args dict is rendered through the JSONPath subset substitutor (Phase 0
      ``source_resolver``) before flattening to CLI flags.

CLI convention (lowest-common-denominator):
    Each declared argument becomes one ``--name value`` pair (or ``--name`` for
    flag-typed). ``list``/``csv`` values become a comma-joined string. ``flag``
    types are emitted only when truthy. Output paths are appended last as
    ``--output-dir {run_output_dir}``.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import resource as _resource_module  # type: ignore[import-not-found]
except ImportError:
    _resource_module = None  # type: ignore[assignment]

from deerflow.report_templates.script_registry import (
    ArgSpec,
    ScriptDescriptor,
    ScriptRegistry,
    UnknownScriptError,
)
from deerflow.report_templates.source_resolver import (
    JSONPathError,
    evaluate,
    extract_expressions,
    parse,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DataRunnerError(Exception):
    """Base error for any data-runner failure (script crash, timeout, etc.)."""


class ScriptExecutionError(DataRunnerError):
    """Raised when a script exits non-zero or returns malformed output."""

    def __init__(self, *, script: str, code: str, message: str, details: dict | None = None) -> None:
        self.script = script
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"{script!r}: [{code}] {message}")


class ScriptTimeoutError(DataRunnerError):
    """Raised when a script exceeds its declared ``timeout_seconds``."""


class OutputTooLargeError(DataRunnerError):
    """Raised when any declared output file exceeds ``max_output_bytes``."""


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StepResult:
    """Outcome of one script invocation."""

    step_id: str
    script: str
    outputs: dict[str, Any]  # output_id → parsed JSON content
    output_paths: dict[str, str]  # output_id → absolute on-disk path
    stdout_excerpt: str
    duration_seconds: float


# ---------------------------------------------------------------------------
# Argument substitution & flattening
# ---------------------------------------------------------------------------


def render_args(
    args: dict[str, Any],
    context: dict[str, Any],
    *,
    run_output_dir: Path | None = None,
) -> dict[str, Any]:
    """Substitute ``{{ ... }}`` placeholders inside the args mapping.

    Recursively walks dicts and lists. Values that contain a single
    ``{{ expr }}`` are replaced with the *parsed* JSONPath value (preserving
    types — lists/numbers/etc.). Values mixed with non-placeholder text are
    rendered as strings via ``str()``.

    **step-output → file-path coercion** (when ``run_output_dir`` is provided):
        If an arg value is a single full-string placeholder of the form
        ``{{ $.steps.<step>.<output> }}`` AND the placeholder resolves to a
        dict AND ``{run_output_dir}/data/<output>.json`` exists, the arg
        value is coerced to that absolute file path string. Lets DSL authors
        pass step outputs to scripts that expect ``--input <path>`` without
        having to type out the path manually.

        Silent fallback to the regular (stringified-dict) behaviour when any
        of the three conditions is not met. Args without a path-friendly
        intent (e.g. nested dict args) are unaffected.
    """
    return _render_recursive(args, context, run_output_dir=run_output_dir)


def _render_recursive(
    value: Any, context: dict[str, Any], *, run_output_dir: Path | None = None
) -> Any:
    if isinstance(value, dict):
        return {k: _render_recursive(v, context, run_output_dir=run_output_dir) for k, v in value.items()}
    if isinstance(value, list):
        return [_render_recursive(v, context, run_output_dir=run_output_dir) for v in value]
    if isinstance(value, str):
        return _render_string(value, context, run_output_dir=run_output_dir)
    return value


def _render_string(
    text: str, context: dict[str, Any], *, run_output_dir: Path | None = None
) -> Any:
    exprs = extract_expressions(text)
    if not exprs:
        return text
    stripped = text.strip()
    # Single full-string placeholder → preserve native type
    if len(exprs) == 1 and stripped.startswith("{{") and stripped.endswith("}}"):
        expr = exprs[0]
        ast = parse(expr)
        resolved = evaluate(ast, context)
        # step-output → file-path coercion (see render_args docstring)
        coerced = _maybe_coerce_to_step_output_path(
            expr=expr, resolved=resolved, run_output_dir=run_output_dir
        )
        return coerced if coerced is not None else resolved
    # Mixed text — interpolate
    out = text
    for expr in exprs:
        ast = parse(expr)
        resolved = evaluate(ast, context)
        # Search for the literal placeholder substring to replace
        for raw in _iter_raw_placeholders(text, expr):
            out = out.replace(raw, _stringify(resolved), 1)
    return out


def _maybe_coerce_to_step_output_path(
    *, expr: str, resolved: Any, run_output_dir: Path | None
) -> str | None:
    """Coerce a placeholder result to ``{run_output_dir}/data/<output>.json``.

    Returns the coerced path string if **all** these gates pass, else None
    (caller falls back to the regular ``resolved`` value):

    1. ``run_output_dir`` was supplied (i.e. caller is in args-rendering scope).
    2. The placeholder expression is exactly ``$.steps.<step>.<output>`` —
       two segments after ``steps``, no deeper traversal, no array selectors.
    3. The resolved value is a ``dict`` (step outputs are always dicts; if it
       isn't one, the caller likely wants the scalar value as-is).
    4. ``{run_output_dir}/data/<output>.json`` exists on disk.

    Silent fallback policy: any gate failure returns None and lets the caller
    use the original (stringified dict) behaviour. Errors are NEVER raised
    from this function — the coercion is an opportunistic upgrade.
    """
    if run_output_dir is None:
        return None
    segments = _step_output_segments(expr)
    if segments is None:
        return None
    _step_id, output_id = segments
    if not isinstance(resolved, dict):
        return None
    candidate = (run_output_dir / "data" / f"{output_id}.json").resolve()
    try:
        if not candidate.exists():
            return None
    except OSError:
        # e.g. permission errors on the lookup — silently fall back.
        return None
    return str(candidate)


def _step_output_segments(expr: str) -> tuple[str, str] | None:
    """Parse ``$.steps.<step>.<output>`` into (step_id, output_id).

    Returns None when the expression has any other shape — deeper paths,
    array-all selectors, or root other than ``$.steps``.
    """
    try:
        ast = parse(expr)
    except JSONPathError:
        return None
    # AST nodes are dataclasses: Root() / FieldAccess(name=...) / ArrayAll()
    # Expected shape: [Root, FieldAccess("steps"), FieldAccess(step), FieldAccess(output)]
    if len(ast) != 4:
        return None
    types_ok = (
        type(ast[0]).__name__ == "Root"
        and type(ast[1]).__name__ == "FieldAccess"
        and type(ast[2]).__name__ == "FieldAccess"
        and type(ast[3]).__name__ == "FieldAccess"
    )
    if not types_ok:
        return None
    if getattr(ast[1], "name", None) != "steps":
        return None
    step_id = getattr(ast[2], "name", None)
    output_id = getattr(ast[3], "name", None)
    if not isinstance(step_id, str) or not isinstance(output_id, str):
        return None
    return step_id, output_id


def _iter_raw_placeholders(text: str, expr: str):
    """Yield the raw `{{ ... }}` substrings that contain ``expr`` (handles spacing)."""
    import re

    needle = re.compile(r"\{\{\s*" + re.escape(expr) + r"\s*\}\}")
    return needle.findall(text)


def _stringify(value: Any) -> str:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return ""
    return str(value)


# ---------------------------------------------------------------------------
# Arg → CLI conversion
# ---------------------------------------------------------------------------


def apply_args_aliases(args: dict[str, Any], descriptor: ScriptDescriptor) -> dict[str, Any]:
    """Translate DSL-side short aliases to the canonical script enum values.

    Some scripts declare an ``args_aliases`` map in their ``report_scripts.yaml``
    so DSL templates can use ergonomic short names (e.g. ``mom``/``yoy``) while
    the underlying script only accepts the canonical long form
    (``previous_month``/``previous_year_month``). The translation is applied
    here, after JSONPath substitution and before CLI assembly, so that scripts
    never see the short aliases. Unrecognized values pass through unchanged
    — the script (and arg validator) catches them.
    """
    aliases = getattr(descriptor, "args_aliases", None) or {}
    if not aliases:
        return args
    translated: dict[str, Any] = {}
    for name, value in args.items():
        mapping = aliases.get(name)
        if not mapping:
            translated[name] = value
            continue
        if isinstance(value, list):
            translated[name] = [mapping.get(v, v) if isinstance(v, str) else v for v in value]
        elif isinstance(value, str):
            translated[name] = mapping.get(value, value)
        else:
            translated[name] = value
    return translated


def args_to_cli(args: dict[str, Any], descriptor: ScriptDescriptor) -> list[str]:
    """Turn the (substituted) args mapping into a ``--name value`` argv tail.

    Skips values that are ``None`` or empty lists. ``flag`` types only emit
    the flag when the value is truthy.
    """
    cli: list[str] = []
    for name, spec in descriptor.args_schema.items():
        if name not in args:
            continue
        value = args[name]
        if value is None:
            continue
        flag = f"--{name.replace('_', '-')}"
        spec_type = (getattr(spec, "type", "") or "").lower()
        if spec_type == "flag":
            if value:
                cli.append(flag)
            continue
        if isinstance(value, list):
            if not value:
                continue
            cli.append(flag)
            cli.append(",".join(str(v) for v in value))
            continue
        if isinstance(value, bool):
            if value:
                cli.append(flag)
            continue
        cli.extend([flag, str(value)])
    return cli


# ---------------------------------------------------------------------------
# Main entry: run_script
# ---------------------------------------------------------------------------


def _resolve_descriptor(
    qualified_name: str, registry: ScriptRegistry
) -> ScriptDescriptor:
    desc = registry.get(qualified_name)
    if desc is None:
        skill_name, _, _ = qualified_name.partition("/")
        try:
            from deerflow.report_templates.telemetry import get_telemetry

            get_telemetry().record_skill_unavailable(
                skill_name=skill_name or "<unknown>",
                action="disabled_after_publish",
                script_qualified_name=qualified_name,
            )
        except Exception:  # noqa: BLE001
            logger.debug("skill_unavailable telemetry failed", exc_info=True)
        raise UnknownScriptError(qualified_name, available=list(registry.scripts.keys()))
    return desc


def _resolve_output_paths(
    descriptor: ScriptDescriptor, run_output_dir: Path
) -> dict[str, Path]:
    """Substitute ``{run_output_dir}`` placeholder in declared output paths."""
    resolved: dict[str, Path] = {}
    for of in descriptor.output_files:
        rendered = of.path.replace("{run_output_dir}", str(run_output_dir))
        candidate = Path(rendered).resolve()
        # Path safety: must live under run_output_dir
        try:
            candidate.relative_to(run_output_dir.resolve())
        except ValueError:
            raise DataRunnerError(
                f"output path {candidate} escapes run_output_dir {run_output_dir}"
            )
        candidate.parent.mkdir(parents=True, exist_ok=True)
        resolved[of.id] = candidate
    return resolved


def run_script(
    *,
    step_id: str,
    script_qualified_name: str,
    args: dict[str, Any],
    registry: ScriptRegistry,
    run_output_dir: Path,
    context: dict[str, Any],
    python_executable: str | None = None,
    provider: str | None = None,
) -> StepResult:
    """Execute one script and return its parsed outputs.

    Args:
        step_id: The step's id from the DSL (used in error messages).
        script_qualified_name: ``<skill>/<script>`` namespaced name.
        args: Raw arg dict from the DSL — may contain ``{{ ... }}`` placeholders.
        registry: Pre-loaded ScriptRegistry.
        run_output_dir: Absolute path to ``{run_output_dir}`` — the script's
            scratch area. Must already exist.
        context: JSONPath substitution context (``form`` / ``steps`` / ``run`` /
            ``template`` keys, per §5.6).
        python_executable: Optional override; defaults to ``sys.executable``.

    Returns:
        StepResult — includes parsed output JSON content and absolute paths.

    Raises:
        UnknownScriptError, ScriptExecutionError, ScriptTimeoutError,
        OutputTooLargeError, JSONPathError, DataRunnerError.
    """
    descriptor = _resolve_descriptor(script_qualified_name, registry)

    # 1. Substitute placeholders. Pass run_output_dir so single-full-string
    #    placeholders of the form ``{{ $.steps.<step>.<output> }}`` that
    #    resolve to a dict get coerced into the corresponding output file
    #    path (when that file actually exists on disk).
    try:
        rendered_args = render_args(args, context, run_output_dir=run_output_dir)
    except JSONPathError as e:
        raise ScriptExecutionError(
            script=script_qualified_name,
            code="ARG_RESOLVE_FAILED",
            message=str(e),
        ) from e

    # 2. Resolve output paths.
    output_paths = _resolve_output_paths(descriptor, run_output_dir)

    # 3. Translate DSL short aliases (e.g. mom→previous_month) before CLI build.
    rendered_args = apply_args_aliases(rendered_args, descriptor)

    # 4. Build CLI argv.
    interpreter = python_executable or sys.executable
    cli_tail = args_to_cli(rendered_args, descriptor)
    cli = [interpreter, str(descriptor.entry_path), *cli_tail]
    if output_paths:
        cli.extend(["--output-dir", str(run_output_dir)])

    logger.info(
        "Running script %s [step_id=%s]: %s",
        script_qualified_name,
        step_id,
        " ".join(cli),
    )

    # 4. Run with timeout + resource caps.
    import os as _os
    import time

    # Inject user context as env vars so scripts can call auth-aware Gateway endpoints.
    subprocess_env = dict(_os.environ)
    auth_ctx = context.get("auth") if isinstance(context, dict) else None
    if isinstance(auth_ctx, dict):
        effective_user_id = auth_ctx.get("user_id")
        if effective_user_id is not None:
            subprocess_env["DEER_FLOW_EFFECTIVE_USER_ID"] = str(effective_user_id)
        tenant_id = auth_ctx.get("tenant_id")
        if tenant_id is not None:
            subprocess_env["DEER_FLOW_TENANT_ID"] = str(tenant_id)
        internal_token = auth_ctx.get("_internal_token")
        if internal_token is not None:
            subprocess_env["DEER_FLOW_INTERNAL_AUTH_VALUE"] = str(internal_token)

    # Inject thread_id so the platform bridge can route docker exec into the
    # correct sandbox container when running outside the sandbox.
    run_ctx = context.get("run") if isinstance(context, dict) else None
    if isinstance(run_ctx, dict):
        thread_id = run_ctx.get("thread_id")
        if thread_id is not None:
            subprocess_env["DEER_FLOW_THREAD_ID"] = str(thread_id)

    # Inject provider-driven env vars so scripts can detect platform mode.
    if provider is not None:
        if provider == "platform":
            subprocess_env["USE_PLATFORM"] = "true"
        else:
            subprocess_env["USE_PROVIDER"] = provider

    started = time.time()
    try:
        completed = subprocess.run(
            cli,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=descriptor.timeout_seconds,
            cwd=descriptor.skill_dir,
            check=False,
            env=subprocess_env,
            preexec_fn=_make_resource_limit(descriptor.max_output_bytes) if _can_setrlimit() else None,
        )
    except subprocess.TimeoutExpired as e:
        raise ScriptTimeoutError(
            f"{script_qualified_name!r} timed out after {descriptor.timeout_seconds}s"
        ) from e

    duration = time.time() - started

    # 5. Parse exit code & stderr.
    if completed.returncode != 0:
        details = _parse_structured_error(completed.stderr) or {"stderr": completed.stderr[-4096:]}
        raise ScriptExecutionError(
            script=script_qualified_name,
            code=details.get("code", "SCRIPT_FAILED"),
            message=details.get("message", f"exit code {completed.returncode}"),
            details=details,
        )

    # 6. Read declared output files & enforce size.
    outputs: dict[str, Any] = {}
    output_path_strs: dict[str, str] = {}
    for output_id, path in output_paths.items():
        if not path.exists():
            stdout_error = _parse_structured_error(completed.stdout) or {}
            stdout_excerpt = completed.stdout[-2048:] if completed.stdout else ""
            raise ScriptExecutionError(
                script=script_qualified_name,
                code="OUTPUT_MISSING",
                message=f"script did not produce declared output {output_id!r} at {path}",
                details={
                    "stdout_error": stdout_error.get("error") if stdout_error else None,
                    "stdout_excerpt": stdout_excerpt,
                    "stderr_excerpt": completed.stderr[-2048:] if completed.stderr else "",
                },
            )
        size = path.stat().st_size
        if size > descriptor.max_output_bytes:
            raise OutputTooLargeError(
                f"output {output_id!r} ({size} bytes) exceeds {descriptor.max_output_bytes}"
            )
        try:
            outputs[output_id] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise ScriptExecutionError(
                script=script_qualified_name,
                code="OUTPUT_PARSE_FAILED",
                message=f"cannot parse {output_id!r} as JSON: {e}",
            ) from e
        output_path_strs[output_id] = str(path)

    return StepResult(
        step_id=step_id,
        script=script_qualified_name,
        outputs=outputs,
        output_paths=output_path_strs,
        stdout_excerpt=completed.stdout[-4096:] if completed.stdout else "",
        duration_seconds=duration,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_structured_error(stderr: str) -> dict | None:
    if not stderr:
        return None
    # Try last line as JSON (scripts commonly emit one structured line at the end)
    candidates = [stderr.strip(), stderr.strip().splitlines()[-1] if stderr.strip() else ""]
    for candidate in candidates:
        if candidate.startswith("{") and candidate.endswith("}"):
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
    return None


def _can_setrlimit() -> bool:
    return _resource_module is not None and hasattr(_resource_module, "RLIMIT_AS")


def _make_resource_limit(max_bytes: int):  # pragma: no cover — POSIX only
    """Return a preexec_fn that caps virtual memory; no-op on Windows."""
    if _resource_module is None or not hasattr(_resource_module, "RLIMIT_AS"):
        return None

    def _set_limits() -> None:
        # Limit virtual address space — coarse but useful as a soft guard.
        cap = max(max_bytes * 4, 256 * 1024 * 1024)  # at least 256 MiB headroom
        _resource_module.setrlimit(_resource_module.RLIMIT_AS, (cap, cap))

    return _set_limits


# ---------------------------------------------------------------------------
# High-level orchestrators used by tools
# ---------------------------------------------------------------------------


def run_data_steps_and_transforms(
    *,
    dsl: dict[str, Any],
    registry: ScriptRegistry,
    run_output_dir: Path,
    context: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Execute every ``data_steps`` then every ``transforms`` in DSL order.

    Each step's outputs are folded back into ``context["steps"]`` so subsequent
    steps can reference them through JSONPath placeholders.

    Returns the merged ``step_outputs`` mapping for inclusion in
    ``status.json.step_outputs``.
    """
    accumulated: dict[str, dict[str, Any]] = dict(context.get("steps", {}))
    # Always operate on a writable copy of the context.
    ctx = dict(context)
    ctx["steps"] = accumulated

    for kind in ("data_steps", "transforms"):
        for step in dsl.get(kind, []) or []:
            step_id = step["id"]
            name = step["name"]
            args = dict(step.get("args") or {})
            # transforms also accept ``input: <step_id>.<output_id>``
            input_ref = step.get("input")
            if input_ref and "input" not in args:
                args["input"] = _resolve_input_path(input_ref, accumulated, run_output_dir)
            result = run_script(
                step_id=step_id,
                script_qualified_name=name,
                args=args,
                registry=registry,
                run_output_dir=run_output_dir,
                context=ctx,
                provider=step.get("provider"),
            )
            accumulated[step_id] = result.outputs

    return accumulated


def _resolve_input_path(
    ref: str, accumulated: dict[str, dict[str, Any]], run_output_dir: Path
) -> str:
    """Resolve a ``transforms[].input`` short reference to an absolute file path.

    Accepted forms:
      ``<step_id>.<output_id>`` (e.g. ``daily_data.daily_data``)
    """
    parts = ref.split(".")
    if len(parts) != 2:
        raise DataRunnerError(
            f"transforms input ref {ref!r} must be '<step_id>.<output_id>'"
        )
    step_id, output_id = parts
    if step_id not in accumulated:
        raise DataRunnerError(f"transform refers to unknown step {step_id!r}")
    # By convention the file is at {run_output_dir}/data/{output_id}.json
    candidate = (run_output_dir / "data" / f"{output_id}.json").resolve()
    if not candidate.exists():
        raise DataRunnerError(f"transform input file not found: {candidate}")
    return str(candidate)
