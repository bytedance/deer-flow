"""Go's all-skipped verbose package cannot stand in for an executed test.

Outputs below are verbatim captures from ``go test`` (go1.27.1, darwin/arm64)
against a module whose tests call ``t.Skip``.
"""

import pytest

from deerflow.subagents.acceptance_checks import check_acceptance_criteria, render_acceptance_section

ALL_SKIPPED = """\
=== RUN   TestAlpha
    skipper_test.go:5: needs network
--- SKIP: TestAlpha (0.00s)
=== RUN   TestBeta
    skipper_test.go:6: needs credentials
--- SKIP: TestBeta (0.00s)
PASS
ok  \texample.com/acceptancerepro\t1.051s
"""

MIXED_PASS_AND_SKIP = """\
=== RUN   TestGamma
--- PASS: TestGamma (0.00s)
=== RUN   TestDelta
=== RUN   TestDelta/inner
    mixed_test.go:8: nope
--- PASS: TestDelta (0.00s)
    --- SKIP: TestDelta/inner (0.00s)
PASS
ok  \texample.com/acceptancerepro\t0.589s
"""

NON_VERBOSE_OK = "ok  \texample.com/acceptancerepro\t0.124s\n"


def _verdict(output, **overrides):
    execution = {"command": "go test -v ./...", "output_tail": output, "status": "success", "shell_persistent": False, **overrides}
    return check_acceptance_criteria(["tests_passed:go test -v ./..."], bash_executions=[execution])


@pytest.mark.parametrize("output", [ALL_SKIPPED, ALL_SKIPPED.replace("\n", "\r\n")])
def test_all_skipped_verbose_package_remains_unverified(output):
    verdict = _verdict(output)
    assert (verdict["leaves"][0]["checked"], verdict["all_hold"]) == (False, False)
    assert "[UNVERIFIED]" in render_acceptance_section(verdict)


@pytest.mark.parametrize("output", [MIXED_PASS_AND_SKIP, NON_VERBOSE_OK])
def test_executed_or_indistinguishable_package_still_supplies_evidence(output):
    verdict = _verdict(output)
    assert verdict["all_hold"] is True
    assert verdict["unchecked"] == []


def test_skipped_package_does_not_veto_a_passing_sibling_package():
    output = ALL_SKIPPED + MIXED_PASS_AND_SKIP
    verdict = _verdict(output)
    assert verdict["all_hold"] is True


def test_passing_package_followed_by_an_all_skipped_one_still_holds():
    verdict = _verdict(MIXED_PASS_AND_SKIP + ALL_SKIPPED)
    assert verdict["all_hold"] is True


@pytest.mark.parametrize(
    "output",
    [
        "ok  \texample.com/a\t0.001s [no test files]\n",
        "ok  \texample.com/a\t0.001s [no tests to run]\n",
        "?   \texample.com/a\t[no test files]\n",
        ALL_SKIPPED + "ok  \texample.com/a\t0.001s [no test files]\n",
    ],
)
def test_zero_test_packages_stay_unverified(output):
    verdict = _verdict(output)
    assert (verdict["leaves"][0]["checked"], verdict["all_hold"]) == (False, False)


@pytest.mark.parametrize(
    "output",
    [
        "--- FAIL: TestAlpha (0.00s)\nFAIL\nFAIL\texample.com/acceptancerepro\t0.100s\n",
        ALL_SKIPPED + "--- FAIL: TestGamma (0.00s)\nFAIL\nFAIL\texample.com/other\t0.100s\n",
    ],
)
def test_failure_beats_the_skip_rule(output):
    verdict = _verdict(output)
    assert (verdict["leaves"][0]["checked"], verdict["all_hold"]) == (True, False)


def test_skipped_package_cannot_bypass_output_attribution():
    verdict = _verdict(ALL_SKIPPED, command="echo 'go test -v ./...'; true", output_tail="")
    assert verdict["leaves"][0]["checked"] is False


@pytest.mark.parametrize("banner", ["ok  \texample.com/a\t(cached)\n", "ok  \texample.com/a\t0.01s\n"])
def test_cached_and_plain_banners_are_unchanged(banner):
    verdict = _verdict(banner)
    assert verdict["all_hold"] is True


def test_evidence_cap_truncation_keeps_indented_sub_test_results():
    # The harness stores an output *tail*, so a record can begin inside a
    # sub-test block; the indented line is then all the record says.
    verdict = _verdict("    --- SKIP: TestDelta/inner (0.00s)\nPASS\nok  \texample.com/acceptancerepro\t0.589s\n")
    assert (verdict["leaves"][0]["checked"], verdict["all_hold"]) == (False, False)
