from __future__ import annotations

import json
from pathlib import Path

import pytest
from support.evaluation_collection import is_industry_derived_fixture_oracle_path

from deerflow.evaluation.checks import run_check
from deerflow.evaluation.loader import load_eval_suite
from deerflow.evaluation.metrics import build_metrics_summary, compare_paired_variants
from deerflow.evaluation.reports import build_evaluation_report, render_markdown_report
from deerflow.evaluation.results import normalize_attempt_result
from deerflow.evaluation.workspace_seed import materialize_workspace_seed

FIXTURES = Path(__file__).parent / "fixtures" / "evaluation"
INDUSTRY_FIXTURES = FIXTURES / "industry_derived"
COMPLEX_INDUSTRY_SUITE_DIRS = [
    "complex_swe_repobench_multifile",
    "complex_gaia_ragas_evidence_dossier",
    "complex_tau_stabletool_policy",
]
INDUSTRY_SUITE_DIRS = [
    "swe_bench_mini",
    "stable_tool_api",
    "gaia_ragas_grounded_qa",
    "tau_bench_stateful_policy",
    *COMPLEX_INDUSTRY_SUITE_DIRS,
]
TRACE_EVENTS = [
    {"event_type": "run.start", "metadata": {"caller": "lead_agent"}},
    {"event_type": "llm.ai.response", "metadata": {"caller": "lead_agent", "usage": {"input_tokens": 100, "output_tokens": 40, "total_tokens": 140}}},
    {"event_type": "run.end", "metadata": {"status": "success"}},
]


def test_industry_derived_fixture_oracle_tests_are_excluded_from_backend_collection():
    tests_root = Path(__file__).parent
    oracle_files = [
        INDUSTRY_FIXTURES / "swe_bench_mini" / "fixture" / "tests" / "test_intervals.py",
        INDUSTRY_FIXTURES / "complex_swe_repobench_multifile" / "fixture" / "tests" / "test_invoice_pipeline.py",
    ]

    for oracle_file in oracle_files:
        oracle_dir = oracle_file.parent
        assert oracle_file.is_file()
        assert is_industry_derived_fixture_oracle_path(oracle_dir, tests_root=tests_root)
        assert is_industry_derived_fixture_oracle_path(oracle_file, tests_root=tests_root)
    assert not is_industry_derived_fixture_oracle_path(INDUSTRY_FIXTURES / "swe_bench_mini" / "suite.yaml", tests_root=tests_root)
    assert not is_industry_derived_fixture_oracle_path(FIXTURES / "coding_smoke" / "suite.yaml", tests_root=tests_root)


def test_real_case_coding_smoke_runs_workspace_checks_and_command(tmp_path):
    loaded = load_eval_suite(FIXTURES / "coding_smoke" / "suite.yaml")
    item = loaded.suite.items[0]
    workspace = materialize_workspace_seed(
        item.workspace_seed,
        suite_path=loaded.path,
        workspaces_root=tmp_path,
        suite_name=loaded.suite.name,
        suite_item_id=item.id,
        sample_index=0,
        variant_id="default",
    )

    results = [run_check(check, workspace_path=workspace.workspace_path) for check in item.checks]

    assert workspace.seeded_files == ["artifact.txt"]
    assert all(result.passed for result in results)


def test_real_case_trace_gate_exposes_missing_required_event(tmp_path):
    loaded = load_eval_suite(FIXTURES / "memory_multi_session" / "suite.yaml")
    item = loaded.suite.items[0]
    check = item.checks[0]

    result = run_check(check, workspace_path=tmp_path, run_events=[{"event_type": "run.start"}])

    assert result.passed is False
    assert result.failure_kind == "trace_gate_failed"
    assert "run.end" in result.message


def test_real_case_paired_comparison_reports_candidate_improvement():
    loaded = load_eval_suite(FIXTURES / "memory_multi_session" / "suite.yaml")
    attempts = [
        normalize_attempt_result(
            suite_item_id="preference-carryover",
            variant_id="baseline",
            sample_index=0,
            status="failed",
            metrics={"task_success": False, "preference_followed": False, "cross_thread_recall_success": False},
        ),
        normalize_attempt_result(
            suite_item_id="preference-carryover",
            variant_id="candidate",
            sample_index=0,
            status="passed",
            metrics={"task_success": True, "preference_followed": True, "cross_thread_recall_success": True},
        ),
    ]

    comparison = compare_paired_variants(loaded.suite, attempts)

    assert comparison.status == "computed"
    assert comparison.conclusion_label == "improved"
    assert comparison.deltas["task_success_delta"] == 1.0


