"""Offline checks for the benchmark recursion-profile config generator."""

from __future__ import annotations

import json

import pytest

from app.gateway.services import _clamp_recursion_limit
from deerflow.config.app_config import AppConfig
from scripts.benchmark.recursion_profiles.profiles import DEFAULT_MAX_RECURSION_LIMIT, PROFILES, build_config, main, parse_args

pytestmark = pytest.mark.benchmark


@pytest.mark.parametrize(("profile", "recursion_limit"), [("gaia", 150), ("swebench-lite", 250), ("long-horizon", 250)])
def test_profile_defaults(profile: str, recursion_limit: int) -> None:
    assert build_config(profile) == {"recursion_limit": recursion_limit}


def test_ceiling_default_tracks_production_config() -> None:
    assert DEFAULT_MAX_RECURSION_LIMIT == AppConfig.model_fields["max_recursion_limit"].default


@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_every_profile_survives_the_gateway_clamp_unchanged(profile: str) -> None:
    limit = build_config(profile)["recursion_limit"]
    default = AppConfig.model_fields["recursion_limit"].default
    assert _clamp_recursion_limit(limit, DEFAULT_MAX_RECURSION_LIMIT, default) == limit


def test_configurable_overrides_are_included_only_when_set() -> None:
    config = build_config(
        "swebench-lite",
        recursion_limit=300,
        model_name="k2.6",
        thinking_enabled=True,
        is_plan_mode=True,
        subagent_enabled=True,
    )

    assert config == {
        "recursion_limit": 300,
        "configurable": {"model_name": "k2.6", "thinking_enabled": True, "is_plan_mode": True, "subagent_enabled": True},
    }


def test_cli_emits_json_config(capsys) -> None:
    assert main(["--profile", "swebench-lite", "--model-name", "k2.6", "--thinking-enabled", "--indent", "0"]) == 0
    assert json.loads(capsys.readouterr().out) == {"recursion_limit": 250, "configurable": {"model_name": "k2.6", "thinking_enabled": True}}


def test_cli_default_indent_is_pretty_printed(capsys) -> None:
    assert main(["--profile", "gaia"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("{\n")
    assert json.loads(out) == {"recursion_limit": 150}


@pytest.mark.parametrize("flag", ["--recursion-limit", "--max-recursion-limit"])
@pytest.mark.parametrize("value", ["0", "-1", "not-an-int"])
def test_limits_must_be_positive_integers(flag: str, value: str) -> None:
    with pytest.raises(SystemExit):
        parse_args(["--profile", "gaia", flag, value])


@pytest.mark.parametrize("value", [0, -5, True, "250"])
def test_build_config_rejects_values_the_gateway_would_replace(value: object) -> None:
    with pytest.raises(ValueError, match="must be a positive integer"):
        build_config("gaia", recursion_limit=value)  # type: ignore[arg-type]


@pytest.mark.parametrize("ceiling", [0, -1, True, float("nan"), "1000"])
def test_build_config_rejects_a_ceiling_that_is_not_a_positive_int(ceiling: object) -> None:
    with pytest.raises(ValueError, match="max_recursion_limit must be a positive integer"):
        build_config("gaia", recursion_limit=5000, max_recursion_limit=ceiling)  # type: ignore[arg-type]


def test_override_above_server_ceiling_is_rejected() -> None:
    with pytest.raises(ValueError, match="exceeds max_recursion_limit"):
        build_config("gaia", recursion_limit=DEFAULT_MAX_RECURSION_LIMIT + 1)


def test_override_equal_to_server_ceiling_is_allowed() -> None:
    assert build_config("gaia", recursion_limit=DEFAULT_MAX_RECURSION_LIMIT) == {"recursion_limit": DEFAULT_MAX_RECURSION_LIMIT}


def test_custom_server_ceiling_allows_higher_override() -> None:
    assert build_config("gaia", recursion_limit=1500, max_recursion_limit=2000) == {"recursion_limit": 1500}


def test_cli_forwards_custom_server_ceiling(capsys) -> None:
    assert main(["--profile", "gaia", "--recursion-limit", "1500", "--max-recursion-limit", "2000", "--indent", "0"]) == 0
    assert json.loads(capsys.readouterr().out) == {"recursion_limit": 1500}


def test_profile_default_above_custom_server_ceiling_is_rejected() -> None:
    with pytest.raises(ValueError, match="exceeds max_recursion_limit"):
        build_config("gaia", max_recursion_limit=100)


def test_cli_rejects_override_above_server_ceiling(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--profile", "gaia", "--recursion-limit", "1500"])
    assert excinfo.value.code == 2
    assert "exceeds max_recursion_limit" in capsys.readouterr().err
