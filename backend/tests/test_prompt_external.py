"""Tests for externalized prompt templates (06-prompt).

``memory_update`` uses the chat form (:func:`load_prompt_messages`, system/user
split -- mirrors the lead agent's static system). The injected text sections
(staleness_review / consolidation / fact_extraction) use :func:`load_prompt`.
Covers: bundled defaults, ``.format`` rendering, missing-file error, the
``prompts_dir`` / ``agent_name`` override path, and chat system/user split +
byte-stability.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from deerflow.agents.memory.backends.deermem.deermem.core.prompt import (
    CONSOLIDATION_PROMPT,
    FACT_EXTRACTION_PROMPT,
    STALENESS_REVIEW_PROMPT,
    load_prompt,
    load_prompt_messages,
)


def test_load_prompt_returns_bundled_defaults() -> None:
    # The injected text sections are non-empty, carry their role line, and
    # preserve .format placeholders. (memory_update is chat, tested below.)
    sr = load_prompt("staleness_review")
    assert "Staleness Review" in sr
    assert "{stale_facts}" in sr

    co = load_prompt("consolidation")
    assert "Memory Consolidation" in co
    assert "{consolidation_groups}" in co
    assert "{max_groups}" in co

    fe = load_prompt("fact_extraction")
    assert "Extract factual information" in fe
    assert "{message}" in fe


def test_shim_constants_equal_load_prompt_default() -> None:
    # The injected-section shim aliases each load the bundled default
    # (byte-identical), so updater.py's ``CONST.format(...)`` behaves unchanged.
    assert STALENESS_REVIEW_PROMPT == load_prompt("staleness_review")
    assert CONSOLIDATION_PROMPT == load_prompt("consolidation")
    assert FACT_EXTRACTION_PROMPT == load_prompt("fact_extraction")


def test_load_prompt_missing_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_prompt("does_not_exist")


def test_load_prompt_custom_prompts_dir(tmp_path: Path) -> None:
    # prompts_dir (global override): a custom default file wins over bundled.
    (tmp_path / "memory_update.yaml").write_text('format: text\nversion: "9.9"\ntemplate: |\n  CUSTOM GLOBAL PROMPT\n', encoding="utf-8")
    result = load_prompt("memory_update", prompts_dir=str(tmp_path))
    assert "CUSTOM GLOBAL PROMPT" in result
    # A name with no file in the custom dir -> FileNotFoundError (no fallback to bundled).
    with pytest.raises(FileNotFoundError):
        load_prompt("staleness_review", prompts_dir=str(tmp_path))


def test_load_prompt_agent_override_resolves(tmp_path: Path) -> None:
    # agent_name override: {prompts_dir}/{agent_name}/{name}.yaml wins over the
    # default {prompts_dir}/{name}.yaml; absent override falls back to default.
    (tmp_path / "memory_update.yaml").write_text('format: text\nversion: "1.0"\ntemplate: |\n  DEFAULT PROMPT\n', encoding="utf-8")
    (tmp_path / "researcher").mkdir()
    (tmp_path / "researcher" / "memory_update.yaml").write_text('format: text\nversion: "1.0"\ntemplate: |\n  RESEARCHER-SPECIFIC PROMPT\n', encoding="utf-8")
    # Agent "researcher" has an override -> custom template.
    assert "RESEARCHER-SPECIFIC PROMPT" in load_prompt("memory_update", agent_name="researcher", prompts_dir=str(tmp_path))
    # Agent "other" has no override dir -> falls back to the default.
    assert "DEFAULT PROMPT" in load_prompt("memory_update", agent_name="other", prompts_dir=str(tmp_path))
    # "researcher" override does NOT leak into "other" (isolation).
    other = load_prompt("memory_update", agent_name="other", prompts_dir=str(tmp_path))
    assert "RESEARCHER-SPECIFIC" not in other


def test_load_prompt_messages_returns_system_user() -> None:
    # Chat form: system (static rules) + user (dynamic placeholders).
    variables = {
        "current_memory": "CM-VAL",
        "conversation": "CONV-VAL",
        "correction_hint": "CH-VAL",
        "staleness_review_section": "SRS-VAL",
        "consolidation_section": "CS-VAL",
    }
    messages = load_prompt_messages("memory_update", variables)
    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)
    # System carries the static rules + JSON schema (single braces after .format).
    assert "memory management system" in messages[0].content
    assert '"user": {' in messages[0].content
    assert "{{" not in messages[0].content
    assert "Return ONLY valid JSON" in messages[0].content
    # User carries the 5 dynamic placeholders, all substituted.
    assert "CM-VAL" in messages[1].content
    assert "CONV-VAL" in messages[1].content
    assert "CH-VAL" in messages[1].content
    assert "SRS-VAL" in messages[1].content
    assert "CS-VAL" in messages[1].content
    assert "<current_memory>" in messages[1].content


def test_load_prompt_messages_system_byte_stable_across_vars() -> None:
    # The system message has no variables -> renders byte-identical regardless of
    # the per-call vars (prefix-cache friendly, mirrors lead agent's static system).
    vars_a = {
        "current_memory": "AAA",
        "conversation": "AAA",
        "correction_hint": "AAA",
        "staleness_review_section": "AAA",
        "consolidation_section": "AAA",
    }
    vars_b = {
        "current_memory": "BBB",
        "conversation": "BBB",
        "correction_hint": "BBB",
        "staleness_review_section": "BBB",
        "consolidation_section": "BBB",
    }
    sys_a = load_prompt_messages("memory_update", vars_a)[0].content
    sys_b = load_prompt_messages("memory_update", vars_b)[0].content
    assert sys_a == sys_b
    # And neither contains the per-call values (vars are in user, not system).
    assert "AAA" not in sys_a
    assert "BBB" not in sys_b


def test_load_prompt_messages_missing_raises() -> None:
    # No chat yaml for staleness_review -> FileNotFoundError.
    with pytest.raises(FileNotFoundError):
        load_prompt_messages("staleness_review", {})
