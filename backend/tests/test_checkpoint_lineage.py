"""Replay-base resolution rules shared by regenerate, edit replay and branching.

The load-bearing rule here is that a replay base must be a checkpoint the
thread was actually at rest in. A mid-run checkpoint still owns the interrupted
node's pending writes, so resuming from it replays them.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.gateway.checkpoint_lineage import (
    CheckpointParentMissingError,
    find_checkpoint_before_message,
    find_checkpoint_before_message_chronologically,
    is_duration_only_checkpoint,
)

THREAD_ID = "thread-1"

# The metadata a Postgres row carries for a duration-only checkpoint: the
# writer's ``writes.runtime_run_duration`` stamp was dropped by langgraph's
# Postgres metadata serialisation, so only the index keys and ``source``
# survive the round trip.
_POSTGRES_DURATION_METADATA = {
    "source": "update",
    "step": 3,
    "run_durations": {"run-1": 12},
    "run_message_ids": {"ai-1": "run-1"},
}

# A Postgres-shaped leaf inherits these stamps whenever a metadata-copying
# writer (title, goal) stacks on a stamped head, but bumps a channel version.
_POSTGRES_INHERITED_STAMPS = {"source": "update", "step": 4, "run_durations": {"run-1": 12}}


def _snapshot(checkpoint_id: str, messages: list[object], *, next_tasks: tuple[str, ...] = (), parent_id: str | None = None, metadata: dict | None = None, channel_versions: dict | None = None):
    parent_config = None
    if parent_id is not None:
        parent_config = {"configurable": {"thread_id": THREAD_ID, "checkpoint_ns": "", "checkpoint_id": parent_id}}
    return SimpleNamespace(
        values={"messages": messages},
        config={
            "configurable": {
                "thread_id": THREAD_ID,
                "checkpoint_ns": "",
                "checkpoint_id": checkpoint_id,
                "checkpoint_map": None,
            }
        },
        checkpoint={"channel_versions": dict(channel_versions or {})},
        metadata=metadata or {},
        parent_config=parent_config,
        next=next_tasks,
    )


class _Accessor:
    """Minimal accessor over a fixed snapshot list, keyed by checkpoint id."""

    def __init__(self, snapshots: list[object]) -> None:
        self.snapshots = snapshots

    async def aget(self, config):
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id")
        return next(
            (item for item in self.snapshots if item.config["configurable"]["checkpoint_id"] == checkpoint_id),
            SimpleNamespace(values={}, config={}, metadata=None, parent_config=None, next=()),
        )


def _first_turn_history() -> list[object]:
    """Newest-first history of a thread whose only turn is still its first.

    ``DynamicContextMiddleware`` swaps the first user message's id mid-run:
    the injected reminder takes ``{id}`` and the real user message becomes
    ``{id}__user``. So the pre-injection checkpoints hold the very same prompt
    under an id the replay-base lookup does not recognise (#4531).
    """
    system = SystemMessage(id="h1", content="<system-reminder>date</system-reminder>")
    swapped_human = HumanMessage(id="h1__user", content="question")
    raw_human = HumanMessage(id="h1", content="question")
    ai = AIMessage(id="ai-1", content="answer")
    return [
        _snapshot("ckpt-head", [system, swapped_human, ai], parent_id="ckpt-after-inject"),
        _snapshot("ckpt-after-inject", [system, swapped_human], next_tasks=("LoopDetectionMiddleware.before_agent",), parent_id="ckpt-mid"),
        _snapshot("ckpt-mid", [raw_human], next_tasks=("DynamicContextMiddleware.before_agent",), parent_id="ckpt-input"),
        _snapshot("ckpt-input", [], next_tasks=("__start__",), parent_id="ckpt-empty"),
        _snapshot("ckpt-empty", []),
    ]


def test_chronological_scan_skips_checkpoints_with_pending_tasks():
    history = _first_turn_history()

    base, found = find_checkpoint_before_message_chronologically(history, "h1__user")

    assert found is True
    assert base is not None
    assert base.config["configurable"]["checkpoint_id"] == "ckpt-empty"


def test_lineage_walk_skips_checkpoints_with_pending_tasks():
    history = _first_turn_history()
    accessor = _Accessor(history)

    base = asyncio.run(find_checkpoint_before_message(accessor, history[0], "h1__user", max_depth=10))

    assert base.config["configurable"]["checkpoint_id"] == "ckpt-empty"


def test_chronological_scan_prefers_the_previous_turn_boundary():
    """A later turn resolves to the previous run's settled tail, not its input checkpoint."""
    human1 = HumanMessage(id="h1__user", content="first")
    ai1 = AIMessage(id="ai-1", content="first answer")
    human2 = HumanMessage(id="h2", content="second")
    history = [
        _snapshot("ckpt-turn2-head", [human1, ai1, human2, AIMessage(id="ai-2", content="second answer")]),
        _snapshot("ckpt-turn2-mid", [human1, ai1, human2], next_tasks=("model",)),
        _snapshot("ckpt-turn2-input", [human1, ai1], next_tasks=("__start__",)),
        _snapshot("ckpt-turn1-tail", [human1, ai1]),
    ]

    base, found = find_checkpoint_before_message_chronologically(history, "h2")

    assert found is True
    assert base.config["configurable"]["checkpoint_id"] == "ckpt-turn1-tail"


def test_lineage_walk_reports_missing_parent_when_no_settled_ancestor_exists():
    """Fail closed rather than fork a mid-run checkpoint."""
    human = HumanMessage(id="h1__user", content="question")
    history = [
        _snapshot("ckpt-head", [human, AIMessage(id="ai-1", content="answer")], parent_id="ckpt-mid"),
        _snapshot("ckpt-mid", [HumanMessage(id="h1", content="question")], next_tasks=("DynamicContextMiddleware.before_agent",)),
    ]
    accessor = _Accessor(history)

    with pytest.raises(CheckpointParentMissingError):
        asyncio.run(find_checkpoint_before_message(accessor, history[0], "h1__user", max_depth=10))


def test_unknown_pending_tasks_do_not_block_selection():
    """Raw full-mode reads cannot derive tasks; absence of evidence stays permissive."""
    human = HumanMessage(id="h1", content="question")
    history = [
        SimpleNamespace(
            values={"messages": [human]},
            config={"configurable": {"thread_id": THREAD_ID, "checkpoint_ns": "", "checkpoint_id": "ckpt-head"}},
            metadata={},
        ),
        SimpleNamespace(
            values={"messages": []},
            config={"configurable": {"thread_id": THREAD_ID, "checkpoint_ns": "", "checkpoint_id": "ckpt-base"}},
            metadata={},
        ),
    ]

    base, found = find_checkpoint_before_message_chronologically(history, "h1")

    assert found is True
    assert base.config["configurable"]["checkpoint_id"] == "ckpt-base"


def test_memory_backed_duration_checkpoint_is_recognised():
    """The marker memory and SQLite savers round-trip unchanged."""
    snapshot = _snapshot(
        "ckpt-duration",
        [],
        metadata={"source": "update", "step": 3, "writes": {"runtime_run_duration": {"run_ids": ["run-1"], "message_ids": []}}},
    )

    assert is_duration_only_checkpoint(snapshot) is True


def test_postgres_duration_checkpoint_is_recognised_without_the_writes_marker():
    """Postgres serialisation pops ``writes``; stamps plus the verbatim shape identify the leaf."""
    parent = _snapshot("ckpt-real", [], channel_versions={"messages": 5})
    snapshot = _snapshot(
        "ckpt-duration",
        [],
        parent_id="ckpt-real",
        metadata=dict(_POSTGRES_DURATION_METADATA),
        channel_versions={"messages": 5},
    )

    assert is_duration_only_checkpoint(snapshot, parent=parent) is True


def test_stamp_fallback_refuses_stamps_without_a_parent():
    """Stamps alone are evidence, not proof — with no parent there is no verdict.

    A title or goal leaf at a window boundary carries the same stamps; the
    conservative answer keeps it addressable, which only ever costs one
    scanned state-equivalent copy.
    """
    snapshot = _snapshot("ckpt-duration", [], metadata=dict(_POSTGRES_DURATION_METADATA), channel_versions={"messages": 5})

    assert is_duration_only_checkpoint(snapshot) is False
    assert is_duration_only_checkpoint(snapshot, parent=None) is False


def test_goal_leaf_inheriting_stamps_is_not_duration_only():
    """``write_thread_goal`` copies the head's metadata and changes the goal channel.

    On Postgres its own ``writes.goal`` marker is popped too, so the inherited
    stamps are the only trace of the duration writer — but the bumped ``goal``
    version breaks the verbatim shape. Classifying it as duration-only made
    the branch scan walk past the leaf and copy channel values from before
    the goal write.
    """
    parent = _snapshot("ckpt-stamped-head", [], channel_versions={"messages": 5, "goal": 2})
    goal_leaf = _snapshot(
        "ckpt-goal",
        [],
        parent_id="ckpt-stamped-head",
        metadata=dict(_POSTGRES_INHERITED_STAMPS),
        channel_versions={"messages": 5, "goal": 3},
    )

    assert is_duration_only_checkpoint(goal_leaf, parent=parent) is False


def test_postgres_attribution_only_duration_checkpoint_is_recognised():
    """A leaf stamped for message attribution alone has an empty ``run_durations`` map."""
    parent = _snapshot("ckpt-real", [], channel_versions={"messages": 5})
    snapshot = _snapshot(
        "ckpt-duration",
        [],
        parent_id="ckpt-real",
        metadata={"source": "update", "step": 3, "run_durations": {}, "run_message_ids": {"ai-1": "run-1"}},
        channel_versions={"messages": 5},
    )

    assert is_duration_only_checkpoint(snapshot, parent=parent) is True


def test_client_update_state_is_not_a_duration_checkpoint():
    """A leaf from langgraph's ``update_state`` carries none of the writer's stamps.

    update_state persists metadata built from scratch on the pinned langgraph
    (``{"source": "update", "step", "parents", ...}`` — no ``writes`` key at
    all), so this shape reaches the stamp fallback tier and stays addressable
    because the index keys are absent.
    """
    snapshot = _snapshot("ckpt-update", [], metadata={"source": "update", "step": 3})

    assert is_duration_only_checkpoint(snapshot) is False


def test_graph_step_checkpoints_are_not_duration_checkpoints():
    for source in ("input", "loop", "step"):
        snapshot = _snapshot("ckpt-step", [], metadata={"source": source, "step": 1, "writes": {"messages": "..."}})
        assert is_duration_only_checkpoint(snapshot) is False
    assert is_duration_only_checkpoint(_snapshot("ckpt-plain", [])) is False
    assert is_duration_only_checkpoint(SimpleNamespace(values={}, config={}, metadata=None)) is False


def test_chronological_scan_skips_postgres_shaped_duration_checkpoints():
    """An interleaved import must not hand the replay base to a metadata-only leaf.

    The duration leaf belongs to an older incarnation whose timestamps interleave
    with the live branch; without the Postgres-shape classification it would be
    selected as the replay base for a message that only the newer real state and
    the head contain.
    """
    human = HumanMessage(id="h1", content="question")
    answer = AIMessage(id="ai-1", content="answer")
    history = [
        _snapshot("ckpt-x-head", [human, answer]),
        _snapshot("ckpt-a-early", [], channel_versions={"messages": 3}),
        _snapshot("ckpt-a-duration", [human], parent_id="ckpt-a-early", metadata=dict(_POSTGRES_DURATION_METADATA), channel_versions={"messages": 3}),
        _snapshot("ckpt-a-input", [], channel_versions={"messages": 2}),
    ]

    base, found = find_checkpoint_before_message_chronologically(history, "h1")

    assert found is True
    assert base.config["configurable"]["checkpoint_id"] == "ckpt-a-early"


def test_chronological_scan_keeps_goal_leaf_addressable():
    """The imported-history fallback must not walk past a goal write either.

    The goal leaf inherits the stamps but bumped the goal version, so the
    verbatim shape fails and it stays a replay-base candidate.
    """
    human = HumanMessage(id="h1", content="question")
    ai = AIMessage(id="ai-1", content="answer")
    human2 = HumanMessage(id="h2", content="follow-up")
    ai2 = AIMessage(id="ai-2", content="answer-2")
    history = [
        _snapshot("ckpt-turn2-head", [human, ai, human2, ai2]),
        _snapshot("ckpt-goal", [human, ai], parent_id="ckpt-turn1-tail", metadata=dict(_POSTGRES_INHERITED_STAMPS), channel_versions={"messages": 5, "goal": 3}),
        _snapshot("ckpt-turn1-tail", [human, ai], channel_versions={"messages": 5}),
    ]

    base, found = find_checkpoint_before_message_chronologically(history, "h2")

    assert found is True
    assert base.config["configurable"]["checkpoint_id"] == "ckpt-goal"


def test_lineage_walk_crosses_chained_postgres_duration_checkpoints():
    """The lineage walk skips duration-only parents even when ``writes`` never comes back."""
    swapped_human = HumanMessage(id="h1__user", content="question")
    raw_human = HumanMessage(id="h1", content="question")
    ai = AIMessage(id="ai-1", content="answer")
    history = [
        _snapshot("ckpt-head", [swapped_human, ai], parent_id="ckpt-leaf-2", channel_versions={"messages": 7}),
        _snapshot("ckpt-leaf-2", [swapped_human, ai], parent_id="ckpt-leaf-1", metadata=dict(_POSTGRES_DURATION_METADATA), channel_versions={"messages": 5}),
        _snapshot("ckpt-leaf-1", [swapped_human, ai], parent_id="ckpt-turn1-tail", metadata=dict(_POSTGRES_DURATION_METADATA), channel_versions={"messages": 5}),
        _snapshot("ckpt-turn1-tail", [raw_human], channel_versions={"messages": 5}),
    ]
    accessor = _Accessor(history)

    base = asyncio.run(find_checkpoint_before_message(accessor, history[0], "h1__user", max_depth=10))

    assert base.config["configurable"]["checkpoint_id"] == "ckpt-turn1-tail"


def test_lineage_walk_keeps_goal_leaf_addressable():
    """A goal write stacked on a stamped head must remain a replay-base candidate.

    The goal leaf inherits the duration stamps on Postgres but bumped the goal
    version; treating it as duration-only would walk past it and hand back a
    base whose channel values predate the goal write.
    """
    human = HumanMessage(id="h1", content="question")
    ai = AIMessage(id="ai-1", content="answer")
    human2 = HumanMessage(id="h2", content="follow-up")
    history = [
        _snapshot("ckpt-turn2-head", [human, ai, human2], parent_id="ckpt-goal", channel_versions={"messages": 6}),
        _snapshot("ckpt-goal", [human, ai], parent_id="ckpt-turn1-tail", metadata=dict(_POSTGRES_INHERITED_STAMPS), channel_versions={"messages": 5, "goal": 3}),
        _snapshot("ckpt-turn1-tail", [human, ai], channel_versions={"messages": 5}),
    ]
    accessor = _Accessor(history)

    base = asyncio.run(find_checkpoint_before_message(accessor, history[0], "h2", max_depth=10))

    assert base.config["configurable"]["checkpoint_id"] == "ckpt-goal"


def test_title_leaf_inheriting_duration_stamps_is_not_duration_only():
    """``_ensure_interrupted_title`` copies the head's metadata, stamps included.

    On memory/SQLite the leaf keeps its own ``writes.runtime_interrupt_title``
    marker, which must win over the inherited ``run_durations`` — otherwise a
    title write stacked on a stamped head would be classified as a duration
    checkpoint even where the marker is authoritative.
    """
    snapshot = _snapshot(
        "ckpt-title",
        [],
        metadata={
            "source": "update",
            "step": 4,
            "writes": {"runtime_interrupt_title": {"title": "hi"}},
            "run_durations": {"run-1": 12},
            "run_message_ids": {"ai-1": "run-1"},
        },
    )

    assert is_duration_only_checkpoint(snapshot) is False


def test_stamp_fallback_disabled_requires_the_writes_marker():
    """Destructive callers must see a Postgres-shaped leaf as *not* duration-only.

    Without the ``writes`` marker the stamps are only evidence, not proof —
    ``checkpoint_retention`` refuses them here and widens the class solely via
    the parent-shape check in ``_mark_duration_leaves_without_the_marker``.
    """
    parent = _snapshot("ckpt-real", [], channel_versions={"messages": 5})
    postgres_shaped = _snapshot("ckpt-duration", [], metadata=dict(_POSTGRES_DURATION_METADATA), channel_versions={"messages": 5})
    marker_backed = _snapshot(
        "ckpt-duration",
        [],
        metadata={"source": "update", "step": 3, "writes": {"runtime_run_duration": {"run_ids": [], "message_ids": []}}},
    )

    assert is_duration_only_checkpoint(postgres_shaped, parent=parent, stamp_fallback=False) is False
    assert is_duration_only_checkpoint(marker_backed, parent=parent, stamp_fallback=False) is True
