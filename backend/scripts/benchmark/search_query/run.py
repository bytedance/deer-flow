"""Compare DeerFlow's first search query with human queries for each backstory."""

import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from statistics import fmean

import httpx

if __package__:
    from .metrics import lexical, semantic
else:  # python scripts/benchmark/search_query/run.py
    from metrics import lexical, semantic

HERE = Path(__file__).resolve().parent
DATASET = HERE / "task" / "uqv100_evaluation_dataset.csv"
DATASET_SHA256 = "92b1dcc723f1fc8967d2906748a6d330aabf702bd0eef5c09cf572f9d86e4a7b"
COLUMNS = ("UQV100Id", "Backstory", "Top 5 SpelledNormQueries")
CONTEXT = {"subagent_enabled": False}


@dataclass
class Case:
    case_id: str
    backstory: str
    references: list[str]


def load_cases(path: Path, expected_hash: str) -> list[Case]:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_hash.lower():
        raise ValueError(f"Dataset SHA-256 mismatch: got {digest}")
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""))
    if not set(COLUMNS).issubset(reader.fieldnames or []):
        raise ValueError(f"Expected CSV columns {COLUMNS}")
    cases = []
    seen = set()
    for row in reader:
        case_id, backstory, raw_queries = (row[key] or "" for key in COLUMNS)
        case_id = case_id.strip()
        references = [query.strip() for query in raw_queries.split("|") if query.strip()]
        if not case_id or case_id in seen or not backstory.strip() or not references or None in row:
            raise ValueError(f"Invalid or duplicate case at CSV line {reader.line_num}")
        seen.add(case_id)
        cases.append(Case(case_id, backstory, references))
    if not cases:
        raise ValueError("Dataset contains no cases")
    return cases


@dataclass
class Result:
    case_id: str
    reference_count: int
    outcome: str = "error"
    generated_query: str | None = None
    semantic_mean: float | None = None
    lexical_jaccard_mean: float | None = None
    thread_id: str | None = None
    decisions: int = 0
    model: str | None = None
    error: str | None = None


class DecisionError(ValueError):
    """A safe diagnostic about the checkpoint, excluding provider payloads."""


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def runtime_artifacts(specifications: list[str]) -> dict:
    """Identify operator-retained deployment snapshots without copying secrets."""
    artifacts = {}
    for specification in specifications:
        name, separator, filename = specification.partition("=")
        if not separator or not name or not filename or name in artifacts:
            raise ValueError("Runtime artifacts must have unique NAME=PATH entries")
        artifacts[name] = {"sha256": hashlib.sha256(Path(filename).read_bytes()).hexdigest()}
    return artifacts


def record_runtime(client: httpx.Client, row: Result, state: dict, records: list[dict]) -> None:
    """Read host-produced evidence, never arbitrary run kwargs/provider payloads."""
    runs = client.get(f"threads/{row.thread_id}/runs").raise_for_status().json()
    previous = {record["run_id"] for record in records}
    current = [run for run in runs if run["run_id"] not in previous]
    if len(current) != 1:
        raise DecisionError("Cannot associate checkpoint with exactly one Gateway run")
    run = current[0]
    record = {"run_id": run["run_id"], "checkpoint_sha256": fingerprint(state)}
    records.append(record)
    proof = run.get("metadata", {}).get("deerflow_assembly_evidence")
    if not isinstance(proof, dict) or proof.get("source") != "host_assembly" or proof.get("schema_version") != 1:
        raise DecisionError("Gateway did not provide supported assembly evidence")
    if proof.get("thread_id") != row.thread_id or proof.get("run_id") != run["run_id"]:
        raise DecisionError("Gateway assembly evidence belongs to another run")
    # The public contract already excludes prompts, headers, URLs and credentials.
    keys = ("schema_version", "source", "thread_id", "run_id", "agent", "model", "parameters", "model_version", "instructions_version", "tools_version", "skills_version", "policy_version", "version")
    if any(key not in proof for key in keys):
        raise DecisionError("Gateway assembly evidence is incomplete")
    row.model = proof["model"]
    record.update(
        {
            "assembly": {key: proof[key] for key in keys},
            "context_messages": [{"type": message["type"], "content": message.get("content")} for message in state.get("messages", []) if message.get("type") in ("human", "system")],
        }
    )


