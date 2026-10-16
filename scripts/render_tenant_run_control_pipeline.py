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
        choices=(
            "revocation",
            "lifetime",
            "checkpoint",
            "checkpoint-regression",
            "effects",
            "effects-regression",
            "effects-final",
            "stream-main",
            "invocation",
            "invocation-red",
            "invocation-final",
        ),
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
    if args.suite == "effects":
        tests = "tests/test_workspace_worker_effects.py"
    if args.suite in ("effects-regression", "effects-final"):
        tests += " tests/test_workspace_run_lifetime.py tests/test_workspace_worker_context.py tests/test_workspace_run_checkpoints.py tests/test_workspace_event_reads.py"
    if args.suite == "effects-final":
        tests += " tests/test_workspace_worker_effects.py tests/test_run_journal.py::test_close_flushes_and_detaches_runtime_dependencies tests/test_run_journal.py::test_close_preserves_buffer_and_dependencies_when_flush_fails tests/test_run_worker_delivery.py::test_delivery_is_durable_before_terminal_run_status tests/test_run_worker_delivery.py::test_delivery_write_retries_before_persisting_success tests/test_run_repository.py::TestRunRepository::test_update_run_completion"
    if args.suite == "stream-main":
        tests = " ".join(
            "tests/test_workspace_worker_effects.py::test_native_journal_and_completion_keep_execution_authority["
            + dialect
            + "-"
            + trigger
            + "]"
            for dialect in ("sqlite", "postgres")
            for trigger in ("normal", "member")
        )
    if args.suite == "invocation":
        tests = "tests/test_workspace_invocation_gate.py"
    if args.suite == "invocation-red":
        tests = "tests/test_workspace_invocation_gate.py tests/test_workspace_worker_effects.py"
    if args.suite == "invocation-final":
        tests += " tests/test_workspace_run_lifetime.py tests/test_workspace_worker_context.py tests/test_workspace_run_checkpoints.py tests/test_workspace_event_reads.py tests/test_workspace_worker_effects.py tests/test_workspace_invocation_gate.py"
        tests += " tests/test_tool_error_handling_middleware.py::test_build_subagent_runtime_middlewares_threads_app_config_to_llm_middleware tests/test_tool_error_handling_middleware.py::test_build_lead_runtime_middlewares_chain_order_matches_agents_md tests/test_model_factory.py::test_uses_first_model_when_name_is_none tests/test_model_factory.py::test_appends_all_tracing_callbacks tests/test_model_request_admission.py::test_fifo_cancellation_and_queue_capacity tests/test_extension_ordering.py::test_core_constraints_are_declared"
    rendered = rendered.replace("@@TEST_PATHS@@", tests)
    if "@@" in rendered:
        parser.error("unresolved pipeline marker")
    print(rendered, end="")


if __name__ == "__main__":
    main()
