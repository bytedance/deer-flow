from __future__ import annotations

from langchain_core.messages import HumanMessage

from deerflow.runtime.runs.callbacks.builder import build_run_callbacks
from deerflow.runtime.runs.types import RunRecord, RunStatus


def _record() -> RunRecord:
    return RunRecord(
        run_id="run-1",
        thread_id="thread-1",
        assistant_id=None,
        status=RunStatus.pending,
        temporary=False,
        multitask_strategy="reject",
        metadata={},
        created_at="",
        updated_at="",
    )


def test_build_run_callbacks_sets_first_human_message_from_string_content():
    artifacts = build_run_callbacks(
        record=_record(),
        graph_input={"messages": [HumanMessage(content="hello world")]},
        event_store=None,
    )

    assert artifacts.completion_data().first_human_message == "hello world"


def test_build_run_callbacks_sets_first_human_message_from_content_blocks():
    artifacts = build_run_callbacks(
        record=_record(),
        graph_input={
            "messages": [
                HumanMessage(
                    content=[
                        {"type": "text", "text": "hello "},
                        {"type": "text", "text": "world"},
                    ]
                )
            ]
        },
        event_store=None,
    )

    assert artifacts.completion_data().first_human_message == "hello world"


def test_build_run_callbacks_sets_first_human_message_from_dict_payload():
    artifacts = build_run_callbacks(
        record=_record(),
        graph_input={
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "hi from dict"}],
                }
            ]
        },
        event_store=None,
    )

    assert artifacts.completion_data().first_human_message == "hi from dict"
