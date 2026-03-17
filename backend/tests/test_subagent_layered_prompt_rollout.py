"""Regression tests for L0-L5 layered prompt rollout on non-writing subagents."""

import re

from src.subagents.builtins import BUILTIN_SUBAGENTS

TARGET_SUBAGENTS = (
    "general-purpose",
    "literature-reviewer",
    "statistical-analyst",
    "code-reviewer",
    "bash",
)

LAYER_HEADERS = (
    "[L0 Constitution]",
    "[L1 Runtime Protocol]",
    "[L2 Stage Recipe]",
    "[L3 Role Contract]",
    "[L4 Venue Style Adapter]",
    "[L5 Expert Reasoning]",
)

BUILTIN_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


def _auto_detect_builtin_names_by_rule() -> list[str]:
    return sorted(name for name in BUILTIN_SUBAGENTS if BUILTIN_NAME_PATTERN.fullmatch(name))


def test_non_writing_subagents_use_l0_l5_layered_headers():
    for subagent_name in TARGET_SUBAGENTS:
        prompt = BUILTIN_SUBAGENTS[subagent_name].system_prompt
        assert f"You are the '{subagent_name}' specialized academic subagent." in prompt
        for header in LAYER_HEADERS:
            assert header in prompt, f"{subagent_name} missing layered header: {header}"


def test_non_writing_subagents_include_l5_reasoning_directives():
    for subagent_name in TARGET_SUBAGENTS:
        prompt = BUILTIN_SUBAGENTS[subagent_name].system_prompt
        assert "Counterfactual check" in prompt
        assert "Causal mechanism breakdown" in prompt
        assert "Confounder elimination" in prompt


def test_non_writing_subagents_have_explicit_role_contracts():
    for subagent_name in TARGET_SUBAGENTS:
        prompt = BUILTIN_SUBAGENTS[subagent_name].system_prompt
        assert "Role mission:" in prompt
        assert "I/O contract:" in prompt
        assert "Workflow:" in prompt
        assert "Role contract unavailable" not in prompt


def test_builtin_name_rule_guard_covers_all_registered_builtins():
    auto_detected = _auto_detect_builtin_names_by_rule()
    assert auto_detected, "No builtins detected by naming rule; guard is misconfigured."
    assert set(auto_detected) == set(BUILTIN_SUBAGENTS), (
        "Detected builtins by naming rule do not match registry. "
        "If a new builtin name is introduced, keep kebab-case naming or update the rule intentionally."
    )


def test_all_builtin_subagents_enforce_layered_l0_l5_contract():
    for subagent_name in _auto_detect_builtin_names_by_rule():
        config = BUILTIN_SUBAGENTS[subagent_name]
        prompt = config.system_prompt
        assert f"You are the '{subagent_name}' specialized academic subagent." in prompt
        for header in LAYER_HEADERS:
            assert header in prompt, f"{subagent_name} missing layered header: {header}"
        assert "Counterfactual check" in prompt
        assert "Causal mechanism breakdown" in prompt
        assert "Confounder elimination" in prompt
        assert "Role mission:" in prompt
        assert "I/O contract:" in prompt
        assert "Workflow:" in prompt
        assert "Role contract unavailable" not in prompt
