"""Shadow evaluation of the memory pre-screen (Jev) from DeerMem extraction records.

This is the pre-``enforce`` evidence for ``TypeSafeMemoryPrescreen`` (design
``docs/superpowers/specs/2026-09-25-jev-memory-prescreening-design.en.md`` §5). It
is an operator run over **shadow records**, not a CI test: in ``mode: shadow`` the
extraction call always runs, so every pre-screen verdict comes with free ground
truth — that same batch's extraction outcome. The script makes no network call,
reads no credential and prints none; its input is a JSONL of DeerMem
``extraction_callback`` payloads, one per line.

What one line must contain (the payload the host already emits)
----------------------------------------------------------------

* ``prescreen`` — ``mode``/``verdict``/``probability``/``skip_threshold``/``model``/
  ``cached``/``digest``/``signals``/``message_count``/``batch_chars``/
  ``duration_ms``/``fallback_reason`` (the judge record, design §5);
* ``success`` and ``token_usage`` — the extraction call's own record;
* ``mutations_accepted`` — the pre-screen's "worth remembering" signal, written
  when the apply ran. ``> 0`` on a ``skip`` verdict means the skip would have lost
  a memory.

Fields the collector must add (absent from the production payload today)
-----------------------------------------------------------------------

* ``trivial_only`` (bool) — the batch's turns were all trivial (``filter_trivial``).
  The mandatory no-network baseline cannot be computed without it; coverage is
  reported instead of assumed.
* ``reviewed`` (bool) and optionally ``review_outcome`` (``worth_remembering`` |
  ``none_worth_remembering``) — the manual review that §5 gate 3 counts *and*
  whose verdict that gate reads: the review must confirm none of the reviewed
  skips was worth remembering, so a reviewed skip whose outcome (or
  ``mutations_accepted`` counter) says otherwise fails the gate. It is also a
  second ground-truth witness for a skip.
* ``stratum`` (string or list) / ``labels`` (list) — the §5 gate 2 subset, one of
  ``identity`` / ``preference`` / ``correction``. A human label, because L3 keeps
  signal-bearing batches out of the network population.
* ``cost_usd`` (float, optional) — the record's billed cost, when known.

Method, and the things it deliberately refuses to do
----------------------------------------------------

* Every record is classified into exactly one population: **network verdicts** (a
  request was really sent), **cache hits** (the same ``digest`` reused), **local
  fallbacks** (L3 / L4 / L5 / L7 / L8 or a failure fallback) and **unjudged** (no
  ``prescreen`` record was emitted at all: no side was enabled, or the round was
  forbidden to judge). Only network verdicts are
  classifier samples; mixing populations would let a cache hit or a local refusal
  vote on the model's accuracy.
* ``saved_call_rate`` (a skip that kept nothing, i.e. the call was really saved)
  and ``miss_rate`` (a skip that lost a memory) share the scored-skip denominator
  and therefore sum to 1; ``saved_call_rate_over_all_verdicts`` keeps the
  network-verdict denominator for the "how many calls did this save" reading.
* A record whose outcome is unknown (skip without ``mutations_accepted``, an
  extraction that failed before the apply) is **censored**: counted, reasoned
  about and excluded from the rates. It is never dropped to claim a pass.
* The no-network heuristic baseline is run over the same scored records as the
  model, so both rates have one denominator: the baseline skips a batch when
  ``signals`` is empty and ``trivial_only`` is true. If it already captures most
  of the saving, a third-party egress path is not justified. §5 gate 4 needs it
  *and* the recorded tokens and p50/p95 verdict latency: recorded calls alone are
  not the evidence the gate asks for, so missing any of them is ``INSUFFICIENT``
  rather than a pass.
* The miss-rate bound is the exact one-sided **Clopper-Pearson** interval,
  computed here from the regularized incomplete beta function by bisection. No
  normal approximation is used anywhere.
* The exit code carries the verdict: ``0`` only when every gate is ``PASS``,
  ``1`` when any gate is ``FAIL`` or ``INSUFFICIENT`` — so an operator can gate
  enablement on ``python scripts/eval_memory_prescreen.py --records ... && <enable>``.

Run from the ``backend/`` directory::

    PYTHONPATH=. uv run python scripts/eval_memory_prescreen.py --records /tmp/shadow.jsonl --json /tmp/prescreen-report.json
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NETWORK = "network"
CACHE_HIT = "cache_hit"
LOCAL_FALLBACK = "local_fallback"
UNJUDGED = "unjudged"
#: Every input record lands in exactly one of these.
POPULATIONS: tuple[str, ...] = (NETWORK, CACHE_HIT, LOCAL_FALLBACK, UNJUDGED)
#: The three populations design §5 defines; ``UNJUDGED`` is the coverage remainder.
DESIGN_POPULATIONS: tuple[str, ...] = (NETWORK, CACHE_HIT, LOCAL_FALLBACK)

VERDICT_SKIP = "skip"
VERDICT_EXTRACT = "extract"

PASS = "PASS"
FAIL = "FAIL"
INSUFFICIENT = "INSUFFICIENT"

REVIEW_WORTH_REMEMBERING = "worth_remembering"
REVIEW_NONE_WORTH_REMEMBERING = "none_worth_remembering"
REVIEW_OUTCOMES: tuple[str, ...] = (REVIEW_WORTH_REMEMBERING, REVIEW_NONE_WORTH_REMEMBERING)

#: The §5 gate 2 subset. Labels are collector-supplied human labels.
SENSITIVE_LABELS = frozenset({"identity", "preference", "correction"})

#: The coordinator's fallback reason -> the design lock it discharges.
FALLBACK_LOCKS: dict[str, str] = {
    "deterministic_signals": "L3",
    "emergency_flush": "L4",
    "over_limit": "L5",
    "shutdown_drain": "L7",
    "staleness_or_consolidation": "L8",
    "request_failed": "failure",
    "no_verdict": "failure",
    "disabled": "off",
}
UNRECORDED_REASON = "(unrecorded)"

CENSORED_EXTRACTION_FAILED = "extraction_failed"
CENSORED_OUTCOME_NOT_RECORDED = "outcome_not_recorded"

DEFAULT_MISS_TARGET = 0.01
DEFAULT_CONFIDENCE = 0.95
DEFAULT_MIN_REVIEWED_SKIPS = 200

_BETA_MAX_ITERATIONS = 300
_BETA_EPSILON = 3e-16
_BETA_TINY = 1e-300
_BETA_BISECTIONS = 200


def _as_int(value: Any) -> int | None:
    """An integer, refusing ``bool`` (``True`` is not a count of mutations)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _as_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _first_int(mapping: Mapping[str, Any], keys: Sequence[str]) -> int | None:
    for key in keys:
        value = _as_int(mapping.get(key))
        if value is not None:
            return value
    return None


