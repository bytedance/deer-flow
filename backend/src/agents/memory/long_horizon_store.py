"""Long-horizon memory with dense embedding, topic memory, and project memory.

Compared to the initial sparse-token version, this module now provides:
- Dense hash-based embeddings (dependency-light, deterministic)
- Topic-level aggregated memory (cross-turn)
- Project-level aggregated memory (cross-thread)
- Backward-compatible migration for existing v1 long-horizon stores
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.config.memory_config import get_memory_config
from src.config.paths import get_paths

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]{2,}|[\u4e00-\u9fff]{2,}")
_PROJECT_ID_RE = re.compile(r"(?:project[_\s-]?id|project)\s*[:=]?\s*([A-Za-z0-9][A-Za-z0-9_.-]{1,63})", re.IGNORECASE)
_COMPILED_PATH_PROJECT_RE = re.compile(r"/research-writing/compiled/([A-Za-z0-9][A-Za-z0-9_.-]{1,63})-[A-Za-z0-9_.-]+\.(?:md|json)\b", re.IGNORECASE)
_STOPWORDS = {
    "the",
    "and",
    "for",
    "that",
    "with",
    "this",
    "from",
    "have",
    "will",
    "into",
    "your",
    "you",
    "are",
    "was",
    "were",
    "has",
    "had",
    "but",
    "not",
    "can",
    "all",
    "use",
    "using",
    "about",
    "please",
    "我们",
    "你们",
    "他们",
    "这个",
    "那个",
    "以及",
    "还有",
    "需要",
    "可以",
    "进行",
    "一个",
    "一些",
    "对于",
    "因为",
}

_store_lock = threading.Lock()


def _resolve_storage_path() -> Path:
    cfg = get_memory_config()
    if cfg.long_horizon_storage_path:
        path = Path(cfg.long_horizon_storage_path)
        return path if path.is_absolute() else get_paths().base_dir / path
    return get_paths().base_dir / ".deer-flow" / "memory_long_horizon.json"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _tokenize(text: str) -> list[str]:
    tokens = [t.lower() for t in _TOKEN_RE.findall(text or "")]
    return [t for t in tokens if t not in _STOPWORDS]


def _to_sparse_vector(text: str) -> dict[str, float]:
    counts = Counter(_tokenize(text))
    if not counts:
        return {}
    norm = math.sqrt(sum(v * v for v in counts.values()))
    if norm <= 0:
        return {}
    return {k: v / norm for k, v in counts.items()}


def _stable_hash_int(value: str) -> int:
    digest = hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=False)


def _normalize_dense_vector(vector: list[float], dim: int) -> list[float]:
    if not vector:
        return []
    if len(vector) != dim:
        return []
    norm = math.sqrt(sum(float(v) * float(v) for v in vector))
    if norm <= 0:
        return []
    return [float(v) / norm for v in vector]


def _to_dense_embedding(text: str, *, dim: int) -> list[float]:
    tokens = _tokenize(text)
    if not tokens:
        return []

    vec = [0.0] * dim
    for token in tokens:
        h = _stable_hash_int(token)
        idx = h % dim
        sign = 1.0 if ((h >> 63) & 1) == 0 else -1.0
        vec[idx] += sign

    # Add lightweight bi-gram signal for better semantic stability.
    for left, right in zip(tokens, tokens[1:]):
        bigram = f"{left}:{right}"
        h = _stable_hash_int(bigram)
        idx = h % dim
        sign = 1.0 if ((h >> 63) & 1) == 0 else -1.0
        vec[idx] += 1.35 * sign

    normalized = _normalize_dense_vector(vec, dim)
    if not normalized:
        return []
    return [round(v, 6) for v in normalized]


def _cosine_similarity_dense(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dim = min(len(a), len(b))
    if dim <= 0:
        return 0.0
    dot = 0.0
    for i in range(dim):
        dot += float(a[i]) * float(b[i])
    return max(0.0, min(1.0, dot))


def _cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    return max(0.0, min(1.0, dot))


def _empty_store() -> dict[str, Any]:
    return {
        "version": "2.1",
        "updated_at": _now_iso(),
        "entries": [],
        "topic_memory": {},
        "project_memory": {},
        "hypothesis_history": [],
    }


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


_HYPOTHESIS_STATUSES = {"supported", "failed", "inconclusive", "reopened"}


def _normalize_hypothesis_status(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in _HYPOTHESIS_STATUSES:
        return normalized
    return "inconclusive"


def _extract_topics(text: str, *, max_topics: int = 6) -> list[str]:
    counts = Counter(_tokenize(text))
    topics: list[str] = []
    for token, _count in counts.most_common():
        if token.isdigit():
            continue
        if len(token) <= 2:
            continue
        topics.append(token)
        if len(topics) >= max_topics:
            break
    return topics


def infer_project_ids_from_text(text: str, *, max_projects: int = 4) -> list[str]:
    hits: list[str] = []
    for match in _PROJECT_ID_RE.findall(text or ""):
        normalized = str(match).strip()
        if not normalized:
            continue
        if normalized not in hits:
            hits.append(normalized)
        if len(hits) >= max_projects:
            return hits
    for match in _COMPILED_PATH_PROJECT_RE.findall(text or ""):
        normalized = str(match).strip()
        if not normalized:
            continue
        if normalized not in hits:
            hits.append(normalized)
        if len(hits) >= max_projects:
            return hits
    return hits


def _sparse_to_dense(sparse: dict[str, float], *, dim: int) -> list[float]:
    if not sparse:
        return []
    vec = [0.0] * dim
    for token, weight in sparse.items():
        h = _stable_hash_int(str(token))
        idx = h % dim
        sign = 1.0 if ((h >> 63) & 1) == 0 else -1.0
        vec[idx] += sign * _coerce_float(weight, 0.0)
    normalized = _normalize_dense_vector(vec, dim)
    if not normalized:
        return []
    return [round(v, 6) for v in normalized]


def _ensure_entry_embedding(item: dict[str, Any], *, dim: int) -> list[float]:
    raw = item.get("embedding")
    if isinstance(raw, list):
        vector = []
        for value in raw:
            try:
                vector.append(float(value))
            except Exception:
                return []
        normalized = _normalize_dense_vector(vector, dim)
        if normalized:
            return [round(v, 6) for v in normalized]
    sparse = item.get("vector")
    if isinstance(sparse, dict):
        return _sparse_to_dense({str(k): _coerce_float(v, 0.0) for k, v in sparse.items()}, dim=dim)
    summary = str(item.get("summary") or "")
    return _to_dense_embedding(summary, dim=dim)


def _normalize_entries(payload: dict[str, Any], *, dim: int) -> list[dict[str, Any]]:
    raw_entries = payload.get("entries", [])
    if not isinstance(raw_entries, list):
        return []

    entries: list[dict[str, Any]] = []
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        summary = str(item.get("summary") or "").strip()
        if not summary:
            continue
        embedding = _ensure_entry_embedding(item, dim=dim)
        if not embedding:
            continue

        thread_id = str(item.get("thread_id") or "").strip()
        topics_raw = item.get("topics")
        topics: list[str] = []
        if isinstance(topics_raw, list):
            topics = [str(topic).strip().lower() for topic in topics_raw if str(topic).strip()]
        if not topics:
            topics = _extract_topics(summary)

        project_ids_raw = item.get("project_ids")
        project_ids: list[str] = []
        if isinstance(project_ids_raw, list):
            project_ids = [str(project).strip() for project in project_ids_raw if str(project).strip()]
        if not project_ids:
            single_project = str(item.get("project_id") or "").strip()
            if single_project:
                project_ids = [single_project]
        if not project_ids:
            project_ids = infer_project_ids_from_text(summary)

        entry = {
            "id": str(item.get("id") or f"lh_{uuid.uuid4().hex[:12]}"),
            "thread_id": thread_id,
            "created_at": str(item.get("created_at") or _now_iso()),
            "summary": summary,
            "embedding": embedding,
            "topics": topics,
            "project_ids": project_ids,
            "project_id": project_ids[0] if project_ids else None,
            "source": item.get("source") if isinstance(item.get("source"), dict) else {},
        }
        entries.append(entry)
    return entries


def _normalize_hypothesis_history(payload: dict[str, Any], *, dim: int) -> list[dict[str, Any]]:
    raw_items = payload.get("hypothesis_history", [])
    if not isinstance(raw_items, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        project_id = str(item.get("project_id") or "").strip()
        statement = str(item.get("statement") or "").strip()
        if not project_id or not statement:
            continue

        hypothesis_id = str(item.get("hypothesis_id") or f"H{len(normalized) + 1}").strip()
        if not hypothesis_id:
            hypothesis_id = f"H{len(normalized) + 1}"
        status = _normalize_hypothesis_status(item.get("validation_status"))
        rationale = str(item.get("rationale") or "").strip()
        section_id = str(item.get("section_id") or "").strip() or None
        thread_id = str(item.get("thread_id") or "").strip()
        created_at = str(item.get("created_at") or _now_iso())
        summary = str(item.get("summary") or "").strip()
        if not summary:
            summary = f"Hypothesis {hypothesis_id} for project {project_id} was {status}: {statement}"
            if rationale:
                summary = f"{summary} Rationale: {rationale}"

        embedding = _ensure_entry_embedding({"summary": summary, "embedding": item.get("embedding")}, dim=dim)
        if not embedding:
            continue

        topics_raw = item.get("topics")
        topics: list[str] = []
        if isinstance(topics_raw, list):
            topics = [str(topic).strip().lower() for topic in topics_raw if str(topic).strip()]
        if not topics:
            topics = _extract_topics(f"{statement} {rationale}")

        evidence_ids = [str(v).strip() for v in item.get("evidence_ids", []) if str(v).strip()] if isinstance(item.get("evidence_ids"), list) else []
        citation_ids = [str(v).strip() for v in item.get("citation_ids", []) if str(v).strip()] if isinstance(item.get("citation_ids"), list) else []

        normalized.append(
            {
                "id": str(item.get("id") or f"lh_hyp_{uuid.uuid4().hex[:12]}"),
                "thread_id": thread_id,
                "project_id": project_id,
                "project_ids": [project_id],
                "section_id": section_id,
                "hypothesis_id": hypothesis_id,
                "statement": statement,
                "validation_status": status,
                "rationale": rationale,
                "summary": summary,
                "embedding": embedding,
                "topics": topics,
                "evidence_ids": evidence_ids,
                "citation_ids": citation_ids,
                "created_at": created_at,
                "source": item.get("source") if isinstance(item.get("source"), dict) else {},
            }
        )
    return normalized


def _rebuild_topic_memory(entries: list[dict[str, Any]], *, dim: int) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        for topic in entry.get("topics", []):
            if not isinstance(topic, str) or not topic:
                continue
            grouped.setdefault(topic, []).append(entry)

    out: dict[str, dict[str, Any]] = {}
    for topic, items in grouped.items():
        items_sorted = sorted(items, key=lambda x: str(x.get("created_at") or ""), reverse=True)
        thread_ids = sorted({str(item.get("thread_id") or "") for item in items_sorted if str(item.get("thread_id") or "")})
        project_ids = sorted(
            {
                project_id
                for item in items_sorted
                for project_id in item.get("project_ids", [])
                if isinstance(project_id, str) and project_id
            }
        )
        summary_parts = [str(item.get("summary") or "").strip() for item in items_sorted[:3]]
        summary = " | ".join(part for part in summary_parts if part)
        if not summary:
            continue
        out[topic] = {
            "topic": topic,
            "updated_at": str(items_sorted[0].get("created_at") or _now_iso()),
            "summary": summary,
            "embedding": _to_dense_embedding(summary, dim=dim),
            "thread_ids": thread_ids,
            "project_ids": project_ids,
            "entry_ids": [str(item.get("id") or "") for item in items_sorted[:8]],
            "count": len(items_sorted),
        }
    return out


def _rebuild_project_memory(entries: list[dict[str, Any]], *, dim: int) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        for project_id in entry.get("project_ids", []):
            if not isinstance(project_id, str) or not project_id:
                continue
            grouped.setdefault(project_id, []).append(entry)

    out: dict[str, dict[str, Any]] = {}
    for project_id, items in grouped.items():
        items_sorted = sorted(items, key=lambda x: str(x.get("created_at") or ""), reverse=True)
        thread_ids = sorted({str(item.get("thread_id") or "") for item in items_sorted if str(item.get("thread_id") or "")})
        summary_parts = [str(item.get("summary") or "").strip() for item in items_sorted[:3]]
        summary = " | ".join(part for part in summary_parts if part)
        if not summary:
            continue
        out[project_id] = {
            "project_id": project_id,
            "updated_at": str(items_sorted[0].get("created_at") or _now_iso()),
            "summary": summary,
            "embedding": _to_dense_embedding(summary, dim=dim),
            "thread_ids": thread_ids,
            "entry_ids": [str(item.get("id") or "") for item in items_sorted[:10]],
            "count": len(items_sorted),
        }
    return out


def _ensure_store_payload(payload: dict[str, Any], *, dim: int) -> dict[str, Any]:
    entries = _normalize_entries(payload, dim=dim)
    hypothesis_history = _normalize_hypothesis_history(payload, dim=dim)
    normalized = {
        "version": "2.1",
        "updated_at": str(payload.get("updated_at") or _now_iso()),
        "entries": entries,
        "topic_memory": _rebuild_topic_memory(entries, dim=dim),
        "project_memory": _rebuild_project_memory(entries, dim=dim),
        "hypothesis_history": hypothesis_history,
    }
    return normalized


def _load_store() -> dict[str, Any]:
    path = _resolve_storage_path()
    if not path.exists():
        return _empty_store()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return _empty_store()
        cfg = get_memory_config()
        dim = int(getattr(cfg, "long_horizon_embedding_dim", 256))
        return _ensure_store_payload(payload, dim=dim)
    except Exception:
        return _empty_store()


def _save_store(payload: dict[str, Any]) -> None:
    path = _resolve_storage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["updated_at"] = _now_iso()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _extract_turn_messages(messages: list[Any], *, max_chars: int) -> tuple[str, str]:
    humans: list[str] = []
    ais: list[str] = []
    for msg in messages:
        msg_type = getattr(msg, "type", None)
        content = getattr(msg, "content", "")
        text = ""
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = " ".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
        else:
            text = str(content)
        text = text.strip()
        if not text:
            continue
        if msg_type == "human":
            humans.append(text)
        elif msg_type == "ai" and not getattr(msg, "tool_calls", None):
            ais.append(text)
    human_text = "\n".join(humans)[-max_chars:]
    ai_text = "\n".join(ais)[-max_chars:]
    return human_text, ai_text


def update_long_horizon_memory(thread_id: str, messages: list[Any]) -> None:
    """Append/update one long-horizon summary entry for a thread."""
    cfg = get_memory_config()
    if not cfg.long_horizon_enabled:
        return

    human_text, ai_text = _extract_turn_messages(messages, max_chars=cfg.long_horizon_summary_chars)
    if not human_text and not ai_text:
        return

    summary = f"User intent: {human_text}\nAssistant outcome: {ai_text}".strip()
    dim = int(getattr(cfg, "long_horizon_embedding_dim", 256))
    embedding = _to_dense_embedding(summary, dim=dim)
    if not embedding:
        return
    topics = _extract_topics(summary)
    project_ids = infer_project_ids_from_text(summary)

    entry = {
        "id": f"lh_{uuid.uuid4().hex[:12]}",
        "thread_id": thread_id,
        "created_at": _now_iso(),
        "summary": summary,
        "embedding": embedding,
        "topics": topics,
        "project_ids": project_ids,
        "project_id": project_ids[0] if project_ids else None,
        "source": {
            "human_excerpt": human_text,
            "assistant_excerpt": ai_text,
        },
    }

    with _store_lock:
        payload = _load_store()
        entries = payload.get("entries", [])
        if not isinstance(entries, list):
            entries = []
        hypothesis_history = payload.get("hypothesis_history", [])
        if not isinstance(hypothesis_history, list):
            hypothesis_history = []
        entries.append(entry)
        max_entries = max(50, int(cfg.long_horizon_max_entries))
        if len(entries) > max_entries:
            entries = entries[-max_entries:]
        payload["entries"] = _normalize_entries({"entries": entries}, dim=dim)
        payload["hypothesis_history"] = _normalize_hypothesis_history({"hypothesis_history": hypothesis_history}, dim=dim)[
            -max(50, int(getattr(cfg, "long_horizon_hypothesis_max_entries", 400))) :
        ]
        if getattr(cfg, "long_horizon_topic_memory_enabled", True):
            payload["topic_memory"] = _rebuild_topic_memory(payload["entries"], dim=dim)
        else:
            payload["topic_memory"] = {}
        if getattr(cfg, "long_horizon_project_memory_enabled", True):
            payload["project_memory"] = _rebuild_project_memory(payload["entries"], dim=dim)
        else:
            payload["project_memory"] = {}
        payload["version"] = "2.1"
        _save_store(payload)


def record_hypothesis_validation_result(
    *,
    thread_id: str,
    project_id: str,
    hypothesis_id: str,
    statement: str,
    validation_status: str,
    rationale: str = "",
    section_id: str | None = None,
    evidence_ids: list[str] | None = None,
    citation_ids: list[str] | None = None,
    source: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Persist one hypothesis validation outcome into long-horizon memory."""
    cfg = get_memory_config()
    if not cfg.long_horizon_enabled or not getattr(cfg, "long_horizon_hypothesis_memory_enabled", True):
        return None

    project = str(project_id or "").strip()
    hypothesis = str(hypothesis_id or "").strip()
    statement_text = str(statement or "").strip()
    if not project or not statement_text:
        return None
    if not hypothesis:
        hypothesis = "unknown"

    status = _normalize_hypothesis_status(validation_status)
    rationale_text = str(rationale or "").strip()
    section = str(section_id or "").strip() or None
    summary = f"Hypothesis {hypothesis} for project {project} was {status}: {statement_text}"
    if rationale_text:
        summary = f"{summary} Rationale: {rationale_text}"

    dim = int(getattr(cfg, "long_horizon_embedding_dim", 256))
    embedding = _to_dense_embedding(summary, dim=dim)
    if not embedding:
        return None

    entry = {
        "id": f"lh_hyp_{uuid.uuid4().hex[:12]}",
        "thread_id": thread_id,
        "project_id": project,
        "project_ids": [project],
        "section_id": section,
        "hypothesis_id": hypothesis,
        "statement": statement_text,
        "validation_status": status,
        "rationale": rationale_text,
        "summary": summary,
        "embedding": embedding,
        "topics": _extract_topics(f"{statement_text} {rationale_text}"),
        "evidence_ids": [str(v).strip() for v in (evidence_ids or []) if str(v).strip()],
        "citation_ids": [str(v).strip() for v in (citation_ids or []) if str(v).strip()],
        "created_at": _now_iso(),
        "source": source if isinstance(source, dict) else {},
    }

    with _store_lock:
        payload = _load_store()
        history = payload.get("hypothesis_history", [])
        if not isinstance(history, list):
            history = []
        history.append(entry)
        max_history = max(50, int(getattr(cfg, "long_horizon_hypothesis_max_entries", 400)))
        if len(history) > max_history:
            history = history[-max_history:]
        payload["hypothesis_history"] = _normalize_hypothesis_history({"hypothesis_history": history}, dim=dim)
        payload["version"] = "2.1"
        _save_store(payload)
    return entry


