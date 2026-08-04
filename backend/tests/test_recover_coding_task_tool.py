from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from deerflow.task_graph.models import CodingTask, TaskStatus
from deerflow.tools.builtins.recover_coding_task_tool import recover_coding_task

RETRY_OPTION = "Retry failed task"


def _approval_messages(
    task_id: str,
    *,
    request_id: str = "request-1",
    response_value: str = RETRY_OPTION,
    response_request_id: str | None = None,
) -> list:
    return [
        ToolMessage(
            id=request_id,
            content="Retry this failed coding task?",
            tool_call_id="call-1",
            name="ask_clarification",
            artifact={
                "human_input": {
                    "version": 1,
                    "kind": "human_input_request",
                    "source": "ask_clarification",
                    "request_id": request_id,
                    "clarification_type": "risk_confirmation",
                    "context": f"coding_task_recovery:{task_id}",
                    "input_mode": "choice_with_other",
                    "options": [
                        {"id": "option-1", "label": RETRY_OPTION, "value": RETRY_OPTION},
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
                    "request_id": response_request_id or request_id,
                    "response_kind": "option",
                    "option_id": "option-1" if response_value == RETRY_OPTION else "option-2",
                    "value": response_value,
                }
            },
        ),
    ]


def _runtime(messages: list, *, thread_id: str | None = "thread-1") -> SimpleNamespace:
    context = {} if thread_id is None else {"thread_id": thread_id}
    return SimpleNamespace(context=context, config={"configurable": {}}, state={"messages": messages})


def test_recover_coding_task_requires_matching_structured_approval(monkeypatch):
    captured: dict = {}

    class FakeGraph:
        def recover(self, task_id: str) -> CodingTask:
            captured["task_id"] = task_id
            return CodingTask(
                id=task_id,
                subject="Implement",
                description="Implement the change",
                status=TaskStatus.pending,
            )

    def fake_create_task_graph(thread_id: str, *, user_id: str) -> FakeGraph:
        captured["thread_id"] = thread_id
        captured["user_id"] = user_id
        return FakeGraph()

    monkeypatch.setattr(
        "deerflow.tools.builtins.recover_coding_task_tool.resolve_runtime_user_id",
        lambda runtime: "alice",
    )
    monkeypatch.setattr(
        "deerflow.tools.builtins.recover_coding_task_tool.create_task_graph",
        fake_create_task_graph,
    )

    result = recover_coding_task.func(
        coding_task_id="coding-implementation",
        runtime=_runtime(_approval_messages("coding-implementation")),
    )

    assert captured == {
        "thread_id": "thread-1",
        "user_id": "alice",
        "task_id": "coding-implementation",
    }
    assert result == "Recovered coding task coding-implementation to pending"


@pytest.mark.parametrize(
    "messages",
    [
        [],
        _approval_messages("another-task"),
        _approval_messages("coding-implementation", response_value="Stop pipeline"),
        _approval_messages("coding-implementation", response_request_id="another-request"),
    ],
    ids=["missing", "wrong-task", "rejected", "wrong-request"],
)
def test_recover_coding_task_rejects_missing_or_mismatched_approval(monkeypatch, messages):
    def unexpected_create_task_graph(*args, **kwargs):
        raise AssertionError("task graph must not be opened without matching approval")

    monkeypatch.setattr(
        "deerflow.tools.builtins.recover_coding_task_tool.create_task_graph",
        unexpected_create_task_graph,
    )

    with pytest.raises(ValueError, match="matching retry approval is required"):
        recover_coding_task.func(
            coding_task_id="coding-implementation",
            runtime=_runtime(messages),
        )


def test_recover_coding_task_requires_thread_id():
    with pytest.raises(ValueError, match="thread_id is required"):
        recover_coding_task.func(
            coding_task_id="coding-implementation",
            runtime=_runtime(_approval_messages("coding-implementation"), thread_id=None),
        )
