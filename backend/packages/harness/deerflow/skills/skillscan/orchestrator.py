"""Native deterministic scanning for DeerFlow skills.

``scan_archive_preflight()`` and ``scan_skill_dir()`` are synchronous pure
functions of their inputs; async callers must dispatch them off the event
loop. Policy is one code constant — ``CRITICAL`` blocks, everything else is a
warning — applied by ``enforce_static_scan()``, which also honours the
``skill_scan.enabled`` kill switch. Rule specs live next to the analyzers
that match them so a rule is authored, read, and tested in one place.
"""

from __future__ import annotations

import ast
import builtins
import io
import logging
import posixpath
import re
import stat
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from deerflow.skills.package_paths import is_eval_fixture_skill_md
from deerflow.skills.skillscan.models import (
    FindingSeverity,
    RuleSpec,
    ScanResult,
    SecurityFinding,
    StaticScanBlockedError,
    StaticScannerError,
)

logger = logging.getLogger(__name__)

MAX_TOTAL_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_FILE_BYTES = 64 * 1024 * 1024

_BLOCK_SEVERITY = "CRITICAL"
_NESTED_ZIP_PEEK_MEMBER_LIMIT = 256
_MAX_ARCHIVE_MEMBERS = 4096

_SPECS = [
    RuleSpec("package-path-traversal", "CRITICAL", "Archive member path traverses outside the skill root.", "Remove parent-directory traversal from the package path."),
    RuleSpec("package-absolute-path", "CRITICAL", "Archive member path is absolute.", "Use relative paths inside the skill archive."),
    RuleSpec("package-symlink", "HIGH", "Package contains a symlink entry.", "Remove symlinks from the skill package."),
    RuleSpec("package-nested-skill-md", "CRITICAL", "Package contains a nested SKILL.md file.", "Keep exactly one SKILL.md at the skill root."),
    RuleSpec("package-oversized-total", "CRITICAL", "Package total uncompressed size exceeds the limit.", "Remove large files or split assets out of the skill package."),
    RuleSpec("package-too-many-members", "CRITICAL", "Package contains more members than the allowed limit.", "Reduce the number of files in the skill package."),
    RuleSpec("package-oversized-file", "CRITICAL", "Package contains a file that exceeds the per-file size limit.", "Remove or shrink the oversized file."),
    RuleSpec("package-executable-binary", "CRITICAL", "Package contains an executable binary.", "Remove binary executables from the skill package."),
    RuleSpec("package-nested-archive", "HIGH", "Package contains a nested archive file.", "Unpack and review nested archives before packaging the skill."),
    RuleSpec("package-hidden-sensitive-file", "HIGH", "Package contains a hidden sensitive file.", "Remove hidden credential or package-manager config files."),
    RuleSpec("package-git-directory", "MEDIUM", "Package contains a .git directory.", "Package only source files needed by the skill, excluding repository metadata."),
    RuleSpec("secret-private-key", "CRITICAL", "Private key material is embedded in skill content.", "Move private keys to a managed secret store and remove them from the skill."),
    RuleSpec("secret-cloud-token", "CRITICAL", "High-confidence cloud or API token is embedded in skill content.", "Move tokens to environment variables or a secret store."),
    RuleSpec("secret-env-assignment", "HIGH", "Secret-like assignment contains a non-placeholder value.", "Replace hardcoded credentials with documented runtime configuration."),
    RuleSpec("declaration-prompt-override", "HIGH", "SKILL.md contains a prompt override phrase.", "Rephrase examples so they describe unsafe text instead of instructing the agent to follow it."),
    RuleSpec("declaration-sensitive-capability", "HIGH", "SKILL.md declares a sensitive capability.", "Make the capability explicit, narrow, and justified, or remove it."),
    RuleSpec("declaration-sensitive-path", "HIGH", "SKILL.md references sensitive host or credential paths.", "Remove references to sensitive host paths unless they are harmless documentation."),
    RuleSpec("declaration-external-endpoint", "MEDIUM", "SKILL.md declares an external network endpoint.", "Document why the endpoint is needed and prefer HTTPS."),
    RuleSpec("python-dynamic-exec", "CRITICAL", "Python dynamic code execution primitive is used in a skill file.", "Remove dynamic execution and replace it with explicit typed logic."),
    RuleSpec("python-shell-exec", "CRITICAL", "Python shell execution primitive is used in a skill file.", "Use subprocess with a fixed argument list and shell=False, or remove shell execution."),
    RuleSpec("python-sensitive-exfil", "CRITICAL", "Python code reads a sensitive path and uses an outbound network sink in the same file.", "Remove the sensitive read or network sink, and keep credential access outside skills."),
    RuleSpec("python-env-dump-exfil", "CRITICAL", "Python code reads the process environment in bulk and uses an outbound network sink in the same file.", "Avoid bulk environment reads and never send environment data over the network."),
    RuleSpec("python-reverse-shell", "CRITICAL", "Python code matches a reverse-shell shape.", "Remove reverse-shell behavior from the skill."),
    RuleSpec("python-dynamic-import", "HIGH", "Python dynamically imports a non-literal module.", "Use explicit imports or a constrained allowlist."),
    RuleSpec("python-subprocess", "HIGH", "Python invokes subprocess without shell=True.", "Review subprocess usage and keep arguments fixed and minimal."),
    RuleSpec("python-sensitive-path-read", "HIGH", "Python reads a sensitive path.", "Remove sensitive host-path access from the skill."),
    RuleSpec("python-unsafe-deserialization", "MEDIUM", "Python uses unsafe deserialization.", "Use safe loaders or trusted typed formats."),
    RuleSpec("shell-reverse-shell", "CRITICAL", "Shell script contains a reverse-shell idiom.", "Remove reverse-shell behavior from the skill."),
    RuleSpec("shell-reverse-shell-heuristic", "HIGH", "Shell script resembles a reverse-shell idiom.", "Confirm this is not reverse-shell behavior; unmistakable reverse-shell signals are blocked outright."),
    RuleSpec("shell-sensitive-exfil", "CRITICAL", "Shell script reads sensitive paths and sends data over the network.", "Remove sensitive reads or outbound transfer commands."),
    RuleSpec("shell-curl-pipe-shell", "HIGH", "Shell script pipes remote content into a shell.", "Download, verify, and execute reviewed code explicitly instead."),
    RuleSpec("shell-destructive-command", "HIGH", "Shell script contains an unmistakably destructive command.", "Remove destructive commands from skill scripts."),
    RuleSpec("shell-env-dump", "MEDIUM", "Shell script dumps the environment.", "Avoid bulk environment dumps in skills."),
    RuleSpec("network-cloud-metadata", "CRITICAL", "Skill content references a cloud metadata service.", "Remove cloud metadata access from the skill."),
    RuleSpec("resource-fork-bomb", "CRITICAL", "Skill content contains a fork-bomb pattern.", "Remove resource-exhaustion payloads."),
    RuleSpec("network-cleartext-http", "MEDIUM", "Skill content references a non-local cleartext HTTP endpoint.", "Use HTTPS or document why cleartext local development is required."),
    RuleSpec("network-local-http", "LOW", "Skill content references a local HTTP endpoint.", "Confirm the local endpoint is expected for this skill."),
]

RULES: dict[str, RuleSpec] = {spec.rule_id: spec for spec in _SPECS}

_ARCHIVE_SUFFIXES = (
    ".zip",
    ".tar",
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".tbz2",
    ".tar.xz",
    ".txz",
    ".7z",
    ".rar",
    ".whl",
)
_HIDDEN_SENSITIVE_FILES = {
    ".env",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "credentials",
    "config",
}
_PLACEHOLDER_VALUES = {"", "x", "xx", "xxx", "xxxx", "changeme", "change-me", "example", "placeholder", "test", "dummy", "your-key", "<your-key>"}
_SENSITIVE_PATH_RE = re.compile(r"(~/.ssh|/etc/passwd|/etc/shadow|/var/run/docker\.sock|docker\.sock|169\.254\.169\.254)")
_EXTERNAL_HTTP_RE = re.compile(r"http://([A-Za-z0-9.-]+)(?::\d+)?(?:/|\b)")
_URL_RE = re.compile(r"https?://[^\s)'\"<>]+")
_LOCAL_HTTP_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
# `rm` with a recursive flag (any order/combination, optional --no-preserve-root)
# targeting the filesystem root, a wildcard, or a complete system-root directory.
# Subpaths like ``/tmp/scratch`` or ``/home/user/project`` stay unflagged.
_DESTRUCTIVE_RM_RE = (
    r"\brm\s+(?:-\S+\s+|--no-preserve-root\s+)*-\S*[rR]\S*\s+"
    r"(?:-\S+\s+|--no-preserve-root\s+)*"
    r"/(?:\*|\s|$|(?:bin|boot|dev|etc|home|lib|lib64|opt|proc|root|run|sbin|srv|sys|usr|var)(?:/\*?)?(?:\s|$))"
)