def _token_counts(usage: Any) -> tuple[int | None, int | None, int | None]:
    """Read input / output / total tokens from a LangChain-style ``usage_metadata``."""
    if not isinstance(usage, Mapping):
        return (None, None, None)
    input_tokens = _first_int(usage, ("input_tokens", "prompt_tokens"))
    output_tokens = _first_int(usage, ("output_tokens", "completion_tokens"))
    total = _as_int(usage.get("total_tokens"))
    if total is None and (input_tokens is not None or output_tokens is not None):
        total = (input_tokens or 0) + (output_tokens or 0)
    return (input_tokens, output_tokens, total)


def _normalize_review_outcome(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    return text if text in REVIEW_OUTCOMES else None


def _sensitive_labels(raw: Mapping[str, Any]) -> frozenset[str]:
    """The record's ``identity`` / ``preference`` / ``correction`` labels, normalised."""
    found: set[str] = set()
    for key in ("stratum", "labels"):
        value = raw.get(key)
        if isinstance(value, str):
            candidates = [value]
        elif isinstance(value, (list, tuple, set, frozenset)):
            candidates = [item for item in value if isinstance(item, str)]
        else:
            continue
        for item in candidates:
            label = item.strip().lower()
            if label in SENSITIVE_LABELS:
                found.add(label)
    return frozenset(found)


@dataclass(frozen=True)
class Prices:
    """Operator-supplied list price, in USD per million tokens (``None`` = unpriced)."""

    input_per_mtok: float | None = None
    output_per_mtok: float | None = None

    @property
    def configured(self) -> bool:
        return self.input_per_mtok is not None or self.output_per_mtok is not None

    def estimate(self, input_tokens: int | None, output_tokens: int | None) -> float | None:
        if not self.configured or (input_tokens is None and output_tokens is None):
            return None
        dollars = (input_tokens or 0) * (self.input_per_mtok or 0.0) + (output_tokens or 0) * (self.output_per_mtok or 0.0)
        return dollars / 1_000_000.0

    def as_dict(self) -> dict[str, Any]:
        return {"input_per_mtok": self.input_per_mtok, "output_per_mtok": self.output_per_mtok}


@dataclass(frozen=True)
class Record:
    """One shadow record, reduced to what the evaluation reads."""

    index: int
    population: str
    verdict: str | None
    fallback_reason: str | None
    mode: str | None
    model: str | None
    cached: bool | None
    probability: float | None
    skip_threshold: float | None
    digest: str | None
    duration_ms: float | None
    signals: frozenset[str]
    signals_known: bool
    message_count: int | None
    batch_chars: int | None
    success: bool | None
    mutations_accepted: int | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cost_usd: float | None
    trivial_only: bool | None
    reviewed: bool
    review_outcome: str | None
    sensitive_labels: frozenset[str]
    censored: bool
    censored_reason: str | None

    @property
    def skip(self) -> bool:
        return self.verdict == VERDICT_SKIP

    @property
    def sensitive(self) -> bool:
        return bool(self.sensitive_labels)

    @property
    def scorable(self) -> bool:
        """Whether "was this batch worth remembering?" has an answer at all."""
        return self.mutations_accepted is not None or self.review_outcome is not None

    @property
    def miss(self) -> bool | None:
        """Whether a skip here would have lost a memory; ``None`` when not scorable.

        Either witness marks a miss: the ``mutations_accepted`` counter (design
        §5's definition) or a human ``review_outcome``. A review saying "not worth
        remembering" never clears a counter that says otherwise — an enablement
        gate reads the more conservative of the two.
        """
        if not self.scorable:
            return None
        if self.review_outcome == REVIEW_WORTH_REMEMBERING:
            return True
        return self.mutations_accepted is not None and self.mutations_accepted > 0


def classify_population(record: Mapping[str, Any]) -> str:
    """Place one raw record in exactly one population (design §5's table).

    A usable verdict means an answer was consumed: it is a cache hit when the
    adapter says so and a network verdict otherwise. No usable verdict means no
    request produced one — L3 / L4 / L5 / L7 / L8 or a failure fallback. No
    ``prescreen`` record at all means no side was enabled for this batch, or the
    round was forbidden to judge: an enabled side always emits its record, even
    when that record is a fallback.
    """
    prescreen = record.get("prescreen")
    if not isinstance(prescreen, Mapping):
        return UNJUDGED
    verdict = prescreen.get("verdict")
    if verdict not in (VERDICT_SKIP, VERDICT_EXTRACT):
        return LOCAL_FALLBACK
    return CACHE_HIT if prescreen.get("cached") is True else NETWORK


def _censored_reason(population: str, mutations_accepted: int | None, review_outcome: str | None, success: bool | None) -> str | None:
    """Why this sample has no outcome to score, or ``None`` when it has one."""
    if population not in (NETWORK, CACHE_HIT):
        return None
    if mutations_accepted is not None or review_outcome is not None:
        return None
    if success is False:
        return CENSORED_EXTRACTION_FAILED
    return CENSORED_OUTCOME_NOT_RECORDED


def parse_record(index: int, raw: Mapping[str, Any]) -> Record:
    """Reduce one payload to the fields the evaluation reads; never raises on shape."""
    block = raw.get("prescreen")
    block = block if isinstance(block, Mapping) else {}
    population = classify_population(raw)
    raw_verdict = block.get("verdict")
    verdict = raw_verdict if raw_verdict in (VERDICT_SKIP, VERDICT_EXTRACT) else None
    review_outcome = _normalize_review_outcome(raw.get("review_outcome"))
    mutations_accepted = _as_int(raw.get("mutations_accepted"))
    success = _as_bool(raw.get("success"))
    input_tokens, output_tokens, total_tokens = _token_counts(raw.get("token_usage"))
    raw_signals = block.get("signals")
    signals_known = isinstance(raw_signals, list)
    signals = frozenset(str(item) for item in raw_signals) if signals_known else frozenset()
    digest = block.get("digest")
    censored_reason = _censored_reason(population, mutations_accepted, review_outcome, success)
    return Record(
        index=index,
        population=population,
        verdict=verdict,
        fallback_reason=block.get("fallback_reason") if isinstance(block.get("fallback_reason"), str) else None,
        mode=block.get("mode") if isinstance(block.get("mode"), str) else None,
        model=block.get("model") if isinstance(block.get("model"), str) else None,
        cached=_as_bool(block.get("cached")),
        probability=_as_float(block.get("probability")),
        skip_threshold=_as_float(block.get("skip_threshold")),
        digest=digest if isinstance(digest, str) and digest else None,
        duration_ms=_as_float(block.get("duration_ms")),
        signals=signals,
        signals_known=signals_known,
        message_count=_as_int(block.get("message_count")),
        batch_chars=_as_int(block.get("batch_chars")),
        success=success,
        mutations_accepted=mutations_accepted,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_usd=_as_float(raw.get("cost_usd")),
        trivial_only=_as_bool(raw.get("trivial_only")),
        reviewed=_as_bool(raw.get("reviewed")) is True or review_outcome is not None,
        review_outcome=review_outcome,
        sensitive_labels=_sensitive_labels(raw),
        censored=censored_reason is not None,
        censored_reason=censored_reason,
    )


def _dig(record: Mapping[str, Any], path: str) -> Any:
    """Resolve a dotted ``--label`` path (``prescreen.mode``) against a raw record."""
    current: Any = record
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def record_matches(record: Mapping[str, Any], filters: Sequence[tuple[str, str]]) -> bool:
    """Whether every ``--label KEY=VALUE`` filter matches; strings compare as text."""
    for path, expected in filters:
        value = _dig(record, path)
        if isinstance(value, str):
            if value != expected:
                return False
            continue
        try:
            parsed = json.loads(expected)
        except json.JSONDecodeError:
            return False
        if value != parsed:
            return False
    return True


def parse_label_filter(text: str) -> tuple[str, str]:
    """``KEY=VALUE`` (dotted keys allowed) for ``--label``; argparse error otherwise."""
    key, separator, value = text.partition("=")
    if not separator or not key.strip():
        raise argparse.ArgumentTypeError(f"--label expects KEY=VALUE (e.g. prescreen.mode=shadow), got {text!r}")
    return key.strip(), value


@dataclass(frozen=True)
class LoadResult:
    records: tuple[Record, ...]
    read: int
    filtered_out: int
    malformed_lines: int
    blank_lines: int


def load_records(path: Path, filters: Sequence[tuple[str, str]] = ()) -> LoadResult:
    """Read the JSONL, apply ``--label`` filtering and parse each line.

    A line that is not a JSON object is *counted*, not dropped: gate D fails the
    run rather than silently shrinking the denominator.
    """
    records: list[Record] = []
    malformed = 0
    blank = 0
    read = 0
    filtered = 0
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            blank += 1
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(raw, Mapping):
            malformed += 1
            continue
        read += 1
        if filters and not record_matches(raw, filters):
            filtered += 1
            continue
        records.append(parse_record(number, raw))
    return LoadResult(records=tuple(records), read=read, filtered_out=filtered, malformed_lines=malformed, blank_lines=blank)


def _rate(numerator: int, denominator: int) -> float | None:
    return None if denominator <= 0 else numerator / denominator


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    """Nearest-rank quantile: the smallest sample at or above ``fraction`` of the mass."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def _latency(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"samples": 0, "p50": None, "p95": None}
    return {"samples": len(values), "p50": statistics.median(values), "p95": _percentile(values, 0.95)}


def _token_totals(rows: Sequence[Record]) -> dict[str, Any]:
    measured = [record for record in rows if record.input_tokens is not None or record.output_tokens is not None or record.total_tokens is not None]
    return {
        "records": len(measured),
        "input": sum(record.input_tokens or 0 for record in measured),
        "output": sum(record.output_tokens or 0 for record in measured),
        "total": sum(record.total_tokens if record.total_tokens is not None else (record.input_tokens or 0) + (record.output_tokens or 0) for record in measured),
    }


def _record_cost(record: Record, prices: Prices) -> float | None:
    if record.cost_usd is not None:
        return record.cost_usd
    return prices.estimate(record.input_tokens, record.output_tokens)


def _cost_totals(rows: Sequence[Record], prices: Prices) -> dict[str, Any]:
    costs = [_record_cost(record, prices) for record in rows]
    priced = [cost for cost in costs if cost is not None]
    if prices.configured:
        pricing = "cli price per million tokens"
    elif priced:
        pricing = "record cost_usd"
    else:
        pricing = "not configured"
    return {"total_usd": sum(priced) if priced else None, "priced_records": len(priced), "unpriced_records": len(costs) - len(priced), "pricing": pricing}


def summarize_population(records: Sequence[Record], population: str, prices: Prices = Prices()) -> dict[str, Any]:
    """One population's table row: counts, decision rates, latency, tokens and cost."""
    rows = [record for record in records if record.population == population]
    skips = [record for record in rows if record.skip]
    extracts = [record for record in rows if record.verdict == VERDICT_EXTRACT]
    scored_skips = [record for record in skips if record.scorable]
    saved = [record for record in scored_skips if record.miss is False]
    misses = [record for record in scored_skips if record.miss is True]
    reason_rows = [record.fallback_reason or UNRECORDED_REASON for record in rows if record.population == LOCAL_FALLBACK or record.fallback_reason is not None]
    summary: dict[str, Any] = {
        "records": len(rows),
        "censored": sum(1 for record in rows if record.censored),
        "censored_reasons": dict(Counter(record.censored_reason for record in rows if record.censored_reason)),
        "verdicts": {"skip": len(skips), "extract": len(extracts), "none": len(rows) - len(skips) - len(extracts)},
        "cached": {
            "true": sum(1 for record in rows if record.cached is True),
            "false": sum(1 for record in rows if record.cached is False),
            "unknown": sum(1 for record in rows if record.cached is None),
        },
        "skip_rate": _rate(len(skips), len(rows)),
        "scored_skips": len(scored_skips),
        "saved_calls": len(saved),
        "misses": len(misses),
        "saved_call_rate": _rate(len(saved), len(scored_skips)),
        "miss_rate": _rate(len(misses), len(scored_skips)),
        "saved_call_rate_over_all_verdicts": _rate(len(saved), len(rows)),
        "missed_digests": [record.digest for record in misses if record.digest],
        "latency_ms": _latency([record.duration_ms for record in rows if record.duration_ms is not None]),
        "tokens": _token_totals(rows),
        "cost": _cost_totals(rows, prices),
    }
    if reason_rows:
        summary["fallback_reasons"] = dict(Counter(reason_rows))
        summary["fallback_locks"] = dict(Counter(FALLBACK_LOCKS.get(reason, "unknown") for reason in reason_rows))
    return summary


def _beta_continued_fraction(a: float, b: float, x: float) -> float:
    """Lentz's continued fraction for the incomplete beta function (Numerical Recipes)."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _BETA_TINY:
        d = _BETA_TINY
    d = 1.0 / d
    h = d
    for m in range(1, _BETA_MAX_ITERATIONS + 1):
        m2 = 2 * m
        numerator = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + numerator * d
        if abs(d) < _BETA_TINY:
            d = _BETA_TINY
        c = 1.0 + numerator / c
        if abs(c) < _BETA_TINY:
            c = _BETA_TINY
        d = 1.0 / d
        h *= d * c
        numerator = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + numerator * d
        if abs(d) < _BETA_TINY:
            d = _BETA_TINY
        c = 1.0 + numerator / c
        if abs(c) < _BETA_TINY:
            c = _BETA_TINY
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _BETA_EPSILON:
            break
    return h


def _regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    """``I_x(a, b)``, the regularized incomplete beta function."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _beta_continued_fraction(a, b, x) / a
    return 1.0 - front * _beta_continued_fraction(b, a, 1.0 - x) / b


def _beta_quantile(probability: float, a: float, b: float) -> float:
    """Inverse of :func:`_regularized_incomplete_beta` in ``x`` (bisection; monotone)."""
    if probability <= 0.0:
        return 0.0
    if probability >= 1.0:
        return 1.0
    low, high = 0.0, 1.0
    for _ in range(_BETA_BISECTIONS):
        middle = (low + high) / 2.0
        if _regularized_incomplete_beta(a, b, middle) < probability:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def clopper_pearson_upper(misses: int, skips: int, confidence: float = DEFAULT_CONFIDENCE) -> float | None:
    """Exact one-sided Clopper-Pearson upper bound for the miss rate.

    Solves ``P(X <= misses) = 1 - confidence`` for the proportion ``p``, i.e.
    ``I_{1-p}(skips - misses, misses + 1) = 1 - confidence``, by bisection on the
    regularized incomplete beta. This is the textbook exact bound: no normal
    approximation is used anywhere in this script. ``None`` when there is no
    sample, ``1.0`` when every skip was a miss.
    """
    if skips <= 0:
        return None
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0, 1), got {confidence!r}")
    misses = max(0, min(misses, skips))
    if misses >= skips:
        return 1.0
    bound = 1.0 - _beta_quantile(1.0 - confidence, float(skips - misses), float(misses + 1))
    return min(1.0, max(0.0, bound))


