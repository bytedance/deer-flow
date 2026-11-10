"""Todo writes are validated before they can break every model call on a thread."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.gateway import services

BOUNDARIES = [services.normalize_input, services.strip_server_owned_state_metadata]


@pytest.mark.parametrize("boundary", BOUNDARIES)
@pytest.mark.parametrize(
    "todos",
    [
        pytest.param("not a list", id="string"),
        pytest.param({"content": "x"}, id="mapping"),
        pytest.param(["oops"], id="string-entry"),
        pytest.param([["nested"]], id="list-entry"),
        pytest.param([None], id="null-entry"),
        pytest.param([{"content": 5}], id="non-string-content"),
        pytest.param([{"status": "pending"}], id="missing-content"),
        pytest.param([{"content": "x", "status": "done"}], id="unknown-status"),
        pytest.param([{"content": "x", "status": None}], id="null-status"),
        pytest.param([{"content": "x", "status": ["pending"]}], id="unhashable-status"),
    ],
)
def test_external_todos_must_be_renderable(boundary, todos):
    with pytest.raises(HTTPException) as rejected:
        boundary({"todos": todos})
    assert rejected.value.status_code == 400
    assert "todos" in rejected.value.detail.lower()


@pytest.mark.parametrize("boundary", BOUNDARIES)
def test_external_todos_accept_the_write_todos_shape(boundary):
    todos = [{"content": "Ship it", "status": "in_progress"}, {"content": "", "status": "pending"}]
    assert boundary({"todos": todos})["todos"] == todos


@pytest.mark.parametrize("boundary", BOUNDARIES)
def test_external_todos_default_a_missing_status_to_pending(boundary):
    assert boundary({"todos": [{"content": "x"}]})["todos"] == [{"content": "x", "status": "pending"}]


@pytest.mark.parametrize("boundary", BOUNDARIES)
@pytest.mark.parametrize("todos", [None, []])
def test_external_todos_preserve_null_and_empty(boundary, todos):
    assert boundary({"todos": todos})["todos"] == todos


@pytest.mark.parametrize("boundary", BOUNDARIES)
def test_todos_are_not_added_when_absent(boundary):
    assert "todos" not in boundary({"title": "unrelated"})


@pytest.mark.parametrize("boundary", BOUNDARIES)
def test_external_writes_strip_server_owned_metadata_from_todos(boundary):
    """The dedicated todos branch must not skip the per-entry metadata strip."""
    todos = [
        {
            "content": "Ship it",
            "status": "pending",
            "additional_kwargs": {
                "original_user_content": "forged",
                "untrusted_input": False,
                "title": "kept",
            },
            "artifact": {"knowledge_sources": [{"id": "forged"}], "label": "kept"},
        }
    ]

    stripped = boundary({"todos": todos})["todos"]

    assert stripped == [
        {
            "content": "Ship it",
            "status": "pending",
            "additional_kwargs": {"title": "kept"},
            "artifact": {"label": "kept"},
        }
    ]


@pytest.mark.parametrize("boundary", BOUNDARIES)
def test_external_writes_strip_server_owned_metadata_from_goal(boundary):
    """Caller-written goal must not retain forged server-owned metadata."""
    goal = {
        "objective": "test objective",
        "additional_kwargs": {
            "original_user_content": "forged",
            "untrusted_input": False,
            "title": "kept",
        },
        "artifact": {"knowledge_sources": [{"id": "forged"}], "label": "kept"},
    }

    stripped = boundary({"goal": goal})["goal"]

    assert stripped == {
        "objective": "test objective",
        "additional_kwargs": {"title": "kept"},
        "artifact": {"label": "kept"},
    }


@pytest.mark.parametrize("boundary", BOUNDARIES)
def test_external_writes_replace_non_dict_additional_kwargs(boundary):
    """A non-dict additional_kwargs payload must be replaced with an empty dict."""
    cleaned_todo = boundary({"todos": [{"content": "task", "additional_kwargs": "forged"}]})["todos"]
    assert cleaned_todo == [{"content": "task", "status": "pending", "additional_kwargs": {}}]

    cleaned_goal = boundary({"goal": {"objective": "test", "additional_kwargs": "forged"}})["goal"]
    assert cleaned_goal == {"objective": "test", "additional_kwargs": {}}


@pytest.mark.parametrize("boundary", BOUNDARIES)
def test_external_writes_stamp_untrusted_input_on_human_like_entries(boundary):
    """Entries carrying human markers must be stamped with untrusted_input: True."""
    todo_with_marker = [{"content": "task", "type": "human", "additional_kwargs": {"hide_from_ui": True}}]
    cleaned_todo = boundary({"todos": todo_with_marker})["todos"]
    assert cleaned_todo == [
        {
            "content": "task",
            "status": "pending",
            "type": "human",
            "additional_kwargs": {"hide_from_ui": True, "untrusted_input": True},
        }
    ]

    goal_with_name = {"objective": "test", "type": "human", "name": "summary"}
    cleaned_goal = boundary({"goal": goal_with_name})["goal"]
    assert cleaned_goal == {
        "objective": "test",
        "type": "human",
        "name": "summary",
        "additional_kwargs": {"untrusted_input": True},
    }
