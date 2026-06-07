"""Tests for the probe sampler — stratified, seeded candidate sampling."""

import pytest
from tg_intel_crawler.probe.sampler import SampledCandidate, stratify_entry


def test_sampled_candidate_holds_all_fields():
    sc = SampledCandidate(
        key="douyinhao88",
        count=246,
        invite_hash=None,
        candidate_type="public",
        stratum="L3",
    )
    assert sc.key == "douyinhao88"
    assert sc.count == 246
    assert sc.invite_hash is None
    assert sc.candidate_type == "public"
    assert sc.stratum == "L3"


def test_sampled_candidate_private_keeps_invite_hash():
    sc = SampledCandidate(
        key="+abcXYZ",
        count=2,
        invite_hash="abcXYZ",
        candidate_type="private",
        stratum="L5",
    )
    assert sc.invite_hash == "abcXYZ"
    assert sc.candidate_type == "private"


@pytest.mark.parametrize("entry,expected", [
    ({"key": "a", "count": 1, "invite_hash": None}, "L1"),
    ({"key": "b", "count": 5, "invite_hash": None}, "L2"),
    ({"key": "c", "count": 9, "invite_hash": None}, "L2"),
    ({"key": "d", "count": 10, "invite_hash": None}, "L3"),
    ({"key": "e", "count": 1181, "invite_hash": None}, "L3"),
    ({"key": "+x", "count": 1, "invite_hash": "x"}, "L4"),
    ({"key": "+y", "count": 5, "invite_hash": "y"}, "L5"),
    ({"key": "+z", "count": 200, "invite_hash": "z"}, "L6"),
])
def test_stratify_entry(entry, expected):
    assert stratify_entry(entry) == expected


def test_stratify_uses_invite_hash_not_key_prefix():
    """A public group whose username happens to start with '+' should never
    appear in practice, but if it did we go by invite_hash, not key."""
    entry = {"key": "+weirdpublicname", "count": 5, "invite_hash": None}
    assert stratify_entry(entry) == "L2"  # public, count 2-9


from tg_intel_crawler.probe.sampler import Sampler


def _entry(key, count, private=False):
    return {
        "key": key,
        "count": count,
        "invite_hash": key.lstrip("+") if private else None,
        "status": "pending",
    }


def _build_pool(per_stratum=10):
    """Generate a synthetic pool with `per_stratum` entries in each L1..L6."""
    pool = []
    for i in range(per_stratum):
        pool.append(_entry(f"pub_low_{i}", 1))                   # L1
        pool.append(_entry(f"pub_mid_{i}", 5))                   # L2
        pool.append(_entry(f"pub_high_{i}", 50))                 # L3
        pool.append(_entry(f"+priv_low_{i}",  1, private=True))  # L4
        pool.append(_entry(f"+priv_mid_{i}",  5, private=True))  # L5
        pool.append(_entry(f"+priv_high_{i}", 50, private=True)) # L6
    return pool


def test_draw_returns_30_with_default_size():
    pool = _build_pool(per_stratum=10)
    samples = Sampler(seed=42).draw(pool, sample_size=30)
    assert len(samples) == 30


def test_draw_distributes_evenly_across_strata():
    pool = _build_pool(per_stratum=10)
    samples = Sampler(seed=42).draw(pool, sample_size=30)
    by_stratum: dict[str, int] = {}
    for s in samples:
        by_stratum[s.stratum] = by_stratum.get(s.stratum, 0) + 1
    assert by_stratum == {"L1": 5, "L2": 5, "L3": 5, "L4": 5, "L5": 5, "L6": 5}


def test_draw_is_reproducible_with_same_seed():
    pool = _build_pool(per_stratum=10)
    a = [s.key for s in Sampler(seed=42).draw(pool, sample_size=30)]
    b = [s.key for s in Sampler(seed=42).draw(pool, sample_size=30)]
    assert a == b


def test_draw_differs_with_different_seed():
    pool = _build_pool(per_stratum=10)
    a = [s.key for s in Sampler(seed=42).draw(pool, sample_size=30)]
    b = [s.key for s in Sampler(seed=99).draw(pool, sample_size=30)]
    assert a != b


def test_draw_handles_understocked_stratum():
    """If a stratum has fewer than per_layer entries, take all of it
    and DO NOT redistribute the deficit to other strata."""
    pool = (
        _build_pool(per_stratum=10)[: 6 * 10]   # 10 each across 6 strata
    )
    # Replace L3 with only 2 entries.
    pool = [e for e in pool if not e["key"].startswith("pub_high_")]
    pool.extend([_entry(f"pub_high_{i}", 50) for i in range(2)])

    samples = Sampler(seed=42).draw(pool, sample_size=30)
    by_stratum: dict[str, int] = {}
    for s in samples:
        by_stratum[s.stratum] = by_stratum.get(s.stratum, 0) + 1
    assert by_stratum["L3"] == 2
    # Other strata still get 5 each — no redistribution.
    assert by_stratum["L1"] == 5
    assert by_stratum["L2"] == 5
    # Total is 27, not 30, because the deficit isn't filled.
    assert len(samples) == 27


def test_draw_with_smaller_sample_size_distributes_evenly():
    """sample_size=12 → each stratum gets 2."""
    pool = _build_pool(per_stratum=10)
    samples = Sampler(seed=42).draw(pool, sample_size=12)
    by_stratum: dict[str, int] = {}
    for s in samples:
        by_stratum[s.stratum] = by_stratum.get(s.stratum, 0) + 1
    assert by_stratum == {"L1": 2, "L2": 2, "L3": 2, "L4": 2, "L5": 2, "L6": 2}


def test_draw_with_remainder_fills_high_count_strata_first():
    """sample_size=15 → 2 each (=12), remainder 3 goes to L3, L6, L2 in that order."""
    pool = _build_pool(per_stratum=10)
    samples = Sampler(seed=42).draw(pool, sample_size=15)
    by_stratum: dict[str, int] = {}
    for s in samples:
        by_stratum[s.stratum] = by_stratum.get(s.stratum, 0) + 1
    # Spec: remainder fills L3, L6, L2, L5, L1, L4 in order.
    assert by_stratum["L3"] == 3
    assert by_stratum["L6"] == 3
    assert by_stratum["L2"] == 3
    assert by_stratum["L1"] == 2
    assert by_stratum["L4"] == 2
    assert by_stratum["L5"] == 2


def test_draw_empty_pool_returns_empty():
    samples = Sampler(seed=42).draw([], sample_size=30)
    assert samples == []


def test_draw_populates_candidate_type_correctly():
    pool = _build_pool(per_stratum=10)
    samples = Sampler(seed=42).draw(pool, sample_size=30)
    for s in samples:
        if s.stratum in ("L1", "L2", "L3"):
            assert s.candidate_type == "public"
            assert s.invite_hash is None
        else:
            assert s.candidate_type == "private"
            assert s.invite_hash is not None
