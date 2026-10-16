"""Render the Shanghai-only physical test pipeline; standard library, no runtime."""

import argparse
import re
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Render the owned Shanghai physical CI template")
    parser.add_argument("phase")
    parser.add_argument("source_sha256")
    parser.add_argument("--suite", choices=("physical", "control"), default="physical")
    args = parser.parse_args()
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", args.phase) is None or re.fullmatch(r"[0-9a-f]{64}", args.source_sha256) is None:
        parser.error("phase and source SHA256 must be canonical")
    root = Path(__file__).resolve().parents[1]
    source = (root / "examples/ecs-native/deploy/Jenkinsfile.tenant-physical.in").read_text(encoding="utf-8")
    rendered = source.replace("@@PHASE@@", args.phase).replace("@@SOURCE_SHA256@@", args.source_sha256)
    rendered = rendered.replace("@@TEST_PATH@@", "tests/test_workspace_execution_" + args.suite + ".py")
    if "@@" in rendered:
        parser.error("unresolved pipeline template marker")
    print(rendered, end="")


if __name__ == "__main__":
    main()
