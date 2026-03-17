"""Tests for research-writing prompt-pack metadata utilities."""

from __future__ import annotations

from src.research_writing import prompt_pack


def test_prompt_pack_metadata_defaults(monkeypatch):
    monkeypatch.delenv(prompt_pack.PROMPT_PACK_ID_ENV_VAR, raising=False)
    monkeypatch.delenv(prompt_pack.PROMPT_PACK_HASH_ENV_VAR, raising=False)
    monkeypatch.delenv(prompt_pack.PROMPT_LAYER_OVERRIDES_ENV_VAR, raising=False)

    metadata = prompt_pack.get_prompt_pack_metadata()

    assert metadata["prompt_pack_id"] == prompt_pack.DEFAULT_PROMPT_PACK_ID
    assert metadata["prompt_pack_hash_source"] == "auto_computed"
    assert isinstance(metadata["prompt_pack_hash"], str)
    assert len(metadata["prompt_pack_hash"]) == 16
    assert any(path.endswith("skills/public/academic-superagent/SKILL.md") for path in metadata["prompt_pack_source_files"])
    assert metadata["prompt_layer_schema_version"] == prompt_pack.PROMPT_LAYER_SCHEMA_VERSION
    assert metadata["runtime_stage_recipe_schema_version"] == prompt_pack.RUNTIME_STAGE_RECIPE_SCHEMA_VERSION
    assert metadata["runtime_stage_recipe_stages"] == ["ingest", "plan", "draft", "verify", "revise", "submit"]
    assert set(metadata["prompt_layer_versions"].keys()) == {"L0", "L1", "L2", "L3", "L4", "L5"}
    assert set(metadata["prompt_layer_rollbacks"].keys()) == {"L0", "L1", "L2", "L3", "L4", "L5"}
    assert set(metadata["prompt_layer_signatures"].keys()) == {"L0", "L1", "L2", "L3", "L4", "L5"}
    assert isinstance(metadata["prompt_layer_compare_ready_layers"], list)
    assert set(metadata["prompt_layer_compare_ready_layers"]) == {"L0", "L1", "L2", "L3", "L4", "L5"}
    assert isinstance(metadata["prompt_layer_diff_summary"], dict)
    assert metadata["prompt_layer_diff_summary"]["total_layers"] == 6
    assert metadata["prompt_layer_diff_summary"]["changed_layer_count"] == 6
    assert metadata["prompt_layer_diff_summary"]["has_diff"] is True
    assert len(metadata["prompt_layer_diff_summary"]["layer_entries"]) == 6
    assert len(metadata["prompt_layer_diff_summary"]["changed_layers"]) == 6
    assert all(
        isinstance(item.get("active_signature"), str) and item.get("active_signature")
        for item in metadata["prompt_layer_diff_summary"]["changed_layers"]
    )
    assert all(
        item.get("compare_ready_source")
        in {"prompt_layer_compare_ready_layers", "computed_active_vs_rollback"}
        for item in metadata["prompt_layer_diff_summary"]["changed_layers"]
    )


def test_prompt_pack_metadata_honors_env_overrides(monkeypatch):
    monkeypatch.setenv(prompt_pack.PROMPT_PACK_ID_ENV_VAR, "rw.superagent.v99")
    monkeypatch.setenv(prompt_pack.PROMPT_PACK_HASH_ENV_VAR, "feedfacefeedface")
    monkeypatch.setenv(prompt_pack.PROMPT_LAYER_OVERRIDES_ENV_VAR, '{"L2":"v0","L4":"v0"}')

    metadata = prompt_pack.get_prompt_pack_metadata()

    assert metadata["prompt_pack_id"] == "rw.superagent.v99"
    assert metadata["prompt_pack_hash"] == "feedfacefeedface"
    assert metadata["prompt_pack_hash_source"] == "env_override"
    assert metadata["prompt_layer_versions"]["L2"] == "v0"
    assert metadata["prompt_layer_versions"]["L4"] == "v0"
    assert metadata["prompt_layer_overrides_applied"] == {"L2": "v0", "L4": "v0"}
    assert metadata["prompt_layer_diff_summary"]["total_layers"] == 6
    assert metadata["prompt_layer_diff_summary"]["changed_layer_count"] == 4
    assert metadata["prompt_layer_diff_summary"]["has_diff"] is True
    assert len(metadata["prompt_layer_diff_summary"]["layer_entries"]) == 6
    assert {item["layer_id"] for item in metadata["prompt_layer_diff_summary"]["changed_layers"]} == {
        "L0",
        "L1",
        "L3",
        "L5",
    }
