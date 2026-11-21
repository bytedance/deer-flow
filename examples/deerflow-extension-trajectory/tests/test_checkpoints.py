from types import SimpleNamespace

from deerflow_extension_trajectory.checkpoints import project, transition


def test_uploaded_images_are_extracted_before_text_truncation():
    text = (
        "hello\n"
        + "x" * 4100
        + "\n<current_uploads>\n- photo (1).png (176.4 KB)\n  Path: /mnt/user-data/uploads/photo (1).png\nInstructions\n</current_uploads>"
    )
    row = project(snapshot([{"type": "human", "id": "u", "content": text}]))[
        "messages"
    ][0]
    assert row["images"] == [
        {
            "name": "photo (1).png",
            "path": "/mnt/user-data/uploads/photo (1).png",
            "size": "176.4 KB",
        }
    ]
    assert "current_uploads" not in row["display_text"]
    assert row["display_text"].startswith("hello")


def test_upload_preview_rejects_paths_outside_uploads_and_active_images():
    paths = [
        "/etc/private.png",
        "/mnt/user-data/uploads/../secret.png",
        "/mnt/user-data/uploads/a.svg",
        "https://example.com/a.png",
    ]
    text = (
        "<current_uploads>\n"
        + "\n".join(f"- a.png (1 KB)\nPath: {p}" for p in paths)
        + "\n</current_uploads>"
    )
    row = project(snapshot([{"type": "human", "content": text}]))["messages"][0]
    assert row["images"] == []
    assert row["display_text"] == row["text"]


def snapshot(messages, summary="", next_nodes=()):
    return SimpleNamespace(
        values={"messages": messages, "summary_text": summary},
        next=next_nodes,
        config={"configurable": {"checkpoint_id": "b"}},
        parent_config={},
        metadata={},
        created_at="2026-10-08T03:46:33Z",
    )


def test_compaction_retains_earlier_evidence_without_repeating_rescued_user():
    human = {"type": "human", "id": "u", "content": "research"}
    call = {
        "type": "ai",
        "id": "a",
        "tool_calls": [{"id": "c", "name": "web_search", "args": {"query": "test"}}],
    }
    old = project(
        snapshot(
            [human, call], next_nodes=("DeerFlowSummarizationMiddleware.before_model",)
        )
    )
    new = project(snapshot([human], "summary"))
    rows = transition(old, new)
    assert [r["kind"] for r in rows] == ["compaction"]
    assert rows[0]["before_count"] == 2
    assert rows[0]["after_count"] == 1
    assert (
        transition(project(snapshot([])), old)[1]["tool_calls"][0]["name"]
        == "web_search"
    )


def test_tool_errors_use_host_metadata_and_unproven_removal_is_not_compaction():
    old = project(snapshot([{"type": "human", "id": "u", "content": "hello"}]))
    result = {
        "type": "tool",
        "id": "r",
        "tool_call_id": "c",
        "name": "str_replace",
        "content": "blocked",
        "additional_kwargs": {"deerflow_tool_meta": {"status": "error"}},
    }
    new = project(snapshot([result]))
    rows = transition(old, new)
    assert rows[0]["kind"] == "state_change"
    assert rows[1]["tool_status"] == "error"


def test_hidden_context_and_unchanged_messages_do_not_generate_rows():
    s = project(
        snapshot(
            [
                {
                    "type": "system",
                    "id": "s",
                    "content": "private",
                    "additional_kwargs": {"hide_from_ui": True},
                },
                {"type": "ai", "id": "a", "content": "OK"},
            ]
        )
    )
    assert transition(s, s) == []
    assert len(transition(project(snapshot([])), s)) == 1


def test_message_updates_are_marked_and_truncation_keeps_full_content_fingerprint():
    old = project(snapshot([{"type": "ai", "id": "a", "content": "x" * 6000 + "A"}]))
    new = project(snapshot([{"type": "ai", "id": "a", "content": "x" * 6000 + "B"}]))
    rows = transition(old, new)
    assert len(rows) == 1 and rows[0]["updated"]
    assert rows[0]["truncated"]


def test_usage_metadata_changes_are_not_new_assistant_messages():
    old = {
        "type": "ai",
        "id": "a",
        "content": "OK",
        "usage_metadata": {"total_tokens": 1},
    }
    new = {**old, "usage_metadata": {"total_tokens": 2}}
    assert transition(project(snapshot([old])), project(snapshot([new]))) == []


def test_host_message_id_normalization_is_not_a_duplicate_user_turn():
    old = {"type": "human", "id": "temporary", "content": "hello"}
    new = {**old, "id": "temporary__user"}
    assert transition(project(snapshot([old])), project(snapshot([new]))) == []
    # An additional identical question is still a real new message.
    rows = transition(project(snapshot([old])), project(snapshot([old, new])))
    assert len(rows) == 1 and rows[0]["kind"] == "user"


def test_equal_content_without_proven_identity_is_retained():
    old = {"type": "human", "id": "old", "content": "hello"}
    new = {**old, "id": "new"}
    rows = transition(project(snapshot([old])), project(snapshot([new])))
    assert any(row.get("id") == "new" for row in rows)


def test_named_host_control_messages_are_not_visible():
    result = project(
        snapshot([{"type": "human", "name": "todo_reminder", "content": "internal"}])
    )
    assert result["messages"] == []


def test_manual_compaction_including_repeated_calls_uses_compaction_label():
    messages = [
        {"type": "human", "id": "u", "content": "hello"},
        {"type": "ai", "id": "a", "content": "answer"},
    ]
    for prior_marker in ({}, {"manual_compaction": {}}):
        before = snapshot(messages, "old summary")
        before.versions_seen = prior_marker
        after = snapshot(messages[1:], "new summary")
        after.metadata = {"source": "update"}
        after.versions_seen = {"manual_compaction": {}}
        rows = transition(project(before), project(after))
        assert [row["kind"] for row in rows] == ["compaction"]


def test_inherited_manual_marker_alone_does_not_classify_state_edits_as_compaction():
    messages = [
        {"type": "human", "id": "u", "content": "hello"},
        {"type": "ai", "id": "a", "content": "answer"},
    ]
    before = snapshot(messages, "old summary")
    before.versions_seen = {"manual_compaction": {}}
    for retained, summary, source in [
        (messages[1:], "old summary", "update"),
        (messages, "new summary", "update"),
        (messages[1:], "new summary", "loop"),
        (messages[1:], "", "update"),
    ]:
        after = snapshot(retained, summary)
        after.metadata = {"source": source}
        after.versions_seen = {"manual_compaction": {}}
        assert transition(project(before), project(after))[0]["kind"] == "state_change"