def skill_scan_enabled(app_config: Any | None = None) -> bool:
    if app_config is None:
        try:
            from deerflow.config import get_app_config

            app_config = get_app_config()
        except Exception:
            app_config = None
    skill_scan_config = getattr(app_config, "skill_scan", None)
    if skill_scan_config is not None and hasattr(skill_scan_config, "enabled"):
        return bool(skill_scan_config.enabled)
    return True


def format_static_findings(findings: list[SecurityFinding]) -> str:
    parts = []
    for finding in findings:
        location = finding["file"] or "<archive>"
        if finding["line"] is not None:
            location = f"{location}:{finding['line']}"
        parts.append(f"{finding['rule_id']} ({finding['severity']}) at {location}: {finding['message']} Remediation: {finding['remediation']}")
    return "; ".join(parts)


def enforce_static_scan(
    skill_dir: Path,
    *,
    skill_name: str | None = None,
    app_config: Any | None = None,
) -> list[SecurityFinding]:
    if not skill_scan_enabled(app_config):
        return []

    result = scan_skill_dir(Path(skill_dir))
    blocked = [finding for finding in result["findings"] if finding["severity"] == _BLOCK_SEVERITY]
    if blocked:
        raise StaticScanBlockedError(
            blocked,
            skill_name=skill_name,
            message=f"Static security scan blocked skill '{skill_name}': {format_static_findings(blocked)}" if skill_name else f"Static security scan blocked skill content: {format_static_findings(blocked)}",
        )
    if result["scanner_errors"]:
        logger.warning("SkillScan analyzer errors for %s: %s", skill_name or skill_dir, "; ".join(result["scanner_errors"]))
    warnings = [finding for finding in result["findings"] if finding["severity"] != _BLOCK_SEVERITY]
    if warnings:
        logger.warning("SkillScan warning findings for %s: %s", skill_name or skill_dir, format_static_findings(warnings))
    return [dict(finding) for finding in result["findings"]]  # type: ignore[misc]


def scan_archive_preflight(archive_path: Path) -> ScanResult:
    findings: list[SecurityFinding] = []
    scanner_errors: list[str] = []
    total_size = 0
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            members = zf.infolist()
            if len(members) > _MAX_ARCHIVE_MEMBERS:
                # Early-abort before the per-member reads below: a huge member
                # count is a bounded DoS vector even when the total size is small.
                finding = _finding("package-too-many-members", file=None, evidence=f"{len(members)} members")
                return _scan_result([finding], scanner_errors)
            for info in members:
                normalized = _normalize_archive_name(info.filename)
                findings.extend(_scan_archive_member_metadata(info, normalized))
                if info.is_dir():
                    continue
                total_size += max(info.file_size, 0)
                if info.file_size > MAX_FILE_BYTES:
                    findings.append(_finding("package-oversized-file", file=normalized, evidence=f"{info.file_size} bytes"))
                if _is_hidden_sensitive_path(normalized):
                    findings.append(_finding("package-hidden-sensitive-file", file=normalized, evidence=Path(normalized).name))
                if ".git" in PurePosixPath(normalized).parts:
                    findings.append(_finding("package-git-directory", file=normalized, evidence=".git"))
                if _is_symlink_member(info):
                    continue
                try:
                    with zf.open(info) as member:
                        prefix = member.read(8)
                except Exception as e:
                    scanner_errors.append(f"{normalized}: failed to read archive member prefix: {e}")
                    continue
                if _is_executable_binary(prefix):
                    findings.append(_finding("package-executable-binary", file=normalized, evidence=_binary_magic_evidence(prefix)))
                if _is_nested_archive_name(normalized) or _looks_like_archive(prefix):
                    findings.append(_nested_archive_finding(normalized, prefix, lambda: _read_archive_member(zf, info), scanner_errors))
            if total_size > MAX_TOTAL_ARCHIVE_BYTES:
                findings.append(_finding("package-oversized-total", file=None, evidence=f"{total_size} bytes"))
    except (zipfile.BadZipFile, OSError) as e:
        raise StaticScannerError(f"failed to read skill archive: {e}") from e

    return _scan_result(_dedupe(findings), scanner_errors)


def scan_skill_dir(skill_dir: Path) -> ScanResult:
    root = Path(skill_dir)
    if not root.is_dir():
        raise StaticScannerError(f"skill_dir is not a directory: {root}")

    findings: list[SecurityFinding] = []
    scanner_errors: list[str] = []
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        rel_path = _relative_file(path, root)
        try:
            file_bytes = path.read_bytes()
        except OSError as e:
            scanner_errors.append(f"{rel_path}: failed to read file: {e}")
            continue

        findings.extend(_scan_file_package_properties(rel_path, file_bytes, path.stat().st_size))
        text = _decode_text_for_analysis(file_bytes)
        if text is None:
            continue

        try:
            findings.extend(_scan_text_file(rel_path, text))
        except Exception as e:
            scanner_errors.append(f"{rel_path}: analyzer failed: {e}")
            logger.warning("SkillScan analyzer failed for %s", rel_path, exc_info=True)

    return _scan_result(_dedupe(findings), scanner_errors)


def _scan_archive_member_metadata(info: zipfile.ZipInfo, normalized: str) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    if _archive_member_is_absolute(info.filename):
        findings.append(_finding("package-absolute-path", file=normalized, evidence=info.filename))
    elif _archive_member_traverses(info.filename):
        findings.append(_finding("package-path-traversal", file=normalized, evidence=info.filename))
    if _is_symlink_member(info):
        findings.append(_finding("package-symlink", file=normalized, evidence=info.filename))
    parts = PurePosixPath(normalized).parts
    if parts and parts[-1] == "SKILL.md" and len(parts) > 2 and not is_eval_fixture_skill_md(PurePosixPath(normalized)):
        findings.append(_finding("package-nested-skill-md", file=normalized, evidence=normalized))
    return findings


def _scan_file_package_properties(rel_path: str, file_bytes: bytes, file_size: int) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    path = PurePosixPath(rel_path)
    if path.name == "SKILL.md" and len(path.parts) > 1 and not is_eval_fixture_skill_md(path):
        findings.append(_finding("package-nested-skill-md", file=rel_path, evidence=rel_path))
    if file_size > MAX_FILE_BYTES:
        findings.append(_finding("package-oversized-file", file=rel_path, evidence=f"{file_size} bytes"))
    if _is_hidden_sensitive_path(rel_path):
        findings.append(_finding("package-hidden-sensitive-file", file=rel_path, evidence=path.name))
    if ".git" in path.parts:
        findings.append(_finding("package-git-directory", file=rel_path, evidence=".git"))
    if _is_nested_archive_name(rel_path) or _looks_like_archive(file_bytes):
        findings.append(_nested_archive_finding(rel_path, file_bytes[:8], lambda: file_bytes, []))
    if _is_executable_binary(file_bytes[:8]):
        findings.append(_finding("package-executable-binary", file=rel_path, evidence=_binary_magic_evidence(file_bytes[:8])))
    return findings


def _scan_text_file(rel_path: str, text: str) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    findings.extend(_scan_secrets(rel_path, text))
    if PurePosixPath(rel_path).name == "SKILL.md":
        findings.extend(_scan_declaration(rel_path, text))
    if _is_python_path(rel_path, text):
        findings.extend(_scan_python(rel_path, text))
    if _is_shell_path(rel_path, text):
        findings.extend(_scan_shell(rel_path, text))
    findings.extend(_scan_network_and_resource(rel_path, text))
    return findings


