from __future__ import annotations

import hashlib
from typing import cast

from .config import EvaluationConfig
from .dataset import DatasetIntegrityError, EvidenceRecord, LongMemEvalDataset, build_distractor_bank, evidence_record, extract_evidence
from .manifest import OfficialManifest, SyntheticManifest
from .pool import PreparedCase, Scenario, build_case


def _eligible_official_ids(dataset: LongMemEvalDataset, manifest: OfficialManifest) -> dict[str, list[str]]:
    selection = manifest.selection
    by_type: dict[str, list[str]] = {question_type: [] for question_type in selection.eligible_question_types}
    excluded_pilot_ids = set(selection.excluded_pilot_ids)
    excluded_answer_fragments = [fragment.lower() for fragment in selection.answer_excluded_substrings]
    for row in dataset.rows:
        question_type = row.get("question_type")
        question_id = row.get("question_id")
        if question_type not in by_type or not isinstance(question_id, str):
            continue
        if question_id in excluded_pilot_ids or question_id.endswith(selection.exclude_abstention_suffix):
            continue
        answer = evidence_record(row).answer.strip()
        if not selection.answer_min_chars <= len(answer) <= selection.answer_max_chars:
            continue
        if any(fragment in answer.lower() for fragment in excluded_answer_fragments):
            continue
        evidence = extract_evidence(row)
        if not selection.evidence_min_chars <= len(evidence) <= selection.evidence_max_chars:
            continue
        by_type[question_type].append(question_id)
    return {question_type: sorted(question_ids)[: selection.take_per_question_type] for question_type, question_ids in by_type.items()}


def validate_official_selection(dataset: LongMemEvalDataset, manifest: OfficialManifest) -> None:
    selected_by_type = _eligible_official_ids(dataset, manifest)
    scenario_names = manifest.scenario_order
    group_size = manifest.selection.cases_per_type_per_scenario
    expected_take = len(scenario_names) * group_size
    if manifest.selection.take_per_question_type != expected_take:
        raise DatasetIntegrityError("official selection count does not match scenario grouping")
    for scenario_index, scenario in enumerate(scenario_names):
        expected: list[str] = []
        start = scenario_index * group_size
        end = start + group_size
        for question_type in manifest.selection.eligible_question_types:
            candidates = selected_by_type[question_type]
            if len(candidates) != manifest.selection.take_per_question_type:
                raise DatasetIntegrityError(f"not enough eligible {question_type!r} rows for the pinned selection")
            expected.extend(candidates[start:end])
        if manifest.scenarios[scenario] != expected:
            raise DatasetIntegrityError(f"pinned IDs for {scenario!r} do not match the declared selection rule: expected {expected}, got {manifest.scenarios[scenario]}")


def _distractors(case_id: str, bank: list[EvidenceRecord], *, count: int, namespace: str) -> list[EvidenceRecord]:
    if len(bank) < count:
        raise DatasetIntegrityError(f"distractor bank has {len(bank)} rows but {count} are required")
    digest = hashlib.sha256(f"{namespace}:{case_id}".encode()).digest()
    offset = int.from_bytes(digest[:4], "big") % len(bank)
    return [bank[(offset + index) % len(bank)] for index in range(count)]


def build_protocol_cases(
    dataset: LongMemEvalDataset,
    config: EvaluationConfig,
    official_manifest: OfficialManifest,
    synthetic_manifest: SyntheticManifest,
) -> list[PreparedCase]:
    if len(dataset.rows_by_id) != len(dataset.rows):
        raise DatasetIntegrityError("LongMemEval question IDs are not unique")
    validate_official_selection(dataset, official_manifest)
    bank = build_distractor_bank(
        dataset.rows,
        allowed_types=set(config.pool.distractor_types),
        min_evidence_chars=config.pool.distractor_min_evidence_chars,
        max_evidence_chars=config.pool.distractor_max_evidence_chars,
        limit=config.pool.distractor_bank_size,
    )
    if len(bank) != config.pool.distractor_bank_size:
        raise DatasetIntegrityError(f"distractor bank has {len(bank)} rows; expected {config.pool.distractor_bank_size}")

    cases: list[PreparedCase] = []
    for scenario_name in official_manifest.scenario_order:
        question_ids = official_manifest.scenarios[scenario_name]
        scenario = cast(Scenario, scenario_name)
        sorted_ids = sorted(question_ids, key=lambda question_id: (str(dataset.rows_by_id[question_id].get("question_type")), question_id))
        for question_id, loss_rank in zip(sorted_ids, official_manifest.loss_ranks, strict=True):
            support = evidence_record(dataset.rows_by_id[question_id])
            cases.append(
                build_case(
                    support=support,
                    distractors=_distractors(question_id, bank, count=config.pool.distractors, namespace=config.pool.offset_namespace),
                    scenario=scenario,
                    loss_rank=loss_rank,
                    evaluation_time=config.evaluation_time,
                    source="longmemeval",
                )
            )

    for case in synthetic_manifest.cases:
        support = EvidenceRecord(
            question_id=case.case_id,
            question_type="synthetic-correction",
            question=case.question,
            answer=case.answer,
            question_date=None,
            content=case.support_fact,
        )
        cases.append(
            build_case(
                support=support,
                distractors=_distractors(case.case_id, bank, count=config.pool.distractors, namespace=config.pool.offset_namespace),
                scenario="correction_reserve",
                loss_rank=case.loss_rank,
                evaluation_time=config.evaluation_time,
                source="synthetic",
            )
        )
    return cases
