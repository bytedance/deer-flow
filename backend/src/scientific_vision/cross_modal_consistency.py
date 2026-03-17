from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

CROSS_MODAL_SCHEMA_VERSION = "deerflow.cross_modal_consistency.v1"

_CLAIM_SPLIT_RE = re.compile(r"[。\n!?！？;；]+")
_TOKEN_RE = re.compile(r"[A-Za-z]{2,}|[\u4e00-\u9fff]{2,}|[-+]?\d+(?:\.\d+)?%?")
_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")

_CLAIM_KEYWORDS = (
    "increase",
    "decrease",
    "higher",
    "lower",
    "shift",
    "dark",
    "light",
    "peak",
    "cluster",
    "band",
    "gate",
    "silhouette",
    "mixing",
    "升高",
    "降低",
    "增加",
    "减少",
    "变暗",
    "变亮",
    "偏移",
    "峰",
    "条带",
    "细胞群",
    "显著",
)

_DIRECTION_MAP: dict[str, tuple[str, ...]] = {
    "increase": ("increase", "increased", "higher", "up", "elevated", "升高", "增加", "上升", "增强", "更高", "变亮"),
    "decrease": ("decrease", "decreased", "lower", "down", "reduced", "降低", "减少", "下降", "减弱", "更低", "变暗"),
    "shift": ("shift", "shifted", "moved", "偏移", "位移", "左移", "右移"),
    "separation": ("separate", "separation", "clustered", "聚类", "分离", "混杂"),
}

_CLAIM_TYPE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("western_blot_intensity", ("band", "blot", "条带", "western", "loading control", "densitometry", "内参")),
    ("facs_population", ("facs", "gate", "cell population", "细胞群", "流式", "门控")),
    ("embedding_shift", ("tsne", "t-sne", "umap", "embedding", "cluster", "聚类", "嵌入")),
    ("spectrum_peak", ("spectrum", "peak", "wavelength", "intensity", "snr", "光谱", "峰", "波长")),
]

_SUBJECT_HINTS: tuple[str, ...] = (
    "treated",
    "control",
    "patient",
    "cohort",
    "group",
    "sample",
    "lane",
    "处理组",
    "对照组",
    "患者",
    "队列",
    "样本",
    "条带",
    "细胞群",
)

_METRIC_HINTS: tuple[str, ...] = (
    "signal",
    "intensity",
    "population",
    "ratio",
    "percentage",
    "silhouette",
    "mixing",
    "peak",
    "wavelength",
    "snr",
    "信号",
    "强度",
    "比例",
    "占比",
    "峰",
    "波长",
)