def _build_topic_candidates(
    *,
    query_embedding: list[float],
    query_topics: list[str],
    payload: dict[str, Any],
    threshold: float,
    top_k: int,
) -> list[dict[str, Any]]:
    topic_memory = payload.get("topic_memory")
    if not isinstance(topic_memory, dict):
        return []
    candidates: list[dict[str, Any]] = []
    query_topic_set = set(query_topics)
    for topic, raw in topic_memory.items():
        if not isinstance(raw, dict):
            continue
        embedding_raw = raw.get("embedding")
        if not isinstance(embedding_raw, list):
            continue
        embedding = [float(v) for v in embedding_raw if isinstance(v, (int, float))]
        if not embedding:
            continue
        similarity = _cosine_similarity_dense(query_embedding, embedding)
        overlap = 1.0 if str(topic) in query_topic_set else 0.0
        score = max(0.0, min(1.0, similarity * 0.86 + overlap * 0.14))
        if score < threshold * 0.8:
            continue
        summary = str(raw.get("summary") or "").strip()
        if not summary:
            continue
        candidates.append(
            {
                "id": f"topic:{topic}",
                "thread_id": ",".join(str(t) for t in raw.get("thread_ids", []) if isinstance(t, str)),
                "created_at": str(raw.get("updated_at") or ""),
                "summary": summary,
                "score": score,
                "memory_kind": "topic",
                "topics": [str(topic)],
                "project_ids": [str(v) for v in raw.get("project_ids", []) if isinstance(v, str)],
            }
        )
    candidates.sort(key=lambda x: (x["score"], x["created_at"]), reverse=True)
    if top_k <= 0:
        return []
    return candidates[:top_k]


