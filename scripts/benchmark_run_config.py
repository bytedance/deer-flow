#!/usr/bin/env python3
"""Emit reproducible LangGraph run configs for DeerFlow benchmark runs.

The profiles here intentionally cover only runtime knobs that DeerFlow owns.
They do not install or run GAIA/SWE-bench harnesses; instead they produce the
``config`` object that those harnesses or direct ``/api/langgraph`` calls should
send for long-horizon agent evaluations.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BenchmarkProfile:
    """Benchmark-specific run configuration defaults."""

    recursion_limit: int
    description: str


PROFILES: dict[str, BenchmarkProfile] = {
    "gaia": BenchmarkProfile(
        recursion_limit=150,
        description="GAIA-style multi-step tool-use tasks; issue #2820 suggests 100-150.",
    ),
    "swebench-lite": BenchmarkProfile(
        recursion_limit=250,
        description="SWE-bench Lite repository-repair tasks; issue #2820 suggests 250+.",
    ),
    "long-horizon": BenchmarkProfile(
        recursion_limit=250,
        description="Generic long-horizon DeerFlow evaluation profile.",
    ),
}


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def _nonnegative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return parsed


def build_config(
    profile_name: str,
    *,
    recursion_limit: int | None = None,
    model_name: str | None = None,
    thinking_enabled: bool | None = None,
    is_plan_mode: bool | None = None,
    subagent_enabled: bool | None = None,
) -> dict[str, Any]:
    """Build the LangGraph ``config`` object for a benchmark profile."""
    profile = PROFILES[profile_name]
    config: dict[str, Any] = {
        "recursion_limit": recursion_limit if recursion_limit is not None else profile.recursion_limit,
    }
    configurable: dict[str, Any] = {}
    if model_name is not None:
        configurable["model_name"] = model_name
    if thinking_enabled is not None:
        configurable["thinking_enabled"] = thinking_enabled
    if is_plan_mode is not None:
        configurable["is_plan_mode"] = is_plan_mode
    if subagent_enabled is not None:
        configurable["subagent_enabled"] = subagent_enabled
    if configurable:
        config["configurable"] = configurable
    return config


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print a DeerFlow benchmark run config as JSON.",
    )
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        required=True,
        help="Benchmark profile to emit.",
    )
    parser.add_argument(
        "--recursion-limit",
        type=_positive_int,
        help="Override the profile recursion limit.",
    )
    parser.add_argument("--model-name", help="Optional model_name configurable override.")
    parser.add_argument("--thinking-enabled", action="store_true", help="Set configurable.thinking_enabled=true.")
    parser.add_argument("--plan-mode", action="store_true", help="Set configurable.is_plan_mode=true.")
    parser.add_argument("--subagent-enabled", action="store_true", help="Set configurable.subagent_enabled=true.")
    parser.add_argument(
        "--indent",
        type=_nonnegative_int,
        default=2,
        help="JSON indentation level. Use 0 for compact output.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    config = build_config(
        args.profile,
        recursion_limit=args.recursion_limit,
        model_name=args.model_name,
        thinking_enabled=True if args.thinking_enabled else None,
        is_plan_mode=True if args.plan_mode else None,
        subagent_enabled=True if args.subagent_enabled else None,
    )
    indent = None if args.indent == 0 else args.indent
    sys.stdout.write(json.dumps(config, indent=indent, sort_keys=True))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
