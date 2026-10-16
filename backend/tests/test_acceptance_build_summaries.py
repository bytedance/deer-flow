"""Build completion is not proof that delegated tests ran successfully."""

import pytest

from deerflow.subagents.acceptance_checks import check_acceptance_criteria, render_acceptance_section


def _check(output: str, command: str = "mvn test", **overrides):
    execution = {
        "tool_call_id": "test-build",
        "tool_name": "bash",
        "command": command,
        "output_tail": output,
        "status": "success",
        "shell_persistent": False,
        **overrides,
    }
    return check_acceptance_criteria([f"tests_passed:{command}"], bash_executions=[execution])


@pytest.mark.parametrize(
    "output,command",
    [
        ("[INFO] BUILD SUCCESS", "mvn test"),
        ("[INFO] Tests are skipped.\n[INFO] BUILD SUCCESS", "mvn test -DskipTests"),
        ("[INFO] Tests run: 0, Failures: 0, Errors: 0, Skipped: 0\n[INFO] BUILD SUCCESS", "mvn test"),
        ("[INFO] Tests run: 3, Failures: 0, Errors: 0, Skipped: 3\n[INFO] BUILD SUCCESS", "mvn test"),
        ("> Task :test NO-SOURCE\nBUILD SUCCESSFUL in 1s", "gradle test"),
        ("> Task :test SKIPPED\nBUILD SUCCESSFUL in 1s", "gradle test"),
        ("0 tests completed\nBUILD SUCCESSFUL", "gradle test"),
        ("3 tests completed, 3 skipped\nBUILD SUCCESSFUL", "gradle test"),
    ],
)
def test_build_without_executed_tests_remains_unverified(output, command):
    verdict = _check(output, command)
    leaf = verdict["leaves"][0]
    assert (leaf["checked"], leaf["holds"]) == (False, False)
    assert verdict["all_hold"] is False
    assert verdict["unchecked"] == [f"tests_passed:{command}"]
    assert "[UNVERIFIED]" in render_acceptance_section(verdict)


@pytest.mark.parametrize(
    "output,command",
    [
        ("[INFO] Tests run: 3, Failures: 0, Errors: 0, Skipped: 0", "mvn test"),
        ("[INFO] Tests run: 3, Failures: 0, Errors: 0, Skipped: 1, Time elapsed: 0.2 s -- in TestExample", "mvn test"),
        ("Tests run: 1, Failures: 0, Errors: 0, Skipped: 0\r\n[INFO] BUILD SUCCESS", "mvn test"),
        ("3 tests completed, 0 failed, 1 skipped\nBUILD SUCCESSFUL", "gradle test"),
        ("3 tests completed\nBUILD SUCCESSFUL", "gradle test"),
    ],
)
def test_nonzero_test_counts_are_positive_evidence(output, command):
    verdict = _check(output, command)
    assert verdict["all_hold"] is True
    assert "[holds]" in render_acceptance_section(verdict)


@pytest.mark.parametrize("kind", ["Failures", "Errors"])
def test_maven_failure_counts_override_ignored_failure_build_success(kind):
    counts = {"Failures": 0, "Errors": 0, kind: 1}
    output = f"[INFO] Tests run: 3, Failures: {counts['Failures']}, Errors: {counts['Errors']}, Skipped: 0\n[INFO] BUILD SUCCESS"
    verdict = _check(output, "mvn test -Dmaven.test.failure.ignore=true")
    assert (verdict["leaves"][0]["checked"], verdict["leaves"][0]["holds"]) == (True, False)
    assert "[does not hold]" in render_acceptance_section(verdict)


@pytest.mark.parametrize("reverse", [False, True])
def test_empty_maven_module_does_not_veto_a_tested_module(reverse):
    summaries = [
        "[INFO] Tests run: 0, Failures: 0, Errors: 0, Skipped: 0",
        "[INFO] Tests run: 3, Failures: 0, Errors: 0, Skipped: 1",
    ]
    if reverse:
        summaries.reverse()
    assert _check("\n".join(summaries))["all_hold"] is True


def test_failing_module_overrides_a_passing_module():
    output = "[INFO] Tests run: 3, Failures: 0, Errors: 0, Skipped: 0\n[ERROR] Tests run: 2, Failures: 1, Errors: 0, Skipped: 0"
    leaf = _check(output)["leaves"][0]
    assert (leaf["checked"], leaf["holds"]) == (True, False)


@pytest.mark.parametrize(
    "summary",
    [
        "Tests run: 1, Failures: 0, Errors: 0, Skipped: 2",
        "Tests run: -1, Failures: 0, Errors: 0, Skipped: 0",
        "Tests run: 3, Failures: 0, Errors:",
        "Tests run: three, Failures: 0, Errors: 0, Skipped: 0",
        "3 tests completed, 4 skipped",
    ],
)
def test_inconsistent_or_incomplete_count_summary_is_not_proof(summary):
    leaf = _check(summary + "\nBUILD SUCCESS")["leaves"][0]
    assert (leaf["checked"], leaf["holds"]) == (False, False)


@pytest.mark.parametrize("persistent", [None, True])
def test_count_summary_does_not_bypass_shell_provenance(persistent):
    verdict = _check("Tests run: 3, Failures: 0, Errors: 0, Skipped: 0", shell_persistent=persistent)
    assert verdict["leaves"][0]["checked"] is False


def test_count_summary_does_not_bypass_output_attribution():
    verdict = _check("Tests run: 3, Failures: 0, Errors: 0, Skipped: 0", "echo 'unrelated'; mvn test")
    assert verdict["leaves"][0]["checked"] is False


def test_recorded_failure_status_still_overrides_positive_counts():
    leaf = _check("Tests run: 3, Failures: 0, Errors: 0, Skipped: 0", status="error")["leaves"][0]
    assert (leaf["checked"], leaf["holds"]) == (True, False)
