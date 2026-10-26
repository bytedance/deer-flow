"""Offline evaluation contracts; retrieval must never execute a catalog tool."""

import copy
import json
from pathlib import Path

import pytest

from scripts.benchmark.deferred_tools.protocol import load_dataset, score
from scripts.benchmark.deferred_tools.runner import evaluate


def dataset():
    return {
        "version": 1,
        "kind": "synthetic",
        "tools": [
            {"name": "repo_search", "description": "Search repositories", "parameters": {"type": "object", "properties": {"language": {"type": "string"}}}, "routing_keywords": ["repository"]},
            {"name": "secret_delete", "description": "Delete private repositories", "parameters": {"type": "object", "properties": {}}, "routing_keywords": ["repository"]},
        ],
        "cases": [
            {"id": "lookup", "query": "repository search language", "allowed_tools": ["repo_search"], "expected_tools": ["repo_search"], "required_fields": {"repo_search": ["language"]}},
            {"id": "unsupported", "query": "forecast weather", "allowed_tools": ["repo_search"], "expected_tools": [], "required_fields": {}},
        ],
    }


def write_dataset(tmp_path, data=None):
    path = tmp_path / "synthetic.json"
    path.write_text(json.dumps(dataset() if data is None else data), encoding="utf-8")
    return path


def test_native_paths_use_same_post_policy_catalog(tmp_path):
    data = load_dataset(write_dataset(tmp_path))
    report = evaluate(data, adapters=["keywords", "regex", "auto-promote"], repeats=2)
    assert len(report["rows"]) == 6
    for row in report["rows"]:
        assert "secret_delete" not in row["selected_tools"]
        if row["case_id"] == "unsupported":
            assert row["unsupported_rejected"] is True
            assert row["tool_recall"] is None
        else:
            # Raw natural language is intentionally not rewritten for regex.
            if row["adapter"] != "regex":
                assert row["tool_recall"] == 1
                assert row["field_recall"] == 1
            assert row["latency_ms"]["samples"] == 2


@pytest.mark.parametrize("change", ["duplicate_case", "unknown_allowed", "denied_expected", "unknown_field", "duplicate_tool", "not_synthetic", "unknown_key"])
def test_bad_annotations_fail_before_evaluation(tmp_path, change):
    data = dataset()
    if change == "duplicate_case":
        data["cases"].append(copy.deepcopy(data["cases"][0]))
    elif change == "unknown_allowed":
        data["cases"][0]["allowed_tools"].append("missing")
    elif change == "denied_expected":
        data["cases"][0]["expected_tools"] = ["secret_delete"]
    elif change == "unknown_field":
        data["cases"][0]["required_fields"]["repo_search"] = ["invented"]
    elif change == "duplicate_tool":
        data["tools"].append(copy.deepcopy(data["tools"][0]))
    elif change == "not_synthetic":
        data["kind"] = "production"
    else:
        data["cases"][0]["expected_tool"] = "typo"
    with pytest.raises(ValueError):
        load_dataset(write_dataset(tmp_path, data))


def test_grading_counts_partial_and_false_positive_results():
    case = {"expected_tools": ["a", "b"], "required_fields": {"a": ["x", "y"], "b": ["z"]}}
    grade = score(case, {"a": {"properties": {"x": {}}}, "wrong": {"properties": {}}})
    assert grade["tool_recall"] == 0.5
    assert grade["field_recall"] == pytest.approx(1 / 3)
    assert grade["false_positive_tools"] == ["wrong"]
    assert grade["unsupported_rejected"] is None


def test_negative_case_does_not_get_vacuous_perfect_recall():
    negative = {"expected_tools": [], "required_fields": {}}
    assert score(negative, {}) == {"tool_recall": None, "field_recall": None, "false_positive_tools": [], "unsupported_rejected": True}
    assert score(negative, {"wrong": {}})["unsupported_rejected"] is False


def test_fixture_digest_covers_queries_policy_and_schema(tmp_path):
    original = load_dataset(write_dataset(tmp_path))
    for section, key, value in [("cases", "query", "different"), ("cases", "allowed_tools", ["repo_search", "secret_delete"]), ("tools", "description", "changed")]:
        modified = dataset()
        modified[section][0][key] = value
        assert load_dataset(write_dataset(tmp_path, modified))["sha256"] != original["sha256"]


def test_repeats_must_be_positive_and_bounded(tmp_path):
    data = load_dataset(write_dataset(tmp_path))
    for repeats in [0, -1, True, 10001]:
        with pytest.raises(ValueError):
            evaluate(data, adapters=["keywords"], repeats=repeats)


def test_duplicate_or_unknown_adapters_fail(tmp_path):
    data = load_dataset(write_dataset(tmp_path))
    for adapters in [[], ["unknown"], ["keywords", "keywords"]]:
        with pytest.raises(ValueError):
            evaluate(data, adapters=adapters, repeats=1)