def test_real_case_memory_multi_session_report_surfaces_p0_dimensions():
    loaded = load_eval_suite(FIXTURES / "memory_multi_session" / "suite.yaml")
    attempts = [
        normalize_attempt_result(
            suite_item_id="preference-carryover",
            variant_id="baseline",
            sample_index=0,
            status="passed",
            metrics={"task_success": True, "preference_followed": True, "cross_thread_recall_success": True},
        ),
        normalize_attempt_result(
            suite_item_id="preference-carryover",
            variant_id="candidate",
            sample_index=0,
            status="passed",
            metrics={"task_success": True, "preference_followed": True, "cross_thread_recall_success": True},
        ),
        normalize_attempt_result(
            suite_item_id="correction-recovery",
            variant_id="baseline",
            sample_index=0,
            status="failed",
            metrics={"contaminated": True, "correction_recovered": False},
        ),
        normalize_attempt_result(
            suite_item_id="correction-recovery",
            variant_id="candidate",
            sample_index=0,
            status="passed",
            metrics={"contaminated": False, "correction_recovered": True},
        ),
    ]
    metrics = build_metrics_summary(loaded.suite, attempts)
    report = build_evaluation_report(loaded.suite, attempts, eval_run_id="eval-run-memory", dataset_digest=loaded.digest, metrics_summary=metrics)
    markdown = render_markdown_report(report)

    assert report.effect_summary["variants"]["candidate"]["rates"]["preference_follow_rate"]["rate"] == 1.0
    assert report.effect_summary["variants"]["candidate"]["rates"]["cross_thread_recall_success_rate"]["rate"] == 1.0
    assert report.effect_summary["variants"]["candidate"]["rates"]["correction_recovery_rate"]["rate"] == 1.0
    assert report.effect_summary["comparison"]["conclusion_label"] == "improved"
    assert "preference-carryover" in markdown
    assert "correction-recovery" in markdown


@pytest.mark.parametrize("suite_dir", INDUSTRY_SUITE_DIRS)
def test_industry_derived_suites_load_materialize_run_checks_and_report(tmp_path, suite_dir):
    loaded = load_eval_suite(INDUSTRY_FIXTURES / suite_dir / "suite.yaml")
    item = loaded.suite.items[0]

    assert loaded.digest
    assert item.workspace_seed is not None
    assert item.variants == ["baseline", "candidate"]
    assert item.metric_tags
    assert item.checks

    workspace = materialize_workspace_seed(
        item.workspace_seed,
        suite_path=loaded.path,
        workspaces_root=tmp_path,
        suite_name=loaded.suite.name,
        suite_item_id=item.id,
        sample_index=0,
        variant_id="candidate",
    )
    workspace_path = Path(workspace.workspace_path)
    assert workspace.seeded_files

    _apply_industry_oracle(loaded.suite.name, workspace_path)
    check_results = [run_check(check, workspace_path=workspace_path, run_events=TRACE_EVENTS) for check in item.checks]

    assert all(result.passed for result in check_results), [result.model_dump(mode="json", exclude_none=True) for result in check_results]

    attempts = [
        normalize_attempt_result(
            suite_item_id=item.id,
            variant_id=variant.id,
            sample_index=0,
            status="passed",
            workspace_path=str(workspace_path),
            check_results=check_results,
            metrics=_passing_metrics_for_tags(item.metric_tags),
            cost=_cost_for_variant(variant.id),
        )
        for variant in loaded.suite.variants
    ]
    metrics = build_metrics_summary(loaded.suite, attempts)
    report = build_evaluation_report(loaded.suite, attempts, eval_run_id=f"eval-run-{suite_dir}", dataset_digest=loaded.digest, metrics_summary=metrics)
    markdown = render_markdown_report(report)

    assert report.summary.pass_rate == 1.0
    assert report.effect_summary["comparison"]["status"] == "computed"
    assert report.effect_summary["comparison"]["conclusion_label"] == "neutral"
    assert item.id in markdown
    if suite_dir in COMPLEX_INDUSTRY_SUITE_DIRS:
        assert item.expected["benchmark_source"] in markdown
        assert item.expected["deterministic_oracle"] in markdown
        assert "Cost delta:" in markdown
        assert any(check.type == "run_event_exists" for check in item.checks)


def test_industry_derived_suites_do_not_change_existing_real_case_ids():
    coding = load_eval_suite(FIXTURES / "coding_smoke" / "suite.yaml")
    memory = load_eval_suite(FIXTURES / "memory_multi_session" / "suite.yaml")

    assert [item.id for item in coding.suite.items] == ["command-check-smoke"]
    assert [item.id for item in memory.suite.items] == ["preference-carryover", "correction-recovery"]


