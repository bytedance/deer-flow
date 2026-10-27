"""Canonical package digest for review snapshots."""

from __future__ import annotations

import hashlib
from typing import Any

from deerflow.skills.review.models import normalize_relative_path


def compute_package_digest(snapshot: dict[str, Any]) -> str:
    """Return a host-path-independent SHA-256 digest for a package snapshot."""
    records: list[bytes] = []
    for file_entry in snapshot.get("files", []):
        path = normalize_relative_path(str(file_entry["path"]))
        kind = str(file_entry.get("kind") or "unknown")
        size = int(file_entry.get("size") or 0)
        content_digest = str(file_entry.get("sha256") or "")
        record = b"\0".join(
            [
                kind.encode("utf-8"),
                path.encode("utf-8"),
                str(size).encode("ascii"),
                content_digest.encode("ascii"),
            ]
        )
        records.append(record)

    h = hashlib.sha256()
    for record in sorted(records):
        h.update(len(record).to_bytes(8, "big"))
        h.update(record)
    return f"sha256:{h.hexdigest()}"
