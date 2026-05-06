"""CLI entry point for evaluation — ``python -m deerflow.evaluation``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from deerflow.evaluation.dataset import load_dataset
from deerflow.evaluation.runner import EvalRunner


def _agent_factory(message: str) -> str:
    """Placeholder agent — replace with real agent integration."""
    return f"Echo: {message}"


def main() -> None:
    parser = argparse.ArgumentParser(description="DeerFlow Evaluation Runner")
    parser.add_argument("--dataset", required=True, help="Path to JSONL dataset file")
    parser.add_argument("--output", default="eval_report.json", help="Output report path")
    parser.add_argument("--judge-model", default=None, help="Model name for LLM judge")
    parser.add_argument("--compare", default=None, help="Path to second agent config for comparison")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"Dataset not found: {dataset_path}", file=sys.stderr)
        sys.exit(1)

    dataset = load_dataset(dataset_path)
    runner = EvalRunner(judge_model=args.judge_model)

    if args.compare:
        baseline = _agent_factory
        candidate = _agent_factory
        bl_report, ca_report = runner.compare(dataset, baseline, candidate)
        output_path = Path(args.output)
        bl_report.save(output_path.with_name(f"{output_path.stem}_baseline.json"))
        ca_report.save(output_path.with_name(f"{output_path.stem}_candidate.json"))
        print(f"Baseline pass rate: {bl_report.pass_rate:.2%}")
        print(f"Candidate pass rate: {ca_report.pass_rate:.2%}")
    else:
        report = runner.run(dataset, _agent_factory)
        report.save(args.output)
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
