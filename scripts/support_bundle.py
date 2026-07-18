#!/usr/bin/env python3
"""Create a redacted DeerFlow support bundle for community troubleshooting."""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover - exercised only in broken environments
    yaml = None


SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|access[_-]?key|token|secret|password|passwd|pwd|authorization|cookie|credential|private[_-]?key)",
    re.IGNORECASE,
)
ENV_KEY_RE = re.compile(r"(?i)^env$")
VAR_REFERENCE_RE = re.compile(r"^\$\{?[A-Za-z_][A-Za-z0-9_]*\}?$")
ENV_SECRET_RE = re.compile(r"(?im)^([A-Z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|PASSWD|AUTHORIZATION|COOKIE|CREDENTIAL)[A-Z0-9_]*\s*=\s*)(.+)$")
YAML_SECRET_RE = re.compile(r"(?im)^(\s*[\w.-]*(?:api[_-]?key|token|secret|password|passwd|authorization|cookie|credential|private[_-]?key)[\w.-]*\s*:\s*)(.+)$")
BEARER_RE = re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]+")
OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
URL_USERINFO_RE = re.compile(r"([a-zA-Z][\w+.-]*://)([^/?#\s@]+)@")
URL_QUERY_SECRET_RE = re.compile(r"(?i)([?&][\w.-]*(?:api[_-]?key|token|secret|password|passwd|authorization|access[_-]?token|credential)[\w.-]*=)([^&\s#]+)")
CLI_INLINE_SECRET_RE = re.compile(r"(?i)(--?[\w.-]*(?:api[_-]?key|token|secret|password|passwd|authorization|cookie|credential)[\w.-]*=)(\S+)")
SECRET_FLAG_RE = re.compile(r"(?i)^--?[\w.-]*(?:api[_-]?key|token|secret|password|passwd|authorization|cookie|credential)[\w.-]*$")
HEADER_KEY_RE = re.compile(r"(?i)header")
POSIX_HOME_RE = re.compile(r"(?<![\w.-])(/Users|/home)/([^/\s:]+)")
WINDOWS_HOME_RE = re.compile(r"(?i)([A-Z]:\\Users\\)([^\\\s:]+)")
SAFE_THREAD_ID_RE = re.compile(r"^[a-zA-Z0-9._-]+$")
DOCTOR_STATUS_RE = re.compile(r"Status:\s*(\d+)\s+error\(s\),\s*(\d+)\s+warning\(s\)", re.IGNORECASE)
ATTENTION_SIGNAL_NAMES = {
    "doctor_failed",
    "config_missing",
    "config_error",
    "models_missing",
    "extensions_config_error",
    "node_missing",
    "node_version_too_old",
    "nginx_missing",
    "dirty_worktree",
}


def _redact_yaml_secret_match(match: re.Match[str]) -> str:
    prefix = match.group(1)
    value = match.group(2)
    if "authorization" in prefix.lower() and value.lstrip().lower().startswith("bearer "):
        return prefix + BEARER_RE.sub(r"\1<redacted>", value)
    return prefix + "<redacted>"


def redact_text(text: str) -> str:
    """Redact common secret patterns from free-form text."""
    text = POSIX_HOME_RE.sub(r"\1/<user>", text)
    text = WINDOWS_HOME_RE.sub(r"\1<user>", text)
    text = URL_USERINFO_RE.sub(r"\1<redacted>@", text)
    text = URL_QUERY_SECRET_RE.sub(r"\1<redacted>", text)
    text = CLI_INLINE_SECRET_RE.sub(r"\1<redacted>", text)
    text = ENV_SECRET_RE.sub(r"\1<redacted>", text)
    text = YAML_SECRET_RE.sub(_redact_yaml_secret_match, text)
    text = BEARER_RE.sub(r"\1<redacted>", text)
    return OPENAI_KEY_RE.sub("sk-<redacted>", text)


def _redact_secret_flag_list(items: list[Any]) -> list[Any]:
    """Mask the value that follows a secret-like CLI flag (e.g. ['--api-key', 'X'])."""
    redacted: list[Any] = []
    mask_next = False
    for item in items:
        if mask_next:
            redacted.append("<redacted>" if isinstance(item, str) else redact_data(item))
            mask_next = False
            continue
        if isinstance(item, str) and SECRET_FLAG_RE.fullmatch(item):
            redacted.append(item)
            mask_next = True
            continue
        redacted.append(redact_data(item))
    return redacted


