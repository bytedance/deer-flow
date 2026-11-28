from types import SimpleNamespace

from deerflow_extension_trajectory.checkpoints import project, transition


def state(messages, summary, cid, next_nodes=()):
    return SimpleNamespace(
        values={"messages": messages, "summary_text": summary},
        config={"configurable": {"checkpoint_id": cid}},
        next=next_nodes,
        created_at="now",
    )


def test_comparison_keeps_previous_summary_full_content_and_message_order():
    messages = [
        {"type": "human", "id": "u", "content": "request"},
        {
            "type": "ai",
            "id": "a",
            "content": "",
            "tool_calls": [
                {"id": "call", "name": "read_file", "args": {"path": "file"}}
            ],
        },
        {
            "type": "tool",
            "id": "t",
            "tool_call_id": "call",
            "content": "result " * 1000,
        },
        {"type": "ai", "id": "keep", "content": "answer"},
    ]
    before = project(
        state(messages, "old " * 1500, "before", ("Summarization.before_model",)),
        text_limit=None,
        include_content=True,
    )
    after = project(
        state(messages[-1:], "new " * 1500, "after"),
        text_limit=None,
        include_content=True,
    )
    row = transition(before, after, include_comparison=True)[0]
    comparison = row["comparison"]
    assert row["kind"] == "compaction"
    assert comparison["before_checkpoint_id"] == "before"
    assert comparison["after_checkpoint_id"] == "after"
    assert comparison["before_summary"] == "old " * 1500
    assert comparison["after_summary"] == "new " * 1500
    assert [m["id"] for m in comparison["removed_messages"]] == ["u", "a", "t"]
    assert comparison["removed_messages"][-1]["content"] == "result " * 1000
    assert [m["id"] for m in comparison["retained_messages"]] == ["keep"]


def test_comparison_preserves_structured_content_reports_omissions_and_ignores_id_rewrites():
    hidden = {
        "type": "human",
        "id": "h",
        "content": "hidden",
        "additional_kwargs": {"hide_from_ui": True},
    }
    blocks = [
        {"type": "text", "text": "see image"},
        {"type": "image_url", "image_url": {"url": "https://example.com/image.png"}},
    ]
    removed = {"type": "human", "id": "u", "content": blocks}
    keep = {"type": "ai", "id": "old-id", "content": "keep"}
    before = project(
        state([hidden, removed, keep], "", "b", ("Summarization.before_model",)),
        text_limit=None,
        include_content=True,
    )
    after = project(
        state([keep], "summary", "a"),
        text_limit=None,
        include_content=True,
    )
    comparison = transition(before, after, include_comparison=True)[0]["comparison"]
    assert [m["id"] for m in comparison["removed_messages"]] == ["u"]
    assert comparison["removed_messages"][0]["content"] == blocks
    assert comparison["omitted_before_count"] == 1
    assert comparison["omitted_after_count"] == 0
