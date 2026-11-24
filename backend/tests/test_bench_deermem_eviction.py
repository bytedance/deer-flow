"""Contract, dataset, grading, policy, protocol, QA, and reporting suite for the DeerMem eviction benchmark."""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from scripts.benchmark.deermem_eviction.config import load_evaluation_config
from scripts.benchmark.deermem_eviction.dataset import DatasetIntegrityError, EvidenceRecord, LongMemEvalDataset, build_distractor_bank, extract_evidence, load_longmemeval
from scripts.benchmark.deermem_eviction.grading import GRADER_VERSION, OVERLAP_THRESHOLD, grade_answer, normalize_answer
from scripts.benchmark.deermem_eviction.io import sha256_file
from scripts.benchmark.deermem_eviction.manifest import OfficialManifest, load_official_manifest, load_synthetic_manifest
from scripts.benchmark.deermem_eviction.policy import PolicyResult, evaluate_case
from scripts.benchmark.deermem_eviction.pool import PreparedCase, build_case
from scripts.benchmark.deermem_eviction.protocol import _distractors, validate_official_selection
from scripts.benchmark.deermem_eviction.provider import ProviderCallError, ProviderConfigurationError, ProviderSettings, build_client, request_answer, resolve_provider_settings
from scripts.benchmark.deermem_eviction.qa import build_answer_task, render_answer_messages
from scripts.benchmark.deermem_eviction.report import AnswerRowIntegrityError, collect_answer_rows, compute_qa_statistics, grade_answer_rows, summarize_qa_rows, write_qa_report
from scripts.benchmark.deermem_eviction.results import summarize_policy_results, write_policy_run
from scripts.benchmark.deermem_eviction.runner import ensure_run_config_identity, response_path, run_answer_calls, verify_run_identity
from scripts.benchmark.deermem_eviction.stats import exact_mcnemar, paired_bootstrap_difference

pytestmark = pytest.mark.benchmark

BACKEND_ROOT = Path(__file__).parents[1]
EVAL_ROOT = BACKEND_ROOT / "scripts" / "benchmark" / "deermem_eviction"


def _load_config():
    return load_evaluation_config(EVAL_ROOT / "configs" / "pr4789-reproduction-v1.yaml")


# --- test_bench_deermem_eviction_contracts ---


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for child in value.values() for key in _all_keys(child)}
    if isinstance(value, list):
        return {key for child in value for key in _all_keys(child)}
    return set()


def test_committed_protocol_is_pinned_and_does_not_copy_longmemeval_text() -> None:
    config = load_evaluation_config(EVAL_ROOT / "configs" / "pr4789-reproduction-v1.yaml")
    official = load_official_manifest(EVAL_ROOT / "manifests" / "longmemeval-pr4789-v1.json")
    synthetic = load_synthetic_manifest(EVAL_ROOT / "manifests" / "synthetic-corrections-pr4789-v1.json")

    assert config.schema_version == 1
    assert config.protocol_id == "deermem-hybrid-v1-pr4789-reproduction-v1"
    assert config.dataset.revision == "98d7416c24c778c2fee6e6f3006e7a073259d48f"
    assert config.dataset.sha256 == "821a2034d219ab45846873dd14c14f12cfe7776e73527a483f9dac095d38620c"
    assert config.pool.size == 10
    assert config.pool.capacities == [5, 7, 9]
    assert config.pool.qa_capacity == 7
    assert sum(config.policies.hybrid_v1.weights.values()) == 1.0

    official_ids = [question_id for question_ids in official.scenarios.values() for question_id in question_ids]
    assert len(official_ids) == 40
    assert len(set(official_ids)) == 40
    assert set(official.scenarios) == {
        "confirmation_help",
        "access_help",
        "confidence_control",
        "noisy_signal_control",
    }
    assert official.scenario_order == [
        "confirmation_help",
        "access_help",
        "confidence_control",
        "noisy_signal_control",
    ]
    assert len(synthetic.cases) == 5

    raw_official = json.loads((EVAL_ROOT / "manifests" / "longmemeval-pr4789-v1.json").read_text())
    assert not ({"question", "answer", "content", "haystack_sessions"} & _all_keys(raw_official))

    prompt_path = EVAL_ROOT / config.qa.answer_prompt.path
    assert sha256_file(prompt_path) == config.qa.answer_prompt.sha256


def test_cli_contract_validation_is_offline(capsys) -> None:
    from scripts.benchmark.deermem_eviction.cli import main

    assert main(["validate-contracts"]) == 0
    assert "validated 40 official and 5 synthetic cases" in capsys.readouterr().out


def test_required_policy_version_is_checked_against_production() -> None:
    import pytest

    from deerflow.agents.memory.backends.deermem.deermem.core.eviction import EVICTION_POLICY_HYBRID_V1
    from scripts.benchmark.deermem_eviction.policy import require_production_policy

    config = load_evaluation_config(EVAL_ROOT / "configs" / "pr4789-reproduction-v1.yaml")
    assert config.required_policy_version == EVICTION_POLICY_HYBRID_V1
    require_production_policy(config.required_policy_version)
    with pytest.raises(ValueError, match="production implements"):
        require_production_policy("hybrid-v2")


# --- test_bench_deermem_eviction_dataset ---


def _dataset_row(question_id: str, question_type: str, content: str) -> dict[str, object]:
    return {
        "question_id": question_id,
        "question_type": question_type,
        "question": f"Question for {question_id}?",
        "answer": "answer",
        "question_date": "2026/08/13 (Thu) 10:00",
        "haystack_session_ids": [f"session-{question_id}"],
        "haystack_dates": ["2026/08/01 (Sat) 09:00"],
        "haystack_sessions": [[{"role": "user", "content": content, "has_answer": True}]],
    }


def test_load_longmemeval_rejects_hash_mismatch(tmp_path: Path) -> None:
    dataset_path = tmp_path / "oracle.json"
    dataset_path.write_text("[]")

    with pytest.raises(DatasetIntegrityError, match="SHA-256 mismatch"):
        load_longmemeval(dataset_path, expected_sha256="0" * 64)


def test_load_longmemeval_indexes_unique_rows(tmp_path: Path) -> None:
    rows = [_dataset_row("b", "knowledge-update", "b" * 50), _dataset_row("a", "temporal-reasoning", "a" * 50)]
    payload = json.dumps(rows).encode()
    dataset_path = tmp_path / "oracle.json"
    dataset_path.write_bytes(payload)

    dataset = load_longmemeval(dataset_path, expected_sha256=hashlib.sha256(payload).hexdigest())

    assert sorted(dataset.rows_by_id) == ["a", "b"]


