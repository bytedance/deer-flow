"""Run frozen discovery queries and report observations, never execute tools."""

import argparse
import hashlib
import importlib.metadata
import json
import math
import platform
import statistics
import subprocess
from pathlib import Path
from time import perf_counter

from .adapters import ADAPTERS, build_adapter, make_tools
from .protocol import canonical_bytes, load_dataset, score


def evaluate(dataset, *, adapters, repeats):
    if type(repeats) is not int or not 1 <= repeats <= 10000:
        raise ValueError("repeats must be an integer in [1, 10000]")
    if not adapters or len(set(adapters)) != len(adapters) or not set(adapters) <= set(ADAPTERS):
        raise ValueError(f"Choose distinct adapters from {ADAPTERS}")
    definitions = {tool["name"]: tool for tool in dataset["tools"]}
    rows, metadata = [], {}
    cache = {}
    for name in adapters:
        for case in dataset["cases"]:
            # Original catalog order is frozen. Neither query annotations nor
            # denied definitions are provided to an adapter.
            allowed = [t for t in dataset["tools"] if t["name"] in case["allowed_tools"]]
            key = (name, tuple(t["name"] for t in allowed))
            if key not in cache:
                start = perf_counter()
                retrieve, provenance = build_adapter(name, allowed)
                cache[key] = retrieve
                metadata[name] = provenance
                setup_ms = (perf_counter() - start) * 1000
            else:
                retrieve = cache[key]
                setup_ms = None
            # Warmup excludes one-time lazy initialization from warm latency.
            retrieve(case["query"])
            samples, selected, payload_bytes = [], None, None
            for _ in range(repeats):
                start = perf_counter()
                current, size = retrieve(case["query"])
                samples.append((perf_counter() - start) * 1000)
                if not isinstance(current, dict) or not set(current) <= set(case["allowed_tools"]):
                    raise ValueError("Adapter returned a tool outside the post-policy catalog")
                if len(current) > 5:
                    raise ValueError("Adapter exceeded the common top-k budget")
                if selected is not None and current != selected:
                    raise ValueError("Offline retrieval changed across identical repeats")
                selected, payload_bytes = current, size
            # Compare the same complete native schema representation for each
            # shortlist. Actual adapter response bytes remain a separate metric.
            from langchain_core.utils.function_calling import convert_to_openai_function

            full_schemas = [convert_to_openai_function(t) for t in make_tools([definitions[n] for n in selected])]
            row = {
                "adapter": name,
                "case_id": case["id"],
                "selected_tools": list(selected),
                "loaded_tool_count": len(selected),
                "schema_bytes": len(canonical_bytes(full_schemas)),
                "retrieval_payload_bytes": payload_bytes,
                "setup_ms": setup_ms,
                "latency_ms": {"samples": repeats, "p50": statistics.median(samples), "p95": sorted(samples)[math.ceil(0.95 * repeats) - 1]},
                **score(case, selected),
            }
            rows.append(row)
    summary = {}
    for name in adapters:
        group = [r for r in rows if r["adapter"] == name]
        positives = [r for r in group if r["tool_recall"] is not None]
        fields = [r["field_recall"] for r in group if r["field_recall"] is not None]
        negatives = [r for r in group if r["unsupported_rejected"] is not None]
        summary[name] = {
            "positive_cases": len(positives),
            "tool_recall_macro": statistics.mean(r["tool_recall"] for r in positives) if positives else None,
            "input_field_recall_macro": statistics.mean(fields) if fields else None,
            "unsupported_cases": len(negatives),
            "unsupported_rejected": sum(r["unsupported_rejected"] for r in negatives),
            "false_positive_tool_count": sum(len(r["false_positive_tools"]) for r in group),
            "mean_loaded_tools": statistics.mean(r["loaded_tool_count"] for r in group),
            "mean_schema_bytes": statistics.mean(r["schema_bytes"] for r in group),
            "median_case_p50_ms": statistics.median(r["latency_ms"]["p50"] for r in group),
        }
    return {"version": 1, "kind": "synthetic-offline-retrieval", "fixture_sha256": dataset["sha256"], "repeats": repeats, "warmup_calls": 1, "adapters": metadata, "summary": summary, "rows": rows}


def provenance(dataset_path):
    backend = Path(__file__).resolve().parents[3]
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=backend, text=True, capture_output=True, check=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=backend, text=True, capture_output=True, check=True).stdout.strip())
    files = list(Path(__file__).parent.glob("*.py")) + [
        backend / "packages/harness/deerflow/tools/builtins/tool_search.py",
        backend / "packages/harness/deerflow/tools/mcp_metadata.py",
        backend / "packages/harness/deerflow/agents/middlewares/mcp_routing_middleware.py",
    ]
    return {
        "git_revision": git,
        "git_dirty": dirty,
        "python": platform.python_version(),
        "platform": platform.system(),
        "fixture_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "sources": {p.relative_to(backend).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)},
        "packages": {name: importlib.metadata.version(name) for name in ("langchain", "langchain-core", "langgraph", "pydantic")},
        "network_calls": 0,
        "tool_executions": 0,
        "seed": None,
        "clock": "perf_counter; warm local discovery only",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=Path(__file__).with_name("fixtures.json"))
    parser.add_argument("--adapters", default="keywords,regex,auto-promote")
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        data = load_dataset(args.fixture)
        report = evaluate(data, adapters=args.adapters.split(","), repeats=args.repeats)
        report["provenance"] = provenance(args.fixture)
        args.output_dir.mkdir(parents=True, exist_ok=False)
        (args.output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        with (args.output_dir / "rows.jsonl").open("w", encoding="utf-8") as stream:
            for row in report["rows"]:
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Benchmark failed: {exc}\n")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0
