"""Facts stay scoped to saved identities, including repeats and ID collisions."""

import json
from pathlib import Path

from deerflow_extension_trajectory.analysis import analyze_rows, process_evidence
from deerflow_extension_trajectory.checkpoints import fingerprint


def test_shared_browser_and_export_cases():
    for case in json.loads(Path(__file__).with_name("analysis_cases.json").read_text()):
        rows = analyze_rows(case["rows"], thread_id="thread")
        assert [row["row_id"] for row in rows] == case["order"]
        by_id = {row["row_id"]: row for row in rows}
        for entry in case.get("calls", []):
            expected = entry.copy()
            row, index = expected.pop("row"), expected.pop("index", 0)
            fact = by_id[row]["tool_calls"][index]["analysis"]
            assert {key: fact[key] for key in expected} == expected
        for entry in case.get("results", []):
            expected = entry.copy()
            fact = by_id[expected.pop("row")]["analysis"]
            assert {key: fact[key] for key in expected} == expected
        for row in rows:
            assert row["analysis"]["evidence"]["row_id"] == row["row_id"]
            assert row["analysis"]["evidence"]["thread_id"] == "thread"
            assert row["analysis"]["order_basis"] == "checkpoint_parent_chain"


def test_args_identity_uses_complete_canonical_arguments():
    assert fingerprint({"b": 2, "a": 1}) == fingerprint({"a": 1, "b": 2})
    assert fingerprint({"command": "x" * 5000 + "a"}) != fingerprint(
        {"command": "x" * 5000 + "b"}
    )


def test_codes_require_typed_process_evidence_never_success_or_output_text():
    assert process_evidence("Exit Code: 0") == []
    assert (
        process_evidence([{"source": "local", "status": "completed", "exit_code": 0}])[
            0
        ]["exit_code"]
        == 0
    )
    for status, code in [
        ("timeout", 124),
        ("unknown", 0),
        ("completed", True),
        ("completed", "0"),
    ]:
        assert (
            process_evidence(
                [{"source": "local", "status": status, "exit_code": code}]
            )[0]["exit_code"]
            is None
        )


def test_literal_operation_targets_and_shell_quotes():
    from deerflow_extension_trajectory.findings import operation_targets

    path = "/mnt/user-data/workspace/a file.txt"
    assert operation_targets("read_file", {"path": path}) == [path]
    assert operation_targets(
        "bash", {"command": f"cat '{path}' 2>&1; echo EXIT_CODE=$?"}
    ) == [path]
    assert operation_targets(
        "glob", {"path": "/mnt/user-data/workspace", "pattern": "a file.txt"}
    ) == [path]
    for args in [
        {"path": "relative.txt"},
        {"path": "/mnt/user-data/../secret"},
        {"path": "/tmp/*"},
    ]:
        assert operation_targets("read_file", args) == []
    assert operation_targets("bash", {"command": "cat '/bad quote"}) == []
