"""Record/replay support for the no-cloud RAG evaluation CI (RFC v3 §8.2).

The external model outputs (embeddings, rerank scores, image captions) are
produced once during material preparation against the real services and saved
keyed by a normalized hash of their semantic input; the CI replays them while
everything else (parse, chunk, index write, recall, RRF, rerank application,
scope checks, metrics) runs for real.

Shared by the recorder (``scripts/rag_eval_record.py``), the replay service
(``scripts/rag_eval_replay_server.py``) and their tests, so record and replay
agree on the key derivation by construction — a cache miss is a loud error,
never a silent empty answer.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

#: Provider paths whose POST bodies we record/replay, by call kind. The set
#: covers the dialect the fixed combination uses (DashScope) plus the
#: OpenAI-compatible aliases, so a dialect swap keeps working off one fixture.
_EMBED_PATH_MARKERS = ("/services/embeddings/text-embedding", "/v1/embeddings")
_RERANK_PATH_MARKERS = ("/reranks", "/rerank")
_CAPTION_PATH_MARKERS = ("/chat/completions", "/v1/messages")

_DATA_URL_RE = re.compile(r"^data:([^;]+);base64,(.+)$", re.DOTALL)


class UnsupportedReplayRequest(ValueError):
    """The request is not one of the recorded call kinds (never record these)."""


class ReplayMiss(KeyError):
    """The recording holds no entry for the request — the fixture is stale."""


def _stable_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _embed_key(model: str, texts: list[str]) -> str:
    return _stable_hash({"kind": "embed", "model": model, "texts": list(texts)})


def _rerank_key(model: str, query: str, top_n: int | None, instruct: str | None) -> str:
    # The candidate population is deliberately NOT part of the key: the fused
    # list's members at the tie cutoff wobble run to run (observed: the same
    # query returning 18 vs 17 documents, the extra one a tiny title chunk),
    # while a rerank score belongs to (query, document) independently of its
    # company. ``remap_rerank_response`` re-anchors the recorded scores onto
    # the requesting order and refuses to serve when the overlap collapses —
    # that guard, not the key, is what catches real population drift.
    return _stable_hash({"kind": "rerank", "model": model, "query": query, "top_n": top_n, "instruct": instruct})


def _caption_key(model: str, prompt: str, image_sha256: list[str], max_tokens: int | None) -> str:
    return _stable_hash({"kind": "caption", "model": model, "prompt": prompt, "image_sha256": image_sha256, "max_tokens": max_tokens})


def key_for_request(path: str, body: Mapping[str, Any]) -> str:
    """Derive the recording key for one outbound model call.

    Only the fields that decide the answer take part; transport details
    (headers, timeouts) and non-determinative switches stay out, so the
    recording survives a dialect/parameter reshuffle that changes nothing
    about the result. Unknown paths raise — a new outbound call kind must be
    added here deliberately, never recorded by accident.
    """
    if any(marker in path for marker in _EMBED_PATH_MARKERS):
        model = str(body.get("model") or "")
        raw_input = body.get("input")
        if isinstance(raw_input, Mapping):
            texts = list(raw_input.get("texts") or [])
        elif isinstance(raw_input, list):
            texts = [str(item) for item in raw_input]
        else:
            raise UnsupportedReplayRequest(f"unsupported embedding request shape: {type(raw_input).__name__}")
        return _embed_key(model, [str(text) for text in texts])

    if any(marker in path for marker in _RERANK_PATH_MARKERS):
        top_n = body.get("top_n")
        return _rerank_key(
            str(body.get("model") or ""),
            str(body.get("query") or ""),
            int(top_n) if top_n is not None else None,
            body.get("instruct"),
        )

    if any(marker in path for marker in _CAPTION_PATH_MARKERS):
        model = str(body.get("model") or "")
        prompt_parts: list[str] = []
        image_hashes: list[str] = []
        for message in body.get("messages") or []:
            content = message.get("content") if isinstance(message, Mapping) else None
            if isinstance(content, str):
                prompt_parts.append(content)
                continue
            for block in content or []:
                if not isinstance(block, Mapping):
                    continue
                block_type = block.get("type")
                if block_type == "text":
                    prompt_parts.append(str(block.get("text") or ""))
                elif block_type == "image_url":
                    url = str((block.get("image_url") or {}).get("url") or "")
                    match = _DATA_URL_RE.match(url)
                    image_hashes.append(hashlib.sha256((match.group(2) if match else url).encode("utf-8")).hexdigest())
                elif block_type == "image":
                    data = str((block.get("source") or {}).get("data") or "")
                    image_hashes.append(hashlib.sha256(data.encode("utf-8")).hexdigest())
        return _caption_key(model, "\n".join(prompt_parts), image_hashes, body.get("max_tokens"))

    raise UnsupportedReplayRequest(f"path is not a recorded call kind: {path}")


def describe_request(path: str, body: Mapping[str, Any]) -> dict[str, Any]:
    """A small human-readable digest of a recorded call (for the fixture file)."""
    key = key_for_request(path, body)
    if any(marker in path for marker in _EMBED_PATH_MARKERS):
        raw_input = body.get("input")
        texts = raw_input.get("texts") if isinstance(raw_input, Mapping) else raw_input
        return {"kind": "embed", "model": body.get("model"), "n_texts": len(texts or [])}
    if any(marker in path for marker in _RERANK_PATH_MARKERS):
        return {"kind": "rerank", "model": body.get("model"), "query": body.get("query"), "n_documents": len(body.get("documents") or []), "top_n": body.get("top_n")}
    return {"kind": "caption", "model": body.get("model"), "key": key[:16]}


def rerank_documents_for_entry(path: str, body: Mapping[str, Any]) -> list[str] | None:
    """The document list a rerank request carries (stored with the recording so
    the replay can remap returned indices onto a differently-ordered request)."""
    if not any(marker in path for marker in _RERANK_PATH_MARKERS):
        return None
    return [str(doc) for doc in body.get("documents") or []]


#: Below this share of shared documents the rerank replay refuses to serve —
#: small tie-cutoff wobble is tolerated, a collapsed overlap is real drift.
RERANK_OVERLAP_FLOOR = 0.8


def remap_rerank_response(entry: Mapping[str, Any], request_documents: list[str]) -> dict[str, Any]:
    """Rewrite a recorded rerank response's indices onto the request's order.

    Scores are text-anchored: a recorded document absent from this request
    (tie-cutoff wobble) is skipped, a request document the recording never
    scored simply stays unscored (it drops out of the ranked list exactly like
    a degraded candidate). If the two populations barely overlap the fixture
    no longer describes this request — a loud miss, never a silent serving.
    """
    recorded_documents = entry.get("documents")
    if recorded_documents is None:
        return dict(entry["response"])
    position_by_text: dict[str, int] = {}
    for index, document in enumerate(request_documents):
        position_by_text.setdefault(document, index)
    recorded_set = set(recorded_documents)
    request_set = set(request_documents)
    denominator = max(len(recorded_set), len(request_set), 1)
    if len(recorded_set & request_set) / denominator < RERANK_OVERLAP_FLOOR:
        raise ReplayMiss(f"rerank replay: candidate overlap collapsed (key {entry['key'][:16]}…) — the fixture is stale; re-record")
    results = []
    for item in entry["response"].get("results") or []:
        text = recorded_documents[int(item["index"])]
        new_index = position_by_text.get(text)
        if new_index is None:
            continue  # recorded document no longer among the candidates (wobble)
        results.append({**item, "index": new_index})
    remapped = dict(entry["response"])
    remapped["results"] = results
    return remapped


# ── recording IO ─────────────────────────────────────────────────────────


def round_floats(payload: Any, ndigits: int = 6) -> Any:
    """Round every float in a recorded payload (1e-6).

    Scores/vectors keep their rank-relevant precision; the JSONL fixture loses
    ~half its bytes to float tail digits and gzips far better. Applied at
    record time and to converted fixtures alike, so all served values agree.
    """
    if isinstance(payload, float):
        return round(payload, ndigits)
    if isinstance(payload, list):
        return [round_floats(item, ndigits) for item in payload]
    if isinstance(payload, dict):
        return {key: round_floats(value, ndigits) for key, value in payload.items()}
    return payload


def load_recording(path: str | Path) -> dict[str, dict[str, Any]]:
    """Load a JSONL (or ``.gz``) recording into ``{key: entry}`` (loud on conflicts).

    Entries carry the recorded ``response`` plus, for rerank calls, the ordered
    ``documents`` list the response's indices point into.
    """
    recording: dict[str, dict[str, Any]] = {}
    for line in read_recording_lines(path):
        if not line.strip():
            continue
        entry = json.loads(line)
        key = entry["key"]
        existing = recording.get(key)
        if existing is not None and existing["response"] != entry["response"]:
            raise ValueError(f"conflicting recording entries for key {key[:16]}… — the fixture was recorded from diverging runs")
        recording[key] = entry
    return recording


def read_recording_lines(path: str | Path) -> list[str]:
    target = Path(path)
    if target.suffix == ".gz":
        import gzip

        with gzip.open(target, "rt", encoding="utf-8") as handle:
            return handle.read().splitlines()
    return target.read_text(encoding="utf-8").splitlines()


def load_recording_entries(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in read_recording_lines(path) if line.strip()]


def material_fingerprint(materials_dir: str | Path) -> str:
    """Index-input fingerprint over the material files (RFC v3 §8.1).

    A change to any material file changes the fingerprint, so a replay
    recording taken for the old content is detectable instead of being
    silently applied to different inputs.
    """
    from deerflow_knowledge.chunker import MAX_CHUNK_TOKENS, MIN_CHUNK_TOKENS

    base = Path(materials_dir)
    files = sorted(path for path in base.rglob("*") if path.is_file())
    items = [{"name": str(path.relative_to(base)).replace("\\", "/"), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in files]
    return _stable_hash(
        {
            "version": 1,
            "files": items,
            "chunker": f"structure-max{MAX_CHUNK_TOKENS}/min{MIN_CHUNK_TOKENS}/cl100k_base",
        }
    )