def test_builtin_fixture_has_positive_negative_ambiguous_and_denied_cases():
    path = Path(__file__).parents[1] / "scripts/benchmark/deferred_tools/fixtures.json"
    data = load_dataset(path)
    cases = data["cases"]
    assert len(cases) >= 12
    assert sum(not c["expected_tools"] for c in cases) >= 3
    assert any(len(c["expected_tools"]) > 1 for c in cases)
    assert any(len(c["allowed_tools"]) < len(data["tools"]) for c in cases)


def test_real_schemarouter_when_explicitly_installed(tmp_path):
    pytest.importorskip("schemarouter")
    data = load_dataset(write_dataset(tmp_path))
    report = evaluate(data, adapters=["schemarouter"], repeats=1)
    assert report["adapters"]["schemarouter"]["version"] == "0.17.0"
    assert all("secret_delete" not in r["selected_tools"] for r in report["rows"])
    assert all(r["schema_bytes"] >= 0 for r in report["rows"])


def test_real_schemarouter_handles_empty_host_policy(tmp_path):
    pytest.importorskip("schemarouter")
    data = dataset()
    data["cases"] = [{"id": "empty-policy", "query": "repository", "allowed_tools": [], "expected_tools": [], "required_fields": {}}]
    report = evaluate(load_dataset(write_dataset(tmp_path, data)), adapters=["schemarouter"], repeats=1)
    assert report["rows"][0]["selected_tools"] == []
    assert report["rows"][0]["unsupported_rejected"] is True


@pytest.mark.parametrize("fault", ["denied", "over_budget", "unstable"])
def test_adapter_boundary_fails_closed_on_invalid_results(tmp_path, monkeypatch, fault):
    from scripts.benchmark.deferred_tools import runner

    calls = 0

    def build(name, definitions):
        assert "secret_delete" not in [t["name"] for t in definitions]

        def retrieve(query):
            nonlocal calls
            calls += 1
            if fault == "denied":
                return {"secret_delete": {}}, 1
            if fault == "over_budget":
                return {f"extra_{i}": {} for i in range(6)}, 1
            return ({"repo_search": {"description": str(calls)}}, 1)

        return retrieve, {}

    monkeypatch.setattr(runner, "build_adapter", build)
    data = dataset()
    if fault == "over_budget":
        for index in range(6):
            extra = copy.deepcopy(data["tools"][0])
            extra["name"] = f"extra_{index}"
            data["tools"].append(extra)
            data["cases"][0]["allowed_tools"].append(extra["name"])
    with pytest.raises(ValueError):
        evaluate(load_dataset(write_dataset(tmp_path, data)), adapters=["keywords"], repeats=2)


def test_report_excludes_raw_queries_and_schemas(tmp_path):
    data = dataset()
    data["cases"][0]["query"] += " PRIVATE_QUERY_MARKER"
    report = evaluate(load_dataset(write_dataset(tmp_path, data)), adapters=["keywords"], repeats=1)
    assert "PRIVATE_QUERY_MARKER" not in json.dumps(report)
    assert "properties" not in json.dumps(report)


def test_cli_writes_complete_report_and_refuses_existing_output(tmp_path):
    from scripts.benchmark.deferred_tools.runner import main

    output = tmp_path / "report"
    args = ["--fixture", str(write_dataset(tmp_path)), "--adapters", "keywords", "--repeats", "1", "--output-dir", str(output)]
    assert main(args) == 0
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    rows = [json.loads(row) for row in (output / "rows.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows == report["rows"]
    assert report["provenance"]["fixture_sha256"] == report["fixture_sha256"]
    assert report["provenance"]["network_calls"] == 0
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2


def test_optional_adapter_never_silently_substitutes_a_different_version(tmp_path, monkeypatch):
    from scripts.benchmark.deferred_tools import adapters

    monkeypatch.setattr(adapters.importlib.metadata, "version", lambda name: "0.0.0")
    with pytest.raises(ValueError, match="Expected schemarouter==0.17.0"):
        evaluate(load_dataset(write_dataset(tmp_path)), adapters=["schemarouter"], repeats=1)


def test_all_real_adapters_are_networkless_and_do_not_execute_tools(monkeypatch):
    import socket

    from scripts.benchmark.deferred_tools import adapters

    def forbidden(*args, **kwargs):
        pytest.fail("A retrieval-only benchmark tried to connect or execute a tool")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(adapters, "_never_execute", forbidden)
    names = ["keywords", "regex", "auto-promote"]
    try:
        __import__("schemarouter")
    except ImportError:
        pass
    else:
        names.append("schemarouter")
    fixture = Path(__file__).parents[1] / "scripts/benchmark/deferred_tools/fixtures.json"
    report = evaluate(load_dataset(fixture), adapters=names, repeats=1)
    assert len(report["rows"]) == 22 * len(names)