def _apply_industry_oracle(suite_name: str, workspace_path: Path) -> None:
    if suite_name == "industry_swe_bench_mini":
        (workspace_path / "tinycalc" / "intervals.py").write_text(
            "\n".join(
                [
                    "from __future__ import annotations",
                    "",
                    "",
                    "def merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:",
                    "    if not intervals:",
                    "        return []",
                    "    ordered = sorted(intervals)",
                    "    merged = [ordered[0]]",
                    "    for current_start, current_end in ordered[1:]:",
                    "        last_start, last_end = merged[-1]",
                    "        if current_start <= last_end + 1:",
                    "            merged[-1] = (last_start, max(last_end, current_end))",
                    "        else:",
                    "            merged.append((current_start, current_end))",
                    "    return merged",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return

    if suite_name == "industry_stable_tool_api":
        _write_json(
            workspace_path / "result.json",
            {
                "ok": True,
                "tool_name": "reserve_inventory",
                "sku": "widget-a",
                "reserved_quantity": 2,
                "reservation_id": "resv-widget-a-2",
            },
        )
        return

    if suite_name == "industry_gaia_ragas_grounded_qa":
        (workspace_path / "answer.md").write_text(
            "Short answer: Project Nebula migrates on 2026-08-17 09:00 UTC.\n\nSource: KB-2026-NEBULA\n",
            encoding="utf-8",
        )
        return

    if suite_name == "industry_tau_bench_stateful_policy":
        _write_json(
            workspace_path / "db.json",
            {
                "users": {
                    "user-007": {
                        "verified": True,
                        "email": "user007@example.test",
                    }
                },
                "orders": {
                    "ord-1001": {
                        "user_id": "user-007",
                        "status": "refunded",
                        "total_cents": 2599,
                        "refund_id": "rfnd-ord-1001",
                    }
                },
            },
        )
        _write_json(
            workspace_path / "action_log.json",
            [
                {"action": "verify_user", "order_id": "ord-1001", "user_id": "user-007"},
                {"action": "issue_refund", "order_id": "ord-1001", "refund_id": "rfnd-ord-1001"},
            ],
        )
        return

    if suite_name == "industry_complex_swe_repobench_multifile":
        (workspace_path / "billing" / "models.py").write_text(
            "\n".join(
                [
                    "from __future__ import annotations",
                    "",
                    "from dataclasses import dataclass",
                    "",
                    "",
                    "@dataclass(frozen=True)",
                    "class InvoiceLine:",
                    "    sku: str",
                    "    unit_price_cents: int",
                    "    quantity: int",
                    "    discount_cents: int = 0",
                    "    taxable: bool = True",
                    "",
                    "    def net_cents(self) -> int:",
                    "        gross = self.unit_price_cents * self.quantity",
                    "        return max(gross - self.discount_cents, 0)",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (workspace_path / "billing" / "tax.py").write_text(
            "\n".join(
                [
                    "from __future__ import annotations",
                    "",
                    "from decimal import Decimal, ROUND_HALF_UP",
                    "",
                    "",
                    "def calculate_tax_cents(amount_cents: int, rate_bps: int) -> int:",
                    "    value = Decimal(amount_cents) * Decimal(rate_bps) / Decimal(10_000)",
                    "    return int(value.quantize(Decimal('1'), rounding=ROUND_HALF_UP))",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (workspace_path / "billing" / "invoice.py").write_text(
            "\n".join(
                [
                    "from __future__ import annotations",
                    "",
                    "from dataclasses import dataclass",
                    "",
                    "from billing.models import InvoiceLine",
                    "from billing.tax import calculate_tax_cents",
                    "",
                    "",
                    "@dataclass(frozen=True)",
                    "class Invoice:",
                    "    lines: list[InvoiceLine]",
                    "    subtotal_cents: int",
                    "    taxable_subtotal_cents: int",
                    "    tax_cents: int",
                    "    total_cents: int",
                    "    paid_cents: int",
                    "    refunded_cents: int",
                    "    balance_due_cents: int",
                    "",
                    "",
                    "def build_invoice(",
                    "    lines: list[InvoiceLine],",
                    "    *,",
                    "    tax_rate_bps: int,",
                    "    payments_cents: list[int] | None = None,",
                    "    refunds_cents: list[int] | None = None,",
                    ") -> Invoice:",
                    "    payments_cents = payments_cents or []",
                    "    refunds_cents = refunds_cents or []",
                    "    subtotal_cents = sum(line.net_cents() for line in lines)",
                    "    taxable_subtotal_cents = sum(line.net_cents() for line in lines if line.taxable)",
                    "    tax_cents = calculate_tax_cents(taxable_subtotal_cents, tax_rate_bps)",
                    "    total_cents = subtotal_cents + tax_cents",
                    "    paid_cents = sum(payments_cents)",
                    "    refunded_cents = sum(refunds_cents)",
                    "    balance_due_cents = total_cents - (paid_cents - refunded_cents)",
                    "    return Invoice(",
                    "        lines=lines,",
                    "        subtotal_cents=subtotal_cents,",
                    "        taxable_subtotal_cents=taxable_subtotal_cents,",
                    "        tax_cents=tax_cents,",
                    "        total_cents=total_cents,",
                    "        paid_cents=paid_cents,",
                    "        refunded_cents=refunded_cents,",
                    "        balance_due_cents=balance_due_cents,",
                    "    )",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (workspace_path / "billing" / "reporting.py").write_text(
            "\n".join(
                [
                    "from __future__ import annotations",
                    "",
                    "from billing.invoice import Invoice",
                    "",
                    "",
                    "def summarize_invoice(invoice: Invoice) -> dict[str, int | str]:",
                    "    if invoice.balance_due_cents <= 0:",
                    "        status = 'paid'",
                    "    elif invoice.paid_cents == 0:",
                    "        status = 'open'",
                    "    else:",
                    "        status = 'partial'",
                    "    return {",
                    "        'status': status,",
                    "        'subtotal_cents': invoice.subtotal_cents,",
                    "        'tax_cents': invoice.tax_cents,",
                    "        'total_cents': invoice.total_cents,",
                    "        'balance_due_cents': invoice.balance_due_cents,",
                    "    }",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return

    if suite_name == "industry_complex_gaia_ragas_evidence_dossier":
        (workspace_path / "answer.md").write_text(
            "\n".join(
                [
                    "# Answer",
                    "",
                    "- Owner: SRE Aurora (KB-IR-2026-0711).",
                    "- Deadline: 2026-07-18 15:00 UTC (KB-IR-2026-0711).",
                    "- Risk: P1 data freshness degradation (KB-IR-2026-0711).",
                    "- Mitigation guard: freeze the `atlas_writer` feature flag (KB-RUNBOOK-ATLAS-FAILOVER).",
                    "",
                    "# Evidence",
                    "",
                    "- KB-IR-2026-0711 is marked current and supersedes previous Atlas records.",
                    "- KB-RUNBOOK-ATLAS-FAILOVER is the current runbook for the mitigation guard.",
                    "",
                    "# Sources",
                    "",
                    "- KB-IR-2026-0711",
                    "- KB-RUNBOOK-ATLAS-FAILOVER",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return

    if suite_name == "industry_complex_tau_stabletool_policy":
        _write_json(
            workspace_path / "db.json",
            {
                "customers": {"cust-42": {"tier": "gold", "verified": True}},
                "inventory": {"jacket-blue-m": {"available": 2}},
                "orders": {
                    "ret-9001": {
                        "category": "apparel",
                        "customer_id": "cust-42",
                        "defect_evidence": False,
                        "delivered_days_ago": 12,
                        "exchange_sku": "jacket-blue-m",
                        "notes": ["Refund denied; exchange created under delivered-apparel gold customer policy."],
                        "status": "exchange_pending",
                    }
                },
            },
        )
        _write_json(
            workspace_path / "action_log.json",
            [
                {"action": "get_order", "order_id": "ret-9001", "tool_version": "local-tau-stabletool-v1"},
                {"action": "get_inventory", "available": 3, "sku": "jacket-blue-m", "tool_version": "local-tau-stabletool-v1"},
                {"action": "create_exchange", "order_id": "ret-9001", "sku": "jacket-blue-m", "tool_version": "local-tau-stabletool-v1"},
                {"action": "add_note", "order_id": "ret-9001", "tool_version": "local-tau-stabletool-v1"},
            ],
        )
        _write_json(
            workspace_path / "resolution.json",
            {
                "decision": "exchange_pending",
                "order_id": "ret-9001",
                "refund_denied_reason": "policy_requires_exchange_without_defect_evidence",
            },
        )
        return

    raise AssertionError(f"unknown industry suite: {suite_name}")


def _passing_metrics_for_tags(tags: list[str]) -> dict[str, bool]:
    metrics: dict[str, bool] = {}
    if "task_success" in tags:
        metrics["task_success"] = True
    if "preference" in tags:
        metrics["preference_followed"] = True
    if "cross_thread" in tags:
        metrics["cross_thread_recall_success"] = True
    if "isolation" in tags:
        metrics["contaminated"] = False
    if "correction" in tags:
        metrics["correction_recovered"] = True
    return metrics


def _cost_for_variant(variant_id: str) -> dict[str, int]:
    if variant_id == "baseline":
        return {"latency_ms": 1200, "input_tokens": 900, "output_tokens": 300, "total_tokens": 1200}
    return {"latency_ms": 1000, "input_tokens": 850, "output_tokens": 280, "total_tokens": 1130}


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
