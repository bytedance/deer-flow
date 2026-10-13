"""Offline contracts for the opt-in synthetic context snapshot benchmark."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.benchmark.context_snapshot.cases import CASES
from scripts.benchmark.context_snapshot.grading import passed, score
from scripts.benchmark.context_snapshot.report import clean_success, summarize, usage


def test_invoice_grader_allows_divmod_and_detects_rounding_errors():
    case = next(case for case in CASES if case.name == "invoice_total")
    correct = """def invoice_total(lines):
    total = 0
    for line in lines:
        if line.get("cancelled") is True:
            continue
        bps = line.get("discount_bps", 0)
        if not 0 <= bps <= 10000:
            raise ValueError()
        n = line["unit_cents"] * line["quantity"] * (10000 - bps)
        q, r = divmod(abs(n), 10000)
        total += (q + (r >= 5000)) * (1 if n >= 0 else -1)
    return total
"""
    assert passed(score(case, correct))
    assert not passed(score(case, correct.replace("r >= 5000", "r > 5000")))


@pytest.mark.parametrize("content", ["[]", "null", '"text"', '{"unexpected":1}', "invalid"])
def test_json_grader_rejects_nonobjects_and_wrong_shapes(content):
    assert not passed(score(CASES[0], content))


def test_python_grader_rejects_imports_and_times_out():
    case = next(case for case in CASES if case.name == "invoice_total")
    assert not passed(score(case, "import os\ndef invoice_total(lines): return 0"))
    result = score(case, "def invoice_total(lines):\n    while True: pass", timeout_seconds=0.2)
    assert result["error"] == "TimeoutExpired"


def test_python_grader_keeps_standard_types_and_rejects_mutation():
    case = next(case for case in CASES if case.name == "pagination")
    correct = """def paginate(items, page, size):
    if isinstance(items, (bytes, bytearray)):
        raise TypeError()
    if type(page) is not int or type(size) is not int or page <= 0 or size <= 0:
        raise ValueError()
    size = min(size, 3)
    start = (page - 1) * size
    return {"items": list(items[start:start + size]), "total": len(items), "next_page": page + 1 if start + size < len(items) else None}
"""
    assert passed(score(case, correct))
    assert not passed(score(case, correct.replace("    size = min", "    items.append(99)\n    size = min")))


def test_usage_counts_lead_and_worker_and_preserves_unknown_cost():
    calls = [{"usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}, {"usage": {"prompt_tokens": 20, "completion_tokens": 3, "total_tokens": 23}}]
    assert usage(calls)["total_tokens"] == 35
    assert usage(calls)["complete"]
    partial = usage(calls + [{"usage": None}])
    assert partial["total_tokens"] == 35
    assert not partial["complete"]


def test_capped_artifact_is_not_normal_completion_and_stays_in_costs():
    good = {
        "case": "synthetic",
        "repetition": 0,
        "arm": "snapshot",
        "artifact_correct": True,
        "fresh_public_check": True,
        "executor_status": "completed",
        "stop_reason": None,
        "error_type": None,
        "seconds": 1,
        "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10, "requests": 2, "complete": True},
    }
    capped = dict(good, repetition=1, stop_reason="turn_capped", usage=dict(good["usage"], total_tokens=30))
    assert clean_success(good) and not clean_success(capped)
    result = summarize([good, capped])["snapshot"]
    assert result["n"] == 2 and result["clean_success"] == 1
    assert result["mean_total_tokens"] == 20


def test_offline_summary_cli_needs_no_provider_config(tmp_path):
    target = tmp_path / "rows.jsonl"
    target.write_text("", encoding="utf-8")
    result = subprocess.run([sys.executable, "-m", "scripts.benchmark.context_snapshot", "summarize", str(target)], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {}


def test_published_results_include_all_pairs_and_reproduce_summary():
    root = Path(__file__).resolve().parents[1] / "scripts/benchmark/context_snapshot/results"
    rows = [json.loads(line) for line in (root / "2026-09-12.rows.jsonl").read_text().splitlines()]
    assert len(rows) == 16
    summary = summarize(rows)
    assert summary == json.loads((root / "2026-09-12.summary.json").read_text())
    assert all(arm["artifact_correct"] == 8 and arm["clean_success"] == 7 for arm in summary.values())


def test_config_rejects_credentials_instead_of_recording_them(tmp_path):
    from scripts.benchmark.context_snapshot.runner import ROOT, load_config

    config = json.loads((ROOT / "config.json").read_text())
    config["api_key"] = "private-test-value"
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="Unsupported config fields") as exc:
        load_config(path)
    assert "private-test-value" not in str(exc.value)


@pytest.mark.anyio
@pytest.mark.parametrize("api_key", ["", "configured-test-key"])
async def test_provider_auth_and_metadata_redaction(api_key):
    import httpx

    from scripts.benchmark.context_snapshot.runner import ROOT, Transport

    config = json.loads((ROOT / "config.json").read_text())
    transport = Transport("https://provider.invalid/v1", api_key, "synthetic-model", config, 1703)
    try:
        request = httpx.Request("POST", "https://provider.invalid/v1/chat/completions", headers={"Authorization": "Bearer configured-test-key"})
        await transport.on_request(request)
        assert ("authorization" in request.headers) == bool(api_key)
        response = httpx.Response(
            200, request=request, headers={"private-header": "must-not-record"}, json={"choices": [{"message": {"content": "private-payload"}}], "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}}
        )
        await transport.on_response(response)
        assert usage(transport.calls)["total_tokens"] == 6
        encoded = json.dumps(transport.calls)
        assert all(value not in encoded for value in ("configured-test-key", "private-payload", "must-not-record", "provider.invalid"))
    finally:
        await transport.client.aclose()
