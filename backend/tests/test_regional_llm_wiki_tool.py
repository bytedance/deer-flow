"""Safety tests for the manifest-gated Regional LLM Wiki tools."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

from deerflow.tools.builtins import regional_llm_wiki_tool as tool_module


def _sha(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _install_release(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    release_root = runtime_root / "releases" / "release-1"
    page_path = release_root / "llm-wiki" / "01-产品策划中心" / "concepts" / "cloud-his.md"
    evidence_path = release_root / "evidence" / "wiki" / "01-产品策划中心" / "cloud-his.md"
    page_path.parent.mkdir(parents=True)
    evidence_path.parent.mkdir(parents=True)
    page_content = "# 云 HIS\n\n适用范围：区域医疗。\n"
    evidence_content = "# 原始资料\n\n云 HIS 适用于区域医疗。\n"
    page_path.write_text(page_content, encoding="utf-8")
    evidence_path.write_text(evidence_content, encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "release_id": "release-1",
        "source_commit": "abc123",
        "published_at": "2026-09-21T00:00:00Z",
        "pages": [
            {
                "page_id": "concept:cloud-his",
                "path": "llm-wiki/01-产品策划中心/concepts/cloud-his.md",
                "sha256": _sha(page_content),
                "title": "云 HIS",
                "type": "concept",
                "domain": "01-产品策划中心",
                "summary": "区域医疗云 HIS",
                "evidence_ids": ["evidence:cloud-his"],
            }
        ],
        "evidence": [
            {
                "evidence_id": "evidence:cloud-his",
                "path": "evidence/wiki/01-产品策划中心/cloud-his.md",
                "sha256": _sha(evidence_content),
                "allowed_locations": ["L003-L003"],
                "tfs_url": "https://tfs.example.invalid/original",
            }
        ],
    }
    (release_root / "agent-access-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (runtime_root / "current").symlink_to(release_root)
    config = SimpleNamespace(
        regional_llm_wiki=SimpleNamespace(
            enabled=True,
            runtime_root=str(runtime_root),
            max_search_results=5,
            max_page_chars=24_000,
            max_evidence_chars=16_000,
        )
    )
    monkeypatch.setattr(tool_module, "get_app_config", lambda: config)
    return manifest, page_path, evidence_path


def test_search_and_read_are_manifest_gated(tmp_path, monkeypatch):
    _install_release(tmp_path, monkeypatch)

    search = json.loads(tool_module._search("云 HIS", None, 5))
    assert search["status"] == "ok"
    assert search["release_id"] == "release-1"
    assert search["pages"] == [{"domain": "01-产品策划中心", "page_id": "concept:cloud-his", "title": "云 HIS", "type": "concept"}]

    page = json.loads(tool_module._read_page("release-1", "concept:cloud-his"))
    assert page["status"] == "ok"
    assert page["evidence_ids"] == ["evidence:cloud-his"]
    assert "区域医疗" in page["content"]
    assert "path" not in page


def test_search_matches_unsegmented_chinese_question(tmp_path, monkeypatch):
    _install_release(tmp_path, monkeypatch)

    search = json.loads(tool_module._search("云HIS如何规划", None, 5))

    assert search["status"] == "ok"
    assert search["pages"][0]["page_id"] == "concept:cloud-his"


def test_evidence_must_be_declared_by_the_selected_page(tmp_path, monkeypatch):
    _install_release(tmp_path, monkeypatch)

    allowed = json.loads(tool_module._read_evidence("release-1", "concept:cloud-his", "evidence:cloud-his", "L003-L003"))
    assert allowed["status"] == "ok"
    assert allowed["tfs_url"] == "https://tfs.example.invalid/original"

    denied = json.loads(tool_module._read_evidence("release-1", "concept:cloud-his", "evidence:other", None))
    assert denied == {"status": "not_found"}

    invalid_locator = json.loads(tool_module._read_evidence("release-1", "concept:cloud-his", "evidence:cloud-his", "../../secret"))
    assert invalid_locator == {"status": "invalid_request"}


def test_rejects_path_escape_and_does_not_return_content(tmp_path, monkeypatch):
    manifest, _, _ = _install_release(tmp_path, monkeypatch)
    manifest["pages"][0]["path"] = "llm-wiki/../../outside.md"
    release_root = tmp_path / "runtime" / "releases" / "release-1"
    (release_root / "agent-access-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = json.loads(tool_module._read_page("release-1", "concept:cloud-his"))
    assert result == {"status": "integrity_failed"}


def test_rejects_symlinked_page_outside_release(tmp_path, monkeypatch):
    manifest, page_path, _ = _install_release(tmp_path, monkeypatch)
    outside_page = tmp_path / "outside.md"
    outside_page.write_text("outside release", encoding="utf-8")
    page_path.unlink()
    page_path.symlink_to(outside_page)
    manifest["pages"][0]["sha256"] = _sha(outside_page.read_text(encoding="utf-8"))
    release_root = tmp_path / "runtime" / "releases" / "release-1"
    (release_root / "agent-access-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = json.loads(tool_module._read_page("release-1", "concept:cloud-his"))
    assert result == {"status": "integrity_failed"}


def test_rejects_stale_release_and_disabled_reader(tmp_path, monkeypatch):
    _install_release(tmp_path, monkeypatch)
    assert json.loads(tool_module._read_page("old-release", "concept:cloud-his")) == {"status": "not_found"}

    monkeypatch.setattr(
        tool_module,
        "get_app_config",
        lambda: SimpleNamespace(regional_llm_wiki=SimpleNamespace(enabled=False)),
    )
    assert json.loads(tool_module._release_state()) == {"status": "release_unavailable"}


def test_agent_allowlist_filters_configured_builtin_and_mcp_shaped_tools():
    from deerflow.agents.lead_agent.agent import _filter_tools_by_agent_allowlist

    tools = [
        SimpleNamespace(name="search_llm_wiki"),
        SimpleNamespace(name="read_file"),
        SimpleNamespace(name="web_search"),
        SimpleNamespace(name="mcp_sensitive_tool"),
    ]
    result = _filter_tools_by_agent_allowlist(tools, ["search_llm_wiki"])
    assert [tool.name for tool in result] == ["search_llm_wiki"]