def test_extract_evidence_uses_marked_turns_and_per_session_user_fallback() -> None:
    row = {
        "haystack_session_ids": ["s1", "s2"],
        "haystack_dates": ["2026/01/01", "2026/01/02"],
        "haystack_sessions": [
            [
                {"role": "user", "content": "ignore unmarked", "has_answer": False},
                {"role": "assistant", "content": "marked answer", "has_answer": True},
            ],
            [
                {"role": "user", "content": "fallback user"},
                {"role": "assistant", "content": "ignore fallback assistant"},
            ],
        ],
    }

    assert extract_evidence(row) == ("SESSION s1 AT 2026/01/01\nASSISTANT: marked answer\n\nSESSION s2 AT 2026/01/02\nUSER: fallback user")


def test_distractor_bank_is_filtered_sorted_and_bounded() -> None:
    rows = [
        _dataset_row("z", "single-session-user", "z" * 60),
        _dataset_row("a", "single-session-preference", "a" * 60),
        _dataset_row("wrong-type", "knowledge-update", "x" * 60),
        _dataset_row("too-long", "single-session-user", "x" * 800),
    ]

    bank = build_distractor_bank(rows, allowed_types={"single-session-user", "single-session-preference"}, min_evidence_chars=40, max_evidence_chars=700, limit=40)

    assert [item.question_id for item in bank] == ["a", "z"]


# --- test_bench_deermem_eviction_grading ---


def test_config_pins_the_committed_grader_version() -> None:
    config = load_evaluation_config(EVAL_ROOT / "configs" / "pr4789-reproduction-v1.yaml")
    assert config.qa.grader_version == GRADER_VERSION == "deterministic-overlap-v1"


def test_grader_is_blind_by_construction() -> None:
    parameters = inspect.signature(grade_answer).parameters
    assert list(parameters) == ["prediction", "reference"]


def test_normalization_lowercases_strips_and_maps_number_words() -> None:
    assert normalize_answer("Seven WEEKS!") == ["7", "weeks"]
    assert normalize_answer("fifteen") == ["15"]
    assert normalize_answer("eleven") == ["eleven"]
    assert normalize_answer("70-200mm zoom lens") == ["70", "200mm", "zoom", "lens"]
    assert normalize_answer("  \t\n ") == []


def test_empty_and_insufficient_predictions_are_rejected() -> None:
    empty = grade_answer("", "3 weeks")
    assert not empty.correct
    assert empty.rule == "empty-prediction"
    assert not grade_answer("   ", "3 weeks").correct
    result = grade_answer("INSUFFICIENT.", "3 weeks")
    assert not result.correct
    assert result.rule == "insufficient"
    assert not grade_answer("insufficient", "3 weeks").correct


def test_empty_reference_is_a_contract_error() -> None:
    with pytest.raises(ValueError):
        grade_answer("3 weeks", "  .  ")


def test_exact_match_ignores_case_punctuation_and_number_words() -> None:
    assert grade_answer("Every week.", "every week").rule == "exact"
    assert grade_answer("NO", "no").rule == "exact"
    assert grade_answer("seven", "7").rule == "exact"


def test_substring_matches_are_token_level_and_bidirectional() -> None:
    assert grade_answer("132 points", "132").rule == "substring"
    assert grade_answer("132", "132 points").rule == "substring"
    assert grade_answer("Ford F-150 pickup truck.", "Ford F-150").rule == "substring"
    assert grade_answer("Ford F-150 pickup truck.", "a Ford F-150").correct
    assert not grade_answer("5", "25").correct
    assert not grade_answer("no", "north").correct


def test_conflicting_numeric_answers_are_rejected() -> None:
    result = grade_answer("5", "3 weeks")
    assert not result.correct
    assert result.rule == "numeric-conflict"
    assert not grade_answer("12 weeks", "8 weeks").correct


def test_numbers_inside_an_explicit_reference_range_are_accepted() -> None:
    reference = "ranging from 5 to 10 hours"
    assert grade_answer("7", reference).rule == "numeric-range"
    assert grade_answer("5 hours", reference).rule == "numeric-range"
    assert grade_answer("10", reference).correct
    assert not grade_answer("4", reference).correct
    assert not grade_answer("11", reference).correct
    assert grade_answer("7", "ranging from 5 dollars to 10 dollars").rule == "numeric-range"


def test_overlap_requires_sixty_percent_in_both_directions() -> None:
    assert OVERLAP_THRESHOLD == 0.6
    accepted = grade_answer("under my bed", "under the bed")
    assert accepted.correct
    assert accepted.rule == "overlap-accept"
    assert grade_answer("red kite string", "red kite ribbon").correct
    assert not grade_answer("red kite", "red balloon ribbon string flag").correct
    assert not grade_answer("50mm prime lens", "70-200mm zoom lens").correct
    assert not grade_answer("YES", "NO").correct


def test_all_stopword_predictions_cannot_pass_overlap() -> None:
    result = grade_answer("of the", "3 weeks")
    assert not result.correct
    assert result.rule == "overlap-reject"


# --- test_bench_deermem_eviction_policy ---

NOW = datetime(2026, 8, 13, tzinfo=UTC)


def _evidence(question_id: str, question_type: str = "single-session-user") -> EvidenceRecord:
    return EvidenceRecord(
        question_id=question_id,
        question_type=question_type,
        question=f"Question for {question_id}?",
        answer="answer",
        question_date="2026/08/13 (Thu) 10:00",
        content=f"Evidence for {question_id}",
    )


def test_confirmation_scenario_is_deterministic_and_uses_production_policies() -> None:
    support = _evidence("support", "knowledge-update")
    distractors = [_evidence(f"d{i}") for i in range(9)]

    first = build_case(
        support=support,
        distractors=distractors,
        scenario="confirmation_help",
        loss_rank=8,
        evaluation_time=NOW,
    )
    second = build_case(
        support=support,
        distractors=distractors,
        scenario="confirmation_help",
        loss_rank=8,
        evaluation_time=NOW,
    )

    assert first == second
    assert len(first.facts) == 10
    assert [fact["id"] for fact in first.facts] == sorted(fact["id"] for fact in first.facts)

    confidence = evaluate_case(first, policy_name="confidence", capacity=7)
    hybrid = evaluate_case(first, policy_name="hybrid-v1", capacity=7)

    assert confidence.support_all_retained is False
    assert hybrid.support_all_retained is True
    assert confidence.kept_fact_ids != hybrid.kept_fact_ids
    assert all("content" not in evicted for evicted in hybrid.evicted)


