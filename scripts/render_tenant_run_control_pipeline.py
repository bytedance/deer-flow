"""Render the Shanghai native Run control SQL gate; standard library only."""

import argparse
import re
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Render owned native Run control CI")
    parser.add_argument("phase")
    parser.add_argument("source_sha256")
    parser.add_argument(
        "--suite",
        choices=("revocation", "lifetime", "checkpoint", "checkpoint-regression"),
        default="revocation",
    )
    args = parser.parse_args()
    if (
        re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", args.phase) is None
        or re.fullmatch(r"[0-9a-f]{64}", args.source_sha256) is None
    ):
        parser.error("phase and source SHA256 must be canonical")
    root = Path(__file__).resolve().parents[1]
    template = (
        root / "examples/ecs-native/deploy/Jenkinsfile.tenant-run-control.in"
    ).read_text(encoding="utf-8")
    rendered = template.replace("@@PHASE@@", args.phase).replace(
        "@@SOURCE_SHA256@@", args.source_sha256
    )
    tests = "tests/test_workspace_revocation.py"
    if args.suite == "lifetime":
        tests += " tests/test_workspace_run_lifetime.py"
    if args.suite == "checkpoint":
        tests = "tests/test_workspace_run_checkpoints.py"
    if args.suite == "checkpoint-regression":
        tests += " tests/test_workspace_run_lifetime.py tests/test_workspace_worker_context.py"
    rendered = rendered.replace("@@TEST_PATHS@@", tests)
    if "@@" in rendered:
        parser.error("unresolved pipeline marker")
    print(rendered, end="")


if __name__ == "__main__":
    main()
