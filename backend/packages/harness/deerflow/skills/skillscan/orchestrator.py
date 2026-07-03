"""Native deterministic scanning for DeerFlow skills."""

from __future__ import annotations

import ast
import hashlib
import logging
import posixpath
import re
import stat
import zipfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from deerflow.skills.skillscan.models import (
    DEFAULT_SKILLSCAN_POLICY,
    ScanContext,
    ScanResult,
    SecurityFinding,
    SkillScanPolicy,
    StaticScanBlockedError,
    StaticScannerError,
)
from deerflow.skills.skillscan.rules import get_rule

logger = logging.getLogger(__name__)

MAX_TOTAL_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_FILE_BYTES = 64 * 1024 * 1024

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
_TEXT_SUFFIXES = {
    ".bash",
    ".cfg",
    ".env",
    ".ini",
    ".json",
    ".md",
    ".markdown",
    ".py",
    ".rst",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
_PLACEHOLDER_VALUES = {"", "x", "xx", "xxx", "xxxx", "changeme", "change-me", "example", "placeholder", "test", "dummy", "your-key", "<your-key>"}
_SENSITIVE_PATH_RE = re.compile(r"(~/.ssh|/etc/passwd|/etc/shadow|/var/run/docker\.sock|docker\.sock|169\.254\.169\.254)")
_EXTERNAL_HTTP_RE = re.compile(r"http://([A-Za-z0-9.-]+)(?::\d+)?(?:/|\b)")
_URL_RE = re.compile(r"https?://[^\s)'\"<>]+")
_LOCAL_HTTP_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def _default_context(skill_dir: Path | None = None, *, entrypoint: str = "ci", skill_name: str | None = None) -> ScanContext:
    return {
        "entrypoint": entrypoint,  # type: ignore[typeddict-item]
        "skill_name": skill_name,
        "skill_root": str(skill_dir) if skill_dir else None,
        "existing_skill": False,
        "strict": False,
    }


def _policy_from_app_config(app_config: Any | None, policy: SkillScanPolicy | None = None) -> SkillScanPolicy:
    merged: SkillScanPolicy = {**DEFAULT_SKILLSCAN_POLICY}
    if policy:
        merged.update(policy)
    if app_config is None:
        try:
            from deerflow.config import get_app_config

            app_config = get_app_config()
        except Exception:
            app_config = None
    skill_scan_config = getattr(app_config, "skill_scan", None)
    if skill_scan_config is not None and hasattr(skill_scan_config, "enabled"):
        merged["enabled"] = bool(skill_scan_config.enabled)
    return merged


def static_findings_to_dicts(findings: list[SecurityFinding]) -> list[SecurityFinding]:
    return [dict(finding) for finding in findings]  # type: ignore[list-item]


def format_static_findings(findings: list[SecurityFinding]) -> str:
    parts = []
    for finding in findings:
        location = finding["file"] or "<archive>"
        if finding["line"] is not None:
            location = f"{location}:{finding['line']}"
        parts.append(f"{finding['rule_id']} ({finding['severity']}) at {location}: {finding['message']} Remediation: {finding['remediation']}")
    return "; ".join(parts)


def run_static_scan(skill_dir: Path, *, context: ScanContext | None = None, policy: SkillScanPolicy | None = None, app_config: Any | None = None) -> list[SecurityFinding]:
    return scan_skill_dir(skill_dir, context=context, policy=policy, app_config=app_config)["findings"]


def enforce_static_scan(
    skill_dir: Path,
    *,
    skill_name: str | None = None,
    context: ScanContext | None = None,
    policy: SkillScanPolicy | None = None,
    app_config: Any | None = None,
) -> list[SecurityFinding]:
    effective_policy = _policy_from_app_config(app_config, policy)
    if not effective_policy["enabled"]:
        return []

    scan_context = context or _default_context(Path(skill_dir), skill_name=skill_name)
    result = scan_skill_dir(Path(skill_dir), context=scan_context, policy=effective_policy, app_config=app_config)
    blocked = [finding for finding in result["findings"] if finding["severity"] in effective_policy["block_severities"]]
    if blocked:
        raise StaticScanBlockedError(
            blocked,
            skill_name=skill_name,
            message=f"Static security scan blocked skill '{skill_name}': {format_static_findings(blocked)}" if skill_name else f"Static security scan blocked skill content: {format_static_findings(blocked)}",
        )
    if result["scanner_errors"]:
        logger.warning("SkillScan analyzer errors for %s: %s", skill_name or skill_dir, "; ".join(result["scanner_errors"]))
    if result["warnings"]:
        logger.warning("SkillScan warning findings for %s: %s", skill_name or skill_dir, format_static_findings(result["warnings"]))
    return static_findings_to_dicts(result["findings"])


def scan_archive_preflight(
    archive_path: Path,
    *,
    context: ScanContext | None = None,
    policy: SkillScanPolicy | None = None,
    app_config: Any | None = None,
) -> ScanResult:
    effective_policy = _policy_from_app_config(app_config, policy)
    if not effective_policy["enabled"]:
        return _scan_result([], [], effective_policy)

    findings: list[SecurityFinding] = []
    scanner_errors: list[str] = []
    total_size = 0
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            for info in zf.infolist():
                normalized = _normalize_archive_name(info.filename)
                findings.extend(_scan_archive_member_metadata(info, normalized))
                if info.is_dir():
                    continue
                total_size += max(info.file_size, 0)
                if info.file_size > MAX_FILE_BYTES:
                    findings.append(_finding("package-oversized-file", file=normalized, evidence=f"{info.file_size} bytes"))
                if _is_nested_archive_name(normalized):
                    findings.append(_finding("package-nested-archive", file=normalized, evidence=Path(normalized).name))
                if _is_hidden_sensitive_path(normalized):
                    findings.append(_finding("package-hidden-sensitive-file", file=normalized, evidence=Path(normalized).name))
                if ".git" in PurePosixPath(normalized).parts:
                    findings.append(_finding("package-git-directory", file=normalized, evidence=".git"))
                if not _is_symlink_member(info):
                    try:
                        with zf.open(info) as member:
                            prefix = member.read(8)
                    except Exception as e:
                        scanner_errors.append(f"{normalized}: failed to read archive member prefix: {e}")
                    else:
                        if _is_executable_binary(prefix):
                            findings.append(_finding("package-executable-binary", file=normalized, evidence=_binary_magic_evidence(prefix)))
            if total_size > MAX_TOTAL_ARCHIVE_BYTES:
                findings.append(_finding("package-oversized-total", file=None, evidence=f"{total_size} bytes"))
    except (zipfile.BadZipFile, OSError) as e:
        raise StaticScannerError(f"failed to read skill archive: {e}") from e

    return _scan_result(_dedupe(findings), scanner_errors, effective_policy)


def scan_skill_dir(
    skill_dir: Path,
    *,
    context: ScanContext | None = None,
    policy: SkillScanPolicy | None = None,
    app_config: Any | None = None,
) -> ScanResult:
    effective_policy = _policy_from_app_config(app_config, policy)
    if not effective_policy["enabled"]:
        return _scan_result([], [], effective_policy)

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
        text = _decode_text_for_analysis(rel_path, file_bytes)
        if text is None:
            continue

        try:
            findings.extend(_scan_text_file(rel_path, text))
        except Exception as e:
            scanner_errors.append(f"{rel_path}: analyzer failed: {e}")
            logger.warning("SkillScan analyzer failed for %s", rel_path, exc_info=True)

    return _scan_result(_dedupe(findings), scanner_errors, effective_policy)


def scan_file_content(
    content: str | bytes,
    *,
    relative_path: str,
    context: ScanContext | None = None,
    policy: SkillScanPolicy | None = None,
    app_config: Any | None = None,
) -> ScanResult:
    effective_policy = _policy_from_app_config(app_config, policy)
    if not effective_policy["enabled"]:
        return _scan_result([], [], effective_policy)
    if isinstance(content, bytes):
        text = _decode_text_for_analysis(relative_path, content)
        if text is None:
            return _scan_result(_scan_file_package_properties(relative_path, content, len(content)), [], effective_policy)
    else:
        text = content
    return _scan_result(_dedupe([*_scan_file_package_properties(relative_path, text.encode("utf-8"), len(text.encode("utf-8"))), *_scan_text_file(relative_path, text)]), [], effective_policy)


def _scan_archive_member_metadata(info: zipfile.ZipInfo, normalized: str) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    if _archive_member_is_absolute(info.filename):
        findings.append(_finding("package-absolute-path", file=normalized, evidence=info.filename))
    elif _archive_member_traverses(info.filename):
        findings.append(_finding("package-path-traversal", file=normalized, evidence=info.filename))
    if _is_symlink_member(info):
        findings.append(_finding("package-symlink", file=normalized, evidence=info.filename))
    parts = PurePosixPath(normalized).parts
    if parts and parts[-1] == "SKILL.md" and len(parts) > 2:
        findings.append(_finding("package-nested-skill-md", file=normalized, evidence=normalized))
    return findings


def _scan_file_package_properties(rel_path: str, file_bytes: bytes, file_size: int) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    path = PurePosixPath(rel_path)
    if path.name == "SKILL.md" and len(path.parts) > 1:
        findings.append(_finding("package-nested-skill-md", file=rel_path, evidence=rel_path))
    if file_size > MAX_FILE_BYTES:
        findings.append(_finding("package-oversized-file", file=rel_path, evidence=f"{file_size} bytes"))
    if _is_hidden_sensitive_path(rel_path):
        findings.append(_finding("package-hidden-sensitive-file", file=rel_path, evidence=path.name))
    if ".git" in path.parts:
        findings.append(_finding("package-git-directory", file=rel_path, evidence=".git"))
    if _is_nested_archive_name(rel_path) or _looks_like_archive(file_bytes):
        findings.append(_finding("package-nested-archive", file=rel_path, evidence=path.name))
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

    if "169.254.169.254" in text:
        findings.append(_finding_for_text("python-cloud-metadata-access", rel_path, text, "169.254.169.254"))
    if "socket" in text and "dup2" in text and "subprocess" in text:
        findings.append(_finding_for_text("python-reverse-shell", rel_path, text, "dup2"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _SENSITIVE_PATH_RE.search(node.value):
                has_sensitive_read = True
                sensitive_node = sensitive_node or node
            if _is_outbound_url(node.value):
                has_network_sink = True
                network_node = network_node or node

        if isinstance(node, ast.Attribute) and _python_name(node, aliases) == "os.environ":
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

    if has_sensitive_read and has_network_sink:
        findings.append(_finding_for_node("python-sensitive-exfil", rel_path, sensitive_node or network_node, "sensitive read + network sink"))
    elif has_sensitive_read:
        findings.append(_finding_for_node("python-sensitive-path-read", rel_path, sensitive_node, "sensitive path read"))
    if has_env_dump and has_network_sink:
        findings.append(_finding_for_node("python-env-dump-exfil", rel_path, env_node or network_node, "environment dump + network sink"))
    return findings


def _scan_shell(rel_path: str, text: str) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    reverse_re = re.compile(r"(/dev/tcp/|bash\s+-i|nc\s+-e|mkfifo\s+)")
    if match := reverse_re.search(text):
        findings.append(_finding_from_match("shell-reverse-shell", rel_path, text, match))
    if re.search(r"(/etc/shadow|/etc/passwd)", text) and re.search(r"\b(curl|wget|nc|scp)\b", text):
        findings.append(_finding_for_text("shell-sensitive-exfil", rel_path, text, "/etc"))
    if match := re.search(r"\b(curl|wget)\b[^\n|;]*\|\s*(?:sh|bash)\b", text):
        findings.append(_finding_from_match("shell-curl-pipe-shell", rel_path, text, match))
    if match := re.search(r"rm\s+-rf\s+/(?:\s|$)|:\(\)\{\s*:\|:&\s*\};:|dd\s+[^#\n]*\bof=/dev/", text):
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


def _finding(rule_id: str, *, file: str | None, evidence: str | None, line: int | None = None, column: int | None = None, metadata: dict[str, str] | None = None) -> SecurityFinding:
    spec = get_rule(rule_id)
    normalized_evidence = _normalize_evidence(evidence or spec.message)
    path_for_hash = file or ""
    fingerprint = "sha256:" + hashlib.sha256(f"{rule_id}\0{path_for_hash}\0{normalized_evidence}".encode()).hexdigest()
    return {
        "rule_id": rule_id,
        "category": spec.category,
        "severity": spec.severity,
        "confidence": spec.confidence,
        "file": file,
        "line": line,
        "column": column,
        "message": spec.message,
        "remediation": spec.remediation,
        "evidence": evidence,
        "fingerprint": fingerprint,
        "analyzer": spec.analyzer,
        "metadata": metadata or {},
    }


def _finding_from_match(rule_id: str, rel_path: str, text: str, match: re.Match[str]) -> SecurityFinding:
    line, column = _line_column(text, match.start())
    return _finding(rule_id, file=rel_path, line=line, column=column, evidence=match.group(0))


def _finding_for_text(rule_id: str, rel_path: str, text: str, evidence: str) -> SecurityFinding:
    index = text.find(evidence)
    line, column = _line_column(text, index if index >= 0 else 0)
    return _finding(rule_id, file=rel_path, line=line, column=column, evidence=evidence)


def _finding_for_node(rule_id: str, rel_path: str, node: ast.AST | None, evidence: str) -> SecurityFinding:
    return _finding(rule_id, file=rel_path, line=getattr(node, "lineno", 1), column=(getattr(node, "col_offset", 0) + 1 if node is not None else 1), evidence=evidence)


def _scan_result(findings: list[SecurityFinding], scanner_errors: list[str], policy: SkillScanPolicy) -> ScanResult:
    warnings = [finding for finding in findings if finding["severity"] in policy["warn_severities"]]
    blocked = any(finding["severity"] in policy["block_severities"] for finding in findings)
    if scanner_errors and policy["fail_on_scanner_error"]:
        blocked = True
    return {"findings": findings, "blocked": blocked, "warnings": warnings, "scanner_errors": scanner_errors}


def _dedupe(findings: Iterable[SecurityFinding]) -> list[SecurityFinding]:
    seen: set[str] = set()
    deduped: list[SecurityFinding] = []
    for finding in findings:
        key = finding["fingerprint"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)
    return deduped


def _normalize_evidence(value: str) -> str:
    return " ".join(value.split())


def _line_column(text: str, index: int) -> tuple[int, int]:
    prefix = text[: max(index, 0)]
    line = prefix.count("\n") + 1
    last_newline = prefix.rfind("\n")
    column = len(prefix) + 1 if last_newline == -1 else len(prefix) - last_newline
    return line, column


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


def _decode_text_for_analysis(rel_path: str, file_bytes: bytes) -> str | None:
    if b"\x00" in file_bytes[:4096]:
        return None
    suffix = PurePosixPath(rel_path).suffix.lower()
    if suffix not in _TEXT_SUFFIXES and not _has_text_shebang(file_bytes):
        try:
            return file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return None
    try:
        return file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _has_text_shebang(file_bytes: bytes) -> bool:
    first_line = file_bytes.splitlines()[:1]
    return bool(first_line and first_line[0].startswith(b"#!"))


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
    return call_name in {"requests.get", "requests.post", "requests.put", "requests.request", "urllib.request.urlopen", "httpx.get", "httpx.post", "socket.socket"}


def _yaml_load_uses_safe_loader(node: ast.Call) -> bool:
    for keyword in node.keywords:
        if keyword.arg in {"Loader", "loader"}:
            name = _python_name(keyword.value, {})
            if "SafeLoader" in name:
                return True
    return False