def evaluate(case: Case, client: httpx.Client, model: str | None, encoder, *, max_decisions: int = 8, runtime: list[dict] | None = None) -> Result:
    row = Result(case.case_id, len(case.references))
    records = runtime if runtime is not None else []
    try:
        row.thread_id = client.post("threads", json={}).raise_for_status().json()["thread_id"]
        payload = {
            "input": {"messages": [{"role": "user", "content": case.backstory}]},
            # Resuming this breakpoint executes the pending preparatory batch,
            # then stops before the next tools batch. Never resume a search batch.
            "interrupt_before": ["tools"],
            "context": {**CONTEXT, **({"model_name": model} if model else {})},
        }
        for decision in range(1, max_decisions + 1):
            state = client.post(f"threads/{row.thread_id}/runs/wait", json=payload).raise_for_status().json()
            row.decisions = decision
            if not isinstance(state, dict) or state.get("status") == "error":
                raise DecisionError("Gateway run failed; inspect Gateway logs")
            record_runtime(client, row, state, records)
            messages = state.get("messages")
            if not isinstance(messages, list) or not messages or messages[-1].get("type") != "ai":
                raise DecisionError("Gateway did not return an assistant decision; check pending approvals")
            message = messages[-1]
            calls = message.get("tool_calls", [])
            invalid = message.get("invalid_tool_calls", [])
            if invalid:
                raise DecisionError("Cannot identify first search query in malformed tool batch")
            search = next((call for call in calls if call["name"] == "web_search"), None)
            if search is not None:
                break
            if not calls:
                if not message.get("content"):
                    raise DecisionError("Empty assistant response")
                row.outcome = "direct_answer"
                return row
            payload["input"] = None
        else:
            row.outcome = "decision_limit"
            return row
        query = search["args"].get("query")
        if not isinstance(query, str) or not query.strip():
            raise DecisionError("First web_search call has no usable query")
        row.generated_query = query
        row.semantic_mean = fmean(semantic.similarities(query, case.references, encoder))
        row.lexical_jaccard_mean = fmean(lexical.similarity(query, ref) for ref in case.references)
        row.outcome = "scored"
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403):
            raise PermissionError("Gateway denied access. Check DEERFLOW_BENCHMARK_TOKEN and its threads:write, runs:create and runs:read scopes.") from exc
        row.error = f"Gateway HTTP {exc.response.status_code}"
    except DecisionError as exc:
        row.error = str(exc)
    except (httpx.RequestError, KeyError, TypeError, AttributeError, RuntimeError, ValueError) as exc:
        # Keep provider payloads and credentials out of results.
        row.error = type(exc).__name__
    return row


