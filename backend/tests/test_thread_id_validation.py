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


@pytest.mark.parametrize("method_name", ["upload_files", "list_uploads", "delete_upload", "get_artifact"])
def test_client_mutating_and_read_entry_points_validate_thread_id(method_name: str) -> None:
    """RFC #4588: the embedded client validates on all mutating entry points.

    Validation is the first statement of each method, so a bare ``__new__``
    instance is enough — no config, sandbox, or event loop is touched.
    """
    from deerflow.client import DeerFlowClient

    client = DeerFlowClient.__new__(DeerFlowClient)
    method = getattr(client, method_name)
    args = {"upload_files": (["x"],), "list_uploads": (), "delete_upload": ("f.txt",), "get_artifact": ("mnt/user-data/outputs/f.txt",)}[method_name]

    with pytest.raises(ValueError, match="Invalid thread_id"):
        method("bad.thread.id", *args)


def test_support_bundle_thread_id_pattern_matches_canonical() -> None:
    """scripts/support_bundle.py keeps its own copy of the pattern (it must
    run with a broken venv) — pin it byte-identical to the canonical one."""
    import importlib.util
    from pathlib import Path

    from deerflow.utils.thread_id import THREAD_ID_PATTERN

    script = Path(__file__).resolve().parents[2] / "scripts" / "support_bundle.py"
    spec = importlib.util.spec_from_file_location("support_bundle", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.SAFE_THREAD_ID_RE.pattern == THREAD_ID_PATTERN


def test_tui_resume_literal_ref_validated() -> None:
    """The TUI /resume fallback adopts a literal ref as thread id only when
    it satisfies the canonical contract."""
    from deerflow.tui.session import Session

    session = Session.__new__(Session)
    session.client = type("StubClient", (), {"list_threads": lambda self, limit: {"thread_list": []}})()

    assert session.resolve_ref("valid-id_1") == "valid-id_1"
    with pytest.raises(ValueError, match="not a valid thread id"):
        session.resolve_ref("bad.thread.id")