def _redact_env_value(value: Any) -> Any:
    """Mask env values by default; keep only ``$VAR`` / ``${VAR}`` references visible."""
    if isinstance(value, str) and VAR_REFERENCE_RE.fullmatch(value.strip()):
        return value
    if isinstance(value, (dict, list, tuple)):
        return redact_data(value)
    return "<redacted>"


def redact_data(value: Any) -> Any:
    """Recursively redact secret-like mapping keys while preserving structure."""
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            if SECRET_KEY_RE.search(str(key)):
                redacted[key] = "<redacted>"
            elif ENV_KEY_RE.fullmatch(str(key)) and isinstance(item, dict):
                redacted[key] = {k: _redact_env_value(v) for k, v in item.items()}
            elif HEADER_KEY_RE.search(str(key)) and isinstance(item, dict):
                redacted[key] = {k: "<redacted>" for k in item}
            else:
                redacted[key] = redact_data(item)
        return redacted
    if isinstance(value, list):
        return _redact_secret_flag_list(value)
    if isinstance(value, tuple):
        return _redact_secret_flag_list(list(value))
    if isinstance(value, str):
        return redact_text(value)
    return value


def _read_yaml(path: Path) -> Any:
    if not path.exists():
        return {"present": False}
    if yaml is None:
        return {"present": True, "error": "PyYAML is not available"}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return {"present": True, "error": f"{type(exc).__name__}: {exc}"}


def _read_json(path: Path) -> Any:
    if not path.exists():
        return {"present": False}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"present": True, "error": f"{type(exc).__name__}: {exc}"}


def _run_command(args: list[str], cwd: Path, timeout_s: int = 10) -> dict[str, Any]:
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": redact_text((result.stdout or "").strip()),
            "stderr": redact_text((result.stderr or "").strip()),
        }
    except FileNotFoundError:
        return {"ok": False, "error": f"{args[0]} not found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"{args[0]} timed out after {timeout_s}s"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _version_command(name: str, args: list[str], cwd: Path) -> dict[str, Any]:
    result = _run_command(args, cwd=cwd, timeout_s=5)
    return {"name": name, **result}


def collect_environment(project_root: Path) -> dict[str, Any]:
    """Collect non-secret environment and toolchain metadata."""
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "commands": [
            _version_command("node", ["node", "--version"], project_root),
            _version_command("pnpm", ["pnpm", "--version"], project_root),
            _version_command("uv", ["uv", "--version"], project_root),
            _version_command("nginx", ["nginx", "-v"], project_root),
            _version_command("docker", ["docker", "--version"], project_root),
        ],
    }


def collect_config_summary(config_path: Path) -> Any:
    return redact_data(_read_yaml(config_path))


def collect_extensions_summary(extensions_config_path: Path) -> Any:
    return redact_data(_read_json(extensions_config_path))


def collect_git_summary(project_root: Path) -> dict[str, Any]:
    """Collect best-effort git metadata without requiring a git checkout."""
    commands = {
        "branch": ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        "head": ["git", "rev-parse", "HEAD"],
        "upstream": ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        "status_short": ["git", "status", "--short", "--branch"],
        "diff_stat": ["git", "diff", "--stat"],
    }
    return {name: _run_command(command, cwd=project_root) for name, command in commands.items()}


def _validate_thread_id(thread_id: str) -> None:
    if not thread_id or thread_id in {".", ".."} or ".." in thread_id or not SAFE_THREAD_ID_RE.fullmatch(thread_id):
        raise ValueError(f"Invalid thread_id: {thread_id!r}")


def _candidate_thread_data_dirs(project_root: Path, thread_id: str) -> list[Path]:
    _validate_thread_id(thread_id)
    candidates = [
        project_root / ".deer-flow" / "threads" / thread_id / "user-data",
        project_root / "backend" / ".deer-flow" / "threads" / thread_id / "user-data",
    ]
    for base in (project_root / ".deer-flow" / "users", project_root / "backend" / ".deer-flow" / "users"):
        if base.exists():
            candidates.extend(user_dir / "threads" / thread_id / "user-data" for user_dir in base.iterdir() if user_dir.is_dir())
    return candidates