def test_correction_reserve_retains_a_low_confidence_correction() -> None:
    support = _evidence("correction_case", "synthetic-correction")
    distractors = [_evidence(f"d{i}") for i in range(9)]
    case = build_case(
        support=support,
        distractors=distractors,
        scenario="correction_reserve",
        loss_rank=8,
        evaluation_time=NOW,
    )

    confidence = evaluate_case(case, policy_name="confidence", capacity=7)
    hybrid = evaluate_case(case, policy_name="hybrid-v1", capacity=7)

    assert confidence.support_all_retained is False
    assert hybrid.support_all_retained is True
    assert hybrid.reserved_correction_slots == 1


def test_policy_result_contains_ids_and_scores_but_not_dataset_text() -> None:
    case = build_case(
        support=_evidence("support", "knowledge-update"),
        distractors=[_evidence(f"d{i}") for i in range(9)],
        scenario="access_help",
        loss_rank=6,
        evaluation_time=NOW,
    )

    result = evaluate_case(case, policy_name="hybrid-v1", capacity=7).to_public_dict()

    assert result["case_id"] == "support"
    assert result["support_fact_ids"] == ["gold_support"]
    assert all(fact_id.startswith("d_support_") or fact_id == "gold_support" for fact_id in result["kept_fact_ids"])
    assert "question" not in result
    assert "answer" not in result
    assert "facts" not in result


# --- test_bench_deermem_eviction_protocol ---

SCENARIO_ORDER = ["confirmation_help", "access_help", "confidence_control", "noisy_signal_control"]


def _protocol_row(question_id: str, question_type: str, *, answer: str = "short answer", evidence_chars: int = 120) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "question_type": question_type,
        "question": f"question for {question_id}?",
        "answer": answer,
        "haystack_session_ids": ["s1"],
        "haystack_dates": ["2023/05/20"],
        "haystack_sessions": [[{"role": "user", "content": "x" * evidence_chars, "has_answer": True}]],
    }


def _eligible_ids(prefix: str) -> list[str]:
    return [f"{prefix}-{index:03d}" for index in range(1, 21)]


def _dataset(rows: list[dict[str, Any]]) -> LongMemEvalDataset:
    return LongMemEvalDataset(path=Path("synthetic"), sha256="0" * 64, rows=tuple(rows), rows_by_id={row["question_id"]: row for row in rows})


def _rows_with_exclusions() -> list[dict[str, Any]]:
    rows = [_protocol_row(question_id, "knowledge-update") for question_id in _eligible_ids("ku")]
    rows += [_protocol_row(question_id, "temporal-reasoning") for question_id in _eligible_ids("tr")]
    # Every excluded row sorts before the eligible IDs, so a broken exclusion changes the recomputed selection.
    rows.append(_protocol_row("ku-000-pilot", "knowledge-update"))
    rows.append(_protocol_row("ku-000_abs", "knowledge-update"))
    rows.append(_protocol_row("ku-000-long-answer", "knowledge-update", answer="a" * 150))
    rows.append(_protocol_row("ku-000-refusal", "knowledge-update", answer="there is not enough information"))
    rows.append(_protocol_row("ku-000-evidence", "knowledge-update", evidence_chars=2500))
    return rows


def _manifest(*, excluded_pilot_ids: list[str] | None = None, scenarios: dict[str, list[str]] | None = None) -> OfficialManifest:
    if scenarios is None:
        ku, tr = _eligible_ids("ku"), _eligible_ids("tr")
        scenarios = {scenario: ku[index * 5 : (index + 1) * 5] + tr[index * 5 : (index + 1) * 5] for index, scenario in enumerate(SCENARIO_ORDER)}
    return OfficialManifest.model_validate(
        {
            "schema_version": 1,
            "protocol_id": "synthetic-protocol",
            "selection": {
                "eligible_question_types": ["knowledge-update", "temporal-reasoning"],
                "excluded_pilot_ids": ["ku-000-pilot"] if excluded_pilot_ids is None else excluded_pilot_ids,
                "exclude_abstention_suffix": "_abs",
                "answer_min_chars": 1,
                "answer_max_chars": 100,
                "answer_excluded_substrings": ["not enough", "only mentioned"],
                "evidence_min_chars": 1,
                "evidence_max_chars": 2000,
                "take_per_question_type": 20,
                "cases_per_type_per_scenario": 5,
            },
            "scenario_order": SCENARIO_ORDER,
            "loss_ranks": [6, 6, 6, 8, 8, 8, 10, 10, 10, 10],
            "scenarios": scenarios,
        }
    )


def test_selection_recomputation_accepts_a_manifest_matching_the_published_rule() -> None:
    validate_official_selection(_dataset(_rows_with_exclusions()), _manifest())


def test_selection_recomputation_rejects_ids_that_break_the_rule() -> None:
    ku, tr = _eligible_ids("ku"), _eligible_ids("tr")
    scenarios = {scenario: ku[index * 5 : (index + 1) * 5] + tr[index * 5 : (index + 1) * 5] for index, scenario in enumerate(SCENARIO_ORDER)}
    scenarios["confirmation_help"], scenarios["access_help"] = (
        scenarios["confirmation_help"][:9] + [scenarios["access_help"][9]],
        scenarios["access_help"][:9] + [scenarios["confirmation_help"][9]],
    )
    with pytest.raises(DatasetIntegrityError, match="do not match the declared selection rule"):
        validate_official_selection(_dataset(_rows_with_exclusions()), _manifest(scenarios=scenarios))


def test_selection_recomputation_applies_every_published_exclusion() -> None:
    manifest = _manifest()
    excluded = {"ku-000-pilot", "ku-000_abs", "ku-000-long-answer", "ku-000-refusal", "ku-000-evidence"}
    pinned = {question_id for question_ids in manifest.scenarios.values() for question_id in question_ids}
    assert not (excluded & pinned)
    # Dropping the pilot exclusion changes the recomputed selection, so validation must fail against the pinned IDs.
    with pytest.raises(DatasetIntegrityError):
        validate_official_selection(_dataset(_rows_with_exclusions()), _manifest(excluded_pilot_ids=[]))


def test_selection_recomputation_requires_enough_eligible_rows() -> None:
    rows = [row for row in _rows_with_exclusions() if row["question_id"] != "tr-020"]
    with pytest.raises(DatasetIntegrityError, match="not enough eligible"):
        validate_official_selection(_dataset(rows), _manifest())


def _bank(size: int = 5) -> list[EvidenceRecord]:
    return [EvidenceRecord(question_id=f"b{index}", question_type="single-session-user", question="q?", answer="a", question_date=None, content=f"evidence {index}") for index in range(size)]


def test_distractor_offset_derivation_and_wraparound_are_pinned() -> None:
    # Hardcoded expectations for sha256(f"offset-ns:{case_id}").digest()[:4] % 5;
    # a regression in the digest slice, modulus, or wraparound changes these indices.
    bank = _bank()
    no_wrap = _distractors("case-a", bank, count=3, namespace="offset-ns")
    assert [record.question_id for record in no_wrap] == ["b0", "b1", "b2"]
    wraps = _distractors("case-c", bank, count=3, namespace="offset-ns")
    assert [record.question_id for record in wraps] == ["b3", "b4", "b0"]
    assert [record.question_id for record in _distractors("case-a", bank, count=3, namespace="alt-ns")] == ["b1", "b2", "b3"]