def run(cases, client, model, encoder, output: Path, provenance: dict, *, max_decisions: int = 8) -> dict:
    if max_decisions < 1:
        raise ValueError("max_decisions must be positive")
    output.mkdir(parents=True, exist_ok=False)
    (output / ".gitignore").write_text("*\n", encoding="utf-8")
    counts = Counter()
    configuration = {
        "schema_version": 1,
        "case_ids": [case.case_id for case in cases],
        "max_decisions": max_decisions,
        "interrupt_before": ["tools"],
        "context": CONTEXT,
        "client_timeout_seconds": 180,
        "client_retries": 0,
        "model_selection": model,
        "provenance": provenance,
    }
    (output / "configuration.json").write_text(json.dumps(configuration, indent=2) + "\n", encoding="utf-8")
    with (output / "results.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=[f.name for f in fields(Result)] + ["backstory", "human_queries"])
        writer.writeheader()
        for index, case in enumerate(cases):
            runtime = []
            row = evaluate(case, client, model, encoder, max_decisions=max_decisions, runtime=runtime)
            # IDs can originate in caller-supplied datasets; never use them as paths.
            (output / f"runtime-{index:04d}.json").write_text(json.dumps({"case_id": case.case_id, "thread_id": row.thread_id, "runs": runtime}, indent=2) + "\n", encoding="utf-8")
            writer.writerow({**asdict(row), "backstory": case.backstory, "human_queries": json.dumps(case.references, ensure_ascii=False)})
            file.flush()
            counts[row.outcome] += 1
    summary = {
        "backstories": len(cases),
        "outcomes": {key: counts[key] for key in ("scored", "direct_answer", "decision_limit", "error")},
        "coverage": counts["scored"] / len(cases),
        "provenance": provenance,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--dataset-sha256", default=DATASET_SHA256)
    parser.add_argument("--model", help="DeerFlow model name (default: Gateway configuration)")
    parser.add_argument("--max-decisions", type=int, default=8, help="Maximum assistant checkpoints inspected per backstory")
    parser.add_argument("--gateway-revision", required=True, help="Revision/image digest of the running Gateway (operator supplied)")
    parser.add_argument("--runtime-artifact", action="append", required=True, metavar="NAME=PATH", help="Deployment snapshot to fingerprint; repeat for config, prompts, memory and extensions")
    parser.add_argument("--limit", type=int, help="Evaluate the first N backstories in CSV order")
    parser.add_argument("--output-dir", type=Path, help="New directory for results.csv and summary.json")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.max_decisions < 1:
        parser.error("--max-decisions must be positive")
    if not args.gateway_revision.strip():
        parser.error("--gateway-revision must not be blank")
    artifacts = runtime_artifacts(args.runtime_artifact)
    cases = load_cases(args.dataset, args.dataset_sha256)[: args.limit]
    output = args.output_dir or HERE / "runs" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    if output.exists():
        parser.error(f"Output directory already exists: {output}")

    token = os.getenv("DEERFLOW_BENCHMARK_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    url = os.getenv("DEERFLOW_BENCHMARK_URL", "http://127.0.0.1:2026/api")
    with httpx.Client(base_url=url.rstrip("/") + "/", headers=headers, timeout=180) as client:
        encoder = semantic.load_encoder()
        git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=HERE, capture_output=True, text=True, check=False)
        provenance = {
            "git_revision": git.stdout.strip() or None,
            "dataset_sha256": args.dataset_sha256.lower(),
            "source_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in [Path(__file__), *sorted((HERE / "metrics").glob("*.py"))]},
            "model_selection": args.model or "gateway default",
            "gateway_revision": {"value": args.gateway_revision, "source": "operator"},
            "runtime_artifacts": artifacts,
            "started_at_utc": datetime.now(UTC).isoformat(),
            "client_retries": 0,
            "encoder": semantic.MODEL,
            "encoder_revision": semantic.REVISION,
            "sentence_transformers_version": version("sentence-transformers"),
            "python_version": sys.version,
            "package_versions": {package: version(package) for package in ("httpx", "langchain", "langgraph", "deerflow-harness", "numpy", "torch")},
        }
        summary = run(cases, client, args.model, encoder, output, provenance, max_decisions=args.max_decisions)
        if runtime_artifacts(args.runtime_artifact) != artifacts:
            raise ValueError("Deployment snapshots changed during evaluation; discard this run")
    print(f"Results: {output / 'results.csv'}\nSummary: {output / 'summary.json'}")
    print(f"{summary['outcomes']['scored']}/{len(cases)} scored. Outcomes: {summary['outcomes']}")
    return int(bool(summary["outcomes"]["error"]))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, ImportError, httpx.HTTPError) as exc:
        sys.exit(f"Benchmark setup failed: {exc}")