def _build_project_candidates(
    *,
    query_embedding: list[float],
    query_project_ids: list[str],
    payload: dict[str, Any],
    threshold: float,
    top_k: int,
) -> list[dict[str, Any]]:
    project_memory = payload.get("project_memory")
    if not isinstance(project_memory, dict):
        return []
    query_project_set = set(query_project_ids)
    candidates: list[dict[str, Any]] = []
    for project_id, raw in project_memory.items():
        if not isinstance(raw, dict):
            continue
        embedding_raw = raw.get("embedding")
        if not isinstance(embedding_raw, list):
            continue
        embedding = [float(v) for v in embedding_raw if isinstance(v, (int, float))]
        if not embedding:
            continue
        similarity = _cosine_similarity_dense(query_embedding, embedding)
        overlap = 1.0 if str(project_id) in query_project_set else 0.0
        score = max(0.0, min(1.0, similarity * 0.82 + overlap * 0.18))
        if score < threshold * 0.85:
            continue
        summary = str(raw.get("summary") or "").strip()
        if not summary:
            continue
        candidates.append(
            {
                "id": f"project:{project_id}",
                "thread_id": ",".join(str(t) for t in raw.get("thread_ids", []) if isinstance(t, str)),
                "created_at": str(raw.get("updated_at") or ""),
                "summary": summary,
                "score": score,
                "memory_kind": "project",
                "topics": [],
                "project_ids": [str(project_id)],
            }
        )
    candidates.sort(key=lambda x: (x["score"], x["created_at"]), reverse=True)
    if top_k <= 0:
        return []
    return candidates[:top_k]


