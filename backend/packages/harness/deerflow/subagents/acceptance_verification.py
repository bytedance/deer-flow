"""Deterministic checks for delegated-task acceptance criteria.

This layer deliberately performs only checks whose result can be established
without another model.  Criteria that require interpreting a report or
running an arbitrary command are returned as ``unverified``; they are never
treated as passing merely because the subagent claimed success.
"""

from __future__ import annotations

import errno
import posixpath
import re
from collections.abc import Iterable
from html import escape
from typing import Literal, Protocol, TypedDict

AcceptanceStatus = Literal["satisfied", "failed", "unverified"]


class AcceptanceCheck(TypedDict):
    criterion: str
    kind: str
    value: str
    status: AcceptanceStatus
    detail: str


class AcceptanceVerdict(TypedDict):
    source: str
    requirement: str
    acceptance_resolved: bool
    checks: list[AcceptanceCheck]


class _ReadableSandbox(Protocol):
    def download_file(self, path: str) -> bytes: ...


VERDICT_SOURCE = "acceptance_criteria"
VERDICT_REQUIREMENT = "deterministic_leaf_checks"
MAX_CRITERIA = 20
MAX_CRITERION_CHARS = 500
_RENDER_DETAIL_CHARS = 180
_RENDER_MAX_CHARS = 2000
_MAX_DETAIL_CHARS = 500

_FILE_RE = re.compile(r"^file:(.+?)\s+(exists|non-empty)$", re.IGNORECASE)
_FILE_WRITTEN_RE = re.compile(r"^file_written:(.+)$", re.IGNORECASE)
_TESTS_RE = re.compile(r"^tests_passed:(.+)$", re.IGNORECASE)
_RESOURCE_RE = re.compile(r"^resource_created:(.+)$", re.IGNORECASE)


def _bounded_criteria(criteria: Iterable[object] | None) -> list[str]:
    if criteria is None or isinstance(criteria, (str, bytes, bytearray)):
        return []
    try:
        iterator = iter(criteria)
    except TypeError:
        return []
    bounded: list[str] = []
    for raw in iterator:
        if not isinstance(raw, str):
            continue
        value = raw.strip()[:MAX_CRITERION_CHARS].strip()
        if not value:
            continue
        bounded.append(value)
        if len(bounded) >= MAX_CRITERIA:
            break
    return bounded


def parse_acceptance_criteria(criteria: Iterable[object] | None) -> list[tuple[str, str, str]]:
    """Parse canonical criteria into ``(display_text, kind, value)`` tuples.

    Unknown syntax is retained as ``kind='unsupported'`` so it is visible in
    the verdict rather than silently dropped.
    """
    parsed: list[tuple[str, str, str]] = []
    for text in _bounded_criteria(criteria):
        match = _FILE_RE.fullmatch(text)
        if match:
            parsed.append((text, f"file_{match.group(2).lower().replace('-', '_')}", match.group(1).strip()))
            continue
        match = _FILE_WRITTEN_RE.fullmatch(text)
        if match:
            parsed.append((text, "file_written", match.group(1).strip()))
            continue
        match = _TESTS_RE.fullmatch(text)
        if match:
            parsed.append((text, "tests_passed", match.group(1).strip()))
            continue
        match = _RESOURCE_RE.fullmatch(text)
        if match:
            parsed.append((text, "resource_created", match.group(1).strip()))
            continue
        parsed.append((text, "unsupported", text))
    return parsed


def _file_check(kind: str, path: str, sandbox: _ReadableSandbox | None) -> tuple[AcceptanceStatus, str]:
    if not path or "\x00" in path:
        return "unverified", "path is empty or contains a NUL byte"
    # Sandbox providers normalize separators differently; canonicalize before
    # the root check so `..` cannot be interpreted inconsistently downstream.
    path = path.replace("\\", "/")
    # Keep the short paths used by the RFC examples (`/outputs/...`) aligned
    # with the sandbox's canonical `/mnt/user-data/...` virtual paths.
    for alias in ("/workspace", "/uploads", "/outputs"):
        if path == alias or path.startswith(f"{alias}/"):
            path = f"/mnt/user-data{path}"
            break
    if not path.startswith("/"):
        # Delegations commonly describe outputs relative to the mounted
        # workspace (for example ``../outputs/report.md``). Resolve that
        # notation inside the virtual sandbox and reject escapes.
        path = posixpath.normpath(posixpath.join("/mnt/user-data/workspace", path))
    else:
        path = posixpath.normpath(path)
    if path != "/mnt/user-data" and not path.startswith("/mnt/user-data/"):
        return "unverified", "path escapes the sandbox data root"
    if path == "/mnt/user-data" or not path.startswith("/mnt/user-data/"):
        return "unverified", "path is outside the sandbox data root"
    if sandbox is None:
        return "unverified", "sandbox unavailable for deterministic file check"
    try:
        data = sandbox.download_file(path)
    except PermissionError:
        return "unverified", "sandbox refused access to path"
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            return "failed", "file does not exist"
        return "unverified", "sandbox could not inspect path"
    except Exception:
        # Remote providers do not share one exception hierarchy.  A provider
        # error is evidence that the check could not be decided, not proof of
        # failure.
        return "unverified", "sandbox could not inspect path"

    if not isinstance(data, (bytes, bytearray)):
        return "unverified", "sandbox returned an invalid file payload"
    if kind == "file_non_empty" and len(data) == 0:
        return "failed", "file is empty"
    if kind == "file_exists":
        return "satisfied", "file exists"
    if kind == "file_non_empty":
        return "satisfied", f"file contains {len(data)} bytes"
    # ``file_written`` intentionally checks existence only: an empty file is a
    # valid write result and can be distinguished from ``non-empty`` by the
    # caller's criterion.
    return "satisfied", "file exists"


