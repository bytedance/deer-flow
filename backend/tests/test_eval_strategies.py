from datetime import UTC, datetime, timedelta

from deerflow.agents.memory.eval.strategies import ConfidenceOnlyStrategy, MultiSignalStrategy
from deerflow.agents.memory.retrieval_trace import CandidateFact


def _make_candidate(**overrides) -> CandidateFact:
    defaults = {
        "fact_id": "f1",
        "content_preview": "x" * 40,
        "category": "knowledge",
        "confidence": 0.8,
        "layer": None,
        "created_at": None,
    }
    defaults.update(overrides)
    return CandidateFact(**defaults)


def test_confidence_only_sorts_by_confidence_desc() -> None:
    strategy = ConfidenceOnlyStrategy()
    candidates = [
        _make_candidate(fact_id="f1", confidence=0.5),
        _make_candidate(fact_id="f2", confidence=0.9),
        _make_candidate(fact_id="f3", confidence=0.7),
    ]

    results = strategy.rank(candidates, max_tokens=10000)

    assert results[0].fact_id == "f2"
    assert results[0].new_rank == 0
    assert results[1].fact_id == "f3"
    assert results[1].new_rank == 1
    assert results[2].fact_id == "f1"
    assert results[2].new_rank == 2
    assert all(result.included for result in results)


def test_confidence_only_token_budget_limits() -> None:
    strategy = ConfidenceOnlyStrategy()
    candidates = [
        _make_candidate(fact_id="f1", confidence=0.9, content_preview="x" * 40),
        _make_candidate(fact_id="f2", confidence=0.8, content_preview="x" * 40),
        _make_candidate(fact_id="f3", confidence=0.7, content_preview="x" * 40),
    ]

    results = strategy.rank(candidates, max_tokens=20)

    assert results[0].included is True
    assert results[1].included is True
    assert results[2].included is False


def test_confidence_only_score_components() -> None:
    strategy = ConfidenceOnlyStrategy()

    results = strategy.rank([_make_candidate(confidence=0.85)], max_tokens=10000)

    assert results[0].score_components == {"confidence": 0.85}
    assert results[0].score == 0.85


def test_confidence_only_empty_candidates() -> None:
    strategy = ConfidenceOnlyStrategy()

    results = strategy.rank([], max_tokens=10000)

    assert results == []


def test_multi_signal_recent_high_confidence_ranks_first() -> None:
    reference_time = datetime(2026, 4, 14, tzinfo=UTC)
    strategy = MultiSignalStrategy(reference_time=reference_time)
    candidates = [
        _make_candidate(
            fact_id="f1",
            confidence=0.6,
            category="knowledge",
            created_at=(reference_time - timedelta(days=1)).isoformat(),
        ),
        _make_candidate(
            fact_id="f2",
            confidence=0.9,
            category="knowledge",
            created_at=(reference_time - timedelta(days=90)).isoformat(),
        ),
    ]

    results = strategy.rank(candidates, max_tokens=10000)

    assert results[0].fact_id == "f1"
    assert results[0].new_rank == 0
    assert results[1].fact_id == "f2"


def test_multi_signal_correction_category_boost() -> None:
    reference_time = datetime(2026, 4, 14, tzinfo=UTC)
    strategy = MultiSignalStrategy(reference_time=reference_time)
    candidates = [
        _make_candidate(
            fact_id="f1",
            category="correction",
            confidence=0.6,
            created_at=(reference_time - timedelta(days=1)).isoformat(),
        ),
        _make_candidate(
            fact_id="f2",
            category="knowledge",
            confidence=0.7,
            created_at=(reference_time - timedelta(days=1)).isoformat(),
        ),
    ]

    results = strategy.rank(candidates, max_tokens=10000)

    assert results[0].fact_id == "f1"
    assert results[0].new_rank == 0
    assert results[1].fact_id == "f2"


def test_multi_signal_missing_created_at_uses_zero_recency() -> None:
    reference_time = datetime(2026, 4, 14, tzinfo=UTC)
    strategy = MultiSignalStrategy(reference_time=reference_time)

    results = strategy.rank([_make_candidate(confidence=0.9, created_at=None)], max_tokens=10000)

    assert results[0].score_components["recency"] == 0.0


def test_multi_signal_deterministic_with_reference_time() -> None:
    reference_time = datetime(2026, 4, 14, tzinfo=UTC)
    strategy = MultiSignalStrategy(reference_time=reference_time)
    candidates = [
        _make_candidate(
            fact_id="f1",
            confidence=0.6,
            category="knowledge",
            created_at=(reference_time - timedelta(days=1)).isoformat(),
        ),
        _make_candidate(
            fact_id="f2",
            confidence=0.9,
            category="correction",
            created_at=(reference_time - timedelta(days=90)).isoformat(),
        ),
    ]

    results1 = strategy.rank(candidates, max_tokens=10000)
    results2 = strategy.rank(candidates, max_tokens=10000)

    assert len(results1) == len(results2)
    for result1, result2 in zip(results1, results2, strict=True):
        assert abs(result1.score - result2.score) < 1e-9
        assert result1.score_components == result2.score_components


def test_multi_signal_score_components_complete() -> None:
    reference_time = datetime(2026, 4, 14, tzinfo=UTC)
    strategy = MultiSignalStrategy(reference_time=reference_time)
    candidate = _make_candidate(created_at=(reference_time - timedelta(days=1)).isoformat())

    results = strategy.rank([candidate], max_tokens=10000)

    assert set(results[0].score_components) == {"confidence", "recency", "category_boost", "composite"}
