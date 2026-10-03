"""Tests for projecting LangGraph interrupts onto the wire format.

``serialize_interrupts`` is the single source of truth shared by
``DeerFlowClient`` (stream events) and the Gateway REST layer (thread state
and history). Both surfaces must agree, or a client that reconciles a resumed
stream against a refetched snapshot sees two different shapes for the same
pending approval.
"""

from __future__ import annotations

from types import SimpleNamespace

from langgraph.types import Interrupt

from deerflow.runtime import serialize_interrupts, serialize_tasks_for_api
from deerflow.runtime.serialization import serialize


def test_projects_slotted_interrupt_objects() -> None:
    """``Interrupt`` uses ``__slots__``, so it must be read field by field."""
    interrupts = (Interrupt(value={"action": "bash"}, id="int-1"),)

    assert serialize_interrupts(interrupts) == [{"id": "int-1", "value": {"action": "bash"}}]


def test_absent_channel_yields_nothing() -> None:
    for empty in (None, (), []):
        assert serialize_interrupts(empty) == []


def test_already_serialized_entries_pass_through() -> None:
    """A checkpoint replay can hand back dicts rather than ``Interrupt``s."""
    payload = [{"id": "int-2", "value": {"action": "write_file"}}]

    assert serialize_interrupts(payload) == payload


def test_entries_without_a_value_are_skipped() -> None:
    """Anything that is not interrupt-shaped must not reach the client."""
    assert serialize_interrupts([object(), Interrupt(value=1, id="int-3")]) == [{"id": "int-3", "value": 1}]


def test_a_bare_interrupt_is_treated_as_one_entry() -> None:
    """Tolerate a single object where a tuple is normally published."""
    assert serialize_interrupts(Interrupt(value="approve?", id="int-4")) == [{"id": "int-4", "value": "approve?"}]


def test_string_payload_is_not_iterated_character_by_character() -> None:
    """A str is Iterable; treating it as a sequence would emit garbage."""
    assert serialize_interrupts("not-an-interrupt") == []


def test_nested_payload_is_json_serialisable() -> None:
    """Interrupt values carry tool args, which may hold LangChain objects."""
    value = {"action_request": {"action": "bash", "args": {"command": "ls"}}}

    assert serialize_interrupts([Interrupt(value=value, id="int-5")]) == [{"id": "int-5", "value": value}]


def test_tasks_projection_keeps_interrupts() -> None:
    """The REST ``tasks`` projection previously dropped the payload entirely.

    Keeping only ``{id, name}`` made a parked approval invisible to any client
    that refetched thread state instead of following the stream.
    """
    task = SimpleNamespace(id="task-1", name="tools", interrupts=(Interrupt(value={"action": "bash"}, id="int-6"),))

    assert serialize_tasks_for_api([task]) == [{"id": "task-1", "name": "tools", "interrupts": [{"id": "int-6", "value": {"action": "bash"}}]}]


def test_tasks_projection_omits_interrupts_when_there_are_none() -> None:
    """An ordinary in-flight task must not grow an empty key."""
    task = SimpleNamespace(id="task-2", name="model", interrupts=())

    assert serialize_tasks_for_api([task]) == [{"id": "task-2", "name": "model"}]


def test_tasks_projection_tolerates_missing_attributes() -> None:
    """Snapshots from older checkpoints may not carry every field."""
    assert serialize_tasks_for_api([SimpleNamespace()]) == [{"id": "", "name": ""}]


def test_tasks_projection_handles_no_tasks() -> None:
    for empty in (None, (), []):
        assert serialize_tasks_for_api(empty) == []


def test_updates_frame_keeps_the_interrupt_readable() -> None:
    """The web chat stream's only in-stream witness to a park.

    ``forceChatRunStreamOptions`` deletes the ``values`` mode, so the browser
    never sees the ``values`` snapshot that carries ``__interrupt__``. LangGraph
    also emits the pending interrupt on ``updates``, and that frame is what the
    frontend reads (``extractUpdateInterrupts``). It reaches ``serialize`` with
    no mode-specific branch, so the generic ``Interrupt`` projection is what
    keeps it usable — losing it would leave the approval card undrawn until the
    post-stream history refetch.
    """
    frame = {"__interrupt__": (Interrupt(value={"action_requests": [{"name": "bash_tool"}]}, id="int-7"),)}

    assert serialize(frame, mode="updates") == {"__interrupt__": [{"value": {"action_requests": [{"name": "bash_tool"}]}, "id": "int-7"}]}