def baseline_summary(records: Sequence[Record], prices: Prices = Prices()) -> dict[str, Any]:
    """The mandatory no-network baseline, over the same scored records as the model.

    A batch is a baseline skip when it carries no deterministic signal and the
    collector marked it ``trivial_only``. Records without ``trivial_only`` (or
    without a readable ``signals`` list) cannot be scored by the heuristic: the
    coverage is reported instead of silently shrinking the denominator.
    """
    evaluated = [record for record in records if record.population == NETWORK]
    computable = [record for record in evaluated if record.trivial_only is not None and record.signals_known]
    scored = [record for record in computable if record.scorable]
    baseline_skips = [record for record in scored if record.trivial_only and not record.signals]
    baseline_saved = [record for record in baseline_skips if record.miss is False]
    baseline_misses = [record for record in baseline_skips if record.miss is True]
    model_skips = [record for record in scored if record.skip]
    model_saved = [record for record in model_skips if record.miss is False]
    model_misses = [record for record in model_skips if record.miss is True]
    baseline_saved_rate = _rate(len(baseline_saved), len(baseline_skips))
    model_saved_rate = _rate(len(model_saved), len(model_skips))
    return {
        "rule": "skip when signals is empty and trivial_only is true",
        "evaluated_verdicts": len(evaluated),
        "computable": len(computable),
        "coverage": _rate(len(computable), len(evaluated)),
        "scored": len(scored),
        "skips": len(baseline_skips),
        "saved_calls": len(baseline_saved),
        "misses": len(baseline_misses),
        "saved_call_rate": baseline_saved_rate,
        "miss_rate": _rate(len(baseline_misses), len(baseline_skips)),
        "model": {
            "skips": len(model_skips),
            "saved_calls": len(model_saved),
            "misses": len(model_misses),
            "saved_call_rate": model_saved_rate,
            "miss_rate": _rate(len(model_misses), len(model_skips)),
        },
        "incremental_saved_calls": len(model_saved) - len(baseline_saved),
        # Difference of saved calls over the shared denominator. Subtracting the
        # conditional rates (saved/skips) would report zero whenever both policies
        # saved every batch they skipped, even if the model skipped far more.
        "incremental_saved_call_rate": _rate(len(model_saved) - len(baseline_saved), len(scored)),
        "trivial_only_missing": sum(1 for record in evaluated if record.trivial_only is None),
        "signals_missing": sum(1 for record in evaluated if not record.signals_known),
        "note": "Both sides are scored over the same scored records; a baseline that nearly matches the model means the third-party egress buys little.",
        "cost": _cost_totals(scored, prices),
    }


