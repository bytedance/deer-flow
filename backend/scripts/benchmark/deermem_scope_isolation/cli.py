from __future__ import annotations

import argparse
import json
from pathlib import Path

from deerflow.models.factory import create_chat_model

from .manifest import load_manifest, validate_production_contract
from .report import compute_metrics, load_identity_rows, load_semantic_rows
from .runner import run_live, run_offline

BACKEND_ROOT = Path(__file__).parents[3]
EVAL_ROOT = Path(__file__).parent
DEFAULT_MANIFEST = EVAL_ROOT / "manifests" / "scope-isolation-v1.json"
DEFAULT_PROMPT = BACKEND_ROOT / "packages" / "harness" / "deerflow" / "agents" / "memory" / "backends" / "deermem" / "deermem" / "core" / "prompts" / "memory_update.chat.yaml"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark DeerMem memory scope admission and identity isolation")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate-contracts", help="validate the manifest and pinned production prompt")

    offline = subparsers.add_parser("run-offline", help="run deterministic replay through production DeerMem")
    offline.add_argument("--output-dir", type=Path, required=True)

    live = subparsers.add_parser("run-live", help="run semantic cases against a configured chat model")
    live.add_argument("--model", required=True)
    live.add_argument("--temperature", type=float, default=0.0)
    live.add_argument("--output-dir", type=Path, required=True)

    report = subparsers.add_parser("report", help="recompute metrics from public row files")
    report.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "report":
        metrics = compute_metrics(load_semantic_rows(args.output_dir), load_identity_rows(args.output_dir))
        print(json.dumps(metrics, indent=2, sort_keys=True))
        return 0

    manifest = load_manifest(DEFAULT_MANIFEST)
    validate_production_contract(manifest, DEFAULT_PROMPT)
    if args.command == "validate-contracts":
        print(f"validated {len(manifest.semantic_cases)} semantic and {len(manifest.identity_cases)} identity cases")
        return 0
    if args.command == "run-offline":
        report = run_offline(
            manifest,
            output_dir=args.output_dir,
            manifest_path=DEFAULT_MANIFEST,
            prompt_path=DEFAULT_PROMPT,
            backend_root=BACKEND_ROOT,
        )
        print(f"evaluated {report.semantic_cases} semantic cases and {report.identity_observations} identity observations")
        return 0

    model = create_chat_model(
        name=args.model,
        thinking_enabled=False,
        attach_tracing=False,
        model_overrides={"temperature": args.temperature},
    )
    report = run_live(
        manifest,
        model=model,
        model_name=args.model,
        temperature=args.temperature,
        output_dir=args.output_dir,
        manifest_path=DEFAULT_MANIFEST,
        prompt_path=DEFAULT_PROMPT,
        backend_root=BACKEND_ROOT,
    )
    print(f"reused={report.reused} called={report.called} failed={len(report.failed)}")
    for failure in report.failed:
        print(failure)
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
