"""Offline unit and CLI tests for scripts/score_issues.py."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "score_issues.py"


@pytest.fixture(scope="module")
def scorer():
    spec = importlib.util.spec_from_file_location("score_issues", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["score_issues"] = module
    spec.loader.exec_module(module)
    return module


def test_classify_issue_kind_distinguishes_bugs_and_features(scorer):
    bug_issue = {
        "title": "[bug] Fresh make config breaks web_fetch",
        "body": "### Steps to reproduce\nRun make config",
        "labels": [{"name": "needs-triage"}],
    }
    feat_issue = {
        "title": "[feat] Per-agent MCP credentials",
        "body": "### Problem / motivation\nShared MCP auth",
        "labels": [{"name": "enhancement"}],
    }
    assert scorer.classify_issue_kind(bug_issue, mode="auto") == "bug"
    assert scorer.classify_issue_kind(feat_issue, mode="auto") == "feature"
    assert scorer.classify_issue_kind(bug_issue, mode="feature") == "feature"


def test_extract_stage0_verifies_existing_repo_paths_and_harness_fallback(scorer):
    issue = {
        "title": "[bug] Task tool validation issue",
        "body": ("### Problem summary\nFound in `scripts/sync_labels.py`, `deerflow/tools/builtins/task_tool.py`, and `backend/nonexistent/fake_file.py`.\n```python\npytest backend/tests\n```\nReproduced on commit 4d7f770fd."),
        "labels": [{"name": "bug"}],
        "assignees": [{"login": "octocat"}],
        "authorAssociation": "MEMBER",
    }
    stage0 = scorer.extract_stage0_signals(issue, repo_root=REPO_ROOT)
    assert "scripts/sync_labels.py" in stage0["verified_repo_paths"]
    assert "backend/packages/harness/deerflow/tools/builtins/task_tool.py" in stage0["verified_repo_paths"]
    assert all("fake_file.py" not in p for p in stage0["verified_repo_paths"])
    assert stage0["has_structured_sections"] is True
    assert stage0["has_code_block"] is True
    assert stage0["has_commit_sha"] is True
    assert stage0["has_test_or_repro_cmd"] is True
    assert stage0["is_maintainer_author"] is True


def test_bug_scoring_caps_synthetic_micro_window_at_p3_while_preserving_fast_track(scorer):
    declared = scorer.load_declared_labels()
    stage0 = {
        "title_has_code_fence": False,
        "verified_repo_paths": ["scripts/sync_labels.py"],
        "has_structured_sections": True,
        "inferred_area": "backend",
    }
    llm = {
        "issue_type": "bug",
        "impact": "low",
        "trigger_realism": "synthetic_or_micro_window",
        "evidence_quality": "unit_or_code_trace_only",
        "change_surface": "localized_1_to_2_files",
        "scope_fit": "core",
        "routing_track": "fast_track_bug",
        "suggested_area": "backend",
        "summary_zh": "同一微秒时钟冲突仅在单测冻结时间下触发，但补丁局部清晰。",
    }
    res = scorer.compute_bug_score(stage0, llm, declared_labels=declared)
    assert res["priority"] == "P3"
    assert res["fast_track_ready"] is True
    assert res["action_zh"] == "可直接提PR"
    assert "P3" not in res["suggested_labels"]
    assert set(res["suggested_labels"]) == {"bug", "area:backend"}


def test_bug_scoring_blocks_fast_track_when_contract_or_security_changes(scorer):
    declared = scorer.load_declared_labels()
    stage0 = {
        "title_has_code_fence": False,
        "verified_repo_paths": [],
        "has_structured_sections": True,
        "inferred_area": "agents",
    }
    llm = {
        "issue_type": "bug",
        "impact": "major",
        "trigger_realism": "specific_channel_or_edge_input",
        "evidence_quality": "verified_end_to_end",
        "change_surface": "cross_cutting_or_contract_change",
        "scope_fit": "core",
        "routing_track": "maintainer_rfc_decision",
        "suggested_area": "agents",
        "summary_zh": "涉及HITL审批安全边界，需维护者先定方案。",
    }
    res = scorer.compute_bug_score(stage0, llm, declared_labels=declared)
    assert res["priority"] == "P1"
    assert res["fast_track_ready"] is False
    assert res["action_zh"] == "需先讨论方案"
    assert set(res["suggested_labels"]) == {"bug", "area:agents", "P1"}


def test_feature_scoring_routes_extension_candidates_and_actionable_core_features(scorer):
    declared = scorer.load_declared_labels()
    stage0 = {"title_has_code_fence": False, "inferred_area": "mcp"}

    ext_llm = {
        "user_value": "useful_enhancement",
        "architecture_fit": "better_as_extension",
        "spec_clarity": "clear_goal_needs_design",
        "maintenance_lightness": "moderate_burden",
        "feature_action": "建议走外部插件/Skill",
        "suggested_area": "mcp",
        "short_tag_scene_zh": "外部绘图MCP",
        "scope_label_zh": "外部扩展配置",
        "summary_zh": "应通过外部MCP接入，无需合入主仓。",
    }
    ext_res = scorer.compute_feature_score(stage0, ext_llm, declared_labels=declared)
    assert ext_res["priority"] == "P3"
    assert ext_res["action_zh"] == "建议走外部插件/Skill"
    assert "P3" not in ext_res["suggested_labels"]

    core_llm = {
        "user_value": "core_pain_point",
        "architecture_fit": "core_natural_fit",
        "spec_clarity": "actionable_spec",
        "maintenance_lightness": "low_burden",
        "feature_action": "可Assign推进",
        "suggested_area": "frontend",
        "short_tag_scene_zh": "CSV表格预览",
        "scope_label_zh": "前端单模块",
        "summary_zh": "只读CSV表格预览组件，边界清晰可直接排期。",
    }
    core_res = scorer.compute_feature_score(stage0, core_llm, declared_labels=declared)
    assert core_res["priority"] == "P1"
    assert core_res["total_score"] == 100
    assert core_res["action_zh"] == "可Assign推进"
    assert set(core_res["suggested_labels"]) == {"enhancement", "area:frontend", "P1"}


def test_cli_offline_and_dry_run_work_under_ascii_stdout(tmp_path: Path):
    sample_issues = [
        {
            "number": 8094,
            "title": "[bug] Fresh make config breaks default web_fetch",
            "url": "https://github.com/bytedance/deer-flow/issues/8094",
            "body": ("### Problem summary\nFresh `make config` copies placeholder keys in `scripts/configure.py`.\n```bash\nmake config\n```\n"),
            "labels": [{"name": "needs-triage"}],
            "assignees": [],
        },
        {
            "number": 4673,
            "title": "[feat] Diagram plot MCP tools support",
            "url": "https://github.com/bytedance/deer-flow/issues/4673",
            "body": "### Problem / motivation\nSupport Excalidraw diagram MCP tools.",
            "labels": [{"name": "enhancement"}],
            "assignees": [],
        },
    ]
    input_file = tmp_path / "issues.json"
    output_json = tmp_path / "results.json"
    output_md = tmp_path / "report.md"
    input_file.write_text(json.dumps(sample_issues, ensure_ascii=False), encoding="utf-8")

    env = {**os.environ, "PYTHONIOENCODING": "ascii"}
    res = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--input-json",
            str(input_file),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
            "--offline",
            "--dry-run",
        ],
        env=env,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert res.returncode == 0, res.stderr
    assert b"UnicodeEncodeError" not in res.stderr
    assert b"[dry-run] gh issue edit 8094" in res.stdout
    assert output_json.is_file()
    assert output_md.is_file()
    parsed = json.loads(output_json.read_text(encoding="utf-8"))
    assert len(parsed) == 2