@dataclass(frozen=True)
class Gate:
    gate_id: str
    status: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"id": self.gate_id, "status": self.status, "detail": self.detail}


@dataclass(frozen=True)
class Evidence:
    """The numbers the design §5 gates read (network population only)."""

    scored_skips: int
    misses: int
    saved_calls: int
    sensitive_scored_skips: Mapping[str, int]
    sensitive_misses: Mapping[str, int]
    reviewed_skips: int
    reviewed_scored_skips: int
    reviewed_missed: int
    saved_skips_with_tokens: int
    latency_samples: int
    baseline_computable: int


@dataclass(frozen=True)
class Coverage:
    """Accounting for the records that could not be scored."""

    records: int
    censored: int
    malformed_lines: int


@dataclass(frozen=True)
class Thresholds:
    miss_target: float = DEFAULT_MISS_TARGET
    confidence: float = DEFAULT_CONFIDENCE
    min_reviewed_skips: int = DEFAULT_MIN_REVIEWED_SKIPS


def evaluate_gates(evidence: Evidence, coverage: Coverage, thresholds: Thresholds = Thresholds()) -> tuple[Gate, ...]:
    """Every gate prints ``PASS`` / ``FAIL`` / ``INSUFFICIENT`` — never silence."""
    gates: list[Gate] = []
    miss_rate = _rate(evidence.misses, evidence.scored_skips)
    upper = clopper_pearson_upper(evidence.misses, evidence.scored_skips, thresholds.confidence)
    if miss_rate is None:
        gates.append(Gate("network_miss_rate", INSUFFICIENT, "no scored skip verdict in the network population; there is no sample for the miss rate or its bound"))
    else:
        status = PASS if miss_rate <= thresholds.miss_target else FAIL
        detail = f"miss_rate={evidence.misses}/{evidence.scored_skips}={miss_rate:.4f} target<={thresholds.miss_target:.4f}; one-sided {thresholds.confidence:.0%} Clopper-Pearson upper bound {upper:.4f} (sample n={evidence.scored_skips})"
        if status == PASS and upper is not None and upper > thresholds.miss_target:
            detail += f"; the point estimate is met but the exact upper bound exceeds the target ({upper:.4f} > {thresholds.miss_target:.4f}) - report the bound, do not read the point estimate as proof"
        gates.append(Gate("network_miss_rate", status, detail))

    missed_by_label = {label: evidence.sensitive_misses.get(label, 0) for label in sorted(SENSITIVE_LABELS)}
    uncovered = [label for label in sorted(SENSITIVE_LABELS) if evidence.sensitive_scored_skips.get(label, 0) == 0]
    per_label = "; ".join(f"{label}: {missed_by_label[label]} miss(es) over {evidence.sensitive_scored_skips.get(label, 0)} scored skip(s)" for label in sorted(SENSITIVE_LABELS))
    if any(count > 0 for count in missed_by_label.values()):
        gates.append(Gate("sensitive_stratum_zero_misses", FAIL, f"a scored skip in a required stratum was worth remembering ({per_label})"))
    elif uncovered:
        gates.append(Gate("sensitive_stratum_zero_misses", INSUFFICIENT, f"no scored skip carries the {uncovered} stratum label(s); the zero-miss check needs evidence for every required stratum {sorted(SENSITIVE_LABELS)} ({per_label})"))
    else:
        gates.append(Gate("sensitive_stratum_zero_misses", PASS, f"zero misses in every required stratum ({per_label})"))

    if evidence.reviewed_skips == 0:
        gates.append(Gate("reviewed_skips_confirm_no_loss", INSUFFICIENT, f"no skip verdict is labelled reviewed; the collector must set reviewed=true / review_outcome (target >={thresholds.min_reviewed_skips})"))
    elif evidence.reviewed_missed:
        gates.append(Gate("reviewed_skips_confirm_no_loss", FAIL, f"{evidence.reviewed_missed} reviewed skip verdict(s) were worth remembering; design §5 gate 3 is a review *confirming* none was, so the review sample contradicts the skip"))
    elif evidence.reviewed_skips < thresholds.min_reviewed_skips:
        gates.append(Gate("reviewed_skips_confirm_no_loss", FAIL, f"{evidence.reviewed_skips} reviewed skip verdict(s) of {thresholds.min_reviewed_skips} required ({evidence.reviewed_scored_skips} of them scored)"))
    elif evidence.reviewed_scored_skips < evidence.reviewed_skips:
        gates.append(
            Gate(
                "reviewed_skips_confirm_no_loss",
                INSUFFICIENT,
                f"{evidence.reviewed_skips - evidence.reviewed_scored_skips} of {evidence.reviewed_skips} reviewed skip(s) carry neither a review_outcome nor mutations_accepted, so the review confirms nothing for them",
            )
        )
    else:
        gates.append(Gate("reviewed_skips_confirm_no_loss", PASS, f"{evidence.reviewed_skips} reviewed skip verdict(s), all scored, none worth remembering ({thresholds.min_reviewed_skips} required)"))

    if coverage.records == 0:
        gates.append(Gate("censoring_disclosed", INSUFFICIENT, "no record was read; there is nothing to account for"))
    elif coverage.malformed_lines > 0:
        gates.append(Gate("censoring_disclosed", FAIL, f"{coverage.malformed_lines} input line(s) were not parseable JSON objects; they were counted but must not be dropped from the denominator"))
    else:
        gates.append(Gate("censoring_disclosed", PASS, f"{coverage.censored} censored sample(s) of {coverage.records} reported with their reasons; none dropped"))

    if evidence.scored_skips == 0:
        gates.append(Gate("savings_recorded", INSUFFICIENT, "no scored skip verdict, so no saved extraction call is recorded"))
    elif evidence.saved_calls == 0:
        gates.append(Gate("savings_recorded", FAIL, f"no scored skip saved an extraction call over {evidence.scored_skips} scored skip(s); the pre-screen as recorded saves nothing"))
    else:
        absent = [
            name
            for name, count in (
                ("tokens on the saved skips", evidence.saved_skips_with_tokens),
                ("verdict latency", evidence.latency_samples),
                ("the no-network baseline (collector field trivial_only)", evidence.baseline_computable),
            )
            if count == 0
        ]
        if absent:
            gates.append(
                Gate(
                    "savings_recorded",
                    INSUFFICIENT,
                    f"{evidence.saved_calls} extraction call(s) recorded saved, but the evidence is incomplete: nothing recorded for "
                    + "; ".join(absent)
                    + " - design §5 gate 4 asks for recorded calls/tokens saved, their p50/p95 latency cost, and the mandatory baseline",
                )
            )
        else:
            recorded = f"{evidence.saved_calls} extraction call(s) recorded saved over {evidence.scored_skips} scored skip(s)"
            observed = f"tokens on {evidence.saved_skips_with_tokens} of them, {evidence.latency_samples} verdict latency sample(s), baseline on {evidence.baseline_computable} record(s)"
            gates.append(Gate("savings_recorded", PASS, f"{recorded}; {observed}"))

    return tuple(gates)


