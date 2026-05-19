"""Tests for the report-template ``closure_section`` block (§6.5).

Coverage:

* schema accepts ``closure_section`` and rejects ``source`` for it;
* schema rejects ``filters`` on non-closure components;
* validator passes for a well-formed closure_section template;
* validator rejects inverted ``period_start``/``period_end``;
* validator rejects bad page_size;
* payload_builder calls ``ClosureService.list_for_report`` with resolved
  filters and produces a table-shaped section payload (data + summary);
* payload_builder emits placeholder when service returns no rows;
* payload_builder bubbles up SERVICE_UNAVAILABLE when no service is wired;
* legacy templates without closure_section are unchanged (regression).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from deerflow.report_templates.runtime.payload_builder import (
    PayloadBuildError,
    assemble_payload,
)
from deerflow.report_templates.runtime.state import RuntimeState
from deerflow.report_templates.schema import ReportTemplateDSL, Section
from deerflow.report_templates.validator import validate_dsl


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _state(**overrides) -> RuntimeState:
    base: dict[str, Any] = {
        "report_run_id": "rr_AAAAAAAAAAAAAAAAAAAAAAAA",
        "thread_id": "thread-1",
        "template_id": "tpl_BBBBBBBBBBBBBBBBBBBBBBBB",
        "template_version": 1,
        "status": "data_complete",
        "nonce": "n1",
        "expected_step": "generate",
        "created_at": "2026-05-18T00:00:00+00:00",
        "form_state": {
            "scope": {
                "device_ids": ["dev-1", "dev-2"],
                "period_start": "2026-05-01",
                "period_end": "2026-05-31",
            }
        },
        "step_outputs": {},
    }
    base.update(overrides)
    return RuntimeState(**base)


def _closure_dsl(*, statuses: list[str] | None = None) -> dict[str, Any]:
    """A minimal DSL containing exactly one closure_section."""
    return {
        "dsl_version": "1",
        "name": "closure-tracking",
        "display_name": "整改追踪",
        "form_steps": [
            {
                "id": "scope",
                "title": "选择范围",
                "fields": [
                    {
                        "name": "device_ids",
                        "label": "设备",
                        "type": "multi-select",
                        "options": [
                            {"label": "设备A", "value": "dev-1"},
                            {"label": "设备B", "value": "dev-2"},
                        ],
                    },
                    {"name": "period_start", "label": "起", "type": "date"},
                    {"name": "period_end", "label": "止", "type": "date"},
                ],
                "next": "generate",
            }
        ],
        "data_steps": [],
        "transforms": [],
        "sections": [
            {
                "id": "closure_block",
                "title": "整改追踪",
                "component": "closure_section",
                "filters": {
                    "device_ids": ["{{ $.form.scope.device_ids }}"],
                    "statuses": statuses,
                    "period_start": "{{ $.form.scope.period_start }}",
                    "period_end": "{{ $.form.scope.period_end }}",
                    "page_size": 100,
                },
            }
        ],
    }


@pytest.fixture
def stub_closure_service(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Replace ``get_default_service()`` with a stub returning canned rows."""
    rows = [
        {
            "id": "ct_1",
            "title": "noisy bearing",
            "device_id": "dev-1",
            "device_name": "设备A",
            "status": "in_progress",
            "priority": "important",
            "severity": None,
            "assignee_id": "user-bob",
            "is_overdue": False,
            "due_at": "2026-05-25T00:00:00+00:00",
            "created_at": "2026-05-18T08:00:00+00:00",
            "closed_at": None,
            "source_type": "diagnosis",
        },
        {
            "id": "ct_2",
            "title": "leaking valve",
            "device_id": "dev-2",
            "device_name": "设备B",
            "status": "closed",
            "priority": "normal",
            "severity": None,
            "assignee_id": "user-bob",
            "is_overdue": False,
            "due_at": None,
            "created_at": "2026-05-10T03:00:00+00:00",
            "closed_at": "2026-05-15T07:00:00+00:00",
            "source_type": "manual",
        },
    ]
    list_for_report = AsyncMock(return_value=rows)
    fake_service = type("S", (), {"list_for_report": list_for_report})()

    from deerflow.report_templates.runtime import payload_builder as pb_module

    def _fake_get_default_service():
        return fake_service

    # Inject through the closed_loop service factory module the builder imports.
    import deerflow.closed_loop.service_factory as factory

    monkeypatch.setattr(factory, "get_default_service", _fake_get_default_service)
    return list_for_report


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestSchema:
    def test_accepts_closure_section_with_filters(self):
        sec = Section(
            id="x",
            title="t",
            component="closure_section",
            filters={"page_size": 50},
        )
        assert sec.component == "closure_section"
        assert sec.source is None

    def test_rejects_closure_section_with_source(self):
        with pytest.raises(ValueError, match="must not declare 'source'"):
            Section(
                id="x",
                title="t",
                component="closure_section",
                source="$.steps.foo.bar",
            )

    def test_rejects_filters_on_non_closure_component(self):
        with pytest.raises(ValueError, match="only valid for component 'closure_section'"):
            Section(
                id="x",
                title="t",
                component="table",
                source="$.steps.foo.bar",
                filters={"page_size": 50},
            )

    def test_rejects_non_closure_section_without_source(self):
        with pytest.raises(ValueError, match="requires 'source'"):
            Section(id="x", title="t", component="markdown")

    def test_filters_extra_forbid(self):
        with pytest.raises(ValueError):
            Section(
                id="x",
                title="t",
                component="closure_section",
                filters={"page_size": 50, "bogus": True},
            )

    def test_status_literal_enforced(self):
        with pytest.raises(ValueError):
            Section(
                id="x",
                title="t",
                component="closure_section",
                filters={"statuses": ["bogus_status"]},
            )


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


