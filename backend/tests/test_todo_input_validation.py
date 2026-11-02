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
@pytest.mark.parametrize("todos", [None, []])
def test_external_todos_preserve_null_and_empty(boundary, todos):
    assert boundary({"todos": todos})["todos"] == todos


@pytest.mark.parametrize("boundary", BOUNDARIES)
def test_todos_are_not_added_when_absent(boundary):
    assert "todos" not in boundary({"title": "unrelated"})