def _build_hypothesis_candidates(
    *,
    query_embedding: list[float],
    query_topics: list[str],
    query_project_ids: list[str],
    payload: dict[str, Any],
    threshold: float,
    top_k: int,
    failure_boost: float,
) -> list[dict[str, Any]]:
    history = payload.get("hypothesis_history")
    if not isinstance(history, list):
        return []
    query_project_set = set(query_project_ids)
    query_topic_set = set(query_topics)
    candidates: list[dict[str, Any]] = []
    for raw in history:
        if not isinstance(raw, dict):
            continue
        embedding_raw = raw.get("embedding")
        if not isinstance(embedding_raw, list):
            continue
        embedding = [float(v) for v in embedding_raw if isinstance(v, (int, float))]
        if not embedding:
            continue
        summary = str(raw.get("summary") or "").strip()
        if not summary:
            continue
        similarity = _cosine_similarity_dense(query_embedding, embedding)
        project_id = str(raw.get("project_id") or "").strip()
        overlap = 1.0 if project_id and project_id in query_project_set else 0.0
        item_topics = [str(topic).strip().lower() for topic in raw.get("topics", []) if str(topic).strip()]
        topic_overlap = len(query_topic_set.intersection(set(item_topics))) if query_topic_set and item_topics else 0
        status = _normalize_hypothesis_status(raw.get("validation_status"))
        status_bonus = failure_boost if status in {"failed", "reopened"} else 0.0
        score = max(0.0, min(1.0, similarity * 0.8 + overlap * 0.14 + min(0.06, topic_overlap * 0.03) + status_bonus))
        if score < threshold * 0.8:
            continue
        candidates.append(
            {
                "id": f"hypothesis:{raw.get('id')}",
                "thread_id": str(raw.get("thread_id") or ""),
                "created_at": str(raw.get("created_at") or ""),
                "summary": summary,
                "score": score,
                "memory_kind": f"hypothesis_{status}",
                "topics": item_topics,
                "project_ids": [project_id] if project_id else [],
                "project_id": project_id or None,
                "hypothesis_id": str(raw.get("hypothesis_id") or ""),
                "validation_status": status,
                "statement": str(raw.get("statement") or ""),
                "section_id": str(raw.get("section_id") or "") or None,
            }
        )
    candidates.sort(key=lambda x: (x["score"], x["created_at"]), reverse=True)
    if top_k <= 0:
        return []
    return candidates[:top_k]


