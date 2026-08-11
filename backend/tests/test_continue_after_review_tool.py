from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from deerflow.task_graph.models import CodingTask, TaskStatus
from deerflow.tools.builtins.continue_after_review_tool import (
    REANALYZE_AND_FIX_OPTION,
    continue_after_review,
)


def _runtime(messages: list) -> SimpleNamespace:
    return SimpleNamespace(
        context={"thread_id": "thread-1"},
        config={"configurable": {}},
        state={"messages": messages},
    )


def _approval_messages(task_id: str, *, response_value: str = REANALYZE_AND_FIX_OPTION) -> list:
    request_id = "request-1"
    return [
        ToolMessage(
            id=request_id,
            content="Continue after review?",
            tool_call_id="call-1",
            name="ask_clarification",
            artifact={
                "human_input": {
                    "version": 1,
                    "kind": "human_input_request",
                    "source": "ask_clarification",
                    "request_id": request_id,
                    "clarification_type": "risk_confirmation",
                    "context": f"coding_review_followup:{task_id}",
                    "input_mode": "choice_with_other",
                    "options": [
                        {"id": "option-1", "label": REANALYZE_AND_FIX_OPTION, "value": REANALYZE_AND_FIX_OPTION},
                        {"id": "option-2", "label": "Stop pipeline", "value": "Stop pipeline"},
                    ],
                }
            },
        ),
        HumanMessage(
            content=response_value,
            additional_kwargs={
                "human_input_response": {
                    "version": 1,
                    "kind": "human_input_response",
                    "source": "ask_clarification",
                    "request_id": request_id,
                    "response_kind": "option",
                    "option_id": "option-1" if response_value == REANALYZE_AND_FIX_OPTION else "option-2",
                    "value": response_value,
                }
            },
        ),
    ]


def test_continue_after_failed_review_appends_pipeline_and_reuses_worktree(monkeypatch):
    captured: dict = {}
    review_task = CodingTask(
        id="coding-review",
        subject="Review",
        description="Review implementation",
        status=TaskStatus.completed,
        worktree="D:/repo/.worktrees/coding-run",
        artifact={"report_type": "review_report", "verdict": "FAIL"},
    )

    class FakeGraph:
        store = SimpleNamespace(load=lambda _task_id: review_task)

        def add_tasks(self, tasks):
            captured["tasks"] = tasks

        def bind_worktree(self, task_ids, worktree):
            captured["bound"] = (task_ids, worktree)

        def get_run_plan(self):
            return SimpleNamespace(
                coding_brief={"goal": "Fix", "acceptance_criteria": ["works"], "tasks": [{"id": "coding-review"}]},
                task_ids=["coding-analysis", "coding-implementation", "coding-review"],
            )

        def save_run_plan(self, coding_brief, task_ids):
            captured["run_plan"] = (coding_brief, task_ids)

    monkeypatch.setattr(
        "deerflow.tools.builtins.continue_after_review_tool.resolve_runtime_user_id",
        lambda _runtime: "alice",
    )
    monkeypatch.setattr(
        "deerflow.tools.builtins.continue_after_review_tool.create_task_graph",
        lambda thread_id, *, user_id: captured.update(thread_id=thread_id, user_id=user_id) or FakeGraph(),
    )

    result = continue_after_review.func(
        review_task_id="coding-review",
        runtime=_runtime(_approval_messages("coding-review")),
    )

    assert [task.id for task in captured["tasks"]] == [
        "coding-review-reanalysis",
        "coding-review-fix",
        "coding-review-rereview",
    ]
    assert [task.blocked_by for task in captured["tasks"]] == [
        ["coding-review"],
        ["coding-review-reanalysis"],
        ["coding-review-fix"],
    ]
    assert captured["bound"] == (
        ["coding-review-reanalysis", "coding-review-fix", "coding-review-rereview"],
        "D:/repo/.worktrees/coding-run",
    )
    assert captured["run_plan"][1] == [
        "coding-analysis",
        "coding-implementation",
        "coding-review",
        "coding-review-reanalysis",
        "coding-review-fix",
        "coding-review-rereview",
    ]
    assert captured["thread_id"] == "thread-1"
    assert captured["user_id"] == "alice"
    assert "coding-review-rereview" in result


@pytest.mark.parametrize("messages", [[], _approval_messages("coding-review", response_value="Stop pipeline")])
def test_continue_after_review_requires_matching_approval(monkeypatch, messages):
    monkeypatch.setattr(
        "deerflow.tools.builtins.continue_after_review_tool.create_task_graph",
        lambda *_args, **_kwargs: pytest.fail("graph must not be opened"),
    )

    with pytest.raises(ValueError, match="matching review follow-up approval"):
        continue_after_review.func(review_task_id="coding-review", runtime=_runtime(messages))
