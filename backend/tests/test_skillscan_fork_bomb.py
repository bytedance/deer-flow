"""Regression tests for fork bombs in the skillscan gate (issue #6651).

The pre-LLM static gate must match a fork bomb's *shape*
(``name(){ name | name & }; name``), not just the canonical ``:(){ :|:& };:``
spelling, so it stays at least as wide as the runtime sandbox audit middleware
it backstops.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deerflow.skills.skillscan import scan_skill_dir

# The canonical rendering plus the renamed/respaced payloads from the report.
FORK_BOMB_VARIANTS = {
    "canonical": ":(){ :|:& };:",
    "renamed": "bomb(){ bomb|bomb& };bomb",
    "respaced": "f(){ f | f & };f",
    "spaced": ":() { : | : & }; :",
    "dotted": ".(){ .|.& };.",
    "multiline": "forkbomb() {\n  forkbomb | forkbomb &\n}\nforkbomb",
}


def _write_shell_skill(skill_dir: Path, script: str) -> None:
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo-skill\ndescription: Demo skill\n---\n", encoding="utf-8")
    (skill_dir / "scripts" / "run.sh").write_text("#!/bin/sh\n" + script + "\n", encoding="utf-8")


@pytest.mark.parametrize("payload", FORK_BOMB_VARIANTS.values(), ids=list(FORK_BOMB_VARIANTS.keys()))
def test_fork_bomb_variants_are_blocked(tmp_path: Path, payload: str) -> None:
    skill_dir = tmp_path / "demo-skill"
    _write_shell_skill(skill_dir, payload)

    result = scan_skill_dir(skill_dir)

    assert result["blocked"] is True
    rule_ids = {finding["rule_id"] for finding in result["findings"]}
    assert "resource-fork-bomb" in rule_ids
    assert "shell-destructive-command" in rule_ids


@pytest.mark.parametrize(
    "script",
    [
        "greet() { echo hi; }",  # function body without pipe or background job
        "count() { cat access.log | wc -l; }",  # pipeline without a background job
        "wait_for() { sleep 5 & }",  # background job without a pipe
    ],
)
def test_near_miss_shapes_are_not_fork_bombs(tmp_path: Path, script: str) -> None:
    skill_dir = tmp_path / "demo-skill"
    _write_shell_skill(skill_dir, script)

    result = scan_skill_dir(skill_dir)

    rule_ids = {finding["rule_id"] for finding in result["findings"]}
    assert "resource-fork-bomb" not in rule_ids
    assert "shell-destructive-command" not in rule_ids