def test_distractor_selection_requires_a_large_enough_bank() -> None:
    with pytest.raises(DatasetIntegrityError, match="required"):
        _distractors("case-a", _bank(size=2), count=3, namespace="offset-ns")


# --- test_bench_deermem_eviction_published_results ---

RESULTS_ROOT = EVAL_ROOT / "results" / "pr4789-reproduction-v1"


ALLOWED_ROW_KEYS = {
    "schema_version",
    "row_id",
    "case_id",
    "source",
    "scenario",
    "question_type",
    "policy",
    "capacity",
    "kept_fact_ids",
    "support_all_retained",
    "support_recall",
    "prediction",
    "grade_correct",
    "grade_rule",
    "grader_version",
    "attempts",
    "request_fingerprint",
    "response_model",
    "usage",
}


def _rows() -> list[dict]:
    return [json.loads(line) for line in (RESULTS_ROOT / "qa.rows.jsonl").read_text(encoding="utf-8").splitlines()]


def test_published_rows_contain_only_allowed_metadata() -> None:
    rows = _rows()
    config = load_evaluation_config(EVAL_ROOT / "configs" / "pr4789-reproduction-v1.yaml")
    assert len(rows) == 90
    assert {row["policy"] for row in rows} == {"confidence", "hybrid-v1"}
    for row in rows:
        assert set(row) == ALLOWED_ROW_KEYS
        assert row["capacity"] == config.pool.qa_capacity
        assert len(row["kept_fact_ids"]) == config.pool.qa_capacity
        assert row["grader_version"] == GRADER_VERSION
        assert isinstance(row["prediction"], str)


def test_published_statistics_are_recomputable_from_the_rows() -> None:
    rows = _rows()
    config = load_evaluation_config(EVAL_ROOT / "configs" / "pr4789-reproduction-v1.yaml")
    statistics = json.loads((RESULTS_ROOT / "qa.stats.json").read_text(encoding="utf-8"))
    grades: dict[str, dict[str, bool]] = {}
    sources: dict[str, str] = {}
    for row in rows:
        grades.setdefault(row["case_id"], {})[row["policy"]] = row["grade_correct"]
        sources[row["case_id"]] = row["source"]
    suites = {
        "official": [case_id for case_id in sorted(grades) if sources[case_id] == "longmemeval"],
        "synthetic": [case_id for case_id in sorted(grades) if sources[case_id] == "synthetic"],
        "overall": sorted(grades),
    }
    for suite, case_ids in suites.items():
        pairs = [(grades[case_id]["confidence"], grades[case_id]["hybrid-v1"]) for case_id in case_ids]
        expected = exact_mcnemar(pairs)
        published = statistics["suites"][suite]["mcnemar"]
        assert published["p_value"] == expected.p_value
        assert published["only_first_correct"] == expected.only_first_correct
        assert published["only_second_correct"] == expected.only_second_correct
        assert statistics["suites"][suite]["cases"] == len(pairs)
        expected_bootstrap = paired_bootstrap_difference(pairs, seed=config.statistics.bootstrap_seed, iterations=config.statistics.bootstrap_iterations, alpha=config.statistics.alpha)
        published_bootstrap = statistics["suites"][suite]["bootstrap"]
        assert published_bootstrap["mean_difference"] == expected_bootstrap.mean_difference
        assert published_bootstrap["lower"] == expected_bootstrap.lower
        assert published_bootstrap["upper"] == expected_bootstrap.upper
        assert (published_bootstrap["seed"], published_bootstrap["iterations"], published_bootstrap["alpha"]) == (expected_bootstrap.seed, expected_bootstrap.iterations, expected_bootstrap.alpha)


def test_published_summary_matches_the_rows_and_run_provenance_is_secret_free() -> None:
    rows = _rows()
    summary = json.loads((RESULTS_ROOT / "qa.summary.json").read_text(encoding="utf-8"))
    for group in summary["groups"]:
        matching = [row for row in rows if (row["source"], row["scenario"], row["policy"]) == (group["source"], group["scenario"], group["policy"])]
        assert len(matching) == group["cases"]
        assert sum(1 for row in matching if row["grade_correct"]) == group["correct"]
    run = json.loads((RESULTS_ROOT / "qa_run.json").read_text(encoding="utf-8"))
    serialized = json.dumps(run)
    assert "sk-" not in serialized
    assert run["qa"]["api_key_env"] == "DEERMEM_EVAL_ANSWER_API_KEY"
    assert run["dataset"]["sha256"] == load_evaluation_config(EVAL_ROOT / "configs" / "pr4789-reproduction-v1.yaml").dataset.sha256


# --- test_bench_deermem_eviction_qa ---


def _template() -> str:
    return (EVAL_ROOT / "prompts" / "answer-v1.txt").read_text(encoding="utf-8")


def _qa_case(case_id: str = "case-1", question_date: str | None = "2023/05/20 (Sat) 02:21") -> PreparedCase:
    config = _load_config()
    facts = [
        {"id": "fact-b", "content": "The cat sleeps in the study.", "category": "context", "confidence": 0.7, "createdAt": "2026-02-14T00:00:00Z", "source": "synthetic"},
        {"id": "fact-a", "content": "The user moved to Lyon.", "category": "context", "confidence": 0.9, "createdAt": "2026-02-14T00:00:00Z", "source": "synthetic"},
        {"id": "fact-c", "content": "The user has two bikes.", "category": "context", "confidence": 0.8, "createdAt": "2026-02-14T00:00:00Z", "source": "synthetic"},
    ]
    return PreparedCase(
        case_id=case_id,
        source="synthetic",
        scenario="correction_reserve",
        question_type="synthetic-correction",
        question="Where does the user live?",
        answer="Lyon",
        question_date=question_date,
        evaluation_time=config.evaluation_time,
        facts=facts,
        usage={},
        support_fact_ids=("fact-a",),
    )


def _qa_policy_result(case: PreparedCase, kept: tuple[str, ...], policy: str = "hybrid-v1") -> PolicyResult:
    return PolicyResult(
        case_id=case.case_id,
        source=case.source,
        scenario=case.scenario,
        question_type=case.question_type,
        policy=policy,  # type: ignore[arg-type]
        capacity=7,
        support_fact_ids=case.support_fact_ids,
        kept_fact_ids=kept,
        evicted=(),
        scores={},
        support_all_retained=True,
        support_recall=1.0,
        reserved_correction_slots=0,
    )


