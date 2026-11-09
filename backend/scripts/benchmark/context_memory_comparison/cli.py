from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from .contract import load_protocol
from .report import write_report
from .runner import ROOT, run

DEFAULT_MANIFEST = ROOT / "manifest.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="DeerFlow Issue #7884 Offline Memory vs Project Context Comparison Benchmark"
    )
    parser.set_defaults(manifest=DEFAULT_MANIFEST)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate committed synthetic manifest without network calls")
    validate.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)

    offline = subparsers.add_parser(
        "run-offline",
        help="Run deterministic offline benchmarks for scope isolation, turn invalidation, and token overhead",
    )
    offline.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    offline.add_argument("--output-dir", type=Path, required=True)

    report = subparsers.add_parser("report", help="Recompute metrics and generate report.json from executed rows")
    report.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    report.add_argument("--output-dir", type=Path, required=True)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    protocol = load_protocol(args.manifest)

    if args.command == "validate":
        print(
            f"Validated {len(protocol.scope_isolation_cases)} scope isolation cases, "
            f"{len(protocol.turn_invalidation_cases)} turn invalidation cases, and "
            f"{len(protocol.token_overhead_cases)} token overhead cases for {protocol.protocol_id}"
        )
        return 0

    if args.command == "run-offline":
        result = run(protocol, manifest_path=args.manifest, output_dir=args.output_dir, mode="offline")
        print(f"Offline execution complete: {result.executed} executed, {result.reused} reused")
        return 0

    if args.command == "report":
        target = write_report(protocol, manifest_path=args.manifest, output_dir=args.output_dir)
        print(f"Wrote benchmark report to {target}")
        return 0

    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
