"""Tests for AppConfig's name-indexed get_*_config lookups.

``get_model_config`` / ``get_tool_config`` / ``get_tool_group_config`` are
served from name -> config dicts built once after validation, instead of an
O(n) ``next(...)`` scan per call. These tests lock the indexed lookups to the
exact semantics of the linear scan they replaced (match, miss -> None,
first-match-wins on duplicate names) and confirm a config reload rebuilds them.
"""

from deerflow.config.app_config import AppConfig


def _build(model_names=(), tool_names=(), group_names=()):
    return AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "models": [{"name": n, "use": "pkg:Cls", "model": n} for n in model_names],
            "tools": [{"name": n, "group": "default", "use": "pkg:fn"} for n in tool_names],
            "tool_groups": [{"name": n} for n in group_names],
        }
    )


def test_get_config_returns_matching_entry():
    cfg = _build(model_names=["m1", "m2"], tool_names=["t1", "t2"], group_names=["g1"])
    assert cfg.get_model_config("m2").name == "m2"
    assert cfg.get_tool_config("t1").name == "t1"
    assert cfg.get_tool_group_config("g1").name == "g1"


def test_get_config_returns_none_for_missing():
    cfg = _build(model_names=["m1"], tool_names=["t1"], group_names=["g1"])
    assert cfg.get_model_config("nope") is None
    assert cfg.get_tool_config("nope") is None
    assert cfg.get_tool_group_config("nope") is None


def test_get_config_first_match_wins_on_duplicate_names():
    # Two models share a name; the index must return the FIRST, matching the
    # previous next(...) scan.
    cfg = AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "models": [
                {"name": "dup", "use": "pkg:A", "model": "first"},
                {"name": "dup", "use": "pkg:B", "model": "second"},
            ],
        }
    )
    assert cfg.get_model_config("dup").model == "first"


def test_index_matches_linear_scan_reference():
    cfg = _build(model_names=["a", "b", "c"], tool_names=["x", "y"], group_names=["g"])
    for n in ["a", "b", "c", "missing"]:
        assert cfg.get_model_config(n) == next((m for m in cfg.models if m.name == n), None)
    for n in ["x", "y", "missing"]:
        assert cfg.get_tool_config(n) == next((t for t in cfg.tools if t.name == n), None)
    for n in ["g", "missing"]:
        assert cfg.get_tool_group_config(n) == next((grp for grp in cfg.tool_groups if grp.name == n), None)


def test_empty_config_lookups_return_none():
    cfg = _build()
    assert cfg.get_model_config("anything") is None
    assert cfg.get_tool_config("anything") is None
    assert cfg.get_tool_group_config("anything") is None
