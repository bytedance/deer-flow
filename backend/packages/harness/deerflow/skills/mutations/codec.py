"""Detached database encodings. Blob storage never enters skill loading roots."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime

from deerflow_extension_api.skill_mutations import AssetRevision, HostCheckResult, Operation, Proposal

from deerflow.skills.mutations.assets import MAX_FILES, MAX_PACKAGE_BYTES, PackageFile, PackageSnapshot
from deerflow.skills.mutations.validation import MAX_MAIN_BYTES


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def encode_package(package: PackageSnapshot) -> bytes:
    return json.dumps([(item.path, base64.b64encode(item.content).decode("ascii"), item.executable) for item in package.files], separators=(",", ":")).encode()


def decode_package(blob: bytes) -> PackageSnapshot:
    try:
        if not isinstance(blob, bytes) or len(blob) > 24 * 1024 * 1024:
            raise ValueError
        rows = json.loads(blob)
        if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_FILES:
            raise ValueError
        files, total, previous = [], 0, ""
        for item in rows:
            if not isinstance(item, list) or len(item) != 3:
                raise ValueError
            path, content, executable = item
            if not isinstance(path, str) or not path or len(path.encode()) > 1024 or path <= previous or "\\" in path or any(ord(c) < 32 for c in path) or any(part in {"", ".", ".."} for part in path.split("/")):
                raise ValueError
            if type(executable) is not bool or not isinstance(content, str):
                raise ValueError
            data = base64.b64decode(content, validate=True)
            total += len(data)
            if total > MAX_PACKAGE_BYTES or (path == "SKILL.md" and len(data) > MAX_MAIN_BYTES):
                raise ValueError
            files.append(PackageFile(path, data, executable))
            previous = path
        result = PackageSnapshot(tuple(files))
        result.main_content
        return result
    except (ValueError, TypeError, StopIteration, UnicodeError, RecursionError) as exc:
        raise ValueError("BLOB_INTEGRITY_ERROR") from exc


def operation_packages(row):
    before, after = decode_package(row.before_blob), decode_package(row.after_blob)
    if before.digest != row.before_revision.get("content_digest") or after.digest != row.after_revision.get("content_digest") or before.digest == after.digest:
        raise ValueError("BLOB_INTEGRITY_ERROR")
    return before, after


def timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, UTC).isoformat()


def proposal_view(row) -> Proposal:
    return Proposal(
        row.proposal_id, row.owner_id, row.target_ref, row.name, AssetRevision(**row.base_revision), row.candidate_hash, row.state, timestamp(row.expires_at), tuple(source["snapshot_ref"] for source in row.sources), row.operation_id
    )


def operation_view(row) -> Operation:
    return Operation(
        row.operation_id,
        row.owner_id,
        row.name,
        row.publication,
        row.views,
        AssetRevision(**row.before_revision),
        AssetRevision(**row.after_revision),
        row.generation,
        row.proposal_id,
        row.reverts_operation_id,
        row.error_code,
        row.superseded_by_generation,
    )


def check_view(row) -> HostCheckResult:
    result = row.check_result
    return HostCheckResult(row.proposal_id, result["decision"], row.candidate_hash, AssetRevision(**row.base_revision), result["policy_version"], timestamp(result["expires_at"]), result["reason_code"])
