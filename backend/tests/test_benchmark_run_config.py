"""Tests for scripts/benchmark_run_config.py."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "benchmark_run_config.py"


spec = importlib.util.spec_from_file_location("deerflow_benchmark_run_config", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
benchmark_run_config = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = benchmark_run_config
spec.loader.exec_module(benchmark_run_config)


@pytest.mark.parametrize(
    ("profile", "recursion_limit"),
    [
        ("gaia", 150),
        ("swebench-lite", 250),
        ("long-horizon", 250),
    ],
)
def test_profile_defaults(profile: str, recursion_limit: int) -> None:
    assert benchmark_run_config.build_config(profile) == {"recursion_limit": recursion_limit}


def test_configurable_overrides_are_included_only_when_set() -> None:
    config = benchmark_run_config.build_config(
        "swebench-lite",
        recursion_limit=300,
        model_name="k2.6",
        thinking_enabled=True,
        is_plan_mode=True,
        subagent_enabled=True,
    )

    assert config == {
        "recursion_limit": 300,
        "configurable": {
            "model_name": "k2.6",
            "thinking_enabled": True,
            "is_plan_mode": True,
            "subagent_enabled": True,
        },
    }


def test_cli_emits_json_config(capsys) -> None:
    result = benchmark_run_config.main(
        [
            "--profile",
            "swebench-lite",
            "--model-name",
            "k2.6",
            "--thinking-enabled",
            "--indent",
            "0",
        ]
    )

    assert result == 0
    assert json.loads(capsys.readouterr().out) == {
        "recursion_limit": 250,
        "configurable": {
            "model_name": "k2.6",
            "thinking_enabled": True,
        },
    }


@pytest.mark.parametrize("value", ["0", "-1", "not-an-int"])
def test_recursion_limit_must_be_positive(value: str) -> None:
    with pytest.raises(SystemExit):
        benchmark_run_config.parse_args(["--profile", "gaia", "--recursion-limit", value])


def test_cli_default_indent_is_pretty_printed(capsys) -> None:
    """Default --indent (2) must produce pretty-printed JSON across multiple lines."""
    assert benchmark_run_config.main(["--profile", "gaia"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("{\n")
    assert '\n  "recursion_limit": 150' in out
    assert json.loads(out) == {"recursion_limit": 150}
