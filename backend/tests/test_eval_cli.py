import json
import subprocess
import sys
from pathlib import Path


def _write_trace_file(path: Path, traces: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for trace in traces:
            fh.write(json.dumps(trace, ensure_ascii=False) + "\n")


def _make_cli_trace(**overrides) -> dict:
    defaults = {
        "trace_id": "t1",
        "timestamp": "2026-04-13T00:00:00Z",
        "agent_name": None,
        "max_tokens": 2000,
        "tokens_used": 500,
        "tokens_remaining": 1500,
        "total_candidates": 3,
        "selected_count": 2,
        "dropped_count": 1,
        "candidates": [
            {
                "fact_id": "f1",
                "content_preview": "x" * 40,
                "category": "knowledge",
                "confidence": 0.9,
                "layer": None,
                "created_at": None,
            },
            {
                "fact_id": "f2",
                "content_preview": "y" * 40,
                "category": "correction",
                "confidence": 0.8,
                "layer": None,
                "created_at": None,
            },
            {
                "fact_id": "f3",
                "content_preview": "z" * 40,
                "category": "preference",
                "confidence": 0.7,
                "layer": None,
                "created_at": None,
            },
        ],
        "selections": [],
        "user_context_included": False,
        "history_sections_included": [],
        "context_tokens": 0,
    }
    defaults.update(overrides)
    return defaults


def test_cli_help_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "deerflow.agents.memory.eval", "replay", "--help"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "trace-path" in result.stdout


def test_cli_missing_trace_path_exits_nonzero() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "deerflow.agents.memory.eval", "replay"],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0


def test_cli_nonexistent_file_exits_one(tmp_path: Path) -> None:
    nonexistent = str(tmp_path / "does_not_exist.jsonl")
    result = subprocess.run(
        [sys.executable, "-m", "deerflow.agents.memory.eval", "replay", "--trace-path", nonexistent],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "error" in result.stderr.lower()


def test_cli_json_output_valid(tmp_path: Path) -> None:
    trace_file = tmp_path / "trace.jsonl"
    _write_trace_file(trace_file, [_make_cli_trace()])

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "deerflow.agents.memory.eval",
            "replay",
            "--trace-path",
            str(trace_file),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    assert "comparisons" in parsed