def test_rendering_pins_fact_order_date_line_and_block_format() -> None:
    messages = render_answer_messages(
        _template(),
        question="Where does the user live?",
        question_date="2023/05/20 (Sat) 02:21",
        retained_facts=[("fact-b", "The cat sleeps in the study."), ("fact-a", "The user moved to Lyon.")],
    )
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "Answer using only the stored memory below. If the answer is not supported, output exactly INSUFFICIENT. For a YES/NO question, output only YES or NO. Otherwise give only the shortest direct answer."
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == ("CURRENT DATE: 2023/05/20 (Sat) 02:21\nSTORED MEMORY:\n[fact-a]\nThe user moved to Lyon.\n\n[fact-b]\nThe cat sleeps in the study.\n\nQUESTION: Where does the user live?")


def test_rendering_omits_the_date_line_when_absent() -> None:
    messages = render_answer_messages(_template(), question="Q?", question_date=None, retained_facts=[("fact-a", "content")])
    assert messages[1]["content"].startswith("STORED MEMORY:\n")
    assert "CURRENT DATE" not in messages[1]["content"]


def test_rendering_rejects_empty_or_duplicate_facts() -> None:
    with pytest.raises(ValueError):
        render_answer_messages(_template(), question="Q?", question_date=None, retained_facts=[])
    with pytest.raises(ValueError):
        render_answer_messages(_template(), question="Q?", question_date=None, retained_facts=[("fact-a", "x"), ("fact-a", "y")])


def test_build_answer_task_renders_only_kept_facts() -> None:
    case = _qa_case()
    task = build_answer_task(case, _qa_policy_result(case, kept=("fact-a", "fact-c")), _template())
    assert task.row_id == "case-1__hybrid-v1"
    assert task.kept_fact_ids == ("fact-a", "fact-c")
    user = task.messages[1]["content"]
    assert "[fact-a]" in user and "[fact-c]" in user
    assert "fact-b" not in user
    with pytest.raises(ValueError):
        build_answer_task(_qa_case(case_id="other"), _qa_policy_result(case, kept=("fact-a",)), _template())


def test_provider_settings_errors_name_the_missing_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _load_config()
    monkeypatch.delenv(config.qa.api_key_env, raising=False)
    monkeypatch.delenv(config.qa.base_url_env, raising=False)
    with pytest.raises(ProviderConfigurationError) as excinfo:
        resolve_provider_settings(config.qa)
    assert config.qa.api_key_env in str(excinfo.value)
    assert config.qa.base_url_env in str(excinfo.value)
    monkeypatch.setenv(config.qa.api_key_env, "secret-key")
    monkeypatch.setenv(config.qa.base_url_env, "https://example.invalid/v1")
    settings = resolve_provider_settings(config.qa)
    assert settings.api_key == "secret-key"
    assert settings.base_url == "https://example.invalid/v1"


def _mock_client(handler, qa) -> httpx.Client:
    return httpx.Client(base_url="https://example.invalid/v1", headers={"Authorization": "Bearer secret-key"}, transport=httpx.MockTransport(handler), timeout=qa.timeout_seconds)


def _success_body(prediction: str = "Lyon") -> dict:
    return {"model": "deepseek-v4-flash", "choices": [{"message": {"role": "assistant", "content": prediction}}], "usage": {"prompt_tokens": 100, "completion_tokens": 3, "detail": "ignored"}}


def test_request_answer_parses_prediction_and_non_secret_metadata() -> None:
    qa = _load_config().qa
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_success_body())

    answer = request_answer(_mock_client(handler, qa), qa, ({"role": "system", "content": "s"}, {"role": "user", "content": "u"}), backoff_seconds=0)
    assert answer.prediction == "Lyon"
    assert answer.attempts == 1
    assert answer.usage == {"prompt_tokens": 100, "completion_tokens": 3}
    assert answer.response_model == "deepseek-v4-flash"
    payload = json.loads(seen[0].content)
    assert payload["model"] == qa.model
    assert payload["temperature"] == qa.temperature
    assert payload["max_tokens"] == qa.max_tokens
    assert payload["stream"] is qa.stream
    assert seen[0].url.path.endswith("/chat/completions")


def test_request_answer_retries_retryable_failures_and_gives_up() -> None:
    qa = _load_config().qa
    statuses = [429, 500]

    def flaky(request: httpx.Request) -> httpx.Response:
        if statuses:
            return httpx.Response(statuses.pop(0), json={})
        return httpx.Response(200, json=_success_body())

    answer = request_answer(_mock_client(flaky, qa), qa, ({"role": "user", "content": "u"},), backoff_seconds=0)
    assert answer.attempts == 3

    def always_broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(ProviderCallError, match="failed after 3 attempts"):
        request_answer(_mock_client(always_broken, qa), qa, ({"role": "user", "content": "u"},), backoff_seconds=0)


def test_request_answer_rejects_non_retryable_and_malformed_responses() -> None:
    qa = _load_config().qa
    with pytest.raises(ProviderCallError, match="non-retryable status 401"):
        request_answer(_mock_client(lambda request: httpx.Response(401, json={}), qa), qa, ({"role": "user", "content": "u"},), backoff_seconds=0)
    with pytest.raises(ProviderCallError, match="choices"):
        request_answer(_mock_client(lambda request: httpx.Response(200, json={"choices": []}), qa), qa, ({"role": "user", "content": "u"},), backoff_seconds=0)


def test_build_client_uses_configured_timeout_and_bearer_header() -> None:
    config = _load_config()
    with build_client(ProviderSettings(base_url="https://example.invalid/v1", api_key="secret-key"), config.qa) as client:
        assert client.headers["Authorization"] == "Bearer secret-key"
        assert client.timeout.read == config.qa.timeout_seconds


def _tasks(count: int = 2) -> list:
    template = _template()
    tasks = []
    for index in range(count):
        case = _qa_case(case_id=f"case-{index}")
        tasks.append(build_answer_task(case, _qa_policy_result(case, kept=("fact-a", "fact-b")), template))
    return tasks


