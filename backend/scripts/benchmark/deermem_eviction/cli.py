from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from .config import EvaluationConfig, load_evaluation_config
from .dataset import LongMemEvalDataset, load_longmemeval
from .grading import GRADER_VERSION
from .io import sha256_file
from .manifest import OfficialManifest, SyntheticManifest, load_official_manifest, load_synthetic_manifest
from .policy import evaluate_case, require_production_policy
from .protocol import build_protocol_cases, validate_official_selection
from .provider import build_client, request_fingerprint, resolve_provider_settings
from .qa import build_answer_task
from .report import collect_answer_rows, compute_qa_statistics, grade_answer_rows, summarize_qa_rows, write_qa_report
from .results import write_policy_run
from .runner import ensure_run_config_identity, run_answer_calls, verify_run_identity

EVAL_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = EVAL_ROOT.parents[2]
DEFAULT_CONFIG = EVAL_ROOT / "configs" / "pr4789-reproduction-v1.yaml"
DEFAULT_OFFICIAL_MANIFEST = EVAL_ROOT / "manifests" / "longmemeval-pr4789-v1.json"
DEFAULT_SYNTHETIC_MANIFEST = EVAL_ROOT / "manifests" / "synthetic-corrections-pr4789-v1.json"


def _load_contracts(args: argparse.Namespace) -> tuple[EvaluationConfig, OfficialManifest, SyntheticManifest, Path]:
    config = load_evaluation_config(args.config)
    official = load_official_manifest(args.official_manifest)
    synthetic = load_synthetic_manifest(args.synthetic_manifest)
    if {config.protocol_id, official.protocol_id, synthetic.protocol_id} != {config.protocol_id}:
        raise ValueError("config and manifests use different protocol IDs")
    if config.qa.grader_version != GRADER_VERSION:
        raise ValueError(f"config pins grader {config.qa.grader_version!r} but the committed grader is {GRADER_VERSION!r}")
    require_production_policy(config.required_policy_version)
    prompt_path = EVAL_ROOT / config.qa.answer_prompt.path
    actual_prompt_sha = sha256_file(prompt_path)
    if actual_prompt_sha != config.qa.answer_prompt.sha256:
        raise ValueError(f"answer prompt SHA-256 mismatch: expected {config.qa.answer_prompt.sha256}, got {actual_prompt_sha}")
    return config, official, synthetic, prompt_path


