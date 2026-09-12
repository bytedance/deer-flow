"""Checkpointed working notes. Values are model reports, never authority."""

import re
from collections.abc import Sequence

from langgraph.channels import BinaryOperatorAggregate

MAX_NOTES = 8
MAX_NOTE_CHARS = 750
MAX_NOTE_SOURCES = 4
NOTE_KEY_PATTERN = re.compile(r"[a-zA-Z0-9_-]{1,40}")
SOURCE_ID_PATTERN = re.compile(r"r[a-f0-9]{32}")


def normalize_task_notes(value: object) -> dict:
    """Drop malformed entries and canonicalize untrusted notes without endorsing them.

    Used before external checkpoint writes and again when reading stored state:
    Overwrite and direct integrations can bypass the reducer. Source IDs are
    syntax-checked here; only the task_note tool checks their availability.
    """
    if not isinstance(value, dict):
        return {}
    notes = {}
    for key, note in value.items():
        if not isinstance(key, str) or not NOTE_KEY_PATTERN.fullmatch(key) or not isinstance(note, dict):
            continue
        content = note.get("content")
        sources = note.get("source_ids", [])
        if not isinstance(content, str) or not content or len(content) > MAX_NOTE_CHARS:
            continue
        if not isinstance(sources, list) or len(sources) > MAX_NOTE_SOURCES or any(not isinstance(source, str) or not SOURCE_ID_PATTERN.fullmatch(source) for source in sources):
            continue
        notes[key] = {"content": content, "source_ids": list(sources), "authority": "model_report"}
        if len(notes) > MAX_NOTES:
            notes.pop(next(iter(notes)))
    return notes


def merge_task_notes(left: dict | None, right: dict | None) -> dict:
    merged = normalize_task_notes(left)
    for key, value in (right if isinstance(right, dict) else {}).items():
        if value is None:
            merged.pop(key, None)
        else:
            merged.update(normalize_task_notes({key: value}))
    # Tools reject new keys at capacity; also bound externally supplied state.
    return dict(list(merged.items())[-MAX_NOTES:])


class TaskNotesChannel(BinaryOperatorAggregate[dict | None]):
    """Validate every checkpoint write, including first writes and Overwrite.

    Keep the optional channel uninitialized until it receives a write so the
    disabled feature does not add a notebook to ordinary state/SSE snapshots.
    """

    def update(self, values: Sequence[dict | None]) -> bool:
        changed = super().update(values)
        if changed:
            self.value = normalize_task_notes(self.value)
        return changed
