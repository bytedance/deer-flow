from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "thread_id",
    [
        "a",
        "A1_b-2",
        "x" * 64,
    ],
)
def test_validate_thread_id_accepts_canonical_ids(thread_id: str) -> None:
    from deerflow.utils.thread_id import validate_thread_id

    assert validate_thread_id(thread_id) == thread_id


@pytest.mark.parametrize(
    "thread_id",
    [
        "",
        "x" * 65,
        "thread.with.dot",
        "../escape",
        "has space",
        "line\nbreak",
        "线程",
    ],
)
def test_validate_thread_id_rejects_noncanonical_ids(thread_id: str) -> None:
    from deerflow.utils.thread_id import validate_thread_id

    with pytest.raises(ValueError, match="Invalid thread_id"):
        validate_thread_id(thread_id)


@pytest.mark.parametrize("thread_id", [1, {}, []])
def test_validate_thread_id_rejects_non_strings(thread_id: object) -> None:
    from deerflow.utils.thread_id import validate_thread_id

    with pytest.raises(ValueError, match="Invalid thread_id"):
        validate_thread_id(thread_id)  # type: ignore[arg-type]
