"""Stratified, seeded sampling of CandidatePool entries for the probe."""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class SampledCandidate:
    """One candidate picked for the probe, with the stratum it was drawn from."""

    key: str                    # e.g. "douyinhao88" or "+abcXYZ"
    count: int                  # cumulative count from the pool
    invite_hash: str | None     # preserved for private candidates; None for public
    candidate_type: str         # "public" | "private"
    stratum: str                # "L1".."L6"


def _count_band(count: int) -> str:
    """Bucket count into one of three bands: 'low' / 'mid' / 'high'."""
    if count <= 1:
        return "low"
    if count <= 9:
        return "mid"
    return "high"


def stratify_entry(entry: dict) -> str:
    """Map a CandidatePool entry to one of 6 strata.

    L1: public, count = 1
    L2: public, count 2-9
    L3: public, count >= 10
    L4: private, count = 1
    L5: private, count 2-9
    L6: private, count >= 10

    Public/private is determined by ``invite_hash`` (None means public),
    NOT by the leading '+' in the key — the key is just a display form.
    """
    is_private = entry.get("invite_hash") is not None
    band = _count_band(int(entry.get("count", 0)))
    table = {
        ("public",  "low"):  "L1",
        ("public",  "mid"):  "L2",
        ("public",  "high"): "L3",
        ("private", "low"):  "L4",
        ("private", "mid"):  "L5",
        ("private", "high"): "L6",
    }
    kind = "private" if is_private else "public"
    return table[(kind, band)]


# Order in which leftover slots are distributed when sample_size doesn't
# divide evenly by 6. High-count strata get the extras first because
# they're rarer in real candidate pools and more informative when present.
_REMAINDER_ORDER = ["L3", "L6", "L2", "L5", "L1", "L4"]
_ALL_STRATA = ["L1", "L2", "L3", "L4", "L5", "L6"]


class Sampler:
    """Stratified, seeded sampling of CandidatePool entries.

    Default ``sample_size=30`` produces 5 per stratum across 6 strata.
    If a stratum has fewer than its quota, take all of it without
    redistributing the deficit (preserves stratum semantics).
    """

    def __init__(self, seed: int = 42):
        self._rng = random.Random(seed)

    def draw(self, pool: list[dict], sample_size: int = 30) -> list[SampledCandidate]:
        if not pool:
            return []

        # 1. Bucket the pool by stratum.
        buckets: dict[str, list[dict]] = {s: [] for s in _ALL_STRATA}
        for entry in pool:
            buckets[stratify_entry(entry)].append(entry)

        # 2. Compute per-stratum quota: floor(size/6) plus remainder
        #    distributed in _REMAINDER_ORDER.
        base = sample_size // 6
        remainder = sample_size - base * 6
        quota: dict[str, int] = {s: base for s in _ALL_STRATA}
        for s in _REMAINDER_ORDER[:remainder]:
            quota[s] += 1

        # 3. Sample each stratum independently.
        out: list[SampledCandidate] = []
        for stratum in _ALL_STRATA:
            available = buckets[stratum]
            want = min(quota[stratum], len(available))
            if want <= 0:
                continue
            picks = self._rng.sample(available, k=want)
            for entry in picks:
                out.append(SampledCandidate(
                    key=entry["key"],
                    count=int(entry.get("count", 0)),
                    invite_hash=entry.get("invite_hash"),
                    candidate_type="private" if entry.get("invite_hash") else "public",
                    stratum=stratum,
                ))
        return out
