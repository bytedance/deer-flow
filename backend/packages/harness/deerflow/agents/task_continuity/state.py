"""Checkpointed working notes. Values are model reports, never authority."""


def merge_task_notes(left: dict | None, right: dict | None) -> dict:
    merged = dict(left or {})
    for key, value in (right or {}).items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    # Tools reject new keys at capacity; also bound externally supplied state.
    return dict(list(merged.items())[-8:])
