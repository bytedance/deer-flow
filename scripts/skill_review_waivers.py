"""Trusted, exact-match waivers for the public-skill CI review gate."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = "deerflow.skill-review-waivers.v1"
MANIFEST_PATH = PurePosixPath(".github/skill-review-waivers.v1.json")
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SAFE_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*\Z")
_REQUIRED_ENTRY_FIELDS = {
    "package",
    "source",
    "rule_id",
    "path",
    "line",
    "evidence",
    "file_sha256",
    "reason",
    "expires_on",
}
_OPTIONAL_ENTRY_FIELDS = {"approved_in"}


class WaiverManifestError(ValueError):
    """Raised when a waiver manifest is missing required trust properties."""


@dataclass(frozen=True)
class SkillReviewWaiver:
    package: str
    source: str
    rule_id: str
    path: str
    line: int
    evidence: str
    file_sha256: str
    reason: str
    expires_on: date
    approved_in: str | None = None

    @property
    def finding_key(self) -> tuple[str, str, str, int, str]:
        return (self.source, self.rule_id, self.path, self.line, self.evidence)


@dataclass(frozen=True)
class WaiverManifest:
    waivers: tuple[SkillReviewWaiver, ...] = ()


EMPTY_MANIFEST = WaiverManifest()


def parse_manifest(payload: bytes | str, *, source: str) -> WaiverManifest:
    """Parse the versioned waiver manifest with strict, fail-closed validation."""
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
        raise WaiverManifestError(f"{source}: invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise WaiverManifestError(f"{source}: manifest root must be an object")
    unknown_root = set(data) - {"schema_version", "waivers"}
    if unknown_root:
        raise WaiverManifestError(f"{source}: unknown root field(s): {', '.join(sorted(unknown_root))}")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise WaiverManifestError(f"{source}: schema_version must be {SCHEMA_VERSION!r}")
    raw_waivers = data.get("waivers")
    if not isinstance(raw_waivers, list):
        raise WaiverManifestError(f"{source}: waivers must be an array")
    if len(raw_waivers) > 256:
        raise WaiverManifestError(f"{source}: waivers must contain at most 256 entries")

    waivers: list[SkillReviewWaiver] = []
    identities: set[tuple[str, str, str, int, str, str]] = set()
    for index, raw in enumerate(raw_waivers):
        entry_source = f"{source}: waivers[{index}]"
        if not isinstance(raw, dict):
            raise WaiverManifestError(f"{entry_source}: entry must be an object")
        fields = set(raw)
        missing = _REQUIRED_ENTRY_FIELDS - fields
        unknown = fields - _REQUIRED_ENTRY_FIELDS - _OPTIONAL_ENTRY_FIELDS
        if missing:
            raise WaiverManifestError(f"{entry_source}: missing field(s): {', '.join(sorted(missing))}")
        if unknown:
            raise WaiverManifestError(f"{entry_source}: unknown field(s): {', '.join(sorted(unknown))}")

        package = _canonical_relative_path(raw["package"], field=f"{entry_source}.package")
        if not package.startswith("skills/public/"):
            raise WaiverManifestError(f"{entry_source}.package: must be below skills/public/")
        path = _canonical_relative_path(raw["path"], field=f"{entry_source}.path")
        source_name = _nonempty_string(raw["source"], field=f"{entry_source}.source")
        rule_id = _nonempty_string(raw["rule_id"], field=f"{entry_source}.rule_id")
        evidence = _nonempty_string(raw["evidence"], field=f"{entry_source}.evidence")
        file_sha256 = _nonempty_string(raw["file_sha256"], field=f"{entry_source}.file_sha256")
        if not _SHA256_RE.fullmatch(file_sha256):
            raise WaiverManifestError(f"{entry_source}.file_sha256: must be sha256 followed by 64 lowercase hex characters")
        reason = _nonempty_string(raw["reason"], field=f"{entry_source}.reason")
        if len(reason) < 20:
            raise WaiverManifestError(f"{entry_source}.reason: must contain at least 20 characters")
        line = raw["line"]
        if isinstance(line, bool) or not isinstance(line, int) or line < 1:
            raise WaiverManifestError(f"{entry_source}.line: must be a positive integer")
        expires_on = _parse_date(raw["expires_on"], field=f"{entry_source}.expires_on")
        approved_in = raw.get("approved_in")
        if approved_in is not None:
            approved_in = _nonempty_string(approved_in, field=f"{entry_source}.approved_in")

        waiver = SkillReviewWaiver(
            package=package,
            source=source_name,
            rule_id=rule_id,
            path=path,
            line=line,
            evidence=evidence,
            file_sha256=file_sha256,
            reason=reason,
            expires_on=expires_on,
            approved_in=approved_in,
        )
        identity = (*waiver.finding_key, waiver.package)
        if identity in identities:
            raise WaiverManifestError(f"{entry_source}: duplicates an earlier waiver")
        identities.add(identity)
        waivers.append(waiver)

    return WaiverManifest(tuple(waivers))


def load_manifest_at_ref(repo_root: Path, ref: str, *, label: str) -> WaiverManifest:
    """Read a manifest from a Git ref; absence means no waivers at that ref."""
    if not _SAFE_REF_RE.fullmatch(ref) or ref.startswith("-") or ".." in ref or ":" in ref:
        raise WaiverManifestError(f"{label}: unsafe Git ref {ref!r}")
    object_name = f"{ref}:{MANIFEST_PATH.as_posix()}"
    result = subprocess.run(
        ["git", "show", object_name],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return EMPTY_MANIFEST
    return parse_manifest(result.stdout, source=f"{label} manifest at {ref}")


def file_sha256(repo_root: Path, waiver: SkillReviewWaiver) -> str | None:
    resolved_repo_root = repo_root.resolve()
    package_candidate = resolved_repo_root / waiver.package
    if package_candidate.is_symlink() or not package_candidate.is_dir():
        return None
    package_root = package_candidate.resolve()
    try:
        package_root.relative_to(resolved_repo_root / "skills" / "public")
    except ValueError:
        return None
    candidate = package_root / waiver.path
    if candidate.is_symlink() or not candidate.is_file():
        return None
    resolved = candidate.resolve()
    try:
        resolved.relative_to(package_root)
    except ValueError:
        return None
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def finding_key(finding: dict[str, Any]) -> tuple[str, str, str, int, str] | None:
    source = finding.get("source")
    rule_id = finding.get("rule_id")
    path = finding.get("path")
    line = finding.get("line")
    evidence = finding.get("evidence")
    if not isinstance(source, str) or not isinstance(rule_id, str) or not isinstance(path, str) or isinstance(line, bool) or not isinstance(line, int) or not isinstance(evidence, str):
        return None
    return (source, rule_id, path, line, evidence)


def matching_waiver(
    finding: dict[str, Any],
    *,
    package: str,
    manifest: WaiverManifest,
    repo_root: Path,
    today: date | None = None,
) -> SkillReviewWaiver | None:
    """Return an active waiver only for an exact error finding and file digest."""
    if finding.get("severity") != "error":
        return None
    key = finding_key(finding)
    if key is None:
        return None
    current_date = today or date.today()
    for waiver in manifest.waivers:
        if waiver.package != package or waiver.finding_key != key:
            continue
        if waiver.expires_on < current_date:
            continue
        if file_sha256(repo_root, waiver) != waiver.file_sha256:
            continue
        return waiver
    return None


def validate_manifest_against_facts(
    manifest: WaiverManifest,
    *,
    facts_by_package: dict[str, dict[str, Any]],
    repo_root: Path,
    today: date | None = None,
) -> list[str]:
    """Reject expired, stale, hash-mismatched, or non-error waiver entries."""
    errors: list[str] = []
    current_date = today or date.today()
    for waiver in manifest.waivers:
        description = f"{waiver.package}/{waiver.path}:{waiver.line} ({waiver.source}/{waiver.rule_id})"
        if waiver.expires_on < current_date:
            errors.append(f"{description}: waiver expired on {waiver.expires_on.isoformat()}")
            continue
        facts = facts_by_package.get(waiver.package)
        if facts is None:
            errors.append(f"{description}: package review facts are unavailable")
            continue
        matches = [finding for finding in facts.get("findings", []) if isinstance(finding, dict) and finding_key(finding) == waiver.finding_key]
        if not matches:
            errors.append(f"{description}: no exact current finding matches this waiver")
            continue
        if len(matches) != 1:
            errors.append(f"{description}: expected one exact current finding, found {len(matches)}")
            continue
        if any(finding.get("severity") != "error" for finding in matches):
            errors.append(f"{description}: waivers may target error findings only; blockers can never be waived")
            continue
        actual_hash = file_sha256(repo_root, waiver)
        if actual_hash != waiver.file_sha256:
            errors.append(f"{description}: file digest changed (expected {waiver.file_sha256}, found {actual_hash or 'unavailable'})")
    return errors


def _canonical_relative_path(value: object, *, field: str) -> str:
    text = _nonempty_string(value, field=field)
    if "\\" in text:
        raise WaiverManifestError(f"{field}: backslashes are not allowed")
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts) or path.as_posix() != text:
        raise WaiverManifestError(f"{field}: must be a canonical relative POSIX path without traversal")
    return text


def _nonempty_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise WaiverManifestError(f"{field}: must be a non-empty string without surrounding whitespace")
    return value


def _parse_date(value: object, *, field: str) -> date:
    text = _nonempty_string(value, field=field)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise WaiverManifestError(f"{field}: must be an ISO 8601 calendar date") from exc
    if parsed.isoformat() != text:
        raise WaiverManifestError(f"{field}: must use YYYY-MM-DD format")
    return parsed