def build_report(
    records: Sequence[Record],
    *,
    source: str,
    malformed_lines: int = 0,
    filtered_out: int = 0,
    read_lines: int = 0,
    blank_lines: int = 0,
    thresholds: Thresholds = Thresholds(),
    prices: Prices = Prices(),
    label_filters: Sequence[tuple[str, str]] = (),
) -> dict[str, Any]:
    """Assemble the full report: populations, model, baseline, stratification, gates."""
    populations = {name: summarize_population(records, name, prices) for name in POPULATIONS}
    network = [record for record in records if record.population == NETWORK]
    scored_skips = [record for record in network if record.skip and record.scorable]
    sensitive_scored_skips = {label: sum(1 for record in scored_skips if label in record.sensitive_labels) for label in sorted(SENSITIVE_LABELS)}
    sensitive_misses = {label: sum(1 for record in scored_skips if label in record.sensitive_labels and record.miss is True) for label in sorted(SENSITIVE_LABELS)}
    reviewed_skips = [record for record in network if record.skip and record.reviewed]
    saved = [record for record in scored_skips if record.miss is False]
    baseline = baseline_summary(records, prices)
    evidence = Evidence(
        scored_skips=len(scored_skips),
        misses=sum(1 for record in scored_skips if record.miss is True),
        saved_calls=len(saved),
        sensitive_scored_skips=sensitive_scored_skips,
        sensitive_misses=sensitive_misses,
        reviewed_skips=len(reviewed_skips),
        reviewed_scored_skips=sum(1 for record in reviewed_skips if record.scorable),
        reviewed_missed=sum(1 for record in reviewed_skips if record.miss is True),
        saved_skips_with_tokens=sum(1 for record in saved if record.total_tokens is not None),
        latency_samples=sum(1 for record in network if record.duration_ms is not None),
        baseline_computable=baseline["computable"],
    )
    coverage = Coverage(records=len(records), censored=sum(1 for record in records if record.censored), malformed_lines=malformed_lines)
    gates = evaluate_gates(evidence, coverage, thresholds)
    verdicts = populations[NETWORK]["verdicts"]
    upper = clopper_pearson_upper(evidence.misses, evidence.scored_skips, thresholds.confidence)
    modes = Counter(record.mode for record in records if record.mode)
    notes = [
        "One record is exactly one population: network verdicts are the only classifier samples; cache hits reuse another verdict and local fallbacks never asked.",
        "saved_call_rate and miss_rate share the scored-skip denominator (so they sum to 1); saved_call_rate_over_all_verdicts keeps the network-verdict denominator.",
        "The no-network baseline needs the collector's trivial_only field; its coverage is reported rather than assumed.",
        "This report embeds no raw record, no conversation text and no credential.",
    ]
    if modes.get("enforce"):
        notes.append("Records with mode=enforce carry no extraction outcome for a skip (no call ran), so such a skip is censored unless the collector records a review_outcome; a miss rate is only meaningful over shadow records.")
    report: dict[str, Any] = {
        "script": "eval_memory_prescreen",
        "source": source,
        "input": {
            "records": len(records),
            "read_lines": read_lines,
            "filtered_out": filtered_out,
            "malformed_lines": malformed_lines,
            "blank_lines": blank_lines,
            "label_filters": [f"{key}={value}" for key, value in label_filters],
        },
        "thresholds": {"miss_target": thresholds.miss_target, "confidence": thresholds.confidence, "min_reviewed_skips": thresholds.min_reviewed_skips},
        "pricing": prices.as_dict(),
        "populations": populations,
        "model": {
            "population": NETWORK,
            "scope": "network verdicts only: the classifier samples",
            "modes": dict(modes),
            "verdicts": verdicts,
            "skip_rate": populations[NETWORK]["skip_rate"],
            "scored_skips": evidence.scored_skips,
            "saved_calls": evidence.saved_calls,
            "saved_call_rate": populations[NETWORK]["saved_call_rate"],
            "saved_call_rate_over_all_verdicts": populations[NETWORK]["saved_call_rate_over_all_verdicts"],
            "misses": evidence.misses,
            "miss_rate": populations[NETWORK]["miss_rate"],
            "miss_rate_upper_bound": {"method": "clopper-pearson one-sided exact", "confidence": thresholds.confidence, "value": upper, "misses": evidence.misses, "scored_skips": evidence.scored_skips},
            "missed_digests": populations[NETWORK]["missed_digests"],
            "latency_ms": populations[NETWORK]["latency_ms"],
            "tokens": populations[NETWORK]["tokens"],
            "cost": populations[NETWORK]["cost"],
        },
        "baseline_heuristic": baseline,
        "sensitive_stratum": {
            "labels": sorted(SENSITIVE_LABELS),
            "by_label": {label: {"scored_skips": sensitive_scored_skips[label], "misses": sensitive_misses[label]} for label in sorted(SENSITIVE_LABELS)},
            "note": (
                "Labels come from the collector's stratum/labels field; L3 keeps signal-bearing batches out of the "
                "network population, so this is a human label. The gate checks every required stratum separately, "
                "because a pooled sample can hide a stratum with no evidence."
            ),
        },
        "review": {
            "reviewed_skips": evidence.reviewed_skips,
            "reviewed_scored_skips": evidence.reviewed_scored_skips,
            "reviewed_missed": evidence.reviewed_missed,
            "review_outcomes": dict(Counter(record.review_outcome for record in network if record.review_outcome)),
            "note": "reviewed comes from the collector; review_outcome is a second ground-truth witness for a skip. Gate 3 requires the review to confirm none was worth remembering, so a reviewed skip found worth remembering fails it.",
        },
        "censoring": {
            "records": len(records),
            "censored": coverage.censored,
            "reasons": dict(Counter(record.censored_reason for record in records if record.censored_reason)),
            "malformed_lines": malformed_lines,
            "note": "A censored sample has no outcome to score; it is counted and reported, never dropped.",
        },
        "collector_contract": {
            "from the DeerMem extraction_callback payload": "prescreen.{mode,verdict,probability,skip_threshold,model,cached,digest,signals,message_count,batch_chars,duration_ms,fallback_reason}, success, token_usage, mutations_accepted",
            "must be added by the collector": {
                "trivial_only": "bool - every turn in the batch was trivial (filter_trivial); the no-network baseline cannot be computed without it",
                "reviewed": "bool - a human reviewed this skip verdict (design §5 gate 3)",
                "review_outcome": "worth_remembering | none_worth_remembering (optional; a second ground-truth witness)",
                "stratum": "identity | preference | correction (or a labels list); design §5 gate 2 subset",
                "cost_usd": "float (optional) - the record's billed cost, when the collector knows it",
            },
        },
        "notes": notes,
        "gates": [gate.as_dict() for gate in gates],
        "gate_summary": {
            "passed": [gate.gate_id for gate in gates if gate.status == PASS],
            "failed": [gate.gate_id for gate in gates if gate.status == FAIL],
            "insufficient": [gate.gate_id for gate in gates if gate.status == INSUFFICIENT],
            "enable_recommended": all(gate.status == PASS for gate in gates),
        },
    }
    return report