def _scan_secrets(rel_path: str, text: str) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    private_key = re.search(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", text)
    if private_key:
        findings.append(_finding_from_match("secret-private-key", rel_path, text, private_key))

    token_patterns = [
        r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
        r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b",
        r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b",
        r"\bsk-[A-Za-z0-9]{20,}\b",
    ]
    for pattern in token_patterns:
        match = re.search(pattern, text)
        if match and not _looks_like_placeholder(match.group(0)):
            findings.append(_finding_from_match("secret-cloud-token", rel_path, text, match))
            break

    assignment_re = re.compile(r"(?im)\b(token|password|passwd|api[_-]?key|secret|credential)s?\b\s*[:=]\s*[\"']?([^\"'\s#]+)")
    for match in assignment_re.finditer(text):
        value = match.group(2).strip()
        if not _looks_like_placeholder(value):
            findings.append(_finding_from_match("secret-env-assignment", rel_path, text, match))
            break
    return findings


def _scan_declaration(rel_path: str, text: str) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    prompt_re = re.compile(r"(?i)\b(ignore|disregard)\s+(all\s+)?(previous|prior)\s+instructions\b|\boverride\s+(the\s+)?(system|developer)\s+instructions\b")
    if match := prompt_re.search(text):
        findings.append(_finding_from_match("declaration-prompt-override", rel_path, text, match))

    capability_re = re.compile(r"(?i)(execute\s+(arbitrary\s+)?commands?|shell\s+commands?|credential\s+access|read\s+secrets?|arbitrary\s+network|network\s+egress)")
    if match := capability_re.search(text):
        findings.append(_finding_from_match("declaration-sensitive-capability", rel_path, text, match))

    if match := _SENSITIVE_PATH_RE.search(text):
        findings.append(_finding_from_match("declaration-sensitive-path", rel_path, text, match))

    for match in _URL_RE.finditer(text):
        if match.group(0).startswith("http://"):
            host = _http_host(match.group(0))
            if host and host not in _LOCAL_HTTP_HOSTS:
                findings.append(_finding_from_match("declaration-external-endpoint", rel_path, text, match))
                break
    return findings


def _scan_python(rel_path: str, text: str) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return findings

    aliases = _collect_python_aliases(tree)
    has_sensitive_read = False
    has_env_dump = False
    has_network_sink = False
    sensitive_node: ast.AST | None = None
    env_node: ast.AST | None = None
    network_node: ast.AST | None = None
    reverse_shell_parts: set[str] = set()
    reverse_shell_node: ast.AST | None = None

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _SENSITIVE_PATH_RE.search(node.value):
                has_sensitive_read = True
                sensitive_node = sensitive_node or node
            if _is_outbound_url(node.value):
                has_network_sink = True
                network_node = network_node or node

        if isinstance(node, (ast.Attribute, ast.Name)) and _python_name(node, aliases) == "os.environ":
            has_env_dump = True
            env_node = env_node or node

        if not isinstance(node, ast.Call):
            continue

        call_name = _python_call_name(node, aliases)
        if call_name in {"eval", "exec"} or (call_name == "compile" and _compile_mode_is_exec(node)):
            findings.append(_finding_for_node("python-dynamic-exec", rel_path, node, call_name))
        elif call_name in {"os.system", "os.popen"} or (call_name.startswith("subprocess.") and _call_has_shell_true(node)):
            findings.append(_finding_for_node("python-shell-exec", rel_path, node, call_name))
        elif call_name.startswith("subprocess."):
            findings.append(_finding_for_node("python-subprocess", rel_path, node, call_name))
        elif call_name == "__import__" or call_name == "importlib.import_module":
            if not node.args or not isinstance(node.args[0], ast.Constant):
                findings.append(_finding_for_node("python-dynamic-import", rel_path, node, call_name))
        elif call_name in {"pickle.load", "pickle.loads"} or (call_name == "yaml.load" and not _yaml_load_uses_safe_loader(node)):
            findings.append(_finding_for_node("python-unsafe-deserialization", rel_path, node, call_name))

        if _call_is_network_sink(call_name):
            has_network_sink = True
            network_node = network_node or node

        if call_name == "os.dup2":
            reverse_shell_parts.add("dup2")
            reverse_shell_node = reverse_shell_node or node
        elif call_name in {"socket.socket", "socket.create_connection"}:
            reverse_shell_parts.add("socket")
        elif call_name.startswith("subprocess.") or call_name in {"os.system", "os.popen"}:
            reverse_shell_parts.add("subprocess")

    if not has_network_sink:
        if handle_sink := _find_client_handle_sink(tree):
            has_network_sink = True
            network_node = network_node or handle_sink

    if {"dup2", "socket", "subprocess"} <= reverse_shell_parts:
        findings.append(_finding_for_node("python-reverse-shell", rel_path, reverse_shell_node, "socket + dup2 + subprocess"))

    if has_sensitive_read and has_network_sink:
        findings.append(_finding_for_node("python-sensitive-exfil", rel_path, sensitive_node or network_node, "sensitive read + network sink"))
    elif has_sensitive_read:
        findings.append(_finding_for_node("python-sensitive-path-read", rel_path, sensitive_node, "sensitive path read"))
    if has_env_dump and has_network_sink:
        findings.append(_finding_for_node("python-env-dump-exfil", rel_path, env_node or network_node, "environment dump + network sink"))
    return findings


def _scan_shell(rel_path: str, text: str) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    # Unmistakable reverse-shell signals hard-block; weaker idioms (bash -i,
    # mkfifo) only warn->LLM because they appear in legitimate scripts.
    if match := re.search(r"(/dev/tcp/|nc\s+-e\b)", text):
        findings.append(_finding_from_match("shell-reverse-shell", rel_path, text, match))
    if match := re.search(r"(bash\s+-i\b|mkfifo\s+)", text):
        findings.append(_finding_from_match("shell-reverse-shell-heuristic", rel_path, text, match))
    if re.search(r"(/etc/shadow|/etc/passwd)", text) and re.search(r"\b(curl|wget|nc|scp)\b", text):
        findings.append(_finding_for_text("shell-sensitive-exfil", rel_path, text, "/etc"))
    if match := re.search(r"\b(curl|wget)\b[^\n|;]*\|\s*(?:sh|bash)\b", text):
        findings.append(_finding_from_match("shell-curl-pipe-shell", rel_path, text, match))
    if match := re.search(_DESTRUCTIVE_RM_RE + r"|:\(\)\{\s*:\|:&\s*\};:|dd\s+[^#\n]*\bof=/dev/", text):
        findings.append(_finding_from_match("shell-destructive-command", rel_path, text, match))
    if match := re.search(r"\b(env|printenv|export\s+-p)\b", text):
        findings.append(_finding_from_match("shell-env-dump", rel_path, text, match))
    return findings


def _scan_network_and_resource(rel_path: str, text: str) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    if match := re.search(r"(169\.254\.169\.254|metadata\.google\.internal)", text):
        findings.append(_finding_from_match("network-cloud-metadata", rel_path, text, match))
    if match := re.search(r":\(\)\{\s*:\|:&\s*\};:", text):
        findings.append(_finding_from_match("resource-fork-bomb", rel_path, text, match))
    for match in _EXTERNAL_HTTP_RE.finditer(text):
        host = match.group(1)
        if host in _LOCAL_HTTP_HOSTS or host.startswith("10.") or host.startswith("192.168.") or re.match(r"172\.(1[6-9]|2\d|3[01])\.", host):
            findings.append(_finding_from_match("network-local-http", rel_path, text, match))
        else:
            findings.append(_finding_from_match("network-cleartext-http", rel_path, text, match))
        break
    return findings


def _finding(rule_id: str, *, file: str | None, evidence: str | None, line: int | None = None, severity: FindingSeverity | None = None) -> SecurityFinding:
    spec = RULES[rule_id]
    if evidence is not None and rule_id.startswith("secret-"):
        evidence = _redact_secret_evidence(evidence)
    return {
        "rule_id": rule_id,
        "severity": severity or spec.severity,
        "file": file,
        "line": line,
        "message": spec.message,
        "remediation": spec.remediation,
        "evidence": evidence,
    }


def _finding_from_match(rule_id: str, rel_path: str, text: str, match: re.Match[str]) -> SecurityFinding:
    return _finding(rule_id, file=rel_path, line=_line_number(text, match.start()), evidence=match.group(0))


def _finding_for_text(rule_id: str, rel_path: str, text: str, evidence: str) -> SecurityFinding:
    index = text.find(evidence)
    return _finding(rule_id, file=rel_path, line=_line_number(text, index if index >= 0 else 0), evidence=evidence)


def _finding_for_node(rule_id: str, rel_path: str, node: ast.AST | None, evidence: str) -> SecurityFinding:
    return _finding(rule_id, file=rel_path, line=getattr(node, "lineno", 1), evidence=evidence)


def _nested_archive_finding(rel_path: str, prefix: bytes, read_data, scanner_errors: list[str]) -> SecurityFinding:
    name = PurePosixPath(rel_path).name
    if prefix.startswith(b"PK\x03\x04"):
        try:
            data = read_data()
        except Exception as e:
            scanner_errors.append(f"{rel_path}: failed to read nested archive for inspection: {e}")
        else:
            if data is not None and _nested_zip_contains_executable(data):
                return _finding("package-nested-archive", file=rel_path, evidence=f"{name}: contains an executable binary member", severity="CRITICAL")
    return _finding("package-nested-archive", file=rel_path, evidence=name)


def _nested_zip_contains_executable(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as nested:
            for info in nested.infolist()[:_NESTED_ZIP_PEEK_MEMBER_LIMIT]:
                if info.is_dir():
                    continue
                try:
                    with nested.open(info) as member:
                        if _is_executable_binary(member.read(8)):
                            return True
                except Exception:
                    continue
    except (zipfile.BadZipFile, OSError):
        return False
    return False


def _read_archive_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes | None:
    if info.file_size > MAX_FILE_BYTES:
        return None
    with zf.open(info) as member:
        return member.read(MAX_FILE_BYTES + 1)


def _redact_secret_evidence(value: str) -> str:
    # Drop the value entirely: the rule_id already names the secret category, and
    # any retained prefix (e.g. value[:6]) leaks real token bytes into findings
    # that flow to Gateway responses and LLM context.
    return "[redacted]"


def _scan_result(findings: list[SecurityFinding], scanner_errors: list[str]) -> ScanResult:
    blocked = any(finding["severity"] == _BLOCK_SEVERITY for finding in findings)
    return {"findings": findings, "blocked": blocked, "scanner_errors": scanner_errors}


def _dedupe(findings: Iterable[SecurityFinding]) -> list[SecurityFinding]:
    seen: set[tuple[str, str | None, int | None]] = set()
    deduped: list[SecurityFinding] = []
    for finding in findings:
        key = (finding["rule_id"], finding["file"], finding["line"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)
    return deduped


def _line_number(text: str, index: int) -> int:
    return text[: max(index, 0)].count("\n") + 1


def _normalize_archive_name(name: str) -> str:
    return posixpath.normpath(name.replace("\\", "/")).removeprefix("./")


def _archive_member_is_absolute(name: str) -> bool:
    normalized = name.replace("\\", "/")
    return normalized.startswith("/") or PurePosixPath(normalized).is_absolute() or PureWindowsPath(name).is_absolute()


def _archive_member_traverses(name: str) -> bool:
    return ".." in PurePosixPath(name.replace("\\", "/")).parts


def _is_symlink_member(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(info.external_attr >> 16)


def _relative_file(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _is_hidden_sensitive_path(rel_path: str) -> bool:
    parts = PurePosixPath(rel_path).parts
    if ".aws" in parts and parts[-1] == "credentials":
        return True
    if ".git" in parts and parts[-1] == "config":
        return True
    return parts[-1] in _HIDDEN_SENSITIVE_FILES and (parts[-1].startswith(".") or any(token in parts[-1].lower() for token in ("credential", "npmrc", "pypirc", "netrc")))


def _is_nested_archive_name(rel_path: str) -> bool:
    lower = rel_path.lower()
    return any(lower.endswith(suffix) for suffix in _ARCHIVE_SUFFIXES)


def _looks_like_archive(file_bytes: bytes) -> bool:
    return file_bytes.startswith(b"PK\x03\x04") or file_bytes.startswith(b"\x1f\x8b") or file_bytes.startswith(b"7z\xbc\xaf\x27\x1c")


def _is_executable_binary(prefix: bytes) -> bool:
    return prefix.startswith(b"\x7fELF") or prefix.startswith(b"MZ") or prefix.startswith((b"\xfe\xed\xfa", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"))


def _binary_magic_evidence(prefix: bytes) -> str:
    if prefix.startswith(b"\x7fELF"):
        return "ELF"
    if prefix.startswith(b"MZ"):
        return "PE"
    return "Mach-O"


def _decode_text_for_analysis(file_bytes: bytes) -> str | None:
    # Binaries are rejected by the NUL probe and the decode failure below, so
    # every NUL-free, UTF-8-decodable file is analyzed regardless of extension.
    if b"\x00" in file_bytes[:4096]:
        return None
    try:
        return file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _is_python_path(rel_path: str, text: str) -> bool:
    return PurePosixPath(rel_path).suffix.lower() == ".py" or text.startswith("#!") and "python" in text.splitlines()[0].lower()


def _is_shell_path(rel_path: str, text: str) -> bool:
    suffix = PurePosixPath(rel_path).suffix.lower()
    return suffix in {".sh", ".bash"} or text.startswith("#!") and any(shell in text.splitlines()[0].lower() for shell in ("sh", "bash", "zsh"))


def _looks_like_placeholder(value: str) -> bool:
    normalized = value.strip().strip("\"'").lower()
    if normalized in _PLACEHOLDER_VALUES:
        return True
    return normalized.startswith("<") or normalized.startswith("${") or "your" in normalized or "example" in normalized


def _http_host(url: str) -> str | None:
    match = re.match(r"https?://\[?([^]/:]+)", url)
    return match.group(1) if match else None


def _is_outbound_url(value: str) -> bool:
    return bool(value.startswith(("http://", "https://")) and (_http_host(value) or "") not in _LOCAL_HTTP_HOSTS)


def _collect_python_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def _python_name(node: ast.AST, aliases: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        base = _python_name(node.value, aliases)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _python_call_name(node: ast.Call, aliases: dict[str, str]) -> str:
    return _python_name(node.func, aliases)


def _compile_mode_is_exec(node: ast.Call) -> bool:
    if len(node.args) >= 3 and isinstance(node.args[2], ast.Constant):
        return node.args[2].value == "exec"
    return any(keyword.arg == "mode" and isinstance(keyword.value, ast.Constant) and keyword.value.value == "exec" for keyword in node.keywords)


def _call_has_shell_true(node: ast.Call) -> bool:
    return any(keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True for keyword in node.keywords)


def _call_is_network_sink(call_name: str) -> bool:
    return call_name in {
        "requests.get",
        "requests.post",
        "requests.put",
        "requests.patch",
        "requests.delete",
        "requests.head",
        "requests.options",
        "requests.request",
        "httpx.get",
        "httpx.post",
        "httpx.put",
        "httpx.patch",
        "httpx.delete",
        "httpx.head",
        "httpx.options",
        "httpx.request",
        "httpx.stream",
        "urllib.request.urlopen",
        "urllib.request.urlretrieve",
        "socket.socket",
        "socket.create_connection",
    }


# Instance clients split construction from egress: the constructor does no I/O and the
# outbound call is an attribute call on a variable, so neither statement alone is a
# call-name sink. Flagging the constructor would block benign construct-only code, so a
# handle only counts once it is actually used. The binding map is deliberately one level
# and scope-local -- `.get(`/`.post(` collide with dict.get and friends, so a name is a
# sink receiver only where it was bound to a known constructor. Anything broader is the
# taint engine RFC #2634 rules out of Phase 5.
#
# Which scope sees which handle follows Python's own name resolution, not "every live
# binding": a class namespace is not a closure scope for its methods, a function-local
# binding shadows an enclosing name across the whole body, and comprehensions bind their
# targets in a scope of their own. Approximating that with a flat copy reports benign
# code that provably cannot reach the tracked client. Where a handle's identity is not
# decidable one level deep (a comprehension target, a rebind from a call we do not model)
# the name simply stops being a sink receiver -- under-reporting is the safe direction
# for a blocking rule.
_PYTHON_CLIENT_CONSTRUCTORS = {
    "http.client.HTTPConnection",
    "http.client.HTTPSConnection",
    "aiohttp.ClientSession",
    "requests.Session",
    "urllib3.PoolManager",
}
_PYTHON_CLIENT_SINK_METHODS = {"request", "connect", "get", "post", "put", "patch", "delete", "head", "options", "urlopen", "getresponse"}
_PYTHON_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
_PYTHON_COMPREHENSION_NODES = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_PYTHON_MATCH_CAPTURE_NODES = (ast.MatchAs, ast.MatchStar, ast.MatchMapping)


@dataclass
class _ClientScope:
    handles: dict[str, str]
    aliases: dict[str, str]
    shadowed: set[str] = field(default_factory=set)

    def copy_without(self, names: set[str] | None = None) -> _ClientScope:
        names = names or set()
        return _ClientScope(
            handles={name: constructor for name, constructor in self.handles.items() if name not in names},
            aliases={name: target for name, target in self.aliases.items() if name not in names},
            shadowed=self.shadowed | names,
        )

    @staticmethod
    def join(branches: list[_ClientScope], path_local: dict[str, str] | None = None) -> _ClientScope:
        """The may-state after a set of alternative branches: what could hold a client on *any* of them.

        Alternatives are not applied one after another -- only one of them runs. Folding them into a
        single destructive map lets whichever branch happens to be visited last erase what another
        branch still holds, which misses a client Python really calls (a branch that rebinds the name
        hides one that does not) and invents one that it never calls. Joining instead keeps a name a
        sink receiver when any feasible branch leaves it a client, and drops it only when every
        feasible branch replaced it.

        Alias targets join the same way, except that a disagreement resolves toward the target that
        can still name a constructor: a name that resolves to a client module on one path resolves to
        one after the join, so replacing an alias on a path that may not run cannot hide the sink.

        ``path_local`` carries bindings Python unbinds only on the branch that ran -- an
        `except ... as` target -- which every other path leaves untouched, so they are restored here.
        """
        joined = _ClientScope(handles={}, aliases={})
        for branch in branches:
            joined.shadowed.update(branch.shadowed)
            for name, constructor in branch.handles.items():
                joined.handles.setdefault(name, constructor)
            for name, target in branch.aliases.items():
                current = joined.aliases.get(name)
                if current is None or (not _alias_names_a_constructor(current) and _alias_names_a_constructor(target)):
                    joined.aliases[name] = target
        for name, constructor in (path_local or {}).items():
            joined.handles.setdefault(name, constructor)
        return joined

    def replace_with(self, other: _ClientScope) -> None:
        self.handles.clear()
        self.handles.update(other.handles)
        self.aliases.clear()
        self.aliases.update(other.aliases)
        self.shadowed.clear()
        self.shadowed.update(other.shadowed)


@dataclass(frozen=True)
class _ClientExit:
    kind: str = "fallthrough"
    exception: type[BaseException] | None = None
    exception_known: bool = False
    group: tuple[type[BaseException], ...] | None = None


_CLIENT_FALLTHROUGH = _ClientExit()


def _alias_names_a_constructor(target: str) -> bool:
    return any(constructor == target or constructor.startswith(f"{target}.") for constructor in _PYTHON_CLIENT_CONSTRUCTORS)


def _literal_exception_class(node: ast.AST | None, scope: _ClientScope) -> type[BaseException] | None:
    """Resolve an unshadowed builtin exception class; ordinary bound names stay unknown."""
    if not isinstance(node, ast.Name) or node.id in scope.shadowed:
        return None
    candidate = getattr(builtins, node.id, None)
    return candidate if isinstance(candidate, type) and issubclass(candidate, BaseException) else None


def _selected_handler_index(handlers: list[ast.ExceptHandler], raised: type[BaseException], scope: _ClientScope) -> tuple[bool, int | None]:
    """Return ``(decidable, index)``; a decidable ``None`` means no handler matches."""
    for index, handler in enumerate(handlers):
        if handler.type is None:
            return True, index
        caught = _literal_exception_class(handler.type, scope)
        if caught is None:
            return False, None
        if issubclass(raised, caught):
            return True, index
    return True, None


def _raised_group_classes(node: ast.AST | None, scope: _ClientScope) -> tuple[type[BaseException], ...] | None:
    """The classes in a literal unshadowed ``ExceptionGroup`` construction, when decidable."""
    if not isinstance(node, ast.Call):
        return None
    if not isinstance(node.func, ast.Name) or node.func.id in scope.shadowed or node.func.id not in {"ExceptionGroup", "BaseExceptionGroup"} or len(node.args) != 2 or not isinstance(node.args[1], (ast.List, ast.Tuple)):
        return None
    classes = []
    for element in node.args[1].elts:
        found = _literal_exception_class(element.func if isinstance(element, ast.Call) else element, scope)
        if found is None:
            return None
        classes.append(found)
    return tuple(classes)


def _match_case_decision(subject: ast.AST, case: ast.match_case, scope: _ClientScope) -> bool | None:
    """Whether a pattern provably matches or misses; ``None`` keeps both paths feasible.

    Only source-fixed forms are decided: a wildcard, unshadowed ``object()``, and a literal subject
    against a literal value. Guards are evaluated separately after a successful pattern.
    """
    pattern = case.pattern
    while isinstance(pattern, ast.MatchAs) and pattern.pattern is not None:
        pattern = pattern.pattern
    if isinstance(pattern, ast.MatchAs):  # `case _:` / `case name:`
        return True
    if isinstance(pattern, ast.MatchClass) and isinstance(pattern.cls, ast.Name) and pattern.cls.id == "object" and "object" not in scope.shadowed and not pattern.patterns and not pattern.kwd_patterns:
        return True
    if isinstance(pattern, ast.MatchValue) and isinstance(pattern.value, ast.Constant) and isinstance(subject, ast.Constant):
        return type(subject.value) is type(pattern.value.value) and subject.value == pattern.value.value
    return None


def _find_client_handle_sink(tree: ast.AST) -> ast.AST | None:
    found: list[ast.AST] = []
    module = _ClientScope(handles={}, aliases={})
    _walk_client_scope(tree, module, module, module, found, _evaluated_annotation_nodes(tree))
    return found[0] if found else None


def _evaluated_annotation_nodes(tree: ast.AST) -> frozenset[int]:
    """`id()`s of the nodes whose annotation Python actually evaluates at runtime.

    Two kinds land here. (1) An annotated assignment: only module- and class-body annotations are
    evaluated (a class body runs eagerly, even when nested in a function); a function-local variable
    annotation is never evaluated. (2) A function/async-function def: its parameter and return
    annotations are evaluated at def time in the enclosing scope, regardless of nesting. Either way,
    `from __future__ import annotations` postpones every annotation in the module to an unevaluated
    string. Annotations the runtime never evaluates must not be scanned, or benign code is hard-blocked.
    """
    if any(isinstance(node, ast.ImportFrom) and node.module == "__future__" and any(alias.name == "annotations" for alias in node.names) for node in getattr(tree, "body", [])):
        return frozenset()
    evaluated: set[int] = set()

    def visit(node: ast.AST, in_function: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.AnnAssign) and not in_function:
                evaluated.add(id(child))
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                evaluated.add(id(child))  # signature annotations evaluate at def time in the enclosing scope
                visit(child, True)
            elif isinstance(child, ast.Lambda):
                visit(child, True)  # a lambda has no annotations
            elif isinstance(child, ast.ClassDef):
                visit(child, False)  # a class body evaluates its annotations even inside a function
            else:
                visit(child, in_function)

    visit(tree, False)
    return frozenset(evaluated)


def _literal_truth(node: ast.AST) -> bool | None:
    """Truthiness only where evaluating the syntax cannot invoke user code."""
    if isinstance(node, ast.Constant):
        return bool(node.value)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return bool(node.elts)
    if isinstance(node, ast.Dict):
        return bool(node.keys)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        value = _literal_truth(node.operand)
        return None if value is None else not value
    if isinstance(node, ast.NamedExpr):
        return _literal_truth(node.value)
    return None


def _literal_iterable_length(node: ast.AST) -> int | None:
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return len(node.elts)
    if isinstance(node, ast.Dict):
        return len(node.keys)
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes, tuple, frozenset)):
        return len(node.value)
    return None


def _merge_client_exits(exits: list[_ClientExit]) -> _ClientExit:
    if not exits:
        return _ClientExit(kind="terminal")
    first = exits[0]
    return first if all(exit_state == first for exit_state in exits[1:]) else _ClientExit(kind="terminal")


def _walk_client_statements(
    statements: list[ast.stmt],
    scope: _ClientScope,
    inherited: _ClientScope,
    walrus: _ClientScope,
    found: list[ast.AST],
    annotated: frozenset[int],
) -> _ClientExit:
    for statement in statements:
        exit_state = _walk_client_scope(statement, scope, inherited, walrus, found, annotated)
        if exit_state.kind != "fallthrough":
            return exit_state
    return _CLIENT_FALLTHROUGH


def _walk_client_boolop(
    node: ast.BoolOp,
    scope: _ClientScope,
    inherited: _ClientScope,
    walrus: _ClientScope,
    found: list[ast.AST],
    annotated: frozenset[int],
) -> None:
    active = [scope.copy_without()]
    completed: list[_ClientScope] = []
    is_and = isinstance(node.op, ast.And)
    for index, value in enumerate(node.values):
        following: list[_ClientScope] = []
        for branch in active:
            branch_walrus = branch if walrus is scope else walrus
            _walk_client_scope(value, branch, inherited, branch_walrus, found, annotated)
            if index == len(node.values) - 1:
                completed.append(branch)
                continue
            truth = _literal_truth(value)
            stops = truth is not None and truth != is_and
            continues = truth is not None and truth == is_and
            if stops:
                completed.append(branch)
            elif continues:
                following.append(branch)
            else:
                completed.append(branch.copy_without())
                following.append(branch)
        active = following
    scope.replace_with(_ClientScope.join(completed or active or [scope]))


def _walk_client_handler_body(
    handler: ast.ExceptHandler,
    entry: _ClientScope,
    found: list[ast.AST],
    annotated: frozenset[int],
) -> tuple[_ClientScope, _ClientExit]:
    body_scope = entry.copy_without({handler.name} if handler.name else None)
    exit_state = _walk_client_statements(handler.body, body_scope, body_scope, body_scope, found, annotated)
    if handler.name:
        _drop_client_bindings(body_scope, {handler.name})
    return body_scope, exit_state


def _walk_client_scope(node: ast.AST, scope: _ClientScope, inherited: _ClientScope, walrus: _ClientScope, found: list[ast.AST], annotated: frozenset[int]) -> _ClientExit:
    """Walk executable AST in CPython order and carry a conservative client-handle may-state."""
    if isinstance(node, ast.Module):
        return _walk_client_statements(node.body, scope, inherited, walrus, found, annotated)
    if isinstance(node, _PYTHON_SCOPE_NODES):
        _walk_client_nested_scope(node, scope, inherited, walrus, found, annotated)
        return _CLIENT_FALLTHROUGH
    if isinstance(node, _PYTHON_COMPREHENSION_NODES):
        _walk_client_comprehension(node, scope, inherited, walrus, found, annotated)
        return _CLIENT_FALLTHROUGH
    if isinstance(node, ast.Call) and _call_is_client_handle_sink(node, scope.handles):
        found.append(node)
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        if node.value is not None:
            _walk_client_scope(node.value, scope, inherited, walrus, found, annotated)
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        _bind_client_targets(targets, node.value, scope, inherited, walrus, found, annotated)
        if isinstance(node, ast.AnnAssign) and id(node) in annotated:
            _walk_client_scope(node.annotation, scope, inherited, walrus, found, annotated)
        return _CLIENT_FALLTHROUGH
    if isinstance(node, ast.NamedExpr):
        _walk_client_scope(node.value, scope, inherited, walrus, found, annotated)
        _rebind_client_scope([node.target], node.value, scope)
        if walrus is not scope:
            _rebind_client_scope([node.target], node.value, walrus)
        return _CLIENT_FALLTHROUGH
    if isinstance(node, ast.AugAssign):
        _walk_client_target_exprs(node.target, scope, inherited, walrus, found, annotated)
        _walk_client_scope(node.value, scope, inherited, walrus, found, annotated)
        _rebind_client_scope([node.target], None, scope)
        return _CLIENT_FALLTHROUGH
    if isinstance(node, ast.BoolOp):
        _walk_client_boolop(node, scope, inherited, walrus, found, annotated)
        return _CLIENT_FALLTHROUGH
    if isinstance(node, ast.IfExp):
        _walk_client_scope(node.test, scope, inherited, walrus, found, annotated)
        truth = _literal_truth(node.test)
        branches = [node.body] if truth is True else [node.orelse] if truth is False else [node.body, node.orelse]
        states = []
        for expression in branches:
            branch = scope.copy_without()
            _walk_client_scope(expression, branch, inherited, branch if walrus is scope else walrus, found, annotated)
            states.append(branch)
        scope.replace_with(_ClientScope.join(states))
        return _CLIENT_FALLTHROUGH
    if isinstance(node, ast.If):
        _walk_client_scope(node.test, scope, inherited, walrus, found, annotated)
        truth = _literal_truth(node.test)
        alternatives = [node.body] if truth is True else [node.orelse] if truth is False else [node.body, node.orelse]
        falling: list[_ClientScope] = []
        terminal_scopes: list[_ClientScope] = []
        exits: list[_ClientExit] = []
        for statements in alternatives:
            branch = scope.copy_without()
            exit_state = _walk_client_statements(statements, branch, branch, branch, found, annotated)
            exits.append(exit_state)
            (falling if exit_state.kind == "fallthrough" else terminal_scopes).append(branch)
        if falling:
            scope.replace_with(_ClientScope.join(falling))
            return _CLIENT_FALLTHROUGH
        scope.replace_with(_ClientScope.join(terminal_scopes or [scope]))
        return _merge_client_exits(exits)
    if isinstance(node, ast.While):
        _walk_client_scope(node.test, scope, inherited, walrus, found, annotated)
        truth = _literal_truth(node.test)
        if truth is False:
            return _walk_client_statements(node.orelse, scope, inherited, walrus, found, annotated)
        entry = scope.copy_without()
        iteration = entry.copy_without()
        body_exit = _walk_client_statements(node.body, iteration, iteration, iteration, found, annotated)
        if truth is True:
            scope.replace_with(iteration)
            if body_exit.kind == "break":
                return _CLIENT_FALLTHROUGH
            if body_exit.kind in {"fallthrough", "continue"}:
                return _ClientExit(kind="terminal")
            return body_exit
        falling: list[_ClientScope] = []
        zero = entry.copy_without()
        if _walk_client_statements(node.orelse, zero, zero, zero, found, annotated).kind == "fallthrough":
            falling.append(zero)
        if body_exit.kind == "break":
            falling.append(iteration)
        elif body_exit.kind in {"fallthrough", "continue"}:
            if _walk_client_statements(node.orelse, iteration, iteration, iteration, found, annotated).kind == "fallthrough":
                falling.append(iteration)
        if falling:
            scope.replace_with(_ClientScope.join(falling))
            return _CLIENT_FALLTHROUGH
        scope.replace_with(_ClientScope.join([entry, iteration]))
        return body_exit
    if isinstance(node, (ast.For, ast.AsyncFor)):
        _walk_client_scope(node.iter, scope, inherited, walrus, found, annotated)
        length = _literal_iterable_length(node.iter) if isinstance(node, ast.For) else None
        if length == 0:
            return _walk_client_statements(node.orelse, scope, inherited, walrus, found, annotated)
        entry = scope.copy_without()
        iteration = entry.copy_without()
        body_exit = _CLIENT_FALLTHROUGH

        def run_iteration(start: _ClientScope) -> tuple[_ClientScope, _ClientExit]:
            state = start.copy_without()
            _bind_client_targets([node.target], None, state, state, state, found, annotated)
            return state, _walk_client_statements(node.body, state, state, state, found, annotated)

        if length is not None:
            state = entry
            for _ in range(min(length, 8)):
                state, body_exit = run_iteration(state)
                if body_exit.kind == "break":
                    scope.replace_with(state)
                    return _CLIENT_FALLTHROUGH
                if body_exit.kind not in {"fallthrough", "continue"}:
                    scope.replace_with(state)
                    return body_exit
            if length > 8:
                # Widen very large literal loops to a stable may-state instead of walking attacker-
                # controlled list sizes. The one-level handle lattice converges quickly in practice.
                for _ in range(8):
                    candidate, body_exit = run_iteration(state)
                    if body_exit.kind == "break":
                        scope.replace_with(candidate)
                        return _CLIENT_FALLTHROUGH
                    if body_exit.kind not in {"fallthrough", "continue"}:
                        scope.replace_with(candidate)
                        return body_exit
                    widened = _ClientScope.join([state, candidate])
                    if widened == state:
                        break
                    state = widened
            scope.replace_with(state)
            return _walk_client_statements(node.orelse, scope, scope, scope, found, annotated)
        falling: list[_ClientScope] = []
        zero = entry.copy_without()
        if _walk_client_statements(node.orelse, zero, zero, zero, found, annotated).kind == "fallthrough":
            falling.append(zero)
        loop_head = entry.copy_without()
        for _ in range(8):
            iteration, body_exit = run_iteration(loop_head)
            if body_exit.kind == "break":
                falling.append(iteration)
                break
            if body_exit.kind not in {"fallthrough", "continue"}:
                break
            widened = _ClientScope.join([loop_head, iteration])
            if widened == loop_head:
                loop_head = widened
                break
            loop_head = widened
        else:
            iteration = loop_head
        if body_exit.kind in {"fallthrough", "continue"}:
            if _walk_client_statements(node.orelse, loop_head, loop_head, loop_head, found, annotated).kind == "fallthrough":
                falling.append(loop_head)
        if falling:
            scope.replace_with(_ClientScope.join(falling))
            return _CLIENT_FALLTHROUGH
        scope.replace_with(_ClientScope.join([entry, iteration]))
        return body_exit
    if isinstance(node, ast.withitem):
        _walk_client_scope(node.context_expr, scope, inherited, walrus, found, annotated)
        if node.optional_vars is not None:
            _bind_client_targets([node.optional_vars], node.context_expr, scope, inherited, walrus, found, annotated)
        return _CLIENT_FALLTHROUGH
    if isinstance(node, (ast.With, ast.AsyncWith)):
        for item in node.items:
            _walk_client_scope(item, scope, inherited, walrus, found, annotated)
        return _walk_client_statements(node.body, scope, inherited, walrus, found, annotated)
    if isinstance(node, ast.Raise):
        if node.exc is not None:
            _walk_client_scope(node.exc, scope, inherited, walrus, found, annotated)
        if node.cause is not None:
            _walk_client_scope(node.cause, scope, inherited, walrus, found, annotated)
        group = _raised_group_classes(node.exc, scope)
        raised = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
        exception = _literal_exception_class(raised, scope)
        return _ClientExit(kind="raise", exception=exception, exception_known=exception is not None or group is not None, group=group)
    if isinstance(node, ast.Return):
        if node.value is not None:
            _walk_client_scope(node.value, scope, inherited, walrus, found, annotated)
        return _ClientExit(kind="return")
    if isinstance(node, ast.Break):
        return _ClientExit(kind="break")
    if isinstance(node, ast.Continue):
        return _ClientExit(kind="continue")
    if isinstance(node, ast.TryStar):
        body_exit = _walk_client_statements(node.body, scope, inherited, walrus, found, annotated)
        group = body_exit.group
        if group is None and body_exit.kind == "raise" and body_exit.exception_known and body_exit.exception is not None:
            group = (body_exit.exception,)
        caught_types = [_literal_exception_class(handler.type, scope) for handler in node.handlers]
        decidable = group is not None and all(caught is not None or handler.type is None for handler, caught in zip(node.handlers, caught_types, strict=True))
        result = _CLIENT_FALLTHROUGH
        if decidable:
            remaining = list(group)
            handler_terminal = False
            for handler, caught in zip(node.handlers, caught_types, strict=True):
                if handler.type is not None:
                    _walk_client_scope(handler.type, scope, inherited, walrus, found, annotated)
                matched = remaining if handler.type is None else [raised for raised in remaining if issubclass(raised, caught)]
                if not matched:
                    continue
                clause_scope, clause_exit = _walk_client_handler_body(handler, scope, found, annotated)
                scope.replace_with(clause_scope)
                remaining = [raised for raised in remaining if raised not in matched]
                handler_terminal = handler_terminal or clause_exit.kind != "fallthrough"
            result = _CLIENT_FALLTHROUGH if not remaining and not handler_terminal else _ClientExit(kind="raise")
        else:
            for handler in node.handlers:
                if handler.type is not None:
                    _walk_client_scope(handler.type, scope, inherited, walrus, found, annotated)
                before = scope.copy_without()
                clause_scope, clause_exit = _walk_client_handler_body(handler, scope, found, annotated)
                if clause_exit.kind == "fallthrough":
                    scope.replace_with(_ClientScope.join([before, clause_scope]))
            if body_exit.kind == "fallthrough":
                else_scope = scope.copy_without()
                else_exit = _walk_client_statements(node.orelse, else_scope, else_scope, else_scope, found, annotated)
                if else_exit.kind == "fallthrough":
                    scope.replace_with(_ClientScope.join([scope, else_scope]))
            result = _CLIENT_FALLTHROUGH
        final_exit = _walk_client_statements(node.finalbody, scope, scope, scope, found, annotated)
        return final_exit if final_exit.kind != "fallthrough" else result
    if isinstance(node, ast.Try):
        body_exit = _walk_client_statements(node.body, scope, inherited, walrus, found, annotated)
        branches: list[_ClientScope] = []
        branch_exits: list[_ClientExit] = []
        result = body_exit
        if body_exit.kind in {"return", "break", "continue", "terminal"}:
            pass
        else:
            selected_known = False
            selected: int | None = None
            if body_exit.kind == "raise" and body_exit.exception_known and body_exit.exception is not None:
                selected_known, selected = _selected_handler_index(node.handlers, body_exit.exception, scope)
            selection_scope = scope.copy_without()
            if selected_known:
                last_type = len(node.handlers) if selected is None else selected + 1
                for handler in node.handlers[:last_type]:
                    if handler.type is not None:
                        _walk_client_scope(handler.type, selection_scope, selection_scope, selection_scope, found, annotated)
                if selected is not None:
                    body_scope, handler_exit = _walk_client_handler_body(node.handlers[selected], selection_scope, found, annotated)
                    branch_exits.append(handler_exit)
                    if handler_exit.kind == "fallthrough":
                        branches.append(body_scope)
                    else:
                        result = handler_exit
                else:
                    result = body_exit
            else:
                for handler in node.handlers:
                    if handler.type is not None:
                        _walk_client_scope(handler.type, selection_scope, selection_scope, selection_scope, found, annotated)
                    body_scope, handler_exit = _walk_client_handler_body(handler, selection_scope, found, annotated)
                    branch_exits.append(handler_exit)
                    if handler_exit.kind == "fallthrough":
                        branches.append(body_scope)
                if body_exit.kind == "fallthrough":
                    else_scope = scope.copy_without()
                    else_exit = _walk_client_statements(node.orelse, else_scope, else_scope, else_scope, found, annotated)
                    branch_exits.append(else_exit)
                    if else_exit.kind == "fallthrough":
                        branches.append(else_scope)
            if branches:
                scope.replace_with(_ClientScope.join(branches))
                result = _CLIENT_FALLTHROUGH
            elif branch_exits and not selected_known:
                result = _merge_client_exits(branch_exits)
        final_exit = _walk_client_statements(node.finalbody, scope, scope, scope, found, annotated)
        return final_exit if final_exit.kind != "fallthrough" else result
    if isinstance(node, ast.Match):
        _walk_client_scope(node.subject, scope, inherited, walrus, found, annotated)
        branches: list[_ClientScope] = []
        terminal_scopes: list[_ClientScope] = []
        exits: list[_ClientExit] = []
        exhaustive = False
        for case in node.cases:
            pattern_decision = _match_case_decision(node.subject, case, scope)
            if pattern_decision is False:
                continue
            captures = _match_pattern_capture_names(case.pattern)
            case_scope = scope.copy_without(captures)
            guard_truth = True
            if case.guard is not None:
                _walk_client_scope(case.guard, case_scope, inherited, case_scope, found, annotated)
                guard_truth = _literal_truth(case.guard)
                scope.replace_with(case_scope)
                if guard_truth is False:
                    continue
            else:
                exhaustive = pattern_decision is True
            body_scope = case_scope.copy_without()
            body_exit = _walk_client_statements(case.body, body_scope, body_scope, body_scope, found, annotated)
            exits.append(body_exit)
            (branches if body_exit.kind == "fallthrough" else terminal_scopes).append(body_scope)
            if exhaustive and guard_truth is True:
                break
        if not exhaustive:
            branches.append(scope.copy_without())
        if branches:
            scope.replace_with(_ClientScope.join(branches))
            return _CLIENT_FALLTHROUGH
        scope.replace_with(_ClientScope.join(terminal_scopes or [scope]))
        return _merge_client_exits(exits)
    if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
        _drop_client_bindings(scope, {node.id})
    elif isinstance(node, (ast.Import, ast.ImportFrom)):
        _bind_client_import(node, scope)
        return _CLIENT_FALLTHROUGH
    for child in ast.iter_child_nodes(node):
        _walk_client_scope(child, scope, inherited, walrus, found, annotated)
    return _CLIENT_FALLTHROUGH


def _walk_client_nested_scope(node: ast.AST, scope: _ClientScope, inherited: _ClientScope, walrus: _ClientScope, found: list[ast.AST], annotated: frozenset[int]) -> None:
    for expr in _client_scope_prelude(node, annotated):
        _walk_client_scope(expr, scope, inherited, walrus, found, annotated)
    if isinstance(node, ast.ClassDef):
        # A class body reads the enclosing scope, but the names it binds are not visible to the
        # methods defined in it, so what those methods close over stays the class's own `inherited`.
        inner, nested = inherited.copy_without(), inherited
    else:
        inner = inherited.copy_without(_client_scope_bindings(node))
        nested = inner
    body = node.body if isinstance(node.body, list) else [node.body]
    _walk_client_statements(body, inner, nested, inner, found, annotated)
    if not isinstance(node, ast.Lambda):
        _drop_client_bindings(scope, {node.name})


def _walk_client_comprehension(node: ast.AST, scope: _ClientScope, inherited: _ClientScope, walrus: _ClientScope, found: list[ast.AST], annotated: frozenset[int]) -> None:
    """A comprehension is its own scope: only the outermost iterable is evaluated outside it, and
    each target and its filters run before the following iterable. An assignment expression inside
    it still binds in the containing scope, so `walrus` passes through.
    """
    generators = node.generators
    _walk_client_scope(generators[0].iter, scope, inherited, walrus, found, annotated)
    inner = inherited.copy_without()
    for index, generator in enumerate(generators):
        if index:
            _walk_client_scope(generator.iter, inner, inner, walrus, found, annotated)
        _bind_client_targets([generator.target], None, inner, inner, walrus, found, annotated)
        for condition in generator.ifs:
            _walk_client_scope(condition, inner, inner, walrus, found, annotated)
    elements = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
    for element in elements:
        _walk_client_scope(element, inner, inner, walrus, found, annotated)


def _match_capture_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.MatchMapping):
        return [node.rest] if node.rest else []
    return [node.name] if node.name else []


def _match_pattern_capture_names(pattern: ast.AST) -> set[str]:
    """Every name a case pattern binds when it matches (nested captures included)."""
    names: set[str] = set()
    for node in ast.walk(pattern):
        if isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            names.add(node.rest)
    return names


def _client_scope_prelude(node: ast.AST, annotated: frozenset[int]) -> list[ast.AST]:
    """Expressions a scope-defining statement evaluates in its *enclosing* scope, not the new one:
    decorators, argument/keyword defaults, class bases/keywords, and -- when the runtime evaluates
    them (`id(node) in annotated`, i.e. not postponed) -- a function's parameter and return annotations.
    """
    if isinstance(node, ast.ClassDef):
        return [*node.decorator_list, *node.bases, *(keyword.value for keyword in node.keywords)]
    defaults = [default for default in [*node.args.defaults, *node.args.kw_defaults] if default is not None]
    if isinstance(node, ast.Lambda):
        return defaults
    annotations = _function_annotation_exprs(node) if id(node) in annotated else []
    return [*node.decorator_list, *defaults, *annotations]


def _function_annotation_exprs(node: ast.AST) -> list[ast.AST]:
    # CPython evaluates parameter annotations at def time as: ordinary positional, positional-only,
    # `*args`, keyword-only, `**kwargs`, then the return annotation -- not the declaration order that
    # puts positional-only first. A walrus in one annotation rebinds a handle the next annotation
    # reads, so emitting them out of runtime order both misses real exfil and hard-blocks benign code.
    args = node.args
    ordered = [*args.args, *args.posonlyargs, args.vararg, *args.kwonlyargs, args.kwarg]
    exprs = [arg.annotation for arg in ordered if arg is not None and arg.annotation is not None]
    if node.returns is not None:
        exprs.append(node.returns)
    return exprs


def _client_scope_bindings(node: ast.AST) -> set[str]:
    """Names local to a function scope: parameters plus everything its body binds anywhere.

    A function-local binding shadows an enclosing name across the whole body rather than from the
    assignment onward, so an inherited handle must not survive into a scope that rebinds the name
    at all. `global`/`nonlocal` opt a name back out of that shadowing.
    """
    args = node.args
    names = {arg.arg for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]}
    for extra in (args.vararg, args.kwarg):
        if extra is not None:
            names.add(extra.arg)
    declared: set[str] = set()
    for statement in node.body if isinstance(node.body, list) else [node.body]:
        _collect_client_scope_bindings(statement, names, declared)
    return names - declared


def _collect_client_scope_bindings(node: ast.AST, names: set[str], declared: set[str]) -> None:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        names.add(node.name)  # The statement binds its own name here; its body is a separate scope.
        return
    if isinstance(node, ast.Lambda):
        return
    if isinstance(node, (ast.Global, ast.Nonlocal)):
        declared.update(node.names)
        return
    if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
        names.add(node.id)
    elif isinstance(node, ast.ExceptHandler) and node.name:
        names.add(node.name)
    elif isinstance(node, (ast.Import, ast.ImportFrom)):
        for alias in node.names:
            names.add(alias.asname or alias.name.split(".")[0])
    elif isinstance(node, _PYTHON_MATCH_CAPTURE_NODES):
        names.update(_match_capture_names(node))
    if isinstance(node, _PYTHON_COMPREHENSION_NODES):
        # Comprehension targets bind in the comprehension's own scope; a walrus inside it binds here.
        for child in ast.walk(node):
            if isinstance(child, ast.NamedExpr):
                _collect_client_scope_bindings(child.target, names, declared)
        return
    for child in ast.iter_child_nodes(node):
        _collect_client_scope_bindings(child, names, declared)


def _rebind_client_scope(targets: list[ast.AST], value: ast.AST | None, scope: _ClientScope) -> None:
    # The value is evaluated before any target is bound, so resolve an aliased constructor before
    # invalidating a target that may use the same name. Attribute and item targets do not bind their
    # receiver (`session.headers = ...` keeps `session`); destructuring binds only its name leaves.
    constructor = _python_call_name(value, scope.aliases) if isinstance(value, ast.Call) else ""
    names = {name for target in targets for name in _client_assignment_target_names(target)}
    _drop_client_bindings(scope, names)
    if constructor in _PYTHON_CLIENT_CONSTRUCTORS:
        for target in targets:
            if isinstance(target, ast.Name):
                scope.handles[target.id] = constructor


def _client_assignment_target_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Starred):
        return _client_assignment_target_names(target.value)
    if isinstance(target, (ast.List, ast.Tuple)):
        return [name for element in target.elts for name in _client_assignment_target_names(element)]
    return []


def _bind_client_targets(targets: list[ast.AST], value: ast.AST | None, scope: _ClientScope, inherited: _ClientScope, walrus: _ClientScope, found: list[ast.AST], annotated: frozenset[int]) -> None:
    """Apply assignment targets in Python's left-to-right order: each target's executable sub-expressions
    are scanned against the current bindings, then that target's name(s) are rebound before the next
    target is analyzed. Tuple/list unpacking binds its elements left to right too; a destructured value
    is not tracked one level deep, so those elements rebind with no constructor.
    """
    for target in targets:
        if isinstance(target, (ast.List, ast.Tuple)):
            _bind_client_targets(target.elts, None, scope, inherited, walrus, found, annotated)
        elif isinstance(target, ast.Starred):
            _bind_client_targets([target.value], None, scope, inherited, walrus, found, annotated)
        else:
            _walk_client_target_exprs(target, scope, inherited, walrus, found, annotated)
            _rebind_client_scope([target], value, scope)


def _walk_client_target_exprs(target: ast.AST, scope: _ClientScope, inherited: _ClientScope, walrus: _ClientScope, found: list[ast.AST], annotated: frozenset[int]) -> None:
    """Walk the sub-expressions Python evaluates while binding a single (non-tuple) target.

    A plain `Name` target binds without evaluating anything, but an attribute or subscript target still
    evaluates its receiver (and a subscript its index), so a sink call placed there runs at bind time and
    must be scanned. The Store name leaf is handled by the caller's `_rebind_client_scope` rebind, so it
    is deliberately not walked as a read here. Tuple/list/starred structure is unpacked by the caller.
    """
    if isinstance(target, ast.Attribute):
        _walk_client_scope(target.value, scope, inherited, walrus, found, annotated)
    elif isinstance(target, ast.Subscript):
        _walk_client_scope(target.value, scope, inherited, walrus, found, annotated)
        _walk_client_scope(target.slice, scope, inherited, walrus, found, annotated)


def _drop_client_bindings(scope: _ClientScope, names: set[str]) -> None:
    scope.shadowed.update(names)
    for name in names:
        scope.handles.pop(name, None)
        scope.aliases.pop(name, None)


def _bind_client_import(node: ast.Import | ast.ImportFrom, scope: _ClientScope) -> None:
    for alias in node.names:
        if alias.name == "*":
            continue
        name = alias.asname or alias.name.split(".")[0]
        _drop_client_bindings(scope, {name})
        if isinstance(node, ast.Import):
            scope.aliases[name] = alias.name if alias.asname else name
        elif node.module:
            scope.aliases[name] = f"{node.module}.{alias.name}"


def _call_is_client_handle_sink(node: ast.Call, handles: dict[str, str]) -> bool:
    func = node.func
    return isinstance(func, ast.Attribute) and func.attr in _PYTHON_CLIENT_SINK_METHODS and isinstance(func.value, ast.Name) and func.value.id in handles


def _yaml_load_uses_safe_loader(node: ast.Call) -> bool:
    for keyword in node.keywords:
        if keyword.arg in {"Loader", "loader"}:
            name = _python_name(keyword.value, {})
            if "SafeLoader" in name:
                return True
    return False
