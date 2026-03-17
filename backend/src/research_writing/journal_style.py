"""Journal-specific style alignment based on recent high-citation samples."""

from __future__ import annotations

import json
import logging
import math
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.config.journal_style_config import JournalStyleConfig, get_journal_style_config

logger = logging.getLogger(__name__)

_OPENALEX_SOURCES_URL = "https://api.openalex.org/sources"
_OPENALEX_WORKS_URL = "https://api.openalex.org/works"

_JOURNAL_QUERY_HINTS: dict[str, str] = {
    "nature": "Nature",
    "science": "Science",
    "cell": "Cell",
    "nature medicine": "Nature Medicine",
    "nature biotechnology": "Nature Biotechnology",
    "nature communications": "Nature Communications",
    "science advances": "Science Advances",
    "cell reports": "Cell Reports",
}


@dataclass
class JournalStyleSample:
    """One high-citation journal exemplar used for few-shot style alignment."""

    title: str
    year: int | None
    cited_by_count: int
    doi: str | None
    openalex_id: str | None
    abstract_excerpt: str
    first_sentence: str
    avg_sentence_words: float
    sentence_count: int
    url: str | None


@dataclass
class JournalStyleBundle:
    """Few-shot bundle and extracted style statistics."""

    venue_name: str
    resolved_journal_name: str
    resolved_source_id: str
    sample_size: int
    collected_at: str
    style_summary: dict[str, Any]
    writing_directives: list[str]
    few_shot_samples: list[dict[str, Any]]
    prompt_material: str
    cache_hit: bool = False


def _http_get_json(url: str, *, timeout_seconds: int) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "DeerFlow/1.0"})
    with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
        payload = response.read().decode("utf-8", errors="replace")
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise ValueError("Expected JSON object response")
    return parsed


def _norm_text(value: str | None) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())


def _sentence_split(text: str) -> list[str]:
    if not text.strip():
        return []
    fragments: list[str] = []
    current = []
    for char in text:
        current.append(char)
        if char in ".!?":
            sentence = _norm_text("".join(current))
            if sentence:
                fragments.append(sentence)
            current = []
    tail = _norm_text("".join(current))
    if tail:
        fragments.append(tail)
    return fragments


def _avg_sentence_words(text: str) -> float:
    sentences = _sentence_split(text)
    if not sentences:
        return 0.0
    total_words = 0
    for sentence in sentences:
        total_words += len([token for token in sentence.split(" ") if token])
    return total_words / max(len(sentences), 1)


def _decode_openalex_abstract(inverted_index: dict[str, Any] | None) -> str:
    if not isinstance(inverted_index, dict) or not inverted_index:
        return ""
    max_pos = -1
    for idxs in inverted_index.values():
        if not isinstance(idxs, list):
            continue
        for pos in idxs:
            if isinstance(pos, int):
                max_pos = max(max_pos, pos)
    if max_pos < 0:
        return ""
    words = [""] * (max_pos + 1)
    for token, idxs in inverted_index.items():
        if not isinstance(idxs, list):
            continue
        for pos in idxs:
            if isinstance(pos, int) and 0 <= pos < len(words):
                words[pos] = token
    return _norm_text(" ".join(item for item in words if item))


def _truncate_excerpt(text: str, *, max_chars: int) -> str:
    normalized = _norm_text(text)
    if len(normalized) <= max_chars:
        return normalized
    clipped = normalized[: max_chars - 3]
    if " " in clipped:
        clipped = clipped.rsplit(" ", maxsplit=1)[0]
    return f"{clipped}..."


def _resolve_journal_query(venue_name: str) -> str:
    normalized = _norm_text(venue_name)
    lower = normalized.lower()
    if lower in _JOURNAL_QUERY_HINTS:
        return _JOURNAL_QUERY_HINTS[lower]
    for key, value in _JOURNAL_QUERY_HINTS.items():
        if key in lower:
            return value
    return normalized


def _score_source_match(*, query: str, source: dict[str, Any]) -> float:
    display_name = _norm_text(str(source.get("display_name") or ""))
    if not display_name:
        return -1.0
    query_norm = query.lower()
    display_norm = display_name.lower()
    score = 0.0
    if display_norm == query_norm:
        score += 100.0
    elif display_norm.startswith(query_norm):
        score += 70.0
    elif query_norm in display_norm:
        score += 45.0
    else:
        score += 10.0

    works_count = source.get("works_count")
    if isinstance(works_count, int) and works_count > 0:
        score += min(20.0, math.log10(float(works_count)))
    return score


