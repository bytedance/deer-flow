"""Core metrics for academic evaluation."""

from __future__ import annotations

from math import isclose


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 1.0
    return max(0.0, min(1.0, numerator / denominator))


def metric_citation_fidelity(generated: list[str], verified: list[str]) -> float:
    if not generated:
        return 1.0
    verified_set = {v.strip().lower() for v in verified}
    generated_set = {g.strip().lower() for g in generated}
    correct = len(generated_set & verified_set)
    return _safe_ratio(correct, len(generated_set))


def metric_claim_grounding(claims: list[dict]) -> float:
    if not claims:
        return 1.0
    total = 0.0
    max_total = 0.0
    for claim in claims:
        claim_type = str(claim.get("type") or "weak").lower()
        has_evidence = bool(claim.get("has_evidence"))
        has_citation = bool(claim.get("has_citation"))
        if claim_type in {"strong", "result"}:
            max_total += 1.0
            total += 1.0 if (has_evidence and has_citation) else 0.0
        elif claim_type in {"method", "comparative", "causal", "numeric"}:
            max_total += 1.0
            total += 1.0 if has_evidence else 0.5 if has_citation else 0.0
        else:
            max_total += 1.0
            total += 1.0 if (has_evidence or has_citation) else 0.5
    return _safe_ratio(total, max_total)


def metric_abstract_body_consistency(abstract_numbers: list[float], body_numbers: list[float], *, tolerance: float = 1e-4) -> float:
    if not abstract_numbers:
        return 1.0
    if not body_numbers:
        return 0.0

    matched = 0
    for value in abstract_numbers:
        if any(isclose(value, candidate, rel_tol=tolerance, abs_tol=tolerance) for candidate in body_numbers):
            matched += 1
    return _safe_ratio(matched, len(abstract_numbers))


def metric_reviewer_rebuttal_completeness(comment_ids: list[str], addressed_ids: list[str]) -> float:
    if not comment_ids:
        return 1.0
    comments = {cid.strip() for cid in comment_ids}
    addressed = {aid.strip() for aid in addressed_ids}
    return _safe_ratio(len(comments & addressed), len(comments))


def metric_venue_fit(required_items: list[str], satisfied_items: list[str]) -> float:
    if not required_items:
        return 1.0
    required = {item.strip().lower() for item in required_items}
    satisfied = {item.strip().lower() for item in satisfied_items}
    return _safe_ratio(len(required & satisfied), len(required))


def metric_cross_modality_synthesis(expected_items: int, used_items: int) -> float:
    if expected_items <= 0:
        return 1.0
    return _safe_ratio(float(used_items), float(expected_items))


def metric_long_horizon_consistency(revision_terms: list[list[str]], revision_numbers: list[list[float]]) -> float:
    """Estimate consistency across revisions using term + number stability."""
    if len(revision_terms) <= 1 and len(revision_numbers) <= 1:
        return 1.0

    term_scores: list[float] = []
    for prev, curr in zip(revision_terms, revision_terms[1:], strict=False):
        prev_set = {t.lower() for t in prev}
        curr_set = {t.lower() for t in curr}
        union = len(prev_set | curr_set)
        intersection = len(prev_set & curr_set)
        term_scores.append(_safe_ratio(intersection, union if union else 1))

    number_scores: list[float] = []
    for prev_numbers, curr_numbers in zip(revision_numbers, revision_numbers[1:], strict=False):
        if not prev_numbers and not curr_numbers:
            number_scores.append(1.0)
            continue
        if not prev_numbers or not curr_numbers:
            number_scores.append(0.0)
            continue
        matched = 0
        for value in prev_numbers:
            if any(isclose(value, candidate, rel_tol=1e-4, abs_tol=1e-4) for candidate in curr_numbers):
                matched += 1
        number_scores.append(_safe_ratio(matched, len(prev_numbers)))

    merged = []
    if term_scores:
        merged.append(sum(term_scores) / len(term_scores))
    if number_scores:
        merged.append(sum(number_scores) / len(number_scores))
    return sum(merged) / len(merged) if merged else 1.0