def test_run_answer_calls_persists_rows_and_resumes_without_new_calls(tmp_path: Path) -> None:
    config = _load_config()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_success_body())

    tasks = _tasks()
    with _mock_client(handler, config.qa) as client:
        first = run_answer_calls(tasks, config=config, client=client, output_dir=tmp_path, backoff_seconds=0)
        assert (first.reused, first.called, first.failed) == (0, 2, ())
        assert len(calls) == 2
        row = json.loads(response_path(tmp_path, tasks[0].row_id).read_text(encoding="utf-8"))
        assert set(row) == {"schema_version", "row_id", "case_id", "source", "scenario", "policy", "capacity", "kept_fact_ids", "prediction", "attempts", "request_fingerprint", "response_model", "usage", "created_at"}
        assert row["prediction"] == "Lyon"
        serialized = json.dumps(row)
        assert "Where does the user live" not in serialized
        assert "The user moved to Lyon." not in serialized
        assert "Bearer" not in serialized

        second = run_answer_calls(tasks, config=config, client=client, output_dir=tmp_path, backoff_seconds=0)
        assert (second.reused, second.called, second.failed) == (2, 0, ())
        assert len(calls) == 2

        response_path(tmp_path, tasks[0].row_id).write_text("{not json", encoding="utf-8")
        third = run_answer_calls(tasks, config=config, client=client, output_dir=tmp_path, backoff_seconds=0)
        assert (third.reused, third.called, third.failed) == (1, 1, ())
        assert len(calls) == 3


def test_run_answer_calls_refuses_to_reuse_a_row_bound_to_another_case(tmp_path: Path) -> None:
    config = _load_config()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_success_body())

    tasks = _tasks()
    with _mock_client(handler, config.qa) as client:
        run_answer_calls(tasks, config=config, client=client, output_dir=tmp_path, backoff_seconds=0)
        assert len(calls) == 2
        path = response_path(tmp_path, tasks[0].row_id)
        original = json.loads(path.read_text(encoding="utf-8"))
        for field, value in (("case_id", tasks[1].case_id), ("source", f"not-{tasks[0].source}"), ("scenario", f"not-{tasks[0].scenario}")):
            path.write_text(json.dumps(dict(original, **{field: value})), encoding="utf-8")
            report = run_answer_calls(tasks, config=config, client=client, output_dir=tmp_path, backoff_seconds=0)
            assert (report.reused, report.called, report.failed) == (1, 1, ())
        assert len(calls) == 5


def test_run_answer_calls_reports_failures_without_writing_rows(tmp_path: Path) -> None:
    config = _load_config()

    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    tasks = _tasks(count=1)
    with _mock_client(broken, config.qa) as client:
        report = run_answer_calls(tasks, config=config, client=client, output_dir=tmp_path, backoff_seconds=0)
    assert report.called == 0
    assert len(report.failed) == 1
    assert tasks[0].row_id in report.failed[0]
    assert not response_path(tmp_path, tasks[0].row_id).exists()


def test_run_directory_is_bound_to_the_full_protocol_identity(tmp_path: Path) -> None:
    config = _load_config()
    paths = {
        "config_path": EVAL_ROOT / "configs" / "pr4789-reproduction-v1.yaml",
        "official_manifest_path": EVAL_ROOT / "manifests" / "longmemeval-pr4789-v1.json",
        "synthetic_manifest_path": EVAL_ROOT / "manifests" / "synthetic-corrections-pr4789-v1.json",
        "prompt_path": EVAL_ROOT / "prompts" / "answer-v1.txt",
    }
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text("[]", encoding="utf-8")
    backend_root = Path(__file__).parents[1]
    output_dir = tmp_path / "run"

    ensure_run_config_identity(output_dir, config=config, dataset_path=dataset_path, backend_root=backend_root, **paths)
    marker = json.loads((output_dir / "qa_run.json").read_text(encoding="utf-8"))
    assert marker["qa"]["model"] == config.qa.model
    assert set(marker["artifacts"]) == {"config_sha256", "official_manifest_sha256", "synthetic_manifest_sha256", "answer_prompt_sha256", "dataset_sha256"}
    assert "secret" not in json.dumps(marker).lower()
    ensure_run_config_identity(output_dir, config=config, dataset_path=dataset_path, backend_root=backend_root, **paths)

    for changed_key, marker_field in (("config_path", "config_sha256"), ("synthetic_manifest_path", "synthetic_manifest_sha256"), ("prompt_path", "answer_prompt_sha256")):
        changed_paths = dict(paths)
        changed_file = tmp_path / f"changed-{changed_key}"
        changed_file.write_text(paths[changed_key].read_text(encoding="utf-8") + "\n", encoding="utf-8")
        changed_paths[changed_key] = changed_file
        with pytest.raises(ValueError, match=f"different protocol artifacts.*{marker_field}"):
            ensure_run_config_identity(output_dir, config=config, dataset_path=dataset_path, backend_root=backend_root, **changed_paths)


def test_verify_run_identity_is_read_only_and_names_the_changed_artifact(tmp_path: Path) -> None:
    config = _load_config()
    paths = {
        "config_path": EVAL_ROOT / "configs" / "pr4789-reproduction-v1.yaml",
        "official_manifest_path": EVAL_ROOT / "manifests" / "longmemeval-pr4789-v1.json",
        "synthetic_manifest_path": EVAL_ROOT / "manifests" / "synthetic-corrections-pr4789-v1.json",
        "prompt_path": EVAL_ROOT / "prompts" / "answer-v1.txt",
    }
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text("[]", encoding="utf-8")
    output_dir = tmp_path / "run"

    with pytest.raises(ValueError, match="missing"):
        verify_run_identity(output_dir, dataset_path=dataset_path, **paths)

    ensure_run_config_identity(output_dir, config=config, dataset_path=dataset_path, backend_root=Path(__file__).parents[1], **paths)
    verify_run_identity(output_dir, dataset_path=dataset_path, **paths)

    changed_prompt = tmp_path / "changed-prompt.txt"
    changed_prompt.write_text(paths["prompt_path"].read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="refusing to grade.*|answer_prompt_sha256"):
        verify_run_identity(output_dir, dataset_path=dataset_path, **{**paths, "prompt_path": changed_prompt})


def test_resume_revalidates_stored_rows_against_the_current_task(tmp_path: Path) -> None:
    config = _load_config()
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_success_body())

    tasks = _tasks(count=1)
    with _mock_client(handler, config.qa) as client:
        run_answer_calls(tasks, config=config, client=client, output_dir=tmp_path, backoff_seconds=0)
        assert len(calls) == 1

        unchanged = run_answer_calls(tasks, config=config, client=client, output_dir=tmp_path, backoff_seconds=0)
        assert (unchanged.reused, unchanged.called) == (1, 0)
        assert len(calls) == 1

        changed_message = replace(tasks[0], messages=(tasks[0].messages[0], {"role": "user", "content": "a different question"}))
        after_message_change = run_answer_calls([changed_message], config=config, client=client, output_dir=tmp_path, backoff_seconds=0)
        assert (after_message_change.reused, after_message_change.called) == (0, 1)
        assert len(calls) == 2

        changed_kept = replace(changed_message, kept_fact_ids=("fact-a",))
        after_kept_change = run_answer_calls([changed_kept], config=config, client=client, output_dir=tmp_path, backoff_seconds=0)
        assert (after_kept_change.reused, after_kept_change.called) == (0, 1)
        assert len(calls) == 3


