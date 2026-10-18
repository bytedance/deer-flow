"""Render the Shanghai-only physical test pipeline; standard library, no runtime."""

import argparse
import re
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Render the owned Shanghai physical CI template")
    parser.add_argument("phase")
    parser.add_argument("source_sha256")
    parser.add_argument("--suite", choices=("physical", "control", "scheduled-dependency", "shared-pool-dependency"), default="physical")
    args = parser.parse_args()
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", args.phase) is None or re.fullmatch(r"[0-9a-f]{64}", args.source_sha256) is None:
        parser.error("phase and source SHA256 must be canonical")
    root = Path(__file__).resolve().parents[1]
    source = (root / "examples/ecs-native/deploy/Jenkinsfile.tenant-physical.in").read_text(encoding="utf-8")
    rendered = source.replace("@@PHASE@@", args.phase).replace("@@SOURCE_SHA256@@", args.source_sha256)
    test_path = "tests/test_workspace_execution_" + args.suite + ".py"
    if args.suite == "scheduled-dependency":
        test_path = "tests/test_workspace_execution_physical.py::test_scoped_scheduled_c_real_b_docker_resumes_original_occurrence[postgres] tests/test_ecs_native_publication_permissions.py"
    if args.suite == "shared-pool-dependency":
        test_path = (
            "tests/test_workspace_execution_physical.py::test_scoped_shared_pool_c_real_b_docker_resumes_original_occurrence[postgres] "
            "tests/test_workspace_execution_ledger.py::test_pool_claim_filters_unintegrated_scope_before_limit[postgres]"
        )
    rendered = rendered.replace("@@TEST_PATH@@", test_path)
    if "@@" in rendered:
        parser.error("unresolved pipeline template marker")
    print(rendered, end="")


if __name__ == "__main__":
    main()
