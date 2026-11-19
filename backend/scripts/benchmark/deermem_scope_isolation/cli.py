from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from .contract import load_protocol
from .report import write_report
from .runner import ROOT, LiveSettings, run

DEFAULT_MANIFEST = ROOT / "manifest.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reproduce DeerMem semantic scope admission and user/agent identity isolation")
    parser.set_defaults(manifest=DEFAULT_MANIFEST)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate the committed synthetic protocol without network access")
    validate.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)

    offline = subparsers.add_parser("run-offline", help="Run deterministic production-path admission and routing checks (no network or credentials)")
    offline.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    offline.add_argument("--output-dir", type=Path, required=True)

    live = subparsers.add_parser("run-live", help="Explicitly run semantic extraction with an environment-configured model; routing remains an offline suite")
    live.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    live.add_argument("--output-dir", type=Path, required=True)
    live.add_argument("--provider", required=True)
    live.add_argument("--model", required=True)
    live.add_argument("--temperature", type=float, default=0.0)
    live.add_argument("--api-key-env", required=True)
    live.add_argument("--base-url-env")

    report = subparsers.add_parser("report", help="Recompute metrics from protocol-bound rows without provider calls")
    report.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    report.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    protocol = load_protocol(args.manifest)
    if args.command == "validate":
        print(f"validated {len(protocol.semantic_cases)} semantic cases and 1 routing case for {protocol.protocol_id}")
        return 0
    if args.command == "run-offline":
        result = run(protocol, manifest_path=args.manifest, output_dir=args.output_dir, mode="offline")
        print(f"offline rows: {result.executed} executed, {result.reused} reused")
        return 0
    if args.command == "run-live":
        if not 0 <= args.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        settings = LiveSettings(
            provider=args.provider,
            model=args.model,
            temperature=args.temperature,
            api_key_env=args.api_key_env,
            base_url_env=args.base_url_env,
        )
        result = run(protocol, manifest_path=args.manifest, output_dir=args.output_dir, mode="live", settings=settings)
        print(f"live semantic rows: {result.executed} executed, {result.reused} reused")
        return 0
    if args.command == "report":
        target = write_report(protocol, manifest_path=args.manifest, output_dir=args.output_dir)
        print(f"wrote recomputed report to {target}")
        return 0
    raise AssertionError(f"unhandled command: {args.command}")
