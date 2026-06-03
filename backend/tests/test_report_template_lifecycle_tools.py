"""Unit tests for the 6 lifecycle ``report_template_*`` tools (Phase 3).

Each tool returns a JSON string — tests assert the parsed dict shape.

Strategy:
  - Inject a real ``FileSystemReportTemplateRepository`` rooted in ``tmp_path``
    via ``service.set_repository(...)``.
  - Patch ``langgraph.config.get_config`` so each tool sees a synthetic
    ``configurable`` block carrying ``user_id`` / ``tenant_id`` / role flags.
  - Patch ``script_registry.get_registry`` to return a built-in test registry
    matching the §5.2 DSL used elsewhere.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from deerflow.report_templates import service as svc
from deerflow.report_templates.repository import FileSystemReportTemplateRepository
from deerflow.report_templates.script_registry import (
    REPORT_SCRIPTS_FILE,
    _build_registry_from_skills,
)
from deerflow.tools.builtins import report_template_tools as rt


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runtime_root(tmp_path: Path) -> Path:
    return tmp_path / "runtime"


@pytest.fixture
def repo(runtime_root: Path) -> FileSystemReportTemplateRepository:
    repo = FileSystemReportTemplateRepository(runtime_root=runtime_root)
    svc.set_repository(repo)
    yield repo
    svc.reset_repository()


@pytest.fixture
def script_registry(tmp_path: Path):
    """Build a registry equivalent to the daily-report manifest used by §5.2."""
    skill_dir = tmp_path / "daily-report"
    skill_dir.mkdir()
    import yaml

    manifest = {
        "schema_version": "1",
        "scripts": {
            "query_daily": {
                "entry": "scripts/query_daily.py",
                "kind": ["data_step"],
                "args_schema": {"date": {"type": "date", "required": True}},
                "output_files": [
                    {"id": "daily_data", "path": "{run_output_dir}/data/daily_data.json"}
                ],
            },
            "daily_kpi": {
                "entry": "scripts/daily_kpi.py",
                "kind": ["transform"],
                "args_schema": {"input": {"type": "file_path", "required": True}},
                "output_files": [
                    {"id": "daily_kpi", "path": "{run_output_dir}/data/daily_kpi.json"}
                ],
            },
        },
    }
    (skill_dir / REPORT_SCRIPTS_FILE).write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    return _build_registry_from_skills([("daily-report", skill_dir, True)])


@pytest.fixture
def patched_runtime(monkeypatch: pytest.MonkeyPatch, script_registry):
    """Patch langgraph.config + registry so each tool runs offline."""

    def fake_get_config() -> dict:
        return {
            "configurable": {
                "user_id": "user_alice",
                "tenant_id": "tenant_a",
                "is_superadmin": False,
                "is_tenant_admin": False,
            }
        }

    monkeypatch.setattr(rt, "get_config", fake_get_config)
    monkeypatch.setattr(rt, "get_registry", lambda: script_registry)
    yield


@pytest.fixture
def patched_runtime_other_user(monkeypatch: pytest.MonkeyPatch, script_registry):
    """Same as patched_runtime but for a different user (cross-user tests)."""

    def fake_get_config() -> dict:
        return {
            "configurable": {
                "user_id": "user_bob",
                "tenant_id": "tenant_a",
                "is_superadmin": False,
                "is_tenant_admin": False,
            }
        }

    monkeypatch.setattr(rt, "get_config", fake_get_config)
    monkeypatch.setattr(rt, "get_registry", lambda: script_registry)
    yield


# A minimal valid DSL — all referenced scripts exist in the test registry.
GOOD_DSL: dict[str, Any] = {
    "dsl_version": "1",
    "name": "demo",
    "display_name": "Demo",
    "form_steps": [
        {
            "id": "scope",
            "title": "Scope",
            "fields": [{"name": "report_date", "label": "Date", "type": "date", "required": True}],
            "next": "generate",
        }
    ],
    "data_steps": [
        {
            "id": "data1",
            "kind": "script",
            "name": "daily-report/query_daily",
            "args": {"date": "{{ $.form.scope.report_date }}"},
            "outputs": {"daily_data": "daily_data.json"},
        }
    ],
    "transforms": [
        {
            "id": "kpi1",
            "kind": "script",
            "name": "daily-report/daily_kpi",
            "args": {"input": "data1.daily_data"},
            "outputs": {"daily_kpi": "daily_kpi.json"},
        }
    ],
    "sections": [
        {
            "id": "overview",
            "title": "Overview",
            "component": "markdown",
            "source": "$.steps.kpi1.daily_kpi.summary",
        }
    ],
    "export": {"formats": ["md", "pdf"], "renderer": "generic_report"},
}

GOOD_YAML = "# stub yaml\nname: demo\n"


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def _payload(result: str) -> dict:
    return json.loads(result)


def _create_via_tool(dsl: dict | None = None) -> dict:
    """Convenience: drive the create path through save_draft and return template dict."""
    out = _payload(
        rt.report_template_save_draft_tool.invoke(
            {
                "template_id": None,
                "dsl": dsl or GOOD_DSL,
                "dsl_yaml": GOOD_YAML,
                "name": "demo",
                "display_name": "Demo",
                "description": "d",
            }
        )
    )
    assert "template" in out, out
    return out["template"]


# ---------------------------------------------------------------------------
# Tool 1: list
# ---------------------------------------------------------------------------


class TestList:
    def test_lists_empty_initially(self, repo, patched_runtime):
        out = _payload(rt.report_template_list_tool.invoke({}))
        assert out == {"templates": []}

    def test_lists_created_template(self, repo, patched_runtime):
        _create_via_tool()
        out = _payload(rt.report_template_list_tool.invoke({}))
        assert len(out["templates"]) == 1
        assert out["templates"][0]["name"] == "demo"

    def test_invalid_scope_rejected(self, repo, patched_runtime):
        out = _payload(
            rt.report_template_list_tool.invoke({"visibility": "wat"})
        )
        assert out["error"]["code"] == "INVALID_SCOPE"


# ---------------------------------------------------------------------------
# Tool 2: get
# ---------------------------------------------------------------------------


class TestGet:
    def test_get_existing(self, repo, patched_runtime):
        created = _create_via_tool()
        out = _payload(
            rt.report_template_get_tool.invoke({"template_id": created["id"]})
        )
        assert out["template"]["id"] == created["id"]
        assert out["version"] is None

    def test_get_with_version_zero(self, repo, patched_runtime):
        created = _create_via_tool()
        out = _payload(
            rt.report_template_get_tool.invoke(
                {"template_id": created["id"], "version": 0}
            )
        )
        assert out["version"]["version"] == 0
        assert out["version"]["dsl"]["name"] == "demo"

    def test_not_found(self, repo, patched_runtime):
        out = _payload(
            rt.report_template_get_tool.invoke(
                {"template_id": "tpl_AAAAAAAAAAAAAAAAAAAAAAAA"}
            )
        )
        assert out["error"]["code"] == "NOT_FOUND"

    def test_invalid_id(self, repo, patched_runtime):
        out = _payload(
            rt.report_template_get_tool.invoke({"template_id": "tpl_short"})
        )
        assert out["error"]["code"] == "INVALID_ID"

    def test_cross_user_blocked(
        self, repo, patched_runtime, patched_runtime_other_user, monkeypatch
    ):
        # Create the template as alice...
        from langgraph.config import get_config as _real_get_config  # noqa: F401

        # First, fake config to alice and create.
        def alice_config():
            return {
                "configurable": {
                    "user_id": "user_alice",
                    "tenant_id": "tenant_a",
                    "is_superadmin": False,
                    "is_tenant_admin": False,
                }
            }

        monkeypatch.setattr(rt, "get_config", alice_config)
        created = _create_via_tool()

        # Switch to bob — he should not find it via the resolver.
        def bob_config():
            return {
                "configurable": {
                    "user_id": "user_bob",
                    "tenant_id": "tenant_a",
                    "is_superadmin": False,
                    "is_tenant_admin": False,
                }
            }

        monkeypatch.setattr(rt, "get_config", bob_config)
        out = _payload(
            rt.report_template_get_tool.invoke({"template_id": created["id"]})
        )
        assert out["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# Tool 3: validate
# ---------------------------------------------------------------------------


class TestValidate:
    def test_valid_dsl(self, repo, patched_runtime):
        out = _payload(rt.report_template_validate_tool.invoke({"dsl": GOOD_DSL}))
        assert out["valid"] is True
        assert out["errors"] == []

    def test_invalid_dsl(self, repo, patched_runtime):
        bad = copy.deepcopy(GOOD_DSL)
        bad["form_steps"][0]["next"] = "nowhere"
        out = _payload(rt.report_template_validate_tool.invoke({"dsl": bad}))
        assert out["valid"] is False
        assert any(e["code"] == "UNKNOWN_NEXT" for e in out["errors"])

    def test_unknown_script_reported(self, repo, patched_runtime):
        bad = copy.deepcopy(GOOD_DSL)
        bad["data_steps"][0]["name"] = "daily-report/no_such"
        out = _payload(rt.report_template_validate_tool.invoke({"dsl": bad}))
        assert any(e["code"] == "UNKNOWN_SCRIPT" for e in out["errors"])


# ---------------------------------------------------------------------------
# Tool 4: save_draft
# ---------------------------------------------------------------------------


class TestSaveDraft:
    def test_create_then_update(self, repo, patched_runtime):
        created = _create_via_tool()
        assert created["status"] == "draft"
        assert created["current_version"] == 0
        # Update with the etag we just got.
        out = _payload(
            rt.report_template_save_draft_tool.invoke(
                {
                    "template_id": created["id"],
                    "dsl": GOOD_DSL,
                    "dsl_yaml": GOOD_YAML,
                    "display_name": "Renamed",
                    "expected_etag": created["etag"],
                }
            )
        )
        assert out["template"]["display_name"] == "Renamed"
        assert out["template"]["etag"] != created["etag"]

    def test_invalid_dsl_does_not_persist(self, repo, patched_runtime):
        bad = copy.deepcopy(GOOD_DSL)
        bad["form_steps"][0]["next"] = "nowhere"
        out = _payload(
            rt.report_template_save_draft_tool.invoke(
                {
                    "template_id": None,
                    "dsl": bad,
                    "dsl_yaml": GOOD_YAML,
                    "name": "broken",
                    "display_name": "Broken",
                }
            )
        )
        assert out["error"]["code"] == "INVALID_DSL"
        # And nothing was created.
        listed = _payload(rt.report_template_list_tool.invoke({}))
        assert listed["templates"] == []

    def test_update_requires_etag(self, repo, patched_runtime):
        created = _create_via_tool()
        out = _payload(
            rt.report_template_save_draft_tool.invoke(
                {
                    "template_id": created["id"],
                    "dsl": GOOD_DSL,
                    "dsl_yaml": GOOD_YAML,
                }
            )
        )
        assert out["error"]["code"] == "MISSING_ETAG"

    def test_create_requires_name_and_display(self, repo, patched_runtime):
        out = _payload(
            rt.report_template_save_draft_tool.invoke(
                {
                    "template_id": None,
                    "dsl": GOOD_DSL,
                    "dsl_yaml": GOOD_YAML,
                }
            )
        )
        assert out["error"]["code"] == "MISSING_FIELD"

    def test_etag_mismatch_on_update(self, repo, patched_runtime):
        created = _create_via_tool()
        out = _payload(
            rt.report_template_save_draft_tool.invoke(
                {
                    "template_id": created["id"],
                    "dsl": GOOD_DSL,
                    "dsl_yaml": GOOD_YAML,
                    "expected_etag": "stale_etag_value",
                }
            )
        )
        assert out["error"]["code"] == "ETAG_MISMATCH"


# ---------------------------------------------------------------------------
# Tool 5: publish
# ---------------------------------------------------------------------------


class TestPublish:
    def test_publish_creates_v1(self, repo, patched_runtime):
        created = _create_via_tool()
        out = _payload(
            rt.report_template_publish_tool.invoke(
                {
                    "template_id": created["id"],
                    "expected_current_version": 0,
                    "changelog": "first",
                }
            )
        )
        assert out["template"]["status"] == "published"
        assert out["template"]["current_version"] == 1

    def test_publish_wrong_version(self, repo, patched_runtime):
        created = _create_via_tool()
        out = _payload(
            rt.report_template_publish_tool.invoke(
                {"template_id": created["id"], "expected_current_version": 99}
            )
        )
        assert out["error"]["code"] == "VERSION_MISMATCH"

    def test_publish_unknown_template(self, repo, patched_runtime):
        out = _payload(
            rt.report_template_publish_tool.invoke(
                {
                    "template_id": "tpl_AAAAAAAAAAAAAAAAAAAAAAAA",
                    "expected_current_version": 0,
                }
            )
        )
        assert out["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# Tool 6: fork
# ---------------------------------------------------------------------------


class TestFork:
    def test_fork_published_template_to_self(self, repo, patched_runtime):
        created = _create_via_tool()
        # Publish v1.
        published = _payload(
            rt.report_template_publish_tool.invoke(
                {"template_id": created["id"], "expected_current_version": 0}
            )
        )["template"]
        # Now fork.
        out = _payload(
            rt.report_template_fork_tool.invoke(
                {
                    "source_template_id": published["id"],
                    "source_version": 1,
                    "new_name": "fork_demo",
                    "new_display_name": "Fork Demo",
                }
            )
        )
        assert out["template"]["name"] == "fork_demo"
        assert out["template"]["status"] == "draft"
        assert out["template"]["id"] != published["id"]

    def test_fork_zero_version_rejected(self, repo, patched_runtime):
        out = _payload(
            rt.report_template_fork_tool.invoke(
                {
                    "source_template_id": "tpl_AAAAAAAAAAAAAAAAAAAAAAAA",
                    "source_version": 0,
                    "new_name": "x",
                    "new_display_name": "X",
                }
            )
        )
        assert out["error"]["code"] == "INVALID_VERSION"

    def test_fork_unknown_template(self, repo, patched_runtime):
        out = _payload(
            rt.report_template_fork_tool.invoke(
                {
                    "source_template_id": "tpl_AAAAAAAAAAAAAAAAAAAAAAAA",
                    "source_version": 1,
                    "new_name": "x",
                    "new_display_name": "X",
                }
            )
        )
        assert out["error"]["code"] == "NOT_FOUND"