def test_cli_run_qa_fails_fast_without_provider_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from scripts.benchmark.deermem_eviction.cli import main

    config = _load_config()
    monkeypatch.delenv(config.qa.api_key_env, raising=False)
    monkeypatch.delenv(config.qa.base_url_env, raising=False)
    with pytest.raises(ProviderConfigurationError) as excinfo:
        main(["run-qa", "--dataset", str(tmp_path / "missing.json"), "--output-dir", str(tmp_path / "out")])
    assert config.qa.api_key_env in str(excinfo.value)


# --- test_bench_deermem_eviction_report ---


def _report_case(case_id: str, *, source: str, scenario: str, answer: str) -> PreparedCase:
    config = _load_config()
    facts = [{"id": f"{case_id}-fact", "content": "Secret memory content.", "category": "context", "confidence": 0.9, "createdAt": "2026-02-14T00:00:00Z", "source": "synthetic"}]
    return PreparedCase(
        case_id=case_id,
        source=source,  # type: ignore[arg-type]
        scenario=scenario,  # type: ignore[arg-type]
        question_type="synthetic-shape",
        question="Secret question text?",
        answer=answer,
        question_date=None,
        evaluation_time=config.evaluation_time,
        facts=facts,
        usage={},
        support_fact_ids=(f"{case_id}-fact",),
    )


def _report_policy_result(case: PreparedCase, policy: str) -> PolicyResult:
    return PolicyResult(
        case_id=case.case_id,
        source=case.source,
        scenario=case.scenario,
        question_type=case.question_type,
        policy=policy,  # type: ignore[arg-type]
        capacity=7,
        support_fact_ids=case.support_fact_ids,
        kept_fact_ids=case.support_fact_ids,
        evicted=(),
        scores={},
        support_all_retained=True,
        support_recall=1.0,
        reserved_correction_slots=0,
    )


def _write_response(output_dir: Path, case: PreparedCase, policy: str, prediction: str, *, capacity: int = 7) -> None:
    row_id = f"{case.case_id}__{policy}"
    path = response_path(output_dir, row_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "schema_version": 1,
        "row_id": row_id,
        "case_id": case.case_id,
        "source": case.source,
        "scenario": case.scenario,
        "policy": policy,
        "capacity": capacity,
        "kept_fact_ids": list(case.support_fact_ids),
        "prediction": prediction,
        "attempts": 1,
        "request_fingerprint": "f" * 64,
        "response_model": "deepseek-v4-flash",
        "usage": {"prompt_tokens": 10, "completion_tokens": 2},
        "created_at": "2026-08-17T00:00:00Z",
    }
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")


def _setup(tmp_path: Path):
    official = _report_case("case-off", source="longmemeval", scenario="access_help", answer="Lyon-Reference-Secret")
    synthetic = _report_case("case-syn", source="synthetic", scenario="correction_reserve", answer="NO")
    cases = [official, synthetic]
    _write_response(tmp_path, official, "confidence", "Paris")
    _write_response(tmp_path, official, "hybrid-v1", "Lyon-Reference-Secret")
    _write_response(tmp_path, synthetic, "confidence", "NO")
    _write_response(tmp_path, synthetic, "hybrid-v1", "NO")
    results = {f"{case.case_id}__{policy}": _report_policy_result(case, policy) for case in cases for policy in ("confidence", "hybrid-v1")}
    fingerprints = {row_id: "f" * 64 for row_id in results}
    return cases, results, fingerprints


def test_exact_mcnemar_matches_the_two_sided_exact_binomial() -> None:
    concordant = exact_mcnemar([(True, True), (False, False)])
    assert concordant.p_value == 1.0
    one_sided_shift = exact_mcnemar([(False, True)] * 5)
    assert one_sided_shift.only_second_correct == 5
    assert one_sided_shift.p_value == pytest.approx(2 * 0.5**5)
    mixed = exact_mcnemar([(False, True)] * 8 + [(True, False)] + [(True, True)] * 3)
    assert (mixed.only_first_correct, mixed.only_second_correct, mixed.both_correct) == (1, 8, 3)
    assert mixed.p_value == pytest.approx(2 * (0.5**9) * (1 + 9), rel=1e-12)


def test_paired_bootstrap_is_seed_deterministic_and_signed_second_minus_first() -> None:
    config = _load_config()
    pairs = [(False, True)] * 4 + [(True, True)] * 4
    first = paired_bootstrap_difference(pairs, seed=config.statistics.bootstrap_seed, iterations=1000, alpha=config.statistics.alpha)
    second = paired_bootstrap_difference(pairs, seed=config.statistics.bootstrap_seed, iterations=1000, alpha=config.statistics.alpha)
    assert first == second
    assert first.mean_difference == pytest.approx(0.5)
    degenerate = paired_bootstrap_difference([(False, True)] * 3, seed=1, iterations=100, alpha=0.05)
    assert (degenerate.mean_difference, degenerate.lower, degenerate.upper) == (1.0, 1.0, 1.0)


def test_grading_is_blind_and_joined_by_row_id(tmp_path: Path) -> None:
    cases, results, fingerprints = _setup(tmp_path)
    rows = collect_answer_rows(tmp_path, cases)
    graded = grade_answer_rows(cases, results, rows, expected_fingerprints=fingerprints)
    by_row = {row["row_id"]: row for row in graded}
    assert not by_row["case-off__confidence"]["grade_correct"]
    assert by_row["case-off__hybrid-v1"]["grade_correct"]
    assert by_row["case-syn__confidence"]["grade_correct"]
    assert by_row["case-syn__hybrid-v1"]["grade_correct"]
    assert all(row["grader_version"] == "deterministic-overlap-v1" for row in graded)


def test_collect_and_integrity_checks_reject_incomplete_or_tampered_rows(tmp_path: Path) -> None:
    cases, results, fingerprints = _setup(tmp_path)
    response_path(tmp_path, "case-syn__hybrid-v1").unlink()
    with pytest.raises(AnswerRowIntegrityError, match="case-syn__hybrid-v1"):
        collect_answer_rows(tmp_path, cases)

    _write_response(tmp_path, cases[1], "hybrid-v1", "NO", capacity=5)
    rows = collect_answer_rows(tmp_path, cases)
    with pytest.raises(AnswerRowIntegrityError, match="capacity/policy"):
        grade_answer_rows(cases, results, rows, expected_fingerprints=fingerprints)

    _write_response(tmp_path, cases[1], "hybrid-v1", "NO")
    rows = collect_answer_rows(tmp_path, cases)
    tampered = dict(results)
    tampered["case-syn__hybrid-v1"] = _report_policy_result(_report_case("case-syn", source="synthetic", scenario="correction_reserve", answer="NO"), "hybrid-v1")
    object.__setattr__(tampered["case-syn__hybrid-v1"], "kept_fact_ids", ("other-fact",))
    with pytest.raises(AnswerRowIntegrityError, match="kept facts"):
        grade_answer_rows(cases, tampered, rows, expected_fingerprints=fingerprints)

    stale = dict(fingerprints)
    stale["case-syn__hybrid-v1"] = "0" * 64
    with pytest.raises(AnswerRowIntegrityError, match="request fingerprint"):
        grade_answer_rows(cases, results, rows, expected_fingerprints=stale)


