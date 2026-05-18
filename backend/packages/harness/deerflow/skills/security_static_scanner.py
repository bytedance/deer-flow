"""Deterministic static security scanning for skill packages."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict

logger = logging.getLogger(__name__)

StaticSeverity = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]


class StaticFinding(TypedDict):
    rule_id: str
    severity: StaticSeverity
    file: str
    line: int
    message: str
    remediation: str


class StaticScannerError(RuntimeError):
    """Raised when the static scanner cannot run reliably."""


@dataclass(frozen=True)
class _SemgrepScanOutput:
    payload: dict[str, Any]
    scan_root: Path


RULES_DIR = Path(__file__).with_name("static_rules")
_SEMGREP_TIMEOUT_SECONDS = 30
_ACTIVE_ENV_SEMGREP_NAMES = ("semgrep", "semgrep.exe", "semgrep.cmd")
_UNTRUSTED_SEMGREP_CONTROL_FILES = {".git", ".gitignore", ".semgrepignore"}
_VALID_SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
_SEMGREP_SEVERITY_MAP: dict[str, StaticSeverity] = {
    "ERROR": "HIGH",
    "WARNING": "MEDIUM",
    "INFO": "LOW",
}


def static_findings_to_dicts(findings: list[StaticFinding]) -> list[StaticFinding]:
    """Return JSON-serialisable copies of findings."""
    return [
        {
            "rule_id": finding["rule_id"],
            "severity": finding["severity"],
            "file": finding["file"],
            "line": finding["line"],
            "message": finding["message"],
            "remediation": finding["remediation"],
        }
        for finding in findings
    ]


def _critical_static_findings(findings: list[StaticFinding]) -> list[StaticFinding]:
    return [finding for finding in findings if finding["severity"] == "CRITICAL"]


def format_static_findings(findings: list[StaticFinding]) -> str:
    parts = []
    for finding in findings:
        location = f"{finding['file']}:{finding['line']}"
        parts.append(f"{finding['rule_id']} ({finding['severity']}) at {location}: {finding['message']} Remediation: {finding['remediation']}")
    return "; ".join(parts)


class StaticScanBlockedError(ValueError):
    """Raised when static findings must block a skill write or install."""

    findings: list[StaticFinding]
    skill_name: str | None

    def __init__(self, findings: list[StaticFinding], *, skill_name: str | None = None) -> None:
        self.findings = static_findings_to_dicts(findings)
        self.skill_name = skill_name
        subject = f"skill '{skill_name}'" if skill_name else "skill content"
        super().__init__(f"Static security scan blocked {subject}: {format_static_findings(self.findings)}")


def enforce_static_scan(skill_dir: Path, *, skill_name: str | None = None) -> list[StaticFinding]:
    """Run static scanning and raise when findings must block the operation."""
    findings = run_static_scan(skill_dir)
    critical = _critical_static_findings(findings)
    if critical:
        raise StaticScanBlockedError(critical, skill_name=skill_name)
    if findings:
        subject = f"skill {skill_name}" if skill_name else str(skill_dir)
        logger.warning("Static security scan produced warning findings for %s: %s", subject, format_static_findings(findings))
    return static_findings_to_dicts(findings)


def run_static_scan(skill_dir: Path) -> list[StaticFinding]:
    """Run Semgrep rules against a skill directory.

    Scanner failures are fatal to the scan. Callers that gate writes or
    installs must block the operation when StaticScannerError is raised.
    """
    skill_root = Path(skill_dir)
    try:
        scan_output = _run_semgrep(skill_root)
    except StaticScannerError:
        raise
    except Exception as e:
        raise StaticScannerError(f"static scanner failed: {e}") from e

    payload = scan_output.payload
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if errors:
        raise StaticScannerError(f"semgrep reported errors: {_format_semgrep_errors(errors)}")

    results = payload.get("results", []) if isinstance(payload, dict) else []
    findings: list[StaticFinding] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        findings.append(_finding_from_semgrep_result(result, scan_output.scan_root))
    return findings


def _format_semgrep_errors(errors: Any) -> str:
    try:
        return json.dumps(errors, ensure_ascii=False)[:1000]
    except (TypeError, ValueError):
        return str(errors)[:1000]


def _run_semgrep(skill_dir: Path) -> _SemgrepScanOutput:
    if not skill_dir.is_dir():
        raise StaticScannerError(f"skill_dir is not a directory: {skill_dir}")
    if not RULES_DIR.is_dir():
        raise StaticScannerError(f"static rules directory not found: {RULES_DIR}")

    semgrep = _resolve_semgrep_executable()

    cmd = [
        str(semgrep),
        "scan",
        "--config",
        str(RULES_DIR),
        "--json",
        "--quiet",
        "--no-rewrite-rule-ids",
        "--metrics",
        "off",
        "--disable-version-check",
        "--no-git-ignore",
        "--max-target-bytes",
        "0",
        "--timeout",
        "5",
    ]
    with tempfile.TemporaryDirectory(prefix="deerflow-semgrep-") as tmp:
        temp_root = Path(tmp)
        scan_dir = temp_root / "scan"
        _copy_sanitized_skill_tree(skill_dir, scan_dir)
        cmd.append(str(scan_dir))
        env = _build_semgrep_env(temp_root, semgrep)
        proc = subprocess.run(
            cmd,
            cwd=temp_root,
            env=env,
            text=True,
            capture_output=True,
            timeout=_SEMGREP_TIMEOUT_SECONDS,
            check=False,
        )
        if proc.returncode != 0:
            message = (proc.stderr or proc.stdout or "").strip()
            raise StaticScannerError(f"semgrep exited with {proc.returncode}: {message[:1000]}")
        try:
            payload = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError as e:
            raise StaticScannerError(f"semgrep produced invalid JSON: {e}") from e
        if not isinstance(payload, dict):
            raise StaticScannerError("semgrep produced non-object JSON")
        return _SemgrepScanOutput(payload=payload, scan_root=scan_dir)


def _resolve_semgrep_executable() -> Path:
    active_bin_dir = Path(sys.executable).parent
    for name in _ACTIVE_ENV_SEMGREP_NAMES:
        candidate = active_bin_dir / name
        if candidate.is_file():
            return candidate

    semgrep = shutil.which("semgrep")
    if semgrep is None:
        raise StaticScannerError("semgrep executable not found")
    return Path(semgrep)


def _copy_sanitized_skill_tree(source_dir: Path, dest_dir: Path) -> None:
    def _ignore_untrusted_control_files(directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in _UNTRUSTED_SEMGREP_CONTROL_FILES}

    shutil.copytree(source_dir, dest_dir, ignore=_ignore_untrusted_control_files)


def _build_semgrep_env(temp_root: Path, semgrep_executable: Path) -> dict[str, str]:
    home_dir = temp_root / "home"
    config_dir = temp_root / "config"
    cache_dir = temp_root / "cache"
    log_dir = temp_root / "logs"
    settings_dir = config_dir / "semgrep"
    for directory in (home_dir, config_dir, cache_dir, log_dir, settings_dir):
        directory.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    semgrep_bin = str(Path(semgrep_executable).parent)
    existing_path = env.get("PATH", "")
    path_entries = [entry for entry in existing_path.split(os.pathsep) if entry and entry != semgrep_bin]
    env.update(
        {
            "HOME": str(home_dir),
            "PATH": os.pathsep.join([semgrep_bin, *path_entries]),
            "XDG_CACHE_HOME": str(cache_dir),
            "XDG_CONFIG_HOME": str(config_dir),
            "SEMGREP_ENABLE_VERSION_CHECK": "0",
            "SEMGREP_LOG_FILE": str(log_dir / "semgrep.log"),
            "SEMGREP_SEND_METRICS": "off",
            "SEMGREP_SETTINGS_FILE": str(settings_dir / "settings.yaml"),
            "SEMGREP_VERSION_CACHE_PATH": str(cache_dir / "semgrep_version"),
        }
    )

    try:
        import certifi
    except Exception:
        logger.warning("Unable to locate certifi CA bundle for Semgrep subprocess", exc_info=True)
    else:
        ca_bundle = certifi.where()
        env["REQUESTS_CA_BUNDLE"] = ca_bundle
        env["SSL_CERT_FILE"] = ca_bundle

    return env


def _finding_from_semgrep_result(result: dict[str, Any], scan_root: Path) -> StaticFinding:
    extra = result.get("extra") if isinstance(result.get("extra"), dict) else {}
    metadata = extra.get("metadata") if isinstance(extra.get("metadata"), dict) else {}
    line = result.get("start", {}).get("line") if isinstance(result.get("start"), dict) else 1
    try:
        line_number = int(line)
    except (TypeError, ValueError):
        line_number = 1

    return {
        "rule_id": str(result.get("check_id") or "unknown-rule"),
        "severity": _coerce_severity(extra, metadata),
        "file": _relative_file(str(result.get("path") or ""), scan_root),
        "line": max(line_number, 1),
        "message": str(extra.get("message") or "Static security rule matched."),
        "remediation": str(metadata.get("remediation") or "Review and remove the flagged content."),
    }


def _coerce_severity(extra: dict[str, Any], metadata: dict[str, Any]) -> StaticSeverity:
    deerflow_severity = str(metadata.get("deerflow_severity") or "").upper()
    if deerflow_severity in _VALID_SEVERITIES:
        return deerflow_severity  # type: ignore[return-value]
    semgrep_severity = str(extra.get("severity") or "").upper()
    return _SEMGREP_SEVERITY_MAP.get(semgrep_severity, "LOW")


def _relative_file(raw_path: str, scan_root: Path) -> str:
    if not raw_path:
        return "<unknown>"
    path = Path(raw_path)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(scan_root.resolve()).as_posix()
        except ValueError:
            return path.name
    return path.as_posix().removeprefix("./")
