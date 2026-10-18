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
            "service-lifetime",
            "service-final",
            "direct-main",
            "goal-stop",
            "direct-final",
            "sandbox-main",
            "sandbox-final",
            "sandbox-reuse",
            "native-dispatch",
            "native-dispatch-final",
            "native-queue-main",
            "native-queue-final",
            "native-receiver-main",
            "native-receiver-final",
            "native-pool-main",
            "native-pool-final",
            "native-stop-main",
            "native-stop-final",
            "native-dependency-main",
            "native-dependency-revocation",
            "native-dependency-dispatched-revocation",
            "native-scheduler-main",
            "native-scheduler-boundaries",
            "native-schema-compatibility",
            "native-scheduler-resource-http",
            "native-scheduler-history-http",
            "native-scheduler-history-http-final",
            "native-scheduler-tool-list",
            "native-scheduler-tool-remote",
            "native-scheduler-tool-remote-final",
            "native-scheduler-tool-remote-boundaries",
            "native-scheduler-tool-create",
            "native-scheduler-tool-create-terminal",
            "native-scheduler-management",
            "native-scheduler-management-boundaries",
            "native-scheduler-manual-own-stop",
            "native-scheduler-installed-dependency",
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
    if args.suite in (
        "invocation-final",
        "service-final",
        "direct-final",
        "sandbox-final",
    ):
        tests += " tests/test_workspace_run_lifetime.py tests/test_workspace_worker_context.py tests/test_workspace_run_checkpoints.py tests/test_workspace_event_reads.py tests/test_workspace_worker_effects.py tests/test_workspace_invocation_gate.py"
        tests += " tests/test_tool_error_handling_middleware.py::test_build_subagent_runtime_middlewares_threads_app_config_to_llm_middleware tests/test_tool_error_handling_middleware.py::test_build_lead_runtime_middlewares_chain_order_matches_agents_md tests/test_model_factory.py::test_uses_first_model_when_name_is_none tests/test_model_factory.py::test_appends_all_tracing_callbacks tests/test_model_request_admission.py::test_fifo_cancellation_and_queue_capacity tests/test_extension_ordering.py::test_core_constraints_are_declared"
    if args.suite == "service-lifetime":
        tests = "tests/test_workspace_model_service_lifetime.py"
    if args.suite in ("service-final", "direct-final", "sandbox-final"):
        tests += " tests/test_workspace_model_service_lifetime.py tests/test_extension_model_invocation.py::test_provider_errors_do_not_expose_credentials tests/test_extension_model_invocation.py::test_host_timeout_caps_request_and_preserves_running_provider tests/test_extension_model_invocation.py::test_sync_provider_retains_slot_until_thread_finishes tests/test_extension_system_model_calls.py::test_zero_observer_path_only_invokes_the_original_call tests/test_extension_system_model_calls.py::test_async_summarization_observes_each_provider_attempt_and_live_store tests/test_extension_system_model_calls.py::test_title_middleware_uses_build_bound_snapshot_and_live_task_store"
    if args.suite == "direct-main":
        tests = "tests/test_workspace_model_service_lifetime.py::test_native_direct_model_retains_actual_provider"
    if args.suite == "goal-stop":
        tests = "tests/test_workspace_model_service_lifetime.py::test_native_system_model_stop_is_not_an_ordinary_fallback"
    if args.suite in ("direct-final", "sandbox-final"):
        tests += " tests/test_goal_worker.py::test_goal_worker_records_a_failed_evaluator_call tests/test_goal_worker.py::test_goal_worker_returns_hidden_continuation_when_goal_is_unmet tests/test_goal_worker.py::test_goal_worker_defers_satisfied_goal_completion_until_run_finalization tests/test_extension_system_model_calls.py::test_goal_evaluator_observes_success_and_failure_with_explicit_snapshot"
    if args.suite in ("native-dispatch", "native-dispatch-final", "native-queue-final"):
        tests = "tests/test_workspace_native_dispatch.py"
    if args.suite == "native-queue-main":
        tests = "tests/test_workspace_native_dispatch.py::test_native_c_dispatch_preserves_original_workspace[sqlite-normal] tests/test_workspace_native_dispatch.py::test_native_c_dispatch_preserves_original_workspace[postgres-normal]"
    if args.suite in ("native-dispatch-final", "native-queue-final"):
        tests += " tests/test_workspace_execution_ledger.py tests/test_ecs_executor_agent_dispatch.py::test_native_capability_rejects_changed_snapshot_and_assignment tests/test_ecs_executor_agent_dispatch.py::test_native_adoption_rejects_changed_durable_payload_before_owner_transfer tests/test_ecs_executor_operations.py::test_controller_remote_all_requires_literal_operator_true"
    if args.suite == "native-queue-final":
        tests += " tests/test_workspace_revocation.py::test_pending_run_stop_preserves_first_intent_and_original_cleanup_binding tests/test_ecs_executor_agent_dispatch.py::test_queued_cancel_recovers_end_after_native_commit_and_job_terminal"
    if args.suite == "sandbox-reuse":
        tests = "tests/test_workspace_sandbox_dispatch.py::test_native_sandbox_thread_recreation_does_not_restore_old_report"
    if args.suite == "sandbox-main":
        tests = "tests/test_workspace_sandbox_dispatch.py"
    if args.suite == "sandbox-final":
        tests += " tests/test_workspace_sandbox_dispatch.py tests/test_ensure_sandbox_initialized.py::test_post_acquire_lookup_failure_unwinds_async_execution_lease tests/test_ensure_sandbox_initialized.py::test_async_fork_restored_owner_holds_non_releasing_scope_lease tests/test_ensure_sandbox_initialized.py::test_async_reuse_replaces_stale_checkpoint_and_owner_binding tests/test_sandbox_authorization.py::test_async_sandbox_tool_authorizes_once_via_async_provider tests/test_sandbox_authorization.py::test_composed_write_authorization_deny_is_not_swallowed tests/test_read_before_write_middleware.py::TestWriteGate::test_new_file_write_allowed tests/test_read_before_write_middleware.py::TestWriteGate::test_overwrite_existing_without_read_blocked"
    if args.suite in ("native-receiver-main", "native-receiver-final"):
        tests = "tests/test_workspace_native_dispatch.py::test_native_c_receiver_uses_original_sql_authority tests/test_workspace_execution_ledger.py::test_pool_claim_filters_unintegrated_scope_before_limit"
    if args.suite == "native-receiver-final":
        tests += " tests/test_ecs_executor_agent_dispatch.py::test_native_capability_rejects_changed_snapshot_and_assignment tests/test_ecs_executor_agent_dispatch.py::test_native_adoption_rejects_changed_durable_payload_before_owner_transfer"
    if args.suite in ("native-pool-main", "native-pool-final"):
        tests = "tests/test_workspace_native_dispatch.py::test_native_c_pool_dispatch_executes_original_run"
    if args.suite == "native-pool-final":
        tests += " tests/test_workspace_execution_ledger.py::test_pool_claim_filters_unintegrated_scope_before_limit tests/test_ecs_executor_agent_dispatch.py::test_native_capability_rejects_changed_snapshot_and_assignment"
    if args.suite in ("native-stop-main", "native-stop-final"):
        tests = "tests/test_ecs_executor_agent_dispatch.py::test_scoped_native_stop_cannot_acknowledge_a_different_missing_container tests/test_ecs_executor_agent_dispatch.py::test_scoped_native_text_run_proves_no_sandbox_start_after_drain"
    if args.suite == "native-stop-final":
        tests += " tests/test_ecs_executor_agent_dispatch.py::test_native_cancel_stop_is_shared_with_task_finalizer tests/test_ecs_executor_agent_dispatch.py::test_native_lost_ownership_retains_attempt_reservation tests/test_workspace_native_dispatch.py::test_native_c_pool_dispatch_executes_original_run"
    if args.suite == "native-dependency-main":
        tests = "tests/test_workspace_native_dependencies.py::test_scoped_native_dependency_notification_resumes_original_goal[normal-postgres]"
    if args.suite == "native-dependency-revocation":
        tests = "tests/test_workspace_native_dependencies.py::test_scoped_native_dependency_notification_resumes_original_goal[notification_member-postgres]"
    if args.suite == "native-dependency-dispatched-revocation":
        tests = "tests/test_workspace_native_dependencies.py::test_scoped_native_dependency_notification_resumes_original_goal[dispatched_member-postgres]"
    if args.suite == "native-scheduler-main":
        tests = "tests/test_workspace_native_scheduler.py::test_scoped_scheduler_occurrence_keeps_original_workspace[normal-postgres]"
    if args.suite == "native-scheduler-boundaries":
        tests = (
            "tests/test_workspace_native_scheduler.py::test_scoped_scheduler_occurrence_keeps_original_workspace[queued_member-postgres] "
            "tests/test_workspace_native_scheduler.py::test_scoped_scheduler_occurrence_keeps_original_workspace[launch_lease-postgres]"
        )
    if args.suite == "native-schema-compatibility":
        tests = "tests/test_workspace_execution_wire.py::test_known_native_schema_starts_scoped_b_and_control[postgres]"
    if args.suite == "native-scheduler-resource-http":
        tests = "tests/test_workspace_native_scheduler.py::test_scoped_scheduler_http_create_list_detail_use_current_resource_scope[postgres]"
    if args.suite == "native-scheduler-history-http":
        tests = "tests/test_workspace_native_scheduler.py::test_scoped_scheduler_http_history_and_thread_relations_keep_private_run[postgres]"
    if args.suite == "native-scheduler-history-http-final":
        tests = (
            "tests/test_workspace_native_scheduler.py::test_scoped_scheduler_http_history_and_thread_relations_keep_private_run[postgres] "
            "tests/test_workspace_native_scheduler.py::test_scoped_scheduler_http_create_list_detail_use_current_resource_scope[postgres]"
        )
    if args.suite == "native-scheduler-tool-list":
        tests = "tests/test_workspace_native_scheduler.py::test_scoped_scheduler_tool_list_uses_original_native_invocation[postgres]"
    if args.suite in ("native-scheduler-tool-remote", "native-scheduler-tool-remote-final"):
        tests = "tests/test_workspace_native_scheduler.py::test_scoped_scheduler_remote_tool_list_preserves_admitted_session[postgres]"
    if args.suite == "native-scheduler-tool-remote-final":
        tests += " tests/test_workspace_native_scheduler.py::test_scoped_scheduler_tool_list_uses_original_native_invocation[postgres]"
    if args.suite == "native-scheduler-tool-remote-boundaries":
        tests = (
            "tests/test_workspace_native_scheduler.py::test_scoped_scheduler_remote_tool_retains_original_authority[token_version-postgres] "
            "tests/test_workspace_native_scheduler.py::test_scoped_scheduler_remote_tool_retains_original_authority[permission_ceiling-postgres]"
        )
    if args.suite == "native-scheduler-tool-create":
        tests = "tests/test_workspace_native_scheduler.py::test_scoped_scheduler_remote_tool_create_queues_original_workspace[postgres]"
    if args.suite == "native-scheduler-tool-create-terminal":
        tests = "tests/test_workspace_native_scheduler.py::test_scoped_scheduler_remote_tool_create_rejects_terminal_writer[postgres]"
    if args.suite == "native-scheduler-management":
        tests = (
            "tests/test_workspace_native_scheduler.py::test_scoped_scheduler_http_management_keeps_original_execution[postgres] "
            "tests/test_workspace_native_scheduler.py::test_scoped_scheduler_remote_tool_management_keeps_original_execution[postgres]"
        )
    if args.suite == "native-scheduler-management-boundaries":
        tests = (
            "tests/test_workspace_native_scheduler.py::test_scoped_scheduler_http_management_preserves_control_boundaries[unknown_wait-postgres] "
            "tests/test_workspace_native_scheduler.py::test_scoped_scheduler_http_management_preserves_control_boundaries[stale_snapshot-postgres]"
        )
    if args.suite == "native-scheduler-manual-own-stop":
        tests = "tests/test_workspace_native_scheduler.py::test_scoped_scheduler_note_manual_and_own_stop_use_native_lifecycle[postgres]"
    if args.suite == "native-scheduler-installed-dependency":
        tests = "tests/test_workspace_native_dependencies.py::test_scoped_installed_scheduler_dependency_transfers_original_occurrence[postgres]"
    rendered = rendered.replace("@@TEST_PATHS@@", tests)
    if "@@" in rendered:
        parser.error("unresolved pipeline marker")
    print(rendered, end="")


if __name__ == "__main__":
    main()
