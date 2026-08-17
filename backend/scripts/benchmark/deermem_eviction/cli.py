from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from .config import EvaluationConfig, load_evaluation_config
from .dataset import LongMemEvalDataset, load_longmemeval
from .grading import GRADER_VERSION
from .io import sha256_file
from .manifest import OfficialManifest, SyntheticManifest, load_official_manifest, load_synthetic_manifest
from .policy import evaluate_case
from .protocol import build_protocol_cases, validate_official_selection
from .results import write_policy_run

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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config, official, synthetic, prompt_path = _load_contracts(args)
    if args.command == "validate-contracts":
        official_count = sum(len(question_ids) for question_ids in official.scenarios.values())
        print(f"validated {official_count} official and {len(synthetic.cases)} synthetic cases")
        return 0

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
    raise AssertionError(f"unhandled command: {args.command}")