def _resolve_openalex_source(*, journal_query: str, timeout_seconds: int) -> tuple[str, str] | None:
    params = {
        "search": journal_query,
        "per-page": "15",
    }
    url = f"{_OPENALEX_SOURCES_URL}?{urllib.parse.urlencode(params)}"
    payload = _http_get_json(url, timeout_seconds=timeout_seconds)
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return None
    candidates: list[tuple[float, str, str]] = []
    for source in results:
        if not isinstance(source, dict):
            continue
        source_id = source.get("id")
        display_name = _norm_text(str(source.get("display_name") or ""))
        if not isinstance(source_id, str) or not source_id.strip() or not display_name:
            continue
        score = _score_source_match(query=journal_query, source=source)
        candidates.append((score, source_id, display_name))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, source_id, display_name = candidates[0]
    return source_id, display_name


def _extract_first_sentence(text: str) -> str:
    sentences = _sentence_split(text)
    return sentences[0] if sentences else ""


def _fetch_high_impact_samples(
    *,
    source_id: str,
    sample_size: int,
    recent_year_window: int,
    timeout_seconds: int,
    max_excerpt_chars: int,
) -> list[JournalStyleSample]:
    from_date = datetime.now(UTC).date().replace(
        year=max(1900, datetime.now(UTC).year - max(1, recent_year_window)),
    )
    params = {
        "filter": f"primary_location.source.id:{source_id},from_publication_date:{from_date.isoformat()}",
        "sort": "cited_by_count:desc",
        "per-page": str(max(1, min(sample_size, 10))),
    }
    url = f"{_OPENALEX_WORKS_URL}?{urllib.parse.urlencode(params)}"
    payload = _http_get_json(url, timeout_seconds=timeout_seconds)
    results = payload.get("results")
    if not isinstance(results, list):
        return []

    samples: list[JournalStyleSample] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        title = _norm_text(str(item.get("title") or ""))
        if not title:
            continue
        abstract = _decode_openalex_abstract(item.get("abstract_inverted_index"))
        excerpt = _truncate_excerpt(abstract, max_chars=max_excerpt_chars)
        first_sentence = _extract_first_sentence(abstract)
        sentence_count = len(_sentence_split(abstract))
        avg_words = _avg_sentence_words(abstract)
        doi_raw = item.get("doi")
        doi = None
        if isinstance(doi_raw, str) and doi_raw.strip():
            doi = doi_raw.strip().replace("https://doi.org/", "").replace("http://doi.org/", "")
        samples.append(
            JournalStyleSample(
                title=title,
                year=item.get("publication_year") if isinstance(item.get("publication_year"), int) else None,
                cited_by_count=item.get("cited_by_count") if isinstance(item.get("cited_by_count"), int) else 0,
                doi=doi,
                openalex_id=item.get("id") if isinstance(item.get("id"), str) else None,
                abstract_excerpt=excerpt,
                first_sentence=first_sentence,
                avg_sentence_words=avg_words,
                sentence_count=sentence_count,
                url=item.get("id") if isinstance(item.get("id"), str) else None,
            )
        )
    return samples[:sample_size]


def _infer_style_summary(samples: list[JournalStyleSample]) -> tuple[dict[str, Any], list[str]]:
    if not samples:
        return (
            {
                "avg_sentence_words": 0.0,
                "avg_abstract_sentences": 0.0,
                "avg_cited_by_count": 0.0,
                "first_sentence_starters": [],
                "rhythm_label": "unknown",
            },
            [],
        )

    avg_sentence_words = sum(item.avg_sentence_words for item in samples) / len(samples)
    avg_abstract_sentences = sum(item.sentence_count for item in samples) / len(samples)
    avg_cited_by_count = sum(item.cited_by_count for item in samples) / len(samples)

    starters: dict[str, int] = {}
    for sample in samples:
        sentence = sample.first_sentence
        if not sentence:
            continue
        token = sentence.split(" ", maxsplit=1)[0].strip(",. ").lower()
        if token:
            starters[token] = starters.get(token, 0) + 1
    top_starters = [token for token, _ in sorted(starters.items(), key=lambda item: item[1], reverse=True)[:5]]

    if avg_sentence_words <= 18:
        rhythm_label = "concise_dense"
        rhythm_directive = "句式偏短、信息密度高，建议每句聚焦单一论证动作并快速推进。"
    elif avg_sentence_words <= 25:
        rhythm_label = "balanced"
        rhythm_directive = "句式中等长度，建议以“证据-解释-限制”三段式维持平衡节奏。"
    else:
        rhythm_label = "long_form_argumentative"
        rhythm_directive = "句式较长且层次复杂，建议使用复合句展开机制解释与对照论证。"

    if avg_abstract_sentences <= 5:
        paragraph_directive = "段落节奏偏紧凑，建议每段 3-5 句，首句开门见山。"
    else:
        paragraph_directive = "段落节奏偏展开，建议每段 5-7 句并保留过渡句。"

    starters_directive = ""
    if top_starters:
        starters_directive = f"常见开篇词：{', '.join(top_starters)}；可用于保持语感一致性。"

    directives = [rhythm_directive, paragraph_directive]
    if starters_directive:
        directives.append(starters_directive)

    summary = {
        "avg_sentence_words": round(avg_sentence_words, 2),
        "avg_abstract_sentences": round(avg_abstract_sentences, 2),
        "avg_cited_by_count": round(avg_cited_by_count, 2),
        "first_sentence_starters": top_starters,
        "rhythm_label": rhythm_label,
    }
    return summary, directives


