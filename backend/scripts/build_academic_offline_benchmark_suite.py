#!/usr/bin/env python3
"""Build layered offline benchmark raw datasets for academic eval loops."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build Core/Failure-mode/Domain-split raw benchmark files that are compatible with import_academic_eval_dataset.py.",
    )
    parser.add_argument(
        "--output-dir",
        default="src/evals/academic/templates/offline_benchmark_suite",
        help="Output directory for layered raw JSON files.",
    )
    parser.add_argument(
        "--core-dataset",
        default="top_tier_accept_reject_v1",
        help="Builtin dataset used to build Core layer.",
    )
    parser.add_argument(
        "--failure-mode-dataset",
        default="failure_mode_library_v1",
        help="Builtin dataset used to build Failure-mode layer.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        default=False,
        help="Allow overwriting existing files.",
    )
    return parser


def main() -> int:
    from src.evals.academic.offline_benchmark_suite import write_offline_benchmark_layers

    args = build_parser().parse_args()
    output_dir = Path(args.output_dir).expanduser()
    if not output_dir.is_absolute():
        output_dir = (Path.cwd() / output_dir).resolve()

    written = write_offline_benchmark_layers(
        output_dir,
        overwrite=args.overwrite,
        core_dataset_name=args.core_dataset,
        failure_mode_dataset_name=args.failure_mode_dataset,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "output_dir": str(output_dir),
                "layer_count": len(written),
                "layers": {key: str(path) for key, path in written.items()},
                "core_dataset": args.core_dataset,
                "failure_mode_dataset": args.failure_mode_dataset,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

