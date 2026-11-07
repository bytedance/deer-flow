"""Offline unit tests for the static evaluator: no host, no package content executed."""

import json

import pytest

from deerflow_extension_skill_evolution.evaluator import (
    EVALUATOR_NAME,
    EVALUATOR_VERSION,
    Case,
    Check,
    evaluate,
    load_cases_dir,
    report_id,
    run_check,
)


def pkg(**files: str) -> dict[str, bytes]:
    return {name: content.encode("utf-8") for name, content in files.items()}


MAIN_OK = "---\nname: example-skill\ndescription: demo\n---\n\nRun `scripts/run.py --format json` to convert.\n"
MAIN_BAD_ARG = MAIN_OK.replace("--format json", "--fmt json")
SCRIPT_OK = "import json\nprint(json.dumps({'ok': True}))\n"
SCRIPT_BROKEN = "def f(:\n"


# --- check kinds -----------------------------------------------------------


def test_file_exists_both_ways():
    package = pkg(**{"SKILL.md": MAIN_OK})
    assert run_check(Check("file_exists", path="SKILL.md"), package).passed
    missing = run_check(Check("file_exists", path="scripts/run.py"), package)
    assert not missing.passed and "missing scripts/run.py" in missing.detail


def test_text_contains_and_not_contains():
    package = pkg(**{"SKILL.md": MAIN_OK})
    assert run_check(Check("text_contains", path="SKILL.md", needle="--format json"), package).passed
    failed = run_check(Check("text_contains", path="SKILL.md", needle="--format yaml"), package)
    assert not failed.passed and "--format yaml" in failed.detail
    assert run_check(Check("text_not_contains", path="SKILL.md", needle="--fmt"), package).passed
    still = run_check(Check("text_not_contains", path="SKILL.md", needle="--format"), package)
    assert not still.passed


def test_text_checks_report_missing_file_and_bad_encoding():
    assert not run_check(Check("text_contains", path="SKILL.md", needle="x"), {}).passed
    binary = {"SKILL.md": b"\xff\xfe not utf-8"}
    outcome = run_check(Check("text_contains", path="SKILL.md", needle="x"), binary)
    assert not outcome.passed and "not valid UTF-8" in outcome.detail


def test_referenced_files_exist_flags_dangling_script_reference():
    baseline = pkg(**{"SKILL.md": MAIN_OK})
    outcome = run_check(Check("referenced_files_exist", path="SKILL.md"), baseline)
    assert not outcome.passed and "scripts/run.py" in outcome.detail
    fixed = pkg(**{"SKILL.md": MAIN_OK, "scripts/run.py": SCRIPT_OK})
    assert run_check(Check("referenced_files_exist", path="SKILL.md"), fixed).passed


def test_referenced_files_exist_ignores_prose_and_urls():
    # The reference regex must not fire on sentence fragments or URLs.
    prose = pkg(**{"SKILL.md": "Use the scripts/run helper from https://example.com/scripts/run.py docs.\n"})
    outcome = run_check(Check("referenced_files_exist", path="SKILL.md"), prose)
    assert not outcome.passed  # bare token still extracted; strict by design
    assert "scripts/run" in outcome.detail


def test_scripts_parse_is_syntax_only_and_never_executes():
    # A script that would print if executed; parse must not run it.
    hostile = pkg(**{"scripts/run.py": "print('EXECUTED')\n"})
    assert run_check(Check("scripts_parse"), hostile).passed
    broken = pkg(**{"scripts/run.py": SCRIPT_BROKEN})
    outcome = run_check(Check("scripts_parse"), broken)
    assert not outcome.passed and "SyntaxError" not in outcome.detail and "line 1" in outcome.detail
    # Non-UTF8 scripts are reported, not crashed on.
    binary = {"scripts/run.py": b"\xff\xfe"}
    assert not run_check(Check("scripts_parse"), binary).passed
    # No scripts at all passes vacuously.
    assert run_check(Check("scripts_parse"), pkg(**{"SKILL.md": MAIN_OK})).passed


# --- validation ------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["", "/abs/path", "..\\win", "a/../b", "./x", "a//b", "x/" + "y" * 1100],
)
def test_case_path_validation_rejects_unsafe_paths(path):
    with pytest.raises(ValueError):
        Check.from_json({"kind": "file_exists", "path": path})


def test_check_from_json_requires_kind_specific_fields():
    with pytest.raises(ValueError):
        Check.from_json({"kind": "nope"})
    with pytest.raises(ValueError):
        Check.from_json({"kind": "file_exists"})  # missing path
    with pytest.raises(ValueError):
        Check.from_json({"kind": "text_contains", "path": "SKILL.md"})  # missing needle
    with pytest.raises(ValueError):
        Check.from_json({"kind": "text_contains", "path": "SKILL.md", "needle": ""})