def _format_rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _format_ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}ms"


def _format_ratio(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def _format_cost(cost: Mapping[str, Any]) -> str:
    if cost["total_usd"] is None:
        return f"not configured ({cost['unpriced_records']} record(s) with no --price-in/--price-out and no record cost_usd)"
    return f"${cost['total_usd']:.4f} ({cost['pricing']}; {cost['priced_records']} priced / {cost['unpriced_records']} unpriced)"


def print_report(report: Mapping[str, Any]) -> None:
    """Print the populations table, the baseline comparison and every gate verdict."""
    input_summary = report["input"]
    filters = ", ".join(input_summary["label_filters"]) or "none"
    print(f"\nMemory pre-screen shadow evaluation: {report['source']}")
    print(f"records: {input_summary['records']} scored; {input_summary['filtered_out']} filtered out; {input_summary['malformed_lines']} malformed line(s); {input_summary['blank_lines']} blank line(s); label filters: {filters}")
    print("\nPopulations (mutually exclusive, design section 5; only network verdicts are classifier samples):")
    print(f"  {'population':<15}{'n':>5}{'skip':>6}{'extract':>8}{'cached':>7}{'censored':>9}{'p50':>10}{'p95':>10}")
    for name in POPULATIONS:
        summary = report["populations"][name]
        latency = summary["latency_ms"]
        print(f"  {name:<15}{summary['records']:>5}{summary['verdicts']['skip']:>6}{summary['verdicts']['extract']:>8}{summary['cached']['true']:>7}{summary['censored']:>9}{_format_ms(latency['p50']):>10}{_format_ms(latency['p95']):>10}")
    for name in DESIGN_POPULATIONS:
        reasons = report["populations"][name].get("fallback_reasons")
        if reasons:
            rendered = ", ".join(f"{reason}={count} [{FALLBACK_LOCKS.get(reason, 'unknown')}]" for reason, count in sorted(reasons.items()))
            print(f"  {name} reasons: {rendered}")

    model = report["model"]
    verdicts = model["verdicts"]
    print(f"\nModel verdicts ({model['scope']}; modes {model['modes'] or 'none'}):")
    print(f"  skip_rate {_format_rate(model['skip_rate'])} ({verdicts['skip']} skip / {verdicts['extract']} extract / {verdicts['none']} no verdict)")
    print(f"  scored skips {model['scored_skips']}; saved calls {model['saved_calls']} = {_format_rate(model['saved_call_rate'])} of scored skips ({_format_rate(model['saved_call_rate_over_all_verdicts'])} of all network verdicts)")
    print(f"  missed memories {model['misses']} = miss_rate {_format_rate(model['miss_rate'])} (a skip with mutations_accepted > 0)")
    bound = model["miss_rate_upper_bound"]
    print(f"  miss-rate upper bound: {_format_ratio(bound['value'])} one-sided at {bound['confidence']:.0%} ({bound['method']}, misses={bound['misses']}, n={bound['scored_skips']})")
    latency = model["latency_ms"]
    tokens = model["tokens"]
    print(f"  verdict latency p50 {_format_ms(latency['p50'])} p95 {_format_ms(latency['p95'])} (n={latency['samples']})")
    print(f"  tokens in={tokens['input']} out={tokens['output']} total={tokens['total']} (n={tokens['records']}); cost {_format_cost(model['cost'])}")
    if model["missed_digests"]:
        print(f"  missed digests: {', '.join(model['missed_digests'])}")

    baseline = report["baseline_heuristic"]
    print(f"\nNo-network heuristic baseline ({baseline['rule']}):")
    coverage = f"{baseline['computable']}/{baseline['evaluated_verdicts']}"
    print(f"  computable on {coverage} network verdicts (coverage {_format_rate(baseline['coverage'])})")
    print(f"  collector field trivial_only missing on {baseline['trivial_only_missing']} record(s); signals missing on {baseline['signals_missing']}")
    baseline_rates = f"saved {_format_rate(baseline['saved_call_rate'])}, miss {_format_rate(baseline['miss_rate'])}"
    print(f"  baseline: skips {baseline['skips']}, saved calls {baseline['saved_calls']}, misses {baseline['misses']} ({baseline_rates})")
    model_on_set = baseline["model"]
    model_rates = f"saved {_format_rate(model_on_set['saved_call_rate'])}, miss {_format_rate(model_on_set['miss_rate'])}"
    print(f"  model on the same {baseline['scored']} scored record(s): skips {model_on_set['skips']}, saved calls {model_on_set['saved_calls']}, misses {model_on_set['misses']} ({model_rates})")
    print(f"  incremental saved calls {baseline['incremental_saved_calls']} ({_format_rate(baseline['incremental_saved_call_rate'])} of the scored records)")

    sensitive = report["sensitive_stratum"]
    review = report["review"]
    censoring = report["censoring"]
    per_label = "; ".join(f"{label}: {data['misses']} miss(es) over {data['scored_skips']} scored skip(s)" for label, data in sensitive["by_label"].items())
    print(f"\nSensitive strata ({', '.join(sensitive['labels'])}): {per_label}.")
    print(f"Review sample: {review['reviewed_skips']} reviewed skip verdict(s) ({review['reviewed_scored_skips']} scored, {review['reviewed_missed']} found worth remembering); review outcomes: {review['review_outcomes'] or 'none'}.")
    print(f"Censoring: {censoring['censored']} censored of {censoring['records']} record(s) {censoring['reasons'] or ''}; malformed lines {censoring['malformed_lines']}.")

    print("\nGates before enforce (design section 5):")
    for gate in report["gates"]:
        print(f"  [{gate['status']:<12}] {gate['id']}: {gate['detail']}")
    summary = report["gate_summary"]
    if summary["enable_recommended"]:
        print("\nEvaluation gates PASSED: every gate is PASS; enforce may be enabled for a controlled window.")
    else:
        print(f"\nDO NOT ENABLE: {len(summary['failed'])} gate(s) failed, {len(summary['insufficient'])} gate(s) lack evidence.")
        if summary["failed"]:
            print(f"  failed: {', '.join(summary['failed'])}")
        if summary["insufficient"]:
            print(f"  insufficient: {', '.join(summary['insufficient'])}")
    print("\nNotes:")
    for note in report["notes"]:
        print(f"  - {note}")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--records", type=Path, required=True, help="JSONL of shadow records: one DeerMem extraction_callback payload per line")
    parser.add_argument("--label", action="append", type=parse_label_filter, default=[], metavar="KEY=VALUE", help="keep only records whose (dotted) field matches; repeatable, all must match")
    parser.add_argument("--json", type=Path, default=None, help="write the full report as JSON to this path")
    parser.add_argument("--miss-target", type=float, default=DEFAULT_MISS_TARGET, help="miss-rate point estimate the gate accepts (default: %(default)s)")
    parser.add_argument("--confidence", type=float, default=DEFAULT_CONFIDENCE, help="confidence for the Clopper-Pearson upper bound (default: %(default)s)")
    parser.add_argument("--min-reviewed-skips", type=int, default=DEFAULT_MIN_REVIEWED_SKIPS, help="reviewed skip verdicts required before enforce (default: %(default)s)")
    parser.add_argument("--price-in", type=float, default=None, help="Jev input price in USD per million tokens (optional; enables the cost estimate)")
    parser.add_argument("--price-out", type=float, default=None, help="Jev output price in USD per million tokens (optional; enables the cost estimate)")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the evaluation; the exit code is the gate verdict (0 only when all PASS)."""
    args = _parse_args(argv)
    loaded = load_records(args.records, args.label)
    thresholds = Thresholds(miss_target=args.miss_target, confidence=args.confidence, min_reviewed_skips=args.min_reviewed_skips)
    prices = Prices(input_per_mtok=args.price_in, output_per_mtok=args.price_out)
    report = build_report(
        loaded.records,
        source=str(args.records),
        malformed_lines=loaded.malformed_lines,
        filtered_out=loaded.filtered_out,
        read_lines=loaded.read,
        blank_lines=loaded.blank_lines,
        thresholds=thresholds,
        prices=prices,
        label_filters=args.label,
    )
    print_report(report)
    if args.json is not None:
        args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nJSON report: {args.json}")
    return 0 if report["gate_summary"]["enable_recommended"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
