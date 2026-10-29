"""Contract tests for the leading ``/skill`` activation gate.

Pins the backend parser's reserved-command set and skill-name grammar to the
shared fixture at ``contracts/slash_skill_contract.json``. The frontend display
parser (``frontend/src/core/skills/slash.ts``) is pinned to the same fixture by
``frontend/tests/unit/core/skills/slash-contract.test.ts``, so a reserved
command added on one side—or a grammar change—cannot silently drift the two
languages apart.
"""

from __future__ import annotations

import json
from pathlib import Path

from deerflow.skills.slash import _SLASH_SKILL_RE, RESERVED_SLASH_SKILL_NAMES

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONTRACT_PATH = _REPO_ROOT / "contracts" / "slash_skill_contract.json"


def _load_contract() -> dict:
    return json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))


def test_contract_file_exists():
    assert _CONTRACT_PATH.is_file(), f"missing shared fixture: {_CONTRACT_PATH}"


def test_reserved_names_match_contract():
    contract = _load_contract()
    assert set(RESERVED_SLASH_SKILL_NAMES) == set(contract["reserved_slash_skill_names"])


def test_skill_name_pattern_matches_contract():
    contract = _load_contract()
    assert _SLASH_SKILL_RE.pattern == contract["skill_name_pattern"]
