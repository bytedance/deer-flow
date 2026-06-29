from ai_report.models import RunParams


def test_run_params_requires_period_binding():
    params = RunParams(
        period_bindings={"本期": "2024Q4"},
        org_scope=[{"branch_num": "27020199", "branch_short_name": "王益联社"}],
        output_formats=["md"],
    )

    assert params.resolve_period("本期") == "2024Q4"


def test_run_params_missing_period_raises_key_error():
    params = RunParams(period_bindings={}, org_scope=[], output_formats=["md"])

    try:
        params.resolve_period("去年同期")
    except KeyError as exc:
        assert "Missing period binding: 去年同期" in str(exc)
    else:
        raise AssertionError("resolve_period should fail for missing aliases")
