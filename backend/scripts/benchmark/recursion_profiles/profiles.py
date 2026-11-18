"""Emit reproducible LangGraph run configs for DeerFlow benchmark runs.

The profiles cover only runtime knobs that DeerFlow owns. They do not install
or run GAIA/SWE-bench harnesses; they produce the ``config`` object that those
harnesses or direct ``/api/langgraph`` calls send for long-horizon evaluations.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any

from deerflow.config.app_config import AppConfig

# The Gateway clamps a request ``recursion_limit`` above ``max_recursion_limit``
# without telling the client; read the shipped default from the production model.
DEFAULT_MAX_RECURSION_LIMIT: int = AppConfig.model_fields["max_recursion_limit"].default


@dataclass(frozen=True)
class BenchmarkProfile:
    """Benchmark-specific run configuration defaults."""

    recursion_limit: int


PROFILES: dict[str, BenchmarkProfile] = {
    "gaia": BenchmarkProfile(recursion_limit=150),
    "swebench-lite": BenchmarkProfile(recursion_limit=250),
    "long-horizon": BenchmarkProfile(recursion_limit=250),
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


def check_server_ceiling(recursion_limit: int, max_recursion_limit: int) -> None:
    """Reject a recursion limit that the Gateway would clamp without telling the client.

    The Gateway clamps any request value above ``max_recursion_limit`` without
    telling the client, so a recorded config of e.g. 1500 would actually run
    with 1000 and silently break reproducibility.

    Raises ``ValueError`` when ``recursion_limit`` exceeds ``max_recursion_limit``.
    """
    if recursion_limit > max_recursion_limit:
        raise ValueError(
            f"recursion_limit {recursion_limit} exceeds max_recursion_limit {max_recursion_limit}; "
            f"the Gateway would clamp it to {max_recursion_limit}, so the recorded config would not match the run. "
            "Choose a smaller profile or --recursion-limit, or pass the target Gateway's actual --max-recursion-limit."
        )


def build_config(
    profile_name: str,
    *,
    recursion_limit: int | None = None,
    max_recursion_limit: int = DEFAULT_MAX_RECURSION_LIMIT,
    model_name: str | None = None,
    thinking_enabled: bool | None = None,
    is_plan_mode: bool | None = None,
    subagent_enabled: bool | None = None,
) -> dict[str, Any]:
    """Build the LangGraph ``config`` object for a benchmark profile."""
    profile = PROFILES[profile_name]
    limit = recursion_limit if recursion_limit is not None else profile.recursion_limit
    # The Gateway replaces a non-positive or non-integer value with its default,
    # so reject it here for the same reason as the ceiling check.
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError(f"recursion_limit must be a positive integer, got {limit!r}; the Gateway would replace it with its default.")
    # Accept only a positive int ceiling, so a bad value fails with a clear error
    # instead of a TypeError or a meaningless comparison (e.g. NaN). Like AppConfig,
    # reject booleans; unlike AppConfig, also reject numeric strings such as "1000".
    if isinstance(max_recursion_limit, bool) or not isinstance(max_recursion_limit, int) or max_recursion_limit < 1:
        raise ValueError(f"max_recursion_limit must be a positive integer, got {max_recursion_limit!r}.")
    check_server_ceiling(limit, max_recursion_limit)
    config: dict[str, Any] = {"recursion_limit": limit}
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Print a DeerFlow benchmark run config as JSON.")
    parser.add_argument("--profile", choices=sorted(PROFILES), required=True, help="Benchmark profile to emit.")
    parser.add_argument("--recursion-limit", type=_positive_int, help="Override the profile recursion limit.")
    parser.add_argument(
        "--max-recursion-limit",
        type=_positive_int,
        default=DEFAULT_MAX_RECURSION_LIMIT,
        help=f"The target Gateway's max_recursion_limit (default {DEFAULT_MAX_RECURSION_LIMIT}).",
    )
    parser.add_argument("--model-name", help="Optional model_name configurable override.")
    parser.add_argument("--thinking-enabled", action="store_true", help="Set configurable.thinking_enabled=true.")
    parser.add_argument("--plan-mode", action="store_true", help="Set configurable.is_plan_mode=true.")
    parser.add_argument("--subagent-enabled", action="store_true", help="Set configurable.subagent_enabled=true.")
    parser.add_argument("--indent", type=_nonnegative_int, default=2, help="JSON indentation level. Use 0 for compact output.")
    return parser


def parse_args(argv: list[str]) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        config = build_config(
            args.profile,
            recursion_limit=args.recursion_limit,
            max_recursion_limit=args.max_recursion_limit,
            model_name=args.model_name,
            thinking_enabled=True if args.thinking_enabled else None,
            is_plan_mode=True if args.plan_mode else None,
            subagent_enabled=True if args.subagent_enabled else None,
        )
    except ValueError as exc:
        parser.error(str(exc))
    indent = None if args.indent == 0 else args.indent
    sys.stdout.write(json.dumps(config, indent=indent, sort_keys=True))
    sys.stdout.write("\n")
    return 0