_CONDITION_HINTS: tuple[str, ...] = (
    "under",
    "after",
    "before",
    "with",
    "without",
    "at",
    "in",
    "在",
    "经过",
    "条件下",
    "处理后",
    "对照下",
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _extract_numbers(text: str, *, max_count: int = 8) -> list[float]:
    values: list[float] = []
    for m in _NUMBER_RE.finditer(text):
        if len(values) >= max_count:
            break
        try:
            values.append(float(m.group(0)))
        except Exception:
            continue
    return values


def _tokenize(text: str) -> set[str]:
    tokens: set[str] = set()
    for m in _TOKEN_RE.finditer(text.lower()):
        t = m.group(0).strip()
        if t:
            tokens.add(t)
    return tokens


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return float(inter) / float(union)


def _detect_directions(text: str) -> list[str]:
    lower = text.lower()
    out: list[str] = []
    for direction, keywords in _DIRECTION_MAP.items():
        if any(k in lower for k in keywords):
            out.append(direction)
    return sorted(set(out))


def _detect_claim_type(text: str) -> str:
    lower = text.lower()
    for claim_type, keywords in _CLAIM_TYPE_RULES:
        if any(k in lower for k in keywords):
            return claim_type
    return "generic_trend"


def _extract_magnitude(text: str) -> str | None:
    m = re.search(r"([-+]?\d+(?:\.\d+)?\s*%|[-+]?\d+(?:\.\d+)?\s*(?:fold|倍))", text, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def _extract_subject(text: str) -> str | None:
    lowered = text.lower()
    for token in _SUBJECT_HINTS:
        if token in lowered:
            return token
    return None


def _extract_metric(text: str) -> str | None:
    lowered = text.lower()
    for token in _METRIC_HINTS:
        if token in lowered:
            return token
    return None


def _extract_condition(text: str) -> str | None:
    lowered = text.lower()
    for token in _CONDITION_HINTS:
        if token in lowered:
            return token
    return None


def decompose_claim(text: str, *, claim_type: str) -> dict[str, Any]:
    """Decompose claim into adjudication-friendly structured slots."""
    directions = _detect_directions(text)
    direction = directions[0] if directions else None
    return {
        "subject": _extract_subject(text),
        "metric": _extract_metric(text) or claim_type,
        "direction": direction,
        "magnitude": _extract_magnitude(text),
        "condition": _extract_condition(text),
    }


def _is_claim_like(sentence: str) -> bool:
    if len(sentence) < 6:
        return False
    lower = sentence.lower()
    if any(k in lower for k in _CLAIM_KEYWORDS):
        return True
    if "%" in sentence:
        return True
    if _NUMBER_RE.search(sentence):
        # Numeric sentence with comparative language.
        return any(x in lower for x in ("than", "vs", "compared", "fold", "倍", "相比", "高于", "低于"))
    return False


def extract_candidate_claims(narrative_text: str, *, max_claims: int = 25) -> list[dict[str, Any]]:
    """Extract claim-like statements from free text."""
    text = (narrative_text or "").strip()
    if not text:
        return []

    chunks = [s.strip(" -\t\r") for s in _CLAIM_SPLIT_RE.split(text)]
    chunks = [c for c in chunks if c]

    claims: list[dict[str, Any]] = []
    for chunk in chunks:
        if not _is_claim_like(chunk):
            continue
        claim_type = _detect_claim_type(chunk)
        claims.append(
            {
                "id": f"C{len(claims) + 1}",
                "text": chunk,
                "claim_type": claim_type,
                "numbers": _extract_numbers(chunk),
                "directions": _detect_directions(chunk),
                "decomposition": decompose_claim(chunk, claim_type=claim_type),
            }
        )
        if len(claims) >= max_claims:
            break

    # Fallback: if nothing matched, audit the entire text as one claim.
    if not claims:
        fallback = text[:700]
        claim_type = _detect_claim_type(fallback)
        claims = [
            {
                "id": "C1",
                "text": fallback,
                "claim_type": claim_type,
                "numbers": _extract_numbers(fallback),
                "directions": _detect_directions(fallback),
                "decomposition": decompose_claim(fallback, claim_type=claim_type),
            }
        ]
    return claims


def _append_string(strings: list[str], value: str, *, max_items: int) -> None:
    if len(strings) >= max_items:
        return
    s = value.strip()
    if not s:
        return
    if len(s) > 500:
        s = s[:500]
    strings.append(s)


def _append_number(numbers: list[float], value: float, *, max_items: int) -> None:
    if len(numbers) >= max_items:
        return
    numbers.append(float(value))


def _collect_strings_and_numbers(
    obj: Any,
    *,
    strings: list[str],
    numbers: list[float],
    depth: int = 0,
    max_items: int = 3000,
) -> None:
    if depth > 6:
        return
    if len(strings) >= max_items and len(numbers) >= max_items:
        return

    if isinstance(obj, str):
        _append_string(strings, obj, max_items=max_items)
        for n in _extract_numbers(obj, max_count=4):
            _append_number(numbers, n, max_items=max_items)
        return
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        _append_number(numbers, float(obj), max_items=max_items)
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            # Skip very noisy raw model output blobs.
            if isinstance(k, str) and k in {"raw_model_output"}:
                continue
            _collect_strings_and_numbers(v, strings=strings, numbers=numbers, depth=depth + 1, max_items=max_items)
        return
    if isinstance(obj, list):
        for item in obj:
            _collect_strings_and_numbers(item, strings=strings, numbers=numbers, depth=depth + 1, max_items=max_items)


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _flatten_sources(report_payloads: list[dict[str, Any]], analysis_payloads: list[dict[str, Any]]) -> tuple[list[str], list[float], list[str], list[str]]:
    strings: list[str] = []
    numbers: list[float] = []
    image_types: list[str] = []
    analysis_schemas: list[str] = []

    for report in report_payloads:
        _collect_strings_and_numbers(report, strings=strings, numbers=numbers)
        rep = report.get("report") if isinstance(report.get("report"), dict) else None
        if isinstance(rep, dict):
            image_type = rep.get("image_type")
            if isinstance(image_type, str) and image_type:
                image_types.append(image_type)

    for analysis in analysis_payloads:
        _collect_strings_and_numbers(analysis, strings=strings, numbers=numbers)
        schema = analysis.get("schema_version")
        if isinstance(schema, str) and schema:
            analysis_schemas.append(schema)

    return _dedupe_preserve_order(strings), numbers[:4000], sorted(set(image_types)), sorted(set(analysis_schemas))


def _direction_contradicted(claim_dirs: list[str], evidence_dirs: list[str]) -> bool:
    c = set(claim_dirs)
    e = set(evidence_dirs)
    return ("increase" in c and "decrease" in e) or ("decrease" in c and "increase" in e)


def _semantic_overlap(claim_dec: dict[str, Any], evidence_dec: dict[str, Any]) -> float:
    score = 0.0
    claim_metric = str(claim_dec.get("metric") or "").lower()
    evidence_metric = str(evidence_dec.get("metric") or "").lower()
    if claim_metric and evidence_metric and (claim_metric == evidence_metric or claim_metric in evidence_metric or evidence_metric in claim_metric):
        score += 0.3

    claim_subject = str(claim_dec.get("subject") or "").lower()
    evidence_subject = str(evidence_dec.get("subject") or "").lower()
    if claim_subject and evidence_subject and (claim_subject == evidence_subject or claim_subject in evidence_subject or evidence_subject in claim_subject):
        score += 0.2

    claim_cond = str(claim_dec.get("condition") or "").lower()
    evidence_cond = str(evidence_dec.get("condition") or "").lower()
    if claim_cond and evidence_cond and (claim_cond == evidence_cond or claim_cond in evidence_cond or evidence_cond in claim_cond):
        score += 0.15

    claim_direction = str(claim_dec.get("direction") or "")
    evidence_direction = str(evidence_dec.get("direction") or "")
    if claim_direction and evidence_direction:
        if claim_direction == evidence_direction:
            score += 0.25
        elif {claim_direction, evidence_direction} == {"increase", "decrease"}:
            score -= 0.25

    claim_mag = str(claim_dec.get("magnitude") or "")
    evidence_mag = str(evidence_dec.get("magnitude") or "")
    if claim_mag and evidence_mag:
        score += 0.1
    return max(-0.25, min(1.0, score))


def _recommend_followups(claim_type: str, verdict: str) -> list[str]:
    if verdict == "supported":
        return []
    if claim_type == "western_blot_intensity":
        return [
            "使用 blot-auditor 子代理复核条带强度与归一化链路。",
            "若有定量表，运行 analyze_densitometry_csv 进行原始数据复核。",
        ]
    if claim_type == "facs_population":
        return [
            "使用 facs-auditor 子代理对 gate 与群体比例进行审计。",
            "若有 FCS 原始文件，运行 analyze_fcs 获取可复现门控结果。",
        ]
    if claim_type == "embedding_shift":
        return [
            "使用 tsne-auditor 子代理复核聚类分离与批次混杂。",
            "若有嵌入 CSV，运行 analyze_embedding_csv 复算 silhouette 与 kNN mixing。",
        ]
    if claim_type == "spectrum_peak":
        return [
            "使用 spectrum-auditor 子代理复核峰位与 SNR。",
            "若有光谱 CSV，运行 analyze_spectrum_csv 进行数值峰检测。",
        ]
    return ["建议补充原始数据 analysis artifact 后再次运行一致性审计。"]


def _score_claim(claim: dict[str, Any], source_strings: list[str], source_numbers: list[float]) -> dict[str, Any]:
    claim_text = str(claim.get("text") or "")
    claim_type = str(claim.get("claim_type") or "generic_trend")
    claim_tokens = _tokenize(claim_text)
    claim_dec = claim.get("decomposition")
    if not isinstance(claim_dec, dict):
        claim_dec = decompose_claim(claim_text, claim_type=claim_type)
    candidates: list[dict[str, Any]] = []
    for snippet in source_strings[:1200]:
        s_score = _jaccard(claim_tokens, _tokenize(snippet))
        if s_score < 0.06:
            continue
        evidence_dec = decompose_claim(snippet, claim_type=claim_type)
        semantic_score = _semantic_overlap(claim_dec, evidence_dec)
        merged_score = (0.65 * s_score) + (0.35 * max(0.0, semantic_score))
        candidates.append(
            {
                "snippet": snippet,
                "score": round(merged_score, 4),
                "lexical_score": round(s_score, 4),
                "semantic_score": round(semantic_score, 4),
                "directions": _detect_directions(snippet),
                "decomposition": evidence_dec,
            }
        )
    candidates.sort(key=lambda x: float(x["score"]), reverse=True)
    top_support = candidates[:3]
    best_score = float(top_support[0]["score"]) if top_support else 0.0

    claim_numbers = [float(x) for x in claim.get("numbers") or [] if isinstance(x, (int, float))]
    numeric_matched = False
    closest_values: list[float] = []
    if claim_numbers and source_numbers:
        matched = 0
        for n in claim_numbers:
            best = min(source_numbers, key=lambda x: abs(float(x) - n))
            closest_values.append(float(best))
            tolerance = max(0.5, abs(n) * 0.2)
            if abs(float(best) - n) <= tolerance:
                matched += 1
        numeric_matched = matched == len(claim_numbers)

    evidence_dirs: list[str] = []
    for row in top_support:
        for d in row.get("directions") or []:
            if isinstance(d, str):
                evidence_dirs.append(d)
    contradicted = _direction_contradicted(claim.get("directions") or [], evidence_dirs)

    if contradicted:
        verdict = "contradicted"
    elif best_score >= 0.33 and (not claim_numbers or numeric_matched):
        verdict = "supported"
    elif best_score >= 0.18 or numeric_matched:
        verdict = "partially_supported"
    else:
        verdict = "unsupported"

    confidence = 0.2 + (best_score * 1.35) + (0.18 if numeric_matched else 0.0) - (0.22 if contradicted else 0.0)
    confidence = max(0.0, min(0.98, confidence))

    uncertainty_reasons: list[str] = []
    if not top_support:
        uncertainty_reasons.append("No high-similarity evidence snippet found.")
    if claim_numbers and not numeric_matched:
        uncertainty_reasons.append("Numeric magnitude not matched within tolerance.")
    if contradicted:
        uncertainty_reasons.append("Opposite trend direction detected in evidence.")
    if verdict == "unsupported":
        uncertainty_reasons.append("Insufficient support for deterministic entailment.")
    entailment = "supported" if verdict == "supported" else "contradicted" if verdict == "contradicted" else "partial"

    return {
        "verdict": verdict,
        "entailment": entailment,
        "confidence": round(confidence, 4),
        "best_support_score": round(best_score, 4),
        "claim_decomposition": claim_dec,
        "numeric_support": {
            "matched": bool(numeric_matched) if claim_numbers else None,
            "claim_numbers": claim_numbers,
            "closest_values": closest_values[: len(claim_numbers)],
        },
        "supporting_evidence": [{"snippet": s["snippet"], "score": s["score"]} for s in top_support],
        "provenance": [
            {
                "snippet": s["snippet"],
                "support_score": s["score"],
                "lexical_score": s.get("lexical_score"),
                "semantic_score": s.get("semantic_score"),
                "decomposition": s.get("decomposition"),
            }
            for s in top_support
        ],
        "uncertainty": {
            "score": round(1.0 - confidence, 4),
            "reasons": uncertainty_reasons or ["Low residual uncertainty."],
        },
        "recommended_next_steps": _recommend_followups(claim_type, verdict),
    }


def _summarize_claims(claims: list[dict[str, Any]]) -> dict[str, int]:
    out = {
        "claims_total": len(claims),
        "supported": 0,
        "partially_supported": 0,
        "unsupported": 0,
        "contradicted": 0,
    }
    for c in claims:
        verdict = c.get("verdict")
        if verdict == "partial":
            verdict = "partially_supported"
        if verdict in out:
            out[verdict] += 1
    return out


def build_consistency_audit(
    *,
    narrative_text: str,
    report_payloads: list[dict[str, Any]],
    analysis_payloads: list[dict[str, Any]],
    report_paths: list[str] | None = None,
    analysis_paths: list[str] | None = None,
    max_claims: int = 25,
) -> dict[str, Any]:
    """Build claim-level cross-modal consistency audit payload."""
    text = (narrative_text or "").strip()
    if not text:
        raise ValueError("narrative_text must be non-empty")

    claims = extract_candidate_claims(text, max_claims=max_claims)
    source_strings, source_numbers, image_types, analysis_schemas = _flatten_sources(report_payloads, analysis_payloads)

    scored_claims: list[dict[str, Any]] = []
    for claim in claims:
        scored = _score_claim(claim, source_strings=source_strings, source_numbers=source_numbers)
        row = dict(claim)
        row.update(scored)
        scored_claims.append(row)

    summary = _summarize_claims(scored_claims)

    return {
        "schema_version": CROSS_MODAL_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "claim_text_sha256": _sha256_text(text),
        "summary": summary,
        "claims": scored_claims,
        "sources": {
            "report_paths": report_paths or [],
            "analysis_paths": analysis_paths or [],
            "image_types": image_types,
            "analysis_schemas": analysis_schemas,
            "source_snippets_used": len(source_strings),
        },
    }


def merge_vision_recheck(
    *,
    audit_payload: dict[str, Any],
    vision_checks: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Merge optional vision re-check results into the audit payload."""
    claims = audit_payload.get("claims")
    if not isinstance(claims, list):
        return audit_payload

    for claim in claims:
        if not isinstance(claim, dict):
            continue
        cid = claim.get("id")
        if not isinstance(cid, str):
            continue
        check = vision_checks.get(cid)
        if not isinstance(check, dict):
            continue
        claim["vision_recheck"] = check
        v_verdict = check.get("verdict")
        if v_verdict == "contradicted":
            claim["verdict"] = "contradicted"
        elif v_verdict == "supported" and claim.get("verdict") in {"unsupported", "partially_supported"}:
            claim["verdict"] = "partially_supported"

    audit_payload["summary"] = _summarize_claims([c for c in claims if isinstance(c, dict)])
    return audit_payload


def build_claim_table_rows(audit_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert audit payload to flattened rows for CSV export."""
    rows: list[dict[str, Any]] = []
    claims = audit_payload.get("claims")
    if not isinstance(claims, list):
        return rows
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        numeric = claim.get("numeric_support") if isinstance(claim.get("numeric_support"), dict) else {}
        vision = claim.get("vision_recheck") if isinstance(claim.get("vision_recheck"), dict) else {}
        rows.append(
            {
                "id": claim.get("id"),
                "claim_type": claim.get("claim_type"),
                "verdict": claim.get("verdict"),
                "entailment": claim.get("entailment"),
                "confidence": claim.get("confidence"),
                "best_support_score": claim.get("best_support_score"),
                "numeric_matched": numeric.get("matched"),
                "vision_verdict": vision.get("verdict"),
                "uncertainty_score": (claim.get("uncertainty") or {}).get("score") if isinstance(claim.get("uncertainty"), dict) else None,
                "provenance_count": len(claim.get("provenance") or []) if isinstance(claim.get("provenance"), list) else 0,
                "text": claim.get("text"),
            }
        )
    return rows


def consistency_signature(audit_payload: dict[str, Any]) -> str:
    normalized = json.dumps(audit_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_text(normalized)

