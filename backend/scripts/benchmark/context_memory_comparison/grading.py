from __future__ import annotations

from typing import Any


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def grade_scope_isolation_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_cases = len(rows)
    total_expected_a = sum(len(r.get("expected_thread_a_canaries", [])) for r in rows)
    present_a = sum(len(r.get("thread_a_canaries_present", [])) for r in rows)

    total_expected_b = sum(len(r.get("expected_thread_b_canaries", [])) for r in rows)
    present_b = sum(len(r.get("thread_b_canaries_present", [])) for r in rows)

    total_crosstalk_leaks = sum(len(r.get("crosstalk_canaries_leaked", [])) for r in rows)
    total_persisted_pollutions = sum(len(r.get("persisted_rejected_canaries", [])) for r in rows)
    total_rejected_expected = sum(len(r.get("expected_rejected_canaries", [])) for r in rows)

    thread_a_retention_rate = _rate(present_a, total_expected_a)
    thread_b_retention_rate = _rate(present_b, total_expected_b)
    project_to_global_contamination_rate = _rate(total_persisted_pollutions, total_rejected_expected)
    cross_thread_crosstalk_rate = float(total_crosstalk_leaks > 0)

    all_passed = (
        thread_a_retention_rate == 1.0
        and thread_b_retention_rate == 1.0
        and cross_thread_crosstalk_rate == 0.0
        and project_to_global_contamination_rate == 0.0
    )

    return {
        "cases": total_cases,
        "scope_isolation_passed": all_passed,
        "cross_thread_crosstalk_rate": cross_thread_crosstalk_rate,
        "project_to_global_contamination_rate": project_to_global_contamination_rate,
        "thread_a_retention_rate": thread_a_retention_rate,
        "thread_b_retention_rate": thread_b_retention_rate,
        "details": {
            "total_crosstalk_leaks": total_crosstalk_leaks,
            "total_persisted_pollutions": total_persisted_pollutions,
            "thread_a_canaries_matched": f"{present_a}/{total_expected_a}",
            "thread_b_canaries_matched": f"{present_b}/{total_expected_b}",
        },
    }


def grade_turn_invalidation_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_cases = len(rows)
    total_t1_expected = sum(len(r.get("expected_turn_1_canaries", [])) for r in rows)
    t1_present = sum(len(r.get("turn_1_canaries_present", [])) for r in rows)

    total_expected_absent = sum(len(r.get("expected_turn_2_absent_canaries", [])) for r in rows)
    stale_injected = sum(len(r.get("turn_2_stale_canaries_present", [])) for r in rows)

    total_expected_present = sum(len(r.get("expected_turn_2_present_canaries", [])) for r in rows)
    fresh_present = sum(len(r.get("turn_2_fresh_canaries_present", [])) for r in rows)

    turn_1_retention_rate = _rate(t1_present, total_t1_expected)
    stale_prompt_injection_rate = _rate(stale_injected, total_expected_absent)
    atomic_replacement_success_rate = _rate(fresh_present, total_expected_present) if total_expected_present else 1.0

    all_passed = (
        turn_1_retention_rate == 1.0
        and stale_prompt_injection_rate == 0.0
        and atomic_replacement_success_rate == 1.0
    )

    return {
        "cases": total_cases,
        "instant_invalidation_passed": all_passed,
        "stale_prompt_injection_rate": stale_prompt_injection_rate,
        "atomic_replacement_success_rate": atomic_replacement_success_rate,
        "turn_1_retention_rate": turn_1_retention_rate,
        "details": {
            "stale_canaries_injected": stale_injected,
            "fresh_canaries_matched": f"{fresh_present}/{total_expected_present}",
            "turn_1_canaries_matched": f"{t1_present}/{total_t1_expected}",
        },
    }


def grade_token_overhead_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_cases = len(rows)
    if total_cases == 0:
        return {
            "cases": 0,
            "avg_memory_tokens": 0.0,
            "avg_project_tokens": 0.0,
            "avg_total_tokens": 0.0,
            "cases_breakdown": [],
        }

    cases_breakdown: list[dict[str, Any]] = []
    total_mem = 0
    total_proj = 0
    total_overall = 0
    total_user_facts = 0
    total_agent_facts = 0
    total_proj_instructions = 0
    total_proj_shelf = 0

    for r in rows:
        tokens = r.get("token_breakdown", {})
        u_facts = tokens.get("user_facts_tokens", 0)
        a_facts = tokens.get("agent_facts_tokens", 0)
        p_inst = tokens.get("project_instructions_tokens", 0)
        p_shelf = tokens.get("project_shelf_tokens", 0)
        mem_tot = tokens.get("memory_total_tokens", 0)
        proj_tot = tokens.get("project_total_tokens", 0)
        overall = tokens.get("total_context_tokens", 0)

        total_user_facts += u_facts
        total_agent_facts += a_facts
        total_proj_instructions += p_inst
        total_proj_shelf += p_shelf
        total_mem += mem_tot
        total_proj += proj_tot
        total_overall += overall

        mem_pct = round((mem_tot / overall * 100) if overall else 0.0, 1)
        proj_pct = round((proj_tot / overall * 100) if overall else 0.0, 1)

        cases_breakdown.append({
            "case_id": r.get("row_id"),
            "description": r.get("description", ""),
            "user_facts_tokens": u_facts,
            "agent_facts_tokens": a_facts,
            "memory_total_tokens": mem_tot,
            "project_instructions_tokens": p_inst,
            "project_shelf_tokens": p_shelf,
            "project_total_tokens": proj_tot,
            "total_context_tokens": overall,
            "memory_percentage": f"{mem_pct}%",
            "project_percentage": f"{proj_pct}%",
        })

    avg_mem = round(total_mem / total_cases, 1)
    avg_proj = round(total_proj / total_cases, 1)
    avg_tot = round(total_overall / total_cases, 1)
    overall_mem_pct = round((total_mem / total_overall * 100) if total_overall else 0.0, 1)
    overall_proj_pct = round((total_proj / total_overall * 100) if total_overall else 0.0, 1)

    return {
        "cases": total_cases,
        "avg_memory_tokens": avg_mem,
        "avg_project_tokens": avg_proj,
        "avg_total_tokens": avg_tot,
        "overall_memory_percentage": f"{overall_mem_pct}%",
        "overall_project_percentage": f"{overall_proj_pct}%",
        "layer_aggregates": {
            "total_user_facts_tokens": total_user_facts,
            "total_agent_facts_tokens": total_agent_facts,
            "total_project_instructions_tokens": total_proj_instructions,
            "total_project_shelf_tokens": total_proj_shelf,
            "total_context_tokens": total_overall,
        },
        "cases_breakdown": cases_breakdown,
    }


def grade_all_rows(
    scope_rows: list[dict[str, Any]],
    invalidation_rows: list[dict[str, Any]],
    token_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    scope_results = grade_scope_isolation_rows(scope_rows)
    inv_results = grade_turn_invalidation_rows(invalidation_rows)
    tok_results = grade_token_overhead_rows(token_rows)

    overall_passed = bool(
        scope_results["scope_isolation_passed"]
        and inv_results["instant_invalidation_passed"]
    )

    return {
        "all_checks_passed": overall_passed,
        "check_1_scope_isolation": scope_results,
        "check_2_instant_invalidation": inv_results,
        "check_3_token_overhead": tok_results,
    }