def test_grading_rejects_a_row_reassigned_to_another_valid_case(tmp_path: Path) -> None:
    cases, results, fingerprints = _setup(tmp_path)
    path = response_path(tmp_path, "case-off__hybrid-v1")
    original = json.loads(path.read_text(encoding="utf-8"))
    for field, value in (("case_id", "case-syn"), ("source", "synthetic"), ("scenario", "correction_reserve"), ("row_id", "case-syn__hybrid-v1")):
        path.write_text(json.dumps(dict(original, **{field: value})) + "\n", encoding="utf-8")
        rows = collect_answer_rows(tmp_path, cases)
        with pytest.raises(AnswerRowIntegrityError, match="case-off__hybrid-v1.*case identity"):
            grade_answer_rows(cases, results, rows, expected_fingerprints=fingerprints)


def test_summary_and_statistics_keep_suites_separate(tmp_path: Path) -> None:
    cases, results, fingerprints = _setup(tmp_path)
    config = _load_config()
    graded = grade_answer_rows(cases, results, collect_answer_rows(tmp_path, cases), expected_fingerprints=fingerprints)
    summary = summarize_qa_rows(graded)
    assert {(group["source"], group["scenario"], group["policy"]): group["accuracy"] for group in summary} == {
        ("longmemeval", "access_help", "confidence"): 0.0,
        ("longmemeval", "access_help", "hybrid-v1"): 1.0,
        ("synthetic", "correction_reserve", "confidence"): 1.0,
        ("synthetic", "correction_reserve", "hybrid-v1"): 1.0,
    }
    statistics = compute_qa_statistics(graded, config)
    assert statistics["suites"]["official"]["cases"] == 1
    assert statistics["suites"]["synthetic"]["cases"] == 1
    assert statistics["suites"]["overall"]["cases"] == 2
    assert statistics["suites"]["official"]["mcnemar"]["only_second_correct"] == 1
    assert statistics["suites"]["official"]["bootstrap"]["seed"] == config.statistics.bootstrap_seed


def test_written_report_redacts_dataset_text_and_refuses_overwrite(tmp_path: Path) -> None:
    cases, results, fingerprints = _setup(tmp_path)
    config = _load_config()
    graded = grade_answer_rows(cases, results, collect_answer_rows(tmp_path, cases), expected_fingerprints=fingerprints)
    write_qa_report(tmp_path, graded=graded, summary=summarize_qa_rows(graded), statistics=compute_qa_statistics(graded, config), config=config)
    rows_text = (tmp_path / "qa.rows.jsonl").read_text(encoding="utf-8")
    assert "Secret question text" not in rows_text
    assert "Secret memory content" not in rows_text
    confidence_official = json.loads(next(line for line in rows_text.splitlines() if '"case-off__confidence"' in line))
    assert "Lyon-Reference-Secret" not in json.dumps(confidence_official)
    assert (tmp_path / "qa.summary.json").exists()
    assert (tmp_path / "qa.stats.json").exists()
    with pytest.raises(FileExistsError):
        write_qa_report(tmp_path, graded=graded, summary=summarize_qa_rows(graded), statistics=compute_qa_statistics(graded, config), config=config)


# --- test_bench_deermem_eviction_results ---


def _results_case() -> PreparedCase:
    support = EvidenceRecord("support", "knowledge-update", "private question", "private answer", None, "private support text")
    distractors = [EvidenceRecord(f"d{i}", "single-session-user", "q", "a", None, f"private distractor {i}") for i in range(9)]
    return build_case(
        support=support,
        distractors=distractors,
        scenario="confirmation_help",
        loss_rank=8,
        evaluation_time=datetime(2026, 8, 13, tzinfo=UTC),
    )


def test_summary_keeps_policy_and_scenario_groups_separate() -> None:
    case = _results_case()
    rows = [
        evaluate_case(case, policy_name="confidence", capacity=7),
        evaluate_case(case, policy_name="hybrid-v1", capacity=7),
    ]

    summary = summarize_policy_results(rows)

    assert [(item["policy"], item["support_all_retained"]) for item in summary] == [
        ("confidence", 0),
        ("hybrid-v1", 1),
    ]


def test_public_policy_run_omits_dataset_text_and_refuses_overwrite(tmp_path: Path) -> None:
    config_path = EVAL_ROOT / "configs" / "pr4789-reproduction-v1.yaml"
    official_manifest_path = EVAL_ROOT / "manifests" / "longmemeval-pr4789-v1.json"
    synthetic_manifest_path = EVAL_ROOT / "manifests" / "synthetic-corrections-pr4789-v1.json"
    prompt_path = EVAL_ROOT / "prompts" / "answer-v1.txt"
    config = load_evaluation_config(config_path)
    case = _results_case()
    rows = [evaluate_case(case, policy_name="confidence", capacity=7), evaluate_case(case, policy_name="hybrid-v1", capacity=7)]
    dataset_path = tmp_path / "private-dataset.json"
    dataset_path.write_text("[]")
    output_dir = tmp_path / "run"

    write_policy_run(
        output_dir,
        results=rows,
        config=config,
        config_path=config_path,
        official_manifest_path=official_manifest_path,
        synthetic_manifest_path=synthetic_manifest_path,
        prompt_path=prompt_path,
        dataset_path=dataset_path,
        backend_root=BACKEND_ROOT,
    )

    raw_text = (output_dir / "policy.raw.jsonl").read_text()
    assert "private question" not in raw_text
    assert "private answer" not in raw_text
    assert "private support text" not in raw_text
    assert len([json.loads(line) for line in raw_text.splitlines()]) == 2
    assert json.loads((output_dir / "summary.json").read_text())["protocol_id"] == config.protocol_id
    assert json.loads((output_dir / "run.json").read_text())["dataset"]["filename"] == config.dataset.filename

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_policy_run(
            output_dir,
            results=rows,
            config=config,
            config_path=config_path,
            official_manifest_path=official_manifest_path,
            synthetic_manifest_path=synthetic_manifest_path,
            prompt_path=prompt_path,
            dataset_path=dataset_path,
            backend_root=BACKEND_ROOT,
        )
