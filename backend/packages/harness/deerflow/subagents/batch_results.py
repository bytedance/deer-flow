"""Bounded native report projection; never expose arbitrary persisted artifacts."""

import copy
import hashlib
import json
import re
from typing import Any

_ITEM_FIELDS = ("id", "item_key", "position", "status", "attempt", "result_preview", "result_truncated", "error", "stop_reason", "acceptance_criteria", "acceptance_verdict", "started_at", "completed_at", "updated_at")
_SOURCE_ID = re.compile(r"[a-f0-9]{32}-[1-9][0-9]{0,2}\Z")
_SOURCE_FIELDS = ("id", "provider", "dataset_id", "document_id", "chunk_id", "dataset_name", "document_name", "text", "pages", "truncated")
MAX_RESULT_CHARS = 1_000_000  # Native configuration/schema ceiling, not current submission settings.


def _evidence(value: object, report: str) -> dict[str, Any] | None:
    """Never publish arbitrary artifacts or truncate a source under its ID."""
    if not isinstance(value, dict):
        return None
    payload = value.get("knowledge_sources")
    if not isinstance(payload, dict) or type(payload.get("version")) is not int or payload["version"] != 1 or not isinstance(payload.get("sources"), list):
        return None
    omitted = payload.get("omitted_count", 0)
    if type(omitted) is not int or not 0 <= omitted <= MAX_RESULT_CHARS:
        return None
    result: dict[str, Any] = {"version": 1, "sources": [], "omitted_count": omitted}
    seen: set[str] = set()
    used = 0
    for raw in payload["sources"][:100]:
        if not isinstance(raw, dict):
            continue
        source_id = raw.get("id")
        if not isinstance(source_id, str) or not _SOURCE_ID.fullmatch(source_id) or source_id in seen or f"](#knowledge-{source_id})" not in report:
            continue
        if raw.get("provider") != "ragflow" or not all(isinstance(raw.get(key), str) for key in _SOURCE_FIELDS[:8]):
            continue
        if any(not 0 < len(raw[key]) <= 256 for key in ("dataset_id", "document_id", "chunk_id")) or any(not raw[key].strip() or len(raw[key]) > 512 for key in ("dataset_name", "document_name")):
            continue
        if not raw["text"].strip() or len(raw["text"]) > 200_000:
            continue
        pages = raw.get("pages")
        if not isinstance(pages, list) or len(pages) > 100 or any(type(page) is not int or not 1 <= page <= 1_000_000 for page in pages) or type(raw.get("truncated")) is not bool:
            continue
        record = {key: copy.deepcopy(raw[key]) for key in _SOURCE_FIELDS}
        cost = len(json.dumps(record, ensure_ascii=False))
        if used + cost > MAX_RESULT_CHARS:
            return None  # Oversized historical artifacts are unsupported, not partly rewritten evidence.
        seen.add(source_id)
        used += cost
        result["sources"].append(record)
    return result


def project_batch_result(row: dict[str, Any]) -> dict[str, Any]:
    result = row.get("result")
    result = result if isinstance(result, str) else None
    projection = copy.deepcopy({key: row.get(key) for key in _ITEM_FIELDS})
    projection["result"] = result[:MAX_RESULT_CHARS] if result is not None else None
    projection["result_truncated"] = row.get("result_truncated") is True or (result is not None and len(result) > MAX_RESULT_CHARS)
    projection["evidence"] = _evidence(row.get("result_artifact"), projection["result"] or "") if row.get("status") == "succeeded" else None
    projection["revision"] = hashlib.sha256(json.dumps(projection, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    return projection