def query_long_horizon_memory(
    query: str,
    *,
    thread_id: str | None = None,
    top_k: int | None = None,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve most relevant long-horizon summaries for the query."""
    cfg = get_memory_config()
    if not cfg.long_horizon_enabled:
        return []
    dim = int(getattr(cfg, "long_horizon_embedding_dim", 256))
    qvec = _to_dense_embedding(query, dim=dim)
    if not qvec:
        return []
    query_topics = _extract_topics(query)
    query_project_ids = []
    if project_id:
        query_project_ids.append(project_id)
    query_project_ids.extend(infer_project_ids_from_text(query))
    dedup_project_ids: list[str] = []
    for value in query_project_ids:
        normalized = str(value).strip()
        if normalized and normalized not in dedup_project_ids:
            dedup_project_ids.append(normalized)
    query_project_ids = dedup_project_ids

    with _store_lock:
        payload = _load_store()
    entries = payload.get("entries", [])
    if not isinstance(entries, list):
        return []

    candidates = []
    threshold = float(cfg.long_horizon_min_similarity)
    allow_cross_thread = bool(getattr(cfg, "long_horizon_cross_thread_enabled", True))
    current_thread_boost = float(getattr(cfg, "long_horizon_current_thread_boost", 0.08))
    project_boost = float(getattr(cfg, "long_horizon_project_boost", 0.12))
    topic_overlap_boost = float(getattr(cfg, "long_horizon_topic_overlap_boost", 0.03))
    query_topics_set = set(query_topics)
    query_project_set = set(query_project_ids)

    for item in entries:
        if not isinstance(item, dict):
            continue
        item_thread_id = str(item.get("thread_id") or "")
        if thread_id and (not allow_cross_thread) and item_thread_id != thread_id:
            continue
        vec = item.get("embedding")
        if not isinstance(vec, list):
            continue
        item_vec = [float(v) for v in vec if isinstance(v, (int, float))]
        if not item_vec:
            continue
        score = _cosine_similarity_dense(qvec, item_vec)
        if thread_id and item_thread_id == thread_id:
            score += current_thread_boost

        item_projects = [str(p).strip() for p in item.get("project_ids", []) if str(p).strip()]
        if not item_projects:
            single_project = str(item.get("project_id") or "").strip()
            if single_project:
                item_projects = [single_project]
        if query_project_set and item_projects and query_project_set.intersection(set(item_projects)):
            score += project_boost

        item_topics = [str(topic).strip().lower() for topic in item.get("topics", []) if str(topic).strip()]
        if query_topics_set and item_topics:
            overlap_count = len(query_topics_set.intersection(set(item_topics)))
            if overlap_count > 0:
                score += topic_overlap_boost * overlap_count

        score = max(0.0, min(1.0, score))
        if score < threshold:
            continue
        candidates.append(
            {
                "id": str(item.get("id") or ""),
                "thread_id": item_thread_id,
                "created_at": str(item.get("created_at") or ""),
                "summary": str(item.get("summary") or ""),
                "score": score,
                "memory_kind": "entry",
                "topics": item_topics,
                "project_ids": item_projects,
            }
        )

    if getattr(cfg, "long_horizon_topic_memory_enabled", True):
        candidates.extend(
            _build_topic_candidates(
                query_embedding=qvec,
                query_topics=query_topics,
                payload=payload,
                threshold=threshold,
                top_k=int(getattr(cfg, "long_horizon_topic_top_k", 2)),
            )
        )
    if getattr(cfg, "long_horizon_project_memory_enabled", True):
        candidates.extend(
            _build_project_candidates(
                query_embedding=qvec,
                query_project_ids=query_project_ids,
                payload=payload,
                threshold=threshold,
                top_k=int(getattr(cfg, "long_horizon_project_top_k", 2)),
            )
        )
    if getattr(cfg, "long_horizon_hypothesis_memory_enabled", True):
        candidates.extend(
            _build_hypothesis_candidates(
                query_embedding=qvec,
                query_topics=query_topics,
                query_project_ids=query_project_ids,
                payload=payload,
                threshold=threshold,
                top_k=int(getattr(cfg, "long_horizon_hypothesis_top_k", 2)),
                failure_boost=float(getattr(cfg, "long_horizon_hypothesis_failure_boost", 0.08)),
            )
        )

    dedup: dict[str, dict[str, Any]] = {}
    for item in candidates:
        item_id = str(item.get("id") or "")
        if not item_id:
            continue
        existing = dedup.get(item_id)
        if existing is None or float(item.get("score", 0.0)) > float(existing.get("score", 0.0)):
            dedup[item_id] = item

    k = top_k if top_k is not None else int(cfg.long_horizon_top_k)
    ranked = list(dedup.values())
    ranked.sort(key=lambda x: (float(x.get("score", 0.0)), str(x.get("created_at") or "")), reverse=True)
    return ranked[: max(1, k)]


def query_hypothesis_validation_memory(
    query: str,
    *,
    thread_id: str | None = None,
    project_id: str | None = None,
    top_k: int = 3,
    include_statuses: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Query only hypothesis-validation trajectories from long-horizon memory."""
    requested_statuses = {
        _normalize_hypothesis_status(item)
        for item in (include_statuses or ["failed", "reopened", "inconclusive", "supported"])
        if str(item).strip()
    }
    hits = query_long_horizon_memory(
        query,
        thread_id=thread_id,
        top_k=max(top_k * 3, top_k + 4),
        project_id=project_id,
    )
    filtered = []
    for item in hits:
        kind = str(item.get("memory_kind") or "")
        if not kind.startswith("hypothesis_"):
            continue
        status = _normalize_hypothesis_status(item.get("validation_status") or kind.replace("hypothesis_", ""))
        if requested_statuses and status not in requested_statuses:
            continue
        normalized = {**item, "validation_status": status}
        filtered.append(normalized)
    filtered.sort(key=lambda x: (float(x.get("score", 0.0)), str(x.get("created_at") or "")), reverse=True)
    return filtered[: max(1, top_k)]


def format_long_horizon_injection(entries: list[dict[str, Any]]) -> str:
    """Format retrieved entries for prompt injection."""
    if not entries:
        return ""
    lines = ["<long_horizon_memory>"]
    for item in entries:
        kind = str(item.get("memory_kind") or "entry")
        thread_id = str(item.get("thread_id") or "")
        project_ids = [str(v) for v in item.get("project_ids", []) if str(v)]
        label_parts = [kind]
        if thread_id:
            label_parts.append(f"thread={thread_id}")
        if project_ids:
            label_parts.append(f"project={project_ids[0]}")
        label = ",".join(label_parts)
        lines.append(f"- [{label}] ({float(item.get('score', 0.0)):.3f}) {item.get('summary', '')}")
    lines.append("</long_horizon_memory>")
    text = "\n".join(lines)
    cfg = get_memory_config()
    return text[: max(200, int(cfg.long_horizon_injection_max_chars))]

