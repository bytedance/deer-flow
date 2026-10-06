"""Regression: `secret-cloud-token` must cover every family the canonical
API-key detector already recognises.

`pii_redaction_middleware._API_KEY_PATTERN` is the repository's canonical
high-confidence API-key detector. SkillScan's `_SECRET_TOKEN_PATTERNS` is the
scanner's copy of the same contract, but it only knew AWS, classic GitHub,
Slack and OpenAI keys. GitHub fine-grained PATs (`github_pat_…`) and Google API
keys (`AIza…`) were missing, so a bare embedded key -- one with no `KEY=`/`KEY:`
assignment for `_SECRET_ASSIGNMENT_RE` to fall back on -- produced no finding
at all, and `scan_skill_dir` did not block.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deerflow.agents.middlewares.pii_redaction_middleware import _API_KEY_PATTERN
from deerflow.skills.skillscan.orchestrator import _scan_text_file, scan_skill_dir

_AWS = "AKIA" + "Q" * 16
_CLASSIC_GITHUB = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
_FINE_GRAINED_PAT = "github_pat_" + "A1b2C3d4E5f6G7h8I9j0K1" * 2
_SLACK = "xoxb-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
_OPENAI = "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
_GOOGLE = "AIza" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r"

# One representative token per family in the canonical detector. The bodies are
# long enough to satisfy both `_API_KEY_PATTERN` and `_SECRET_TOKEN_PATTERNS`,
# so this table pins family *coverage* rather than any minimum-length spelling.
_CANONICAL_FAMILIES = {
    "aws": _AWS,
    "classic_github": _CLASSIC_GITHUB,
    "fine_grained_pat": _FINE_GRAINED_PAT,
    "slack": _SLACK,
    "openai": _OPENAI,
    "google": _GOOGLE,
}

_NEW_FAMILIES = {"fine_grained_pat": _FINE_GRAINED_PAT, "google": _GOOGLE}


def _cloud_token_severities(text: str, rel_path: str = "scripts/run.sh") -> list[str]:
    return [finding["severity"] for finding in _scan_text_file(rel_path, text) if finding["rule_id"] == "secret-cloud-token"]


@pytest.mark.parametrize("family", sorted(_CANONICAL_FAMILIES))
def test_every_canonical_api_key_family_is_flagged_critical(family: str) -> None:
    """A bare embedded key (no assignment) must still reach `secret-cloud-token`."""
    token = _CANONICAL_FAMILIES[family]
    # The canonical detector is the contract; if it knows the family, SkillScan must too.
    assert _API_KEY_PATTERN.search(token) is not None
    text = f'curl -H "Authorization: Bearer {token}" https://api.example.com/v1/models\n'
    assert _cloud_token_severities(text) == ["CRITICAL"]


@pytest.mark.parametrize("family", sorted(_NEW_FAMILIES))
def test_newly_covered_families_are_not_merely_assignment_findings(family: str) -> None:
    """`KEY=<token>` alone only reaches the HIGH `secret-env-assignment` rule."""
    token = _NEW_FAMILIES[family]
    text = f"DEPLOY_KEY={token}\n"
    rule_ids = [finding["rule_id"] for finding in _scan_text_file("scripts/run.sh", text)]
    assert "secret-cloud-token" in rule_ids
    assert _cloud_token_severities(text) == ["CRITICAL"]


def test_token_prefixes_that_are_not_keys_stay_quiet() -> None:
    # Too few characters after the prefix to be a token.
    assert _cloud_token_severities("github_pat_short\n") == []
    assert _cloud_token_severities("AIzaShort\n") == []
    # No word boundary before the prefix, so it is not a token start.
    assert _cloud_token_severities("xgithub_pat_" + "A" * 30 + "\n") == []
    assert _cloud_token_severities("myAIza" + "A" * 35 + "\n") == []
    # Prose mentioning the prefix names must not be reported.
    assert _cloud_token_severities("set github_pat_ or AIza credentials in the vault\n") == []


def test_scan_skill_dir_blocks_a_skill_carrying_a_fine_grained_pat(tmp_path: Path) -> None:
    root = tmp_path / "demo-skill"
    (root / "scripts").mkdir(parents=True)
    (root / "SKILL.md").write_text("---\nname: demo-skill\ndescription: demo\n---\n\nBody.\n", encoding="utf-8")
    (root / "scripts" / "run.sh").write_text(
        f'curl -H "Authorization: Bearer {_FINE_GRAINED_PAT}" https://api.github.com/user\n',
        encoding="utf-8",
    )

    result = scan_skill_dir(root)

    assert "secret-cloud-token" in [finding["rule_id"] for finding in result["findings"]]
    assert result["blocked"] is True