def evaluate_acceptance_criteria(
    criteria: Iterable[object] | None,
    *,
    sandbox: _ReadableSandbox | None = None,
) -> AcceptanceVerdict:
    """Evaluate criteria without LLM calls or arbitrary command execution."""
    checks: list[AcceptanceCheck] = []
    for criterion, kind, value in parse_acceptance_criteria(criteria):
        if kind in {"file_exists", "file_non_empty", "file_written"}:
            status, detail = _file_check(kind, value, sandbox)
        elif kind == "tests_passed":
            status, detail = "unverified", "command criteria require command-level evidence"
        elif kind == "resource_created":
            status, detail = "unverified", "resource criteria require provider-specific evidence"
        else:
            status, detail = "unverified", "criterion syntax is unsupported"
        checks.append({"criterion": criterion, "kind": kind, "value": value, "status": status, "detail": detail})

    return AcceptanceVerdict(
        source=VERDICT_SOURCE,
        requirement=VERDICT_REQUIREMENT,
        acceptance_resolved=bool(checks) and all(check["status"] == "satisfied" for check in checks),
        checks=checks,
    )


def validate_acceptance_verdict(value: object) -> AcceptanceVerdict | None:
    """Validate persisted acceptance metadata before exposing it to a model."""
    if not isinstance(value, dict):
        return None
    if value.get("source") != VERDICT_SOURCE or value.get("requirement") != VERDICT_REQUIREMENT:
        return None
    if not isinstance(value.get("acceptance_resolved"), bool):
        return None
    raw_checks = value.get("checks")
    if not isinstance(raw_checks, list) or len(raw_checks) > MAX_CRITERIA:
        return None
    checks: list[AcceptanceCheck] = []
    for raw in raw_checks:
        if not isinstance(raw, dict):
            return None
        if any(not isinstance(raw.get(key), str) for key in ("criterion", "kind", "value", "detail")):
            return None
        if any(len(raw[key]) > MAX_CRITERION_CHARS for key in ("criterion", "kind", "value")) or len(raw["detail"]) > _MAX_DETAIL_CHARS:
            return None
        status = raw.get("status")
        if status not in {"satisfied", "failed", "unverified"}:
            return None
        checks.append({"criterion": raw["criterion"], "kind": raw["kind"], "value": raw["value"], "status": status, "detail": raw["detail"]})
    expected_resolved = bool(checks) and all(check["status"] == "satisfied" for check in checks)
    if value["acceptance_resolved"] != expected_resolved:
        return None
    return AcceptanceVerdict(
        source=value["source"],
        requirement=value["requirement"],
        acceptance_resolved=value["acceptance_resolved"],
        checks=checks,
    )


def render_acceptance_verdict(verdict: AcceptanceVerdict) -> str:
    """Render compact, neutral ledger text for the lead model."""
    if not verdict["checks"]:
        return ""
    counts = {status: sum(check["status"] == status for check in verdict["checks"]) for status in ("satisfied", "failed", "unverified")}
    parts: list[str] = []
    if counts["satisfied"]:
        parts.append(f"{counts['satisfied']} satisfied")
    if counts["failed"]:
        parts.append(f"{counts['failed']} failed")
    if counts["unverified"]:
        parts.append(f"{counts['unverified']} UNVERIFIED")
    summary = f"acceptance: {', '.join(parts)} - deterministic checks only; UNVERIFIED is not a pass"

    # Criteria are supplied by the model/user. Escape them before placing the
    # verdict into the model-visible delegation ledger.
    def _render_value(value: str) -> str:
        # Keep untrusted criterion/detail text on one ledger line so it cannot
        # spoof a second verdict or inject model-visible ledger structure.
        single_line = value.replace("\r", " ").replace("\n", " ")
        return escape(single_line[:_RENDER_DETAIL_CHARS], quote=False)

    details = [f"{_render_value(check['criterion'])}: {check['status'].upper()} ({_render_value(check['detail'])})" for check in verdict["checks"]]
    rendered = [summary]
    for detail in details:
        candidate = "\n".join([*rendered, detail])
        if len(candidate) > _RENDER_MAX_CHARS:
            rendered.append("... additional acceptance checks omitted from model view")
            break
        rendered.append(detail)
    return "\n".join(rendered)