def _load_validated_dataset(args: argparse.Namespace, config: EvaluationConfig, official: OfficialManifest) -> LongMemEvalDataset:
    dataset = load_longmemeval(args.dataset, expected_sha256=config.dataset.sha256)
    validate_official_selection(dataset, official)
    return dataset


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reproduce DeerMem confidence vs hybrid-v1 capacity evaluation")
    parser.set_defaults(config=DEFAULT_CONFIG, official_manifest=DEFAULT_OFFICIAL_MANIFEST, synthetic_manifest=DEFAULT_SYNTHETIC_MANIFEST)
    subparsers = parser.add_subparsers(dest="command", required=True)

    contracts = subparsers.add_parser("validate-contracts", help="Validate committed config, manifests, and prompt without the dataset")
    contracts.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    contracts.add_argument("--official-manifest", type=Path, default=DEFAULT_OFFICIAL_MANIFEST)
    contracts.add_argument("--synthetic-manifest", type=Path, default=DEFAULT_SYNTHETIC_MANIFEST)

    validate = subparsers.add_parser("validate", help="Validate contracts and the caller-supplied LongMemEval file")
    validate.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    validate.add_argument("--official-manifest", type=Path, default=DEFAULT_OFFICIAL_MANIFEST)
    validate.add_argument("--synthetic-manifest", type=Path, default=DEFAULT_SYNTHETIC_MANIFEST)
    validate.add_argument("--dataset", type=Path, required=True)

    run_policy = subparsers.add_parser("run-policy", help="Run deterministic retention evaluation with no provider calls")
    run_policy.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    run_policy.add_argument("--official-manifest", type=Path, default=DEFAULT_OFFICIAL_MANIFEST)
    run_policy.add_argument("--synthetic-manifest", type=Path, default=DEFAULT_SYNTHETIC_MANIFEST)
    run_policy.add_argument("--dataset", type=Path, required=True)
    run_policy.add_argument("--output-dir", type=Path, required=True)

    run_qa = subparsers.add_parser("run-qa", help="Call the configured answer provider for both policies at the QA capacity (resumable; requires provider environment variables)")
    run_qa.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    run_qa.add_argument("--official-manifest", type=Path, default=DEFAULT_OFFICIAL_MANIFEST)
    run_qa.add_argument("--synthetic-manifest", type=Path, default=DEFAULT_SYNTHETIC_MANIFEST)
    run_qa.add_argument("--dataset", type=Path, required=True)
    run_qa.add_argument("--output-dir", type=Path, required=True)

    grade_qa = subparsers.add_parser("grade-qa", help="Grade completed answer rows blindly and write the public QA rows, summary, and paired statistics")
    grade_qa.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    grade_qa.add_argument("--official-manifest", type=Path, default=DEFAULT_OFFICIAL_MANIFEST)
    grade_qa.add_argument("--synthetic-manifest", type=Path, default=DEFAULT_SYNTHETIC_MANIFEST)
    grade_qa.add_argument("--dataset", type=Path, required=True)
    grade_qa.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config, official, synthetic, prompt_path = _load_contracts(args)
    if args.command == "validate-contracts":
        official_count = sum(len(question_ids) for question_ids in official.scenarios.values())
        print(f"validated {official_count} official and {len(synthetic.cases)} synthetic cases")
        return 0

    provider_settings = resolve_provider_settings(config.qa) if args.command == "run-qa" else None

    dataset = _load_validated_dataset(args, config, official)
    cases = build_protocol_cases(dataset, config, official, synthetic)
    if args.command == "validate":
        print(f"validated dataset {dataset.sha256} and prepared {len(cases)} cases")
        return 0
    if args.command == "run-policy":
        results = [evaluate_case(case, policy_name=policy_name, capacity=capacity, hybrid_config=config.policies.hybrid_v1) for case in cases for capacity in config.pool.capacities for policy_name in ("confidence", "hybrid-v1")]
        write_policy_run(
            args.output_dir,
            results=results,
            config=config,
            config_path=args.config,
            official_manifest_path=args.official_manifest,
            synthetic_manifest_path=args.synthetic_manifest,
            prompt_path=prompt_path,
            dataset_path=args.dataset,
            backend_root=BACKEND_ROOT,
        )
        print(f"wrote {len(results)} policy rows for {len(cases)} cases to {args.output_dir}")
        return 0
    if args.command == "run-qa":
        assert provider_settings is not None
        template = prompt_path.read_text(encoding="utf-8")
        tasks = [build_answer_task(case, evaluate_case(case, policy_name=policy_name, capacity=config.pool.qa_capacity, hybrid_config=config.policies.hybrid_v1), template) for case in cases for policy_name in ("confidence", "hybrid-v1")]
        ensure_run_config_identity(
            args.output_dir,
            config=config,
            config_path=args.config,
            official_manifest_path=args.official_manifest,
            synthetic_manifest_path=args.synthetic_manifest,
            prompt_path=prompt_path,
            dataset_path=args.dataset,
            backend_root=BACKEND_ROOT,
        )
        with build_client(provider_settings, config.qa) as client:
            report = run_answer_calls(tasks, config=config, client=client, output_dir=args.output_dir)
        print(f"answer rows: {report.reused} reused, {report.called} called, {len(report.failed)} failed")
        for failure in report.failed:
            print(f"  failed {failure}")
        return 1 if report.failed else 0
    if args.command == "grade-qa":
        template = prompt_path.read_text(encoding="utf-8")
        results_by_row = {}
        expected_fingerprints = {}
        for case in cases:
            for policy_name in ("confidence", "hybrid-v1"):
                result = evaluate_case(case, policy_name=policy_name, capacity=config.pool.qa_capacity, hybrid_config=config.policies.hybrid_v1)
                task = build_answer_task(case, result, template)
                results_by_row[task.row_id] = result
                expected_fingerprints[task.row_id] = request_fingerprint(config.qa, task.messages)
        verify_run_identity(args.output_dir, config_path=args.config, official_manifest_path=args.official_manifest, synthetic_manifest_path=args.synthetic_manifest, prompt_path=prompt_path, dataset_path=args.dataset)
        rows = collect_answer_rows(args.output_dir, cases)
        graded = grade_answer_rows(cases, results_by_row, rows, expected_fingerprints=expected_fingerprints)
        summary = summarize_qa_rows(graded)
        statistics = compute_qa_statistics(graded, config)
        write_qa_report(args.output_dir, graded=graded, summary=summary, statistics=statistics, config=config)
        for suite, values in statistics["suites"].items():
            mcnemar = values["mcnemar"]
            correct_first = mcnemar["both_correct"] + mcnemar["only_first_correct"]
            correct_second = mcnemar["both_correct"] + mcnemar["only_second_correct"]
            print(f"{suite}: confidence {correct_first}/{values['cases']}, hybrid-v1 {correct_second}/{values['cases']}, exact McNemar p={mcnemar['p_value']:.6f}")
        print(f"graded {len(graded)} rows to {args.output_dir}")
        return 0
    raise AssertionError(f"unhandled command: {args.command}")