def _build_prompt_material(
    *,
    venue_name: str,
    resolved_journal_name: str,
    directives: list[str],
    samples: list[JournalStyleSample],
) -> str:
    lines = [
        f"Target venue: {venue_name}",
        f"Resolved journal source: {resolved_journal_name}",
        "Journal style directives:",
    ]
    for idx, directive in enumerate(directives, start=1):
        lines.append(f"{idx}. {directive}")
    lines.append("")
    lines.append("Few-shot style exemplars (recent high-citation):")
    for idx, sample in enumerate(samples, start=1):
        meta = f"year={sample.year or 'n/a'}, cited_by={sample.cited_by_count}"
        if sample.doi:
            meta = f"{meta}, doi={sample.doi}"
        lines.append(f"[{idx}] {sample.title} ({meta})")
        if sample.first_sentence:
            lines.append(f"  opening: {sample.first_sentence}")
        if sample.abstract_excerpt:
            lines.append(f"  excerpt: {sample.abstract_excerpt}")
    return "\n".join(lines).strip()


def _load_cache(cache_path: Path, *, ttl_hours: int) -> dict[str, Any] | None:
    if not cache_path.exists():
        return None
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    cached_at = raw.get("collected_at")
    if not isinstance(cached_at, str):
        return None
    try:
        cached_dt = datetime.fromisoformat(cached_at)
    except Exception:
        return None
    if cached_dt.tzinfo is None:
        cached_dt = cached_dt.replace(tzinfo=UTC)
    expires = cached_dt + timedelta(hours=max(1, ttl_hours))
    if datetime.now(UTC) > expires:
        return None
    return raw


def _dump_cache(cache_path: Path, payload: dict[str, Any]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def build_journal_style_bundle(
    *,
    venue_name: str,
    cache_path: Path | None = None,
    force_refresh: bool = False,
    sample_size: int | None = None,
    recent_year_window: int | None = None,
    config: JournalStyleConfig | None = None,
) -> dict[str, Any] | None:
    """Build (or read cached) few-shot journal style bundle for one venue."""
    cfg = config or get_journal_style_config()
    if not cfg.enabled:
        return None

    resolved_sample_size = max(1, min(sample_size or cfg.sample_size, 10))
    resolved_year_window = max(1, min(recent_year_window or cfg.recent_year_window, 15))

    if cache_path is not None and not force_refresh:
        cached = _load_cache(cache_path, ttl_hours=cfg.cache_ttl_hours)
        if cached is not None:
            cached["cache_hit"] = True
            return cached

    journal_query = _resolve_journal_query(venue_name)
    source = _resolve_openalex_source(
        journal_query=journal_query,
        timeout_seconds=cfg.request_timeout_seconds,
    )
    if source is None:
        logger.warning("Journal style alignment skipped: source unresolved for venue='%s'", venue_name)
        return None
    source_id, source_name = source

    try:
        samples = _fetch_high_impact_samples(
            source_id=source_id,
            sample_size=resolved_sample_size,
            recent_year_window=resolved_year_window,
            timeout_seconds=cfg.request_timeout_seconds,
            max_excerpt_chars=cfg.max_excerpt_chars,
        )
    except Exception as exc:
        logger.warning("Journal style alignment fetch failed for venue='%s': %s", venue_name, exc)
        return None

    if not samples:
        logger.warning("Journal style alignment skipped: no recent samples for venue='%s'", venue_name)
        return None

    style_summary, directives = _infer_style_summary(samples)
    prompt_material = _build_prompt_material(
        venue_name=venue_name,
        resolved_journal_name=source_name,
        directives=directives,
        samples=samples,
    )
    bundle = JournalStyleBundle(
        venue_name=venue_name,
        resolved_journal_name=source_name,
        resolved_source_id=source_id,
        sample_size=len(samples),
        collected_at=datetime.now(UTC).isoformat(),
        style_summary=style_summary,
        writing_directives=directives,
        few_shot_samples=[asdict(sample) for sample in samples],
        prompt_material=prompt_material,
    )
    payload = asdict(bundle)
    if cache_path is not None:
        _dump_cache(cache_path, payload)
    payload["cache_hit"] = False
    return payload
