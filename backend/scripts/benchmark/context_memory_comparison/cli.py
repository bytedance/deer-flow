from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

from .runner import run_offline


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare DeerMem and project context through an offline Gateway.")
    parser.add_argument("command", choices=["run-offline"])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    report = run_offline()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "report.json"
    with TemporaryDirectory(dir=output_dir) as staging:
        path = Path(staging) / target.name
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        path.replace(target)
    print(f"Wrote {target}")
    return 0 if report["passed"] else 1