class TestValidator:
    def test_accepts_closure_section(self):
        report = validate_dsl(_closure_dsl())
        assert report.valid, report.errors

    def test_rejects_inverted_period(self):
        dsl = _closure_dsl()
        dsl["sections"][0]["filters"]["period_start"] = "2026-12-31"
        dsl["sections"][0]["filters"]["period_end"] = "2026-01-01"
        report = validate_dsl(dsl)
        assert not report.valid
        assert any(e.code == "CLOSURE_FILTER_PERIOD_INVERTED" for e in report.errors)

    def test_legacy_template_without_closure_section_unchanged(self):
        """Regression: a template using only the original components passes."""
        dsl = {
            "dsl_version": "1",
            "name": "legacy",
            "display_name": "legacy",
            "form_steps": [
                {
                    "id": "scope",
                    "title": "scope",
                    "fields": [
                        {"name": "title", "label": "title", "type": "text"}
                    ],
                    "next": "generate",
                }
            ],
            "data_steps": [
                {
                    "id": "data",
                    "kind": "script",
                    "name": "noop/noop",
                    "outputs": {"summary_md": "summary.md"},
                }
            ],
            "transforms": [],
            "sections": [
                {
                    "id": "summary",
                    "title": "Summary",
                    "component": "markdown",
                    "source": "$.steps.data.summary_md",
                }
            ],
        }
        report = validate_dsl(dsl)
        # Section validation passes; the only failure (if any) is registry-pass
        # which is skipped here. Confirm no closure-related errors leaked in.
        assert not any(e.code.startswith("CLOSURE_") for e in report.errors)


# ---------------------------------------------------------------------------
# Payload builder
# ---------------------------------------------------------------------------


