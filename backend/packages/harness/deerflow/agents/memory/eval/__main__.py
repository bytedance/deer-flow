from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from deerflow.agents.memory.eval.comparator import MetricsComparator
from deerflow.agents.memory.eval.formatters import get_formatter
from deerflow.agents.memory.eval.replay import ReplayEvaluator
from deerflow.agents.memory.eval.strategies import ConfidenceOnlyStrategy, MultiSignalStrategy
from deerflow.agents.memory.eval.types import RankingStrategy

STRATEGY_REGISTRY: dict[str, type[RankingStrategy]] = {
    "confidence_only": ConfidenceOnlyStrategy,
    "multi_signal": MultiSignalStrategy,
}


def _build_strategies(spec: str) -> list[RankingStrategy]:
    if spec.strip() == "all":
        return [cls() for cls in STRATEGY_REGISTRY.values()]
    names = [n.strip() for n in spec.split(",") if n.strip()]
    strategies: list[RankingStrategy] = []
    for name in names:
        cls = STRATEGY_REGISTRY.get(name)
        if cls is None:
            print(f"error: unknown strategy {name!r}. Available: {', '.join(STRATEGY_REGISTRY)}", file=sys.stderr)
            sys.exit(1)
        strategies.append(cls())
    return strategies


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m deerflow.agents.memory.eval",
        description="Memory eval harness CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    replay_parser = subparsers.add_parser("replay", help="Replay traces and compare ranking strategies")
    replay_parser.add_argument("--trace-path", required=True, help="Path to JSONL trace file")
    replay_parser.add_argument("--format", default="terminal", choices=["terminal", "json", "md"], dest="format", help="Output format (default: terminal)")
    replay_parser.add_argument("--window", type=int, default=50, help="Number of recent traces to process (default: 50)")
    replay_parser.add_argument("--strategies", default="all", help="Comma-separated strategy names or 'all' (default: all)")

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "replay":
        try:
            trace_path = Path(args.trace_path).resolve()
            if not trace_path.is_file():
                raise FileNotFoundError(f"Trace file not found: {trace_path}")

            strategy_instances = _build_strategies(args.strategies)

            evaluator = ReplayEvaluator(strategies=strategy_instances, baseline="confidence_only")
            results = evaluator.evaluate(trace_path, window=args.window)

            comparator = MetricsComparator(baseline_name="confidence_only")
            comparisons = comparator.compare(results)

            formatter = get_formatter(args.format)
            print(formatter.format(comparisons))

        except FileNotFoundError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)
        except json.JSONDecodeError as exc:
            print(f"error: failed to parse trace file: {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