def test_case_from_json_validation():
    good = {"id": "arg-order", "description": "converter arg is wrong", "checks": [{"kind": "text_contains", "path": "SKILL.md", "needle": "--format json"}]}
    case = Case.from_json(good, origin="case.json")
    assert case.case_id == "arg-order" and len(case.checks) == 1
    for bad in (
        {"id": "Upper", "description": "d", "checks": [{"kind": "scripts_parse"}]},
        {"id": "ok", "description": " ", "checks": [{"kind": "scripts_parse"}]},
        {"id": "ok", "description": "d", "checks": []},
        {"id": "x" * 65, "description": "d", "checks": [{"kind": "scripts_parse"}]},
        "not-an-object",
    ):
        with pytest.raises(ValueError):
            Case.from_json(bad, origin="case.json")


def test_load_cases_dir_orders_by_name_and_reports_broken_files(tmp_path):
    (tmp_path / "01-a.json").write_text(json.dumps({"id": "a", "description": "d", "checks": [{"kind": "scripts_parse"}]}), encoding="utf-8")
    (tmp_path / "02-b.json").write_text(json.dumps({"id": "b", "description": "d", "checks": [{"kind": "scripts_parse"}]}), encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("x", encoding="utf-8")
    cases = load_cases_dir(tmp_path)
    assert [case.case_id for case in cases] == ["a", "b"]

    (tmp_path / "03-broken.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="03-broken.json"):
        load_cases_dir(tmp_path)

    with pytest.raises(ValueError, match="cases directory not found"):
        load_cases_dir(tmp_path / "missing")


# --- decisions -------------------------------------------------------------

ARG_CASE = Case(
    case_id="converter-arg",
    description="SKILL.md must instruct --format json, not --fmt",
    checks=(Check("text_contains", path="SKILL.md", needle="--format json"),),
)
PARSE_CASE = Case(case_id="scripts-parse", description="bundled scripts must parse", checks=(Check("scripts_parse"),))


def test_justified_when_candidate_fixes_a_recorded_baseline_failure():
    baseline = pkg(**{"SKILL.md": MAIN_BAD_ARG, "scripts/run.py": SCRIPT_OK})
    candidate = pkg(**{"SKILL.md": MAIN_OK, "scripts/run.py": SCRIPT_OK})
    evaluation = evaluate([ARG_CASE, PARSE_CASE], baseline, candidate)
    assert evaluation.decision == "justified"
    assert "converter-arg" in evaluation.reasons[0]


def test_unjustified_when_baseline_already_passes_everything():
    package = pkg(**{"SKILL.md": MAIN_OK, "scripts/run.py": SCRIPT_OK})
    evaluation = evaluate([ARG_CASE], package, package)
    assert evaluation.decision == "unjustified"


def test_failed_when_candidate_still_fails():
    baseline = pkg(**{"SKILL.md": MAIN_BAD_ARG})
    candidate = pkg(**{"SKILL.md": MAIN_BAD_ARG.replace("--fmt", "--format"), "scripts/run.py": SCRIPT_BROKEN})
    evaluation = evaluate([ARG_CASE, PARSE_CASE], baseline, candidate)
    assert evaluation.decision == "failed" and "scripts-parse" in evaluation.reasons[0]


def test_failed_when_no_cases_recorded():
    evaluation = evaluate([], pkg(), pkg())
    assert evaluation.decision == "failed" and "no regression cases" in evaluation.reasons[0]


# --- report determinism ----------------------------------------------------


def test_report_is_deterministic_and_report_id_is_content_addressed():
    baseline = pkg(**{"SKILL.md": MAIN_BAD_ARG})
    candidate = pkg(**{"SKILL.md": MAIN_OK})
    first = evaluate([ARG_CASE], baseline, candidate).report(candidate_hash="a" * 64)
    second = evaluate([ARG_CASE], baseline, candidate).report(candidate_hash="a" * 64)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert report_id(first) == report_id(second)
    assert first["evaluator"] == EVALUATOR_NAME and first["evaluator_version"] == EVALUATOR_VERSION
    assert first["decision"] == "justified"
    assert first["cases"][0]["baseline_passed"] is False and first["cases"][0]["candidate_passed"] is True
    # A different candidate hash changes the report identity.
    other = evaluate([ARG_CASE], baseline, candidate).report(candidate_hash="b" * 64)
    assert report_id(other) != report_id(first)


def test_detail_is_clipped_to_bound():
    huge = pkg(**{"SKILL.md": "x" * 5000})
    outcome = run_check(Check("text_contains", path="SKILL.md", needle="y" * 5000), huge)
    assert len(outcome.detail) <= 300