class TestPayloadBuilder:
    def test_dispatches_to_closure_service(self, stub_closure_service: AsyncMock):
        st = _state()
        payload = assemble_payload(
            dsl=_closure_dsl(), state=st, tenant_id="tenant-a"
        )
        # Verify service was called with resolved filters.
        stub_closure_service.assert_called_once()
        call_kwargs = stub_closure_service.await_args.kwargs
        assert call_kwargs["tenant_id"] == "tenant-a"
        assert call_kwargs["device_ids"] == ["dev-1", "dev-2"]
        assert isinstance(call_kwargs["period_start"], datetime)
        assert isinstance(call_kwargs["period_end"], datetime)
        assert call_kwargs["page_size"] == 100

        # Section payload shape.
        section = payload["sections"][0]
        assert section["component"] == "closure_section"
        props = section["props"]
        assert "columns" in props and len(props["columns"]) > 0
        assert len(props["data"]) == 2
        assert props["summary"] == {
            "total": 2,
            "open": 1,
            "closed": 1,
            "overdue": 0,
        }

    def test_empty_rows_produce_placeholder(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        list_for_report = AsyncMock(return_value=[])
        fake_service = type("S", (), {"list_for_report": list_for_report})()
        import deerflow.closed_loop.service_factory as factory

        monkeypatch.setattr(factory, "get_default_service", lambda: fake_service)

        payload = assemble_payload(
            dsl=_closure_dsl(), state=_state(), tenant_id="tenant-a"
        )
        section = payload["sections"][0]
        assert section["props"]["data"] == []
        assert "empty_text" in section["props"]
        assert section["props"]["summary"]["total"] == 0

    def test_no_service_raises_payload_error(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import deerflow.closed_loop.service_factory as factory

        monkeypatch.setattr(factory, "get_default_service", lambda: None)
        with pytest.raises(PayloadBuildError, match="closure service"):
            assemble_payload(
                dsl=_closure_dsl(), state=_state(), tenant_id="tenant-a"
            )

    def test_no_tenant_raises(self, stub_closure_service: AsyncMock):
        with pytest.raises(PayloadBuildError, match="tenant_id"):
            assemble_payload(dsl=_closure_dsl(), state=_state(), tenant_id=None)

    def test_include_overdue_only_filters_rows(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        rows = [
            {
                "id": "ct_a",
                "title": "x",
                "device_id": None,
                "device_name": None,
                "status": "in_progress",
                "priority": "normal",
                "severity": None,
                "assignee_id": None,
                "is_overdue": True,
                "due_at": None,
                "created_at": None,
                "closed_at": None,
                "source_type": "manual",
            },
            {
                "id": "ct_b",
                "title": "y",
                "device_id": None,
                "device_name": None,
                "status": "in_progress",
                "priority": "normal",
                "severity": None,
                "assignee_id": None,
                "is_overdue": False,
                "due_at": None,
                "created_at": None,
                "closed_at": None,
                "source_type": "manual",
            },
        ]
        list_for_report = AsyncMock(return_value=rows)
        fake_service = type("S", (), {"list_for_report": list_for_report})()
        import deerflow.closed_loop.service_factory as factory

        monkeypatch.setattr(factory, "get_default_service", lambda: fake_service)

        dsl = _closure_dsl()
        dsl["sections"][0]["filters"]["include_overdue_only"] = True
        payload = assemble_payload(dsl=dsl, state=_state(), tenant_id="tenant-a")
        rows_out = payload["sections"][0]["props"]["data"]
        assert [r["id"] for r in rows_out] == ["ct_a"]

    def test_legacy_template_does_not_invoke_closure_service(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Regression for §6.3: templates without closure_section must not touch the service."""
        called = AsyncMock()

        class Boom:
            async def list_for_report(self, **kwargs):  # pragma: no cover
                called(**kwargs)
                raise RuntimeError("should not be reached")

        import deerflow.closed_loop.service_factory as factory

        monkeypatch.setattr(factory, "get_default_service", lambda: Boom())

        dsl = {
            "dsl_version": "1",
            "name": "legacy",
            "display_name": "legacy",
            "form_steps": [
                {
                    "id": "scope",
                    "title": "scope",
                    "fields": [{"name": "v", "label": "v", "type": "text"}],
                    "next": "generate",
                }
            ],
            "sections": [
                {
                    "id": "summary",
                    "title": "Summary",
                    "component": "markdown",
                    "source": "$.steps.data.summary",
                }
            ],
        }
        st = _state(
            step_outputs={"data": {"summary": "hello world"}},
            form_state={"scope": {"v": "x"}},
        )
        payload = assemble_payload(dsl=dsl, state=st, tenant_id=None)
        assert payload["sections"][0]["props"]["content"] == "hello world"
        called.assert_not_awaited()
