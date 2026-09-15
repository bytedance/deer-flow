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
)

THREAD_ID = "thread-1"


def _snapshot(checkpoint_id: str, messages: list[object], *, next_tasks: tuple[str, ...] = (), parent_id: str | None = None):
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
        metadata={},
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
