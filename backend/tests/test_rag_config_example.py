"""The shipped RAG templates stay in step with the schema (spec 2026-09-26 §5.3).

``rag_config.example.json`` is the copy an operator pastes into place, so it must load
through the real model and mention every model-reference key the settings form can write —
otherwise a new role ships as a field the template never tells anyone about.
``config.example.yaml`` advertises the same keys as commented examples inside its ``rag:``
block instead of activating one, because a name there points at a ``models:`` entry that
most deployments do not have.

The JSON template's vendor model names were replaced with semantic placeholders by the
2026-09-30 closeout pair (inventory C-2); the vendor-name test below keeps the whole
surface clean, including the YAML template's commented examples.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from deerflow.config.rag_config_file import MODEL_REFERENCE_FIELDS, RagConfigFile

ROOT = Path(__file__).resolve().parents[2]
RAG_EXAMPLE = ROOT / "rag_config.example.json"
CONFIG_EXAMPLE = ROOT / "config.example.yaml"

#: The two roles that had no field at all before spec 2026-09-26.
NEW_ROLE_FIELDS = ("wiki_model", "synthesis_model")

#: The two MinerU cloud knobs that had no field at all before spec 2026-09-29.
NEW_PARSE_KNOBS = ("parse_language", "parse_model_version")

#: The two caption generation knobs that had no field at all before spec 2026-09-30.
NEW_CAPTION_KNOBS = ("caption_max_tokens", "caption_temperature")

#: The five follow-chat thinking flags that had no field at all before spec 2026-10-03.
NEW_THINKING_FLAGS = (
    "extract_thinking",
    "wiki_thinking",
    "judge_thinking",
    "synthesis_thinking",
    "vlm_thinking",
)


def _json_keys() -> list[str]:
    return list(json.loads(RAG_EXAMPLE.read_text(encoding="utf-8")))


def _rag_block() -> str:
    text = CONFIG_EXAMPLE.read_text(encoding="utf-8")
    start = re.search(r"^rag:\s*$", text, re.MULTILINE)
    assert start is not None, "config.example.yaml has no top-level `rag:` block"
    return text[start.end() :]


def test_the_json_template_loads_through_the_real_model():
    payload = json.loads(RAG_EXAMPLE.read_text(encoding="utf-8"))

    RagConfigFile.model_validate(payload)


def test_the_json_template_ships_both_roles_as_empty_overrides():
    payload = json.loads(RAG_EXAMPLE.read_text(encoding="utf-8"))

    for field in NEW_ROLE_FIELDS:
        assert field in payload, f"{field} is missing from rag_config.example.json"
        assert payload[field] == "", f"{field} must ship as an empty override, not {payload[field]!r}"
        assert field in MODEL_REFERENCE_FIELDS, f"{field} is not a model-reference field"


def test_the_json_template_keeps_the_roles_next_to_default_model():
    keys = _json_keys()

    anchor = keys.index("default_model")

    assert keys[anchor + 1 : anchor + 3] == list(NEW_ROLE_FIELDS)


def test_the_yaml_template_advertises_both_roles_as_commented_examples():
    block = _rag_block()

    for field in NEW_ROLE_FIELDS:
        assert re.search(rf"^\s*#\s*{field}:\s*\S", block, re.MULTILINE), f"{field} has no commented example in the rag block"
        # A `models:` entry reference is deployment-specific: the template must not activate one.
        assert not re.search(rf"^\s*{field}:", block, re.MULTILINE), f"{field} must stay commented out"


def test_the_yaml_template_advertises_both_parse_knobs_as_commented_examples():
    block = _rag_block()

    for field in NEW_PARSE_KNOBS:
        assert re.search(rf"^\s*#\s*{field}:\s*\S", block, re.MULTILINE), f"{field} has no commented example in the rag block"
        # Plain values, but the template still activates nothing: every row ships commented.
        assert not re.search(rf"^\s*{field}:", block, re.MULTILINE), f"{field} must stay commented out"


def test_the_yaml_template_keeps_the_parse_rows_in_order():
    block = _rag_block()
    names = re.findall(r"^\s*#\s*(parse_\w+):", block, re.MULTILINE)

    assert names == ["parse_provider", "parse_base_url", "parse_tier", *NEW_PARSE_KNOBS]


def test_the_yaml_template_advertises_both_caption_knobs_as_commented_examples():
    block = _rag_block()

    for field in NEW_CAPTION_KNOBS:
        assert re.search(rf"^\s*#\s*{field}:\s*\S", block, re.MULTILINE), f"{field} has no commented example in the rag block"
        # Plain values, but the template still activates nothing: every row ships commented.
        assert not re.search(rf"^\s*{field}:", block, re.MULTILINE), f"{field} must stay commented out"


def test_the_yaml_template_keeps_the_caption_rows_next_to_vlm_model():
    block = _rag_block()
    names = re.findall(r"^\s*#\s*(vlm_model|caption_\w+):", block, re.MULTILINE)

    assert names == ["vlm_model", *NEW_CAPTION_KNOBS]


def test_the_yaml_template_advertises_the_thinking_flags_as_commented_examples():
    block = _rag_block()

    for field in NEW_THINKING_FLAGS:
        assert re.search(rf"^\s*#\s*{field}:\s*\S", block, re.MULTILINE), f"{field} has no commented example in the rag block"
        # Plain `false` values, but the template still activates nothing: every row ships commented.
        assert not re.search(rf"^\s*{field}:", block, re.MULTILINE), f"{field} must stay commented out"


def test_the_yaml_template_is_bumped_for_the_new_fields():
    # A floor, not an equality: the next schema bump may move it further (the same shape as
    # test_config_version's `> 26` check).
    text = CONFIG_EXAMPLE.read_text(encoding="utf-8")

    version = int(re.search(r"^config_version:\s*(\d+)", text, re.MULTILINE).group(1))

    assert version >= 42, "config.example.yaml must be bumped for the two caption knobs"


#: The vendor model names the two templates must not carry any more (C-2, spec 2026-09-30 D3).
VENDOR_MODEL_NAMES = ("qwen3.7-text-embedding", "qwen3-rerank", "deepseek-v4-flash", "qwen3-vl-plus", "paraformer-zh")


def test_the_example_files_carry_no_vendor_model_names():
    """C-2: the templates are for strangers, not for the developer who wrote them — a vendor
    pick in them reads as a recommendation. The `models:` section's own commented examples
    are a different surface (out of C-2's scope, registered as-is)."""
    for path in (RAG_EXAMPLE, CONFIG_EXAMPLE):
        text = path.read_text(encoding="utf-8")
        for name in VENDOR_MODEL_NAMES:
            assert name not in text, f"{path.name} still carries the vendor model name {name!r}"


def test_the_yaml_example_ships_the_required_model_rows_commented_out():
    """③ 甲 (spec 2026-09-30 D3): a placeholder that stayed active would be injected into every
    existing config by `make config-upgrade` — these rows ship commented (the
    `embedding_base_url` precedent), and A-1's loud refusal covers the gap."""
    block = _rag_block()

    for field in ("embedding_model", "rerank_model"):
        assert re.search(rf"^\s*#\s*{field}:\s*\S", block, re.MULTILINE), f"{field} has no commented example in the rag block"
        assert not re.search(rf"^\s*{field}:", block, re.MULTILINE), f"{field} must stay commented out"


def test_the_yaml_example_ships_the_asr_model_row_commented_out():
    """The video block's row follows the same rule (③ 甲)."""
    text = CONFIG_EXAMPLE.read_text(encoding="utf-8")

    assert re.search(r"^\s*#\s*asr_model:\s*\S", text, re.MULTILINE), "asr_model has no commented example"
    assert not re.search(r"^\s*asr_model:", text, re.MULTILINE), "asr_model must stay commented out"


def test_the_json_example_ships_placeholder_model_names():
    """The JSON template is a pure template: every model-shaped value is a placeholder the
    reader replaces, and its shape still loads through the real model."""
    payload = json.loads(RAG_EXAMPLE.read_text(encoding="utf-8"))

    assert payload["embedding_model"] == "your-embedding-model"
    assert payload["rerank_model"] == "your-rerank-model"
    assert payload["extract_model"] == "your-extract-model"
    assert payload["video"]["asr_model"] == "your-asr-model"
