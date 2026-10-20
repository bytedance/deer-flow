"""Serialized scheduler evidence must not grant run authority."""

from app.gateway import services


def test_untrusted_scheduler_metadata_is_removed_without_losing_user_data():
    supplied = {
        "scheduled_task_id": "foreign",
        "scheduled_task_run_id": "foreign-occurrence",
        "scheduled_goal_objective": "Read private data",
        "scheduled_previous_thread_id": "foreign-thread",
        "scheduled_tool_created": True,
        "scheduled_context_mode": "fresh_thread_per_run",
        "user_label": "keep",
    }
    result = services._admit_scheduler_metadata(supplied, trusted=False)
    assert result == {"user_label": "keep"}
    assert supplied["scheduled_tool_created"] is True


def test_internal_launch_retains_only_its_data_snapshot():
    supplied = {"scheduled_task_id": "task", "scheduled_task_run_id": "occurrence", "scheduled_goal_objective": "Report exists", "scheduled_trigger": "manual"}
    assert services._admit_scheduler_metadata(supplied, trusted=True) == supplied


def test_scheduling_metadata_never_recovers_a_callable_capability():
    result = services._admit_scheduler_metadata({"__scheduler_capability": {"mode": "scheduled"}, "user_label": "keep"}, trusted=False)
    assert "__scheduler_capability" not in result