def _display_path(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except (OSError, ValueError):
        return redact_text(path.as_posix())


def _file_manifest(root: Path, *, max_files: int = 500) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    entries: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if len(entries) >= max_files:
            entries.append({"path": "<truncated>", "reason": f"file limit {max_files} reached"})
            break
        try:
            stat = path.stat()
        except OSError as exc:
            entries.append(
                {
                    "path": redact_text(path.relative_to(root).as_posix()),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        entries.append(
            {
                "path": redact_text(path.relative_to(root).as_posix()),
                "size_bytes": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
            }
        )
    return entries


def collect_thread_summary(project_root: Path, thread_id: str) -> dict[str, Any]:
    """Collect a thread file manifest without reading user file contents."""
    for data_dir in _candidate_thread_data_dirs(project_root, thread_id):
        if data_dir.exists():
            return {
                "thread_id": thread_id,
                "found": True,
                "layout": _display_path(data_dir, project_root),
                "workspace": _file_manifest(data_dir / "workspace"),
                "uploads": _file_manifest(data_dir / "uploads"),
                "outputs": _file_manifest(data_dir / "outputs"),
            }
    return {
        "thread_id": thread_id,
        "found": False,
        "checked_layouts": [_display_path(path, project_root) for path in _candidate_thread_data_dirs(project_root, thread_id)],
    }


def collect_doctor_output(project_root: Path) -> dict[str, Any]:
    backend_dir = project_root / "backend"
    cwd = backend_dir if backend_dir.exists() else project_root
    return _run_command([sys.executable, str(project_root / "scripts" / "doctor.py")], cwd=cwd, timeout_s=60)


def _command_output(command: dict[str, Any] | None) -> str | None:
    if not command:
        return None
    for key in ("stdout", "stderr", "error"):
        value = command.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _environment_versions(environment: dict[str, Any]) -> dict[str, str | None]:
    platform_info = environment.get("platform", {})
    python_version = platform_info.get("python") if isinstance(platform_info, dict) else None
    versions: dict[str, str | None] = {"python": python_version if isinstance(python_version, str) else None}
    for command in environment.get("commands", []):
        if isinstance(command, dict) and isinstance(command.get("name"), str):
            versions[command["name"]] = _command_output(command)
    return versions


def _parse_major_version(version_text: str | None) -> int | None:
    if not version_text:
        return None
    match = re.search(r"v?(\d+)(?:\.\d+)?", version_text)
    return int(match.group(1)) if match else None


def _git_stdout(git_summary: dict[str, Any], key: str) -> str | None:
    value = git_summary.get(key)
    return _command_output(value) if isinstance(value, dict) else None


def _doctor_counts(doctor: dict[str, Any] | None) -> tuple[int | None, int | None]:
    if not doctor:
        return (None, None)
    output = "\n".join(value for value in (_command_output(doctor), doctor.get("stdout"), doctor.get("stderr")) if isinstance(value, str))
    match = DOCTOR_STATUS_RE.search(output)
    if not match:
        return (None, None)
    return (int(match.group(1)), int(match.group(2)))


def _enabled_mapping_keys(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    keys: list[str] = []
    for key, item in value.items():
        if isinstance(item, dict) and item.get("enabled") is False:
            continue
        keys.append(str(key))
    return sorted(keys)


def _config_summary(config_summary: Any) -> dict[str, Any]:
    if not isinstance(config_summary, dict):
        return {"present": True, "shape": type(config_summary).__name__}
    present = config_summary.get("present", True)
    if present is False:
        return {"present": False, "models": 0, "tools": [], "channels": []}
    models = config_summary.get("models")
    tools = config_summary.get("tools")
    channels = config_summary.get("channels")
    return {
        "present": True,
        "config_version": config_summary.get("config_version"),
        "error": config_summary.get("error"),
        "models": len(models) if isinstance(models, list) else 0,
        "tools": sorted(str(tool.get("name")) for tool in tools if isinstance(tool, dict) and tool.get("name")) if isinstance(tools, list) else [],
        "channels": _enabled_mapping_keys(channels),
    }


def _extensions_summary(extensions_summary: Any) -> dict[str, Any]:
    if not isinstance(extensions_summary, dict):
        return {"present": True, "shape": type(extensions_summary).__name__}
    present = extensions_summary.get("present", True)
    if present is False:
        return {"present": False, "mcp_servers": [], "skills": []}
    return {
        "present": True,
        "error": extensions_summary.get("error"),
        "mcp_servers": _enabled_mapping_keys(extensions_summary.get("mcpServers")),
        "skills": _enabled_mapping_keys(extensions_summary.get("skills")),
    }


def _dirty_worktree(status_short: str | None) -> bool:
    if not status_short:
        return False
    return any(line and not line.startswith("##") for line in status_short.splitlines())


def _status_from_signals(signals: dict[str, bool]) -> str:
    if signals["config_missing"] or signals["config_error"] or signals["models_missing"] or signals["extensions_config_error"]:
        return "needs_user_setup"
    if signals["node_missing"] or signals["node_version_too_old"] or signals["nginx_missing"]:
        return "environment_mismatch"
    if not signals["doctor_included"]:
        return "insufficient_evidence"
    if signals["doctor_failed"]:
        return "likely_runtime_issue"
    return "ok"


def _active_signal_names(signals: dict[str, bool]) -> list[str]:
    return [name for name, enabled in signals.items() if enabled and name in ATTENTION_SIGNAL_NAMES]


def _maintainer_next_steps(status: str, signals: dict[str, bool]) -> list[str]:
    steps: list[str] = []
    if status == "needs_user_setup":
        steps.append("Ask the reporter to complete local setup with `make setup`, then rerun `make doctor` and `make support-bundle`.")
    if signals["node_missing"] or signals["node_version_too_old"]:
        steps.append("Ask the reporter to install Node.js 22+ before treating this as an application bug.")
    if signals["config_missing"] or signals["models_missing"]:
        steps.append("Do not triage model/runtime behavior until `config.yaml` exists and at least one model is configured.")
    if signals["config_error"]:
        steps.append("Ask the reporter to fix `config.yaml` syntax or regenerate it with `make setup`.")
    if signals["extensions_config_error"]:
        steps.append("Ask the reporter to fix `extensions_config.json` syntax before triaging MCP/skill behavior.")
    if signals["doctor_failed"] and status == "likely_runtime_issue":
        steps.append("Use `doctor.json` plus the reproduction steps in the issue body to identify the failing subsystem.")
    if signals["thread_summary_included"]:
        steps.append("Use `thread-summary.json` to inspect workspace/upload/output file shape; raw file contents are intentionally absent.")
    if not steps:
        steps.append("Use the issue reproduction steps and evidence JSON files to continue triage.")
    return steps


def _reporter_next_steps(status: str, signals: dict[str, bool]) -> list[str]:
    steps: list[str] = []
    if status == "needs_user_setup":
        steps.append("Run `make setup`, then rerun `make doctor` and `make support-bundle` before filing the issue if the problem changes.")
    if signals["node_missing"] or signals["node_version_too_old"]:
        steps.append("Install Node.js 22+ and rerun `make doctor`.")
    if signals["config_missing"] or signals["models_missing"]:
        steps.append("Create or repair `config.yaml` with `make setup`; model/runtime issues cannot be triaged until at least one model is configured.")
    if signals["config_error"]:
        steps.append("Fix `config.yaml` syntax or regenerate it with `make setup`.")
    if signals["doctor_failed"] and status == "likely_runtime_issue":
        steps.append("Paste the generated issue summary into the GitHub issue. Attach the zip if a maintainer asks for the evidence bundle.")
    if not steps:
        steps.append("Paste the generated issue summary into the GitHub issue if the issue still reproduces. Attach the zip if a maintainer asks for the evidence bundle.")
    return steps


def _evidence_files(*, include_doctor: bool, include_thread_summary: bool) -> list[dict[str, str]]:
    files = [
        ("README.md", "Human-readable entrypoint for the support bundle."),
        ("issue-summary.md", "Markdown summary intended to be pasted into a GitHub issue."),
        ("ai-issue-draft.md", "GitHub issue draft for AI-assisted filing with required placeholders for unknown user facts."),
        ("triage.json", "Stable machine-readable summary for AI or script-assisted triage."),
        ("manifest.json", "Bundle schema, generation time, and privacy declaration."),
        ("environment.json", "OS, Python, and toolchain version probes."),
        ("config-summary.json", "Redacted config.yaml structure."),
        ("extensions-summary.json", "Redacted extensions_config.json structure."),
        ("git.json", "Branch, commit, upstream, status, and diff-stat metadata."),
    ]
    if include_thread_summary:
        files.append(("thread-summary.json", "Optional thread workspace/upload/output file manifests only."))
    if include_doctor:
        files.append(("doctor.json", "Redacted make doctor output."))
    return [{"path": path, "description": description} for path, description in files]


def build_triage_report(
    *,
    manifest: dict[str, Any],
    environment: dict[str, Any],
    config_summary: Any,
    extensions_summary: Any,
    git_summary: dict[str, Any],
    doctor: dict[str, Any] | None,
    thread_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the stable machine-readable summary that maintainers and AI read first."""
    versions = _environment_versions(environment)
    config = _config_summary(config_summary)
    extensions = _extensions_summary(extensions_summary)
    node_major = _parse_major_version(versions.get("node"))
    status_short = _git_stdout(git_summary, "status_short")
    doctor_errors, doctor_warnings = _doctor_counts(doctor)
    signals = {
        "doctor_included": doctor is not None,
        "doctor_failed": bool(doctor and not doctor.get("ok")),
        "config_missing": config.get("present") is False,
        "config_error": bool(config.get("error")),
        "models_missing": bool(config.get("present") is True and config.get("models") == 0),
        "extensions_config_missing": extensions.get("present") is False,
        "extensions_config_error": bool(extensions.get("error")),
        "node_missing": versions.get("node") is not None and "not found" in versions["node"].lower(),
        "node_version_too_old": node_major is not None and node_major < 22,
        "nginx_missing": versions.get("nginx") is not None and "not found" in versions["nginx"].lower(),
        "dirty_worktree": _dirty_worktree(status_short),
        "thread_summary_included": thread_summary is not None,
        "thread_summary_found": bool(thread_summary and thread_summary.get("found")),
    }
    status = _status_from_signals(signals)
    return {
        "schema_version": 1,
        "generated_at": manifest["generated_at"],
        "status": status,
        "active_signals": _active_signal_names(signals),
        "signals": signals,
        "versions": versions,
        "platform": environment.get("platform", {}),
        "config": config,
        "extensions": extensions,
        "git": {
            "branch": _git_stdout(git_summary, "branch"),
            "head": _git_stdout(git_summary, "head"),
            "upstream": _git_stdout(git_summary, "upstream"),
            "dirty_worktree": signals["dirty_worktree"],
        },
        "doctor": {
            "included": doctor is not None,
            "ok": bool(doctor and doctor.get("ok")),
            "returncode": doctor.get("returncode") if doctor else None,
            "errors": doctor_errors,
            "warnings": doctor_warnings,
        },
        "thread": {
            "included": thread_summary is not None,
            "found": bool(thread_summary and thread_summary.get("found")),
        },
        "reporter_next_steps": _reporter_next_steps(status, signals),
        "maintainer_next_steps": _maintainer_next_steps(status, signals),
        "evidence_files": _evidence_files(include_doctor=doctor is not None, include_thread_summary=thread_summary is not None),
        "privacy": manifest["privacy"],
    }


def _markdown_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- None"


def render_issue_summary(triage: dict[str, Any]) -> str:
    """Render Markdown that users can paste into the GitHub issue body."""
    git = triage["git"]
    doctor = triage["doctor"]
    versions = triage["versions"]
    lines = [
        "## DeerFlow support bundle summary",
        "",
        f"- Triage status: {triage['status']}",
        f"- Active signals: {', '.join(triage['active_signals']) or 'none'}",
        f"- Doctor: included={doctor['included']}, ok={doctor['ok']}, errors={doctor['errors']}, warnings={doctor['warnings']}",
        f"- Git: branch={git['branch'] or 'unknown'}, head={git['head'] or 'unknown'}, dirty_worktree={git['dirty_worktree']}",
        f"- Versions: python={versions.get('python') or 'unknown'}, node={versions.get('node') or 'unknown'}, pnpm={versions.get('pnpm') or 'unknown'}, uv={versions.get('uv') or 'unknown'}, nginx={versions.get('nginx') or 'unknown'}",
        "",
        "### Reporter next steps",
        _markdown_list(triage["reporter_next_steps"]),
        "",
        "### Upload guidance",
        "Paste this summary into the GitHub issue. Attach the zip if a maintainer asks for the evidence bundle, or if the summary alone is not enough to diagnose the issue.",
        "",
        "### Maintainer next steps",
        _markdown_list(triage["maintainer_next_steps"]),
        "",
        "### Evidence files in the attached zip",
        _markdown_list([f"`{item['path']}` - {item['description']}" for item in triage["evidence_files"]]),
        "",
        "Privacy: this bundle excludes `.env`, raw conversation messages, and user file contents.",
        "",
    ]
    return "\n".join(lines)


def _os_label(platform_info: dict[str, Any]) -> str:
    system = platform_info.get("system")
    if system == "Darwin":
        return "macOS"
    if system == "Linux":
        return "Linux"
    if system == "Windows":
        return "Windows"
    return "Other"


def _platform_details(platform_info: dict[str, Any]) -> str:
    details = [platform_info.get("machine"), platform_info.get("system"), platform_info.get("release")]
    return ", ".join(str(item) for item in details if item) or "_No response_"


def _draft_affected_areas(triage: dict[str, Any]) -> list[str]:
    signals = triage["signals"]
    areas: list[str] = []
    if signals["config_missing"] or signals["config_error"] or signals["models_missing"] or signals["node_missing"] or signals["node_version_too_old"] or signals["nginx_missing"]:
        areas.append("Config / setup (make, config.yaml, env)")
    if signals["extensions_config_error"]:
        areas.extend(["MCP", "Skills"])
    if not areas:
        areas.append("Not sure")
    return areas


def _doctor_excerpt(doctor: dict[str, Any] | None, *, max_lines: int = 80, max_chars: int = 12000) -> str:
    output = _command_output(doctor) if doctor else None
    if not output:
        return "<REQUIRED: paste key log lines. Do not invent if unknown.>"
    output = redact_text(output)
    lines = output.splitlines()
    truncated = False
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        truncated = True
    excerpt = "\n".join(lines)
    if len(excerpt) > max_chars:
        excerpt = excerpt[:max_chars].rstrip()
        truncated = True
    if truncated:
        excerpt += "\n<support bundle doctor output truncated>"
    return excerpt


def render_ai_issue_draft(triage: dict[str, Any], issue_summary: str, doctor: dict[str, Any] | None) -> str:
    """Render a GitHub issue body scaffold for AI-assisted reporters."""
    versions = triage["versions"]
    git = triage["git"]
    platform_info = triage["platform"]
    lines = [
        "# AI issue draft",
        "",
        "Use this when a coding agent or AI assistant files a DeerFlow bug report.",
        "Do not file this issue until every REQUIRED placeholder is replaced.",
        "Do not invent if unknown; ask the reporter for missing reproduction facts instead.",
        "",
        "## Issue title",
        "",
        "[bug] <REQUIRED: one-line problem summary>",
        "",
        "### Before you start",
        "",
        "- [ ] I searched [existing issues](https://github.com/bytedance/deer-flow/issues?q=is%3Aissue) and this is not a duplicate.",
        "- [ ] I can reproduce this on the latest `main`.",
        "",
        "### Problem summary",
        "",
        "<!-- REQUIRED: One sentence describing the bug. Do not invent if unknown. -->",
        "<REQUIRED: one sentence problem summary>",
        "",
        "### Affected area(s)",
        "",
        "\n".join(_draft_affected_areas(triage)),
        "<!-- AI hint: derived from support bundle signals; adjust only if the reporter's reproduction proves a better area. -->",
        "",
        "### What happened?",
        "",
        "<!-- REQUIRED: Actual behavior and key error lines. Do not invent if unknown. -->",
        "<REQUIRED: describe what happened>",
        "",
        "### Expected behavior",
        "",
        "<!-- REQUIRED: What should have happened instead. Do not invent if unknown. -->",
        "<REQUIRED: describe expected behavior>",
        "",
        "### Steps to reproduce",
        "",
        "<!-- REQUIRED: Exact commands and sequence. Do not invent if unknown. -->",
        "1. <REQUIRED: first command or action>",
        "2. <REQUIRED: next command or action>",
        "",
        "### Relevant logs",
        "",
        "<!-- Include additional gateway/frontend/sandbox logs if the reporter has them. Keep secrets redacted. -->",
        "```shell",
        _doctor_excerpt(doctor),
        "```",
        "",
        "### How are you running DeerFlow?",
        "",
        "<REQUIRED: choose Local, Docker, CI, or Other>",
        "",
        "### Operating system",
        "",
        _os_label(platform_info),
        "",
        "### Platform details",
        "",
        _platform_details(platform_info),
        "",
        "### Python version",
        "",
        versions.get("python") or "_No response_",
        "",
        "### Node.js version",
        "",
        versions.get("node") or "_No response_",
        "",
        "### pnpm version",
        "",
        versions.get("pnpm") or "_No response_",
        "",
        "### uv version",
        "",
        versions.get("uv") or "_No response_",
        "",
        "### Git state",
        "",
        f"branch: {git['branch'] or 'unknown'}",
        f"commit: {git['head'] or 'unknown'}",
        f"upstream: {git['upstream'] or 'unknown'}",
        f"dirty_worktree: {git['dirty_worktree']}",
        "",
        "### Support bundle summary",
        "",
        issue_summary.rstrip(),
        "",
        "### Additional context",
        "",
        "Attach the zip only if a maintainer asks for the evidence bundle, or if the summary alone is not enough.",
        "",
    ]
    return "\n".join(lines)


def render_bundle_readme(triage: dict[str, Any]) -> str:
    """Render the support bundle README."""
    lines = [
        "# DeerFlow Support Bundle",
        "",
        "## Start here",
        "",
        "Paste `issue-summary.md` into the GitHub issue body.",
        "If an AI assistant is filing the issue, start from `ai-issue-draft.md` and replace every REQUIRED placeholder first.",
        "Maintainers or AI triage tools should read `triage.json` first, then inspect the evidence JSON files only as needed.",
        "",
        "## Triage Summary",
        "",
        f"- Status: {triage['status']}",
        f"- Active signals: {', '.join(triage['active_signals']) or 'none'}",
        "",
        "## Reporter next steps",
        "",
        _markdown_list(triage["reporter_next_steps"]),
        "",
        "## Upload guidance",
        "",
        "Paste `issue-summary.md` into the GitHub issue. Attach the zip if a maintainer asks for the evidence bundle, or if the summary alone is not enough to diagnose the issue.",
        "",
        "## Maintainer next steps",
        "",
        _markdown_list(triage["maintainer_next_steps"]),
        "",
        "## Files",
        "",
        _markdown_list([f"`{item['path']}` - {item['description']}" for item in triage["evidence_files"]]),
        "",
        "## Privacy",
        "",
        "- `.env` is not included.",
        "- Raw conversation messages are not included.",
        "- Thread workspace/upload/output file contents are not included; optional thread data is a file manifest only.",
        "",
    ]
    return "\n".join(lines)


def _default_out_path(project_root: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return project_root / ".deer-flow" / "support-bundles" / f"deer-flow-support-bundle-{timestamp}.zip"


def _write_json(zf: zipfile.ZipFile, name: str, data: Any) -> None:
    zf.writestr(f"{name}.json", json.dumps(data, indent=2, sort_keys=True) + "\n")


def _write_text(zf: zipfile.ZipFile, name: str, text: str) -> None:
    zf.writestr(name, text)


def _issue_summary_sidecar_path(out_path: Path) -> Path:
    return out_path.with_name(f"{out_path.stem}-issue-summary.md")


def _issue_draft_sidecar_path(out_path: Path) -> Path:
    return out_path.with_name(f"{out_path.stem}-issue-draft.md")


def create_support_bundle(
    *,
    project_root: Path,
    out_path: Path | None = None,
    config_path: Path | None = None,
    extensions_config_path: Path | None = None,
    thread_id: str | None = None,
    include_doctor: bool = False,
) -> Path:
    """Create a redacted support bundle and return the zip path."""
    project_root = project_root.resolve()
    config_path = (config_path or project_root / "config.yaml").resolve()
    extensions_config_path = (extensions_config_path or project_root / "extensions_config.json").resolve()
    out_path = (out_path or _default_out_path(project_root)).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if thread_id:
        _validate_thread_id(thread_id)

    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "project": project_root.name,
        "includes": {
            "doctor": include_doctor,
            "thread_summary": thread_id is not None,
        },
        "privacy": {
            "redacted_secret_fields": True,
            "raw_thread_messages": False,
            "raw_user_files": False,
            "raw_env_file": False,
        },
    }

    environment = collect_environment(project_root)
    config_summary = collect_config_summary(config_path)
    extensions_summary = collect_extensions_summary(extensions_config_path)
    git_summary = collect_git_summary(project_root)
    thread_summary = collect_thread_summary(project_root, thread_id) if thread_id else None
    doctor = collect_doctor_output(project_root) if include_doctor else None
    triage = build_triage_report(
        manifest=manifest,
        environment=environment,
        config_summary=config_summary,
        extensions_summary=extensions_summary,
        git_summary=git_summary,
        doctor=doctor,
        thread_summary=thread_summary,
    )

    issue_summary = render_issue_summary(triage)
    issue_draft = render_ai_issue_draft(triage, issue_summary, doctor)
    with zipfile.ZipFile(out_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        _write_text(zf, "README.md", render_bundle_readme(triage))
        _write_text(zf, "issue-summary.md", issue_summary)
        _write_text(zf, "ai-issue-draft.md", issue_draft)
        _write_json(zf, "triage", triage)
        _write_json(zf, "manifest", manifest)
        _write_json(zf, "environment", environment)
        _write_json(zf, "config-summary", config_summary)
        _write_json(zf, "extensions-summary", extensions_summary)
        _write_json(zf, "git", git_summary)
        if thread_summary is not None:
            _write_json(zf, "thread-summary", thread_summary)
        if doctor is not None:
            _write_json(zf, "doctor", doctor)

    _issue_summary_sidecar_path(out_path).write_text(issue_summary, encoding="utf-8")
    _issue_draft_sidecar_path(out_path).write_text(issue_draft, encoding="utf-8")
    return out_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    repo_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--project-root", type=Path, default=repo_root, help="DeerFlow project root")
    parser.add_argument("--config", type=Path, default=None, help="Path to config.yaml")
    parser.add_argument("--extensions-config", type=Path, default=None, help="Path to extensions_config.json")
    parser.add_argument("--thread-id", default=None, help="Optional thread id to include file manifests for")
    parser.add_argument("--out", type=Path, default=None, help="Output zip path")
    parser.add_argument("--include-doctor", action="store_true", help="Include redacted make doctor output")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        bundle_path = create_support_bundle(
            project_root=args.project_root,
            out_path=args.out,
            config_path=args.config,
            extensions_config_path=args.extensions_config,
            thread_id=args.thread_id,
            include_doctor=args.include_doctor,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    with zipfile.ZipFile(bundle_path) as zf:
        triage = json.loads(zf.read("triage.json").decode("utf-8"))
    print(f"Support bundle: {bundle_path}")
    print(f"Issue summary: {_issue_summary_sidecar_path(bundle_path)}")
    print(f"Issue draft: {_issue_draft_sidecar_path(bundle_path)}")
    print("Suggested next steps:")
    for step in triage["reporter_next_steps"]:
        print(f"- {step}")
    print("If you still file an issue, paste the issue summary.")
    print("If an AI assistant files the issue, start from the issue draft and replace every REQUIRED placeholder.")
    print("Attach the zip if a maintainer asks for the evidence bundle, or if the summary alone is not enough.")
    print("Maintainers or AI triage tools should read triage.json first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
