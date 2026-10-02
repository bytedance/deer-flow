"""Source-pinned offline orchestration and reporting for issue #2805."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[3]
CONFIG_PATH = HERE / "config.json"
FIXTURES_PATH = HERE / "fixtures.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest()


def load_inputs(config_path: Path, fixtures_path: Path) -> tuple[dict, list[dict]]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    payload = json.loads(fixtures_path.read_text(encoding="utf-8"))
    if config.get("schema_version") != 1 or payload.get("schema_version") != 1 or payload.get("synthetic") is not True:
        raise ValueError("Expected version-1 explicitly synthetic fixtures/config")
    if payload.get("score_origin") != "hand_authored":
        raise ValueError("This offline fixture set uses hand-authored scores only")
    cases = payload["cases"]
    if not cases or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Case IDs must be nonempty and unique")
    for case in cases:
        if not isinstance(case["id"], str) or not case["id"] or type(case["stalled"]) is not bool or type(case["vary_args"]) is not bool:
            raise ValueError("Invalid case identity/labels")
        if type(case["steps"]) is not int or not 1 <= case["steps"] <= 1000:
            raise ValueError("steps must be an integer in [1, 1000]")
        if not case["tools"] or not all(isinstance(tool, str) and tool for tool in case["tools"]):
            raise ValueError("Each case needs tool names")
        evaluation = case["evaluation"]
        if evaluation is not None:
            for key in ("task_progress", "tool_usefulness"):
                if type(evaluation[key]) is not int or not 0 <= evaluation[key] <= 3:
                    raise ValueError("Fixture scores must be integers in [0, 3]")
        meta = case["meta"]
        if meta["status"] not in {"success", "error", "partial_success"} or type(meta["recoverable_by_model"]) is not bool:
            raise ValueError("Invalid structured tool result metadata")
        if meta["recommended_next_action"] not in {"continue", "rewrite_query", "try_alternative", "summarize", "stop"}:
            raise ValueError("Invalid recovery action")
        if meta["source"] not in {"exception", "tool_return", "content_analysis", "progress_middleware"}:
            raise ValueError("Invalid metadata source")
        # Validate format strings before starting any worker.
        from .worker import expand_case

        expand_case(case)
    return config, cases


def validate_checkout(root: Path, pins: dict[str, str]) -> None:
    for relative, expected in pins.items():
        path = root / relative
        if not path.is_file() or text_sha256(path) != expected:
            raise ValueError(f"Source pin mismatch: {relative}")


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True, encoding="utf-8").strip()


def worker_result(root: Path, policy: str, cases: list[dict], config: dict, tokenizer_file: Path | None = None) -> dict:
    command = [sys.executable, str(HERE / "worker.py"), "--root", str(root.resolve()), "--policy", policy]
    if tokenizer_file:
        command.extend(["--tokenizer-file", str(tokenizer_file.resolve())])
    completed = subprocess.run(command, input=json.dumps({"cases": cases, "config": config}), capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)
    if completed.returncode:
        raise RuntimeError(f"{policy} replay failed:\n{completed.stderr}")
    return json.loads(completed.stdout)


def run_worker(root: Path, policy: str, cases: list[dict], config: dict) -> list[dict]:
    return worker_result(root, policy, cases, config)["rows"]


def summarize(rows: list[dict]) -> dict:
    groups = defaultdict(list)
    for row in rows:
        groups[row["policy"]].append(row)
    summary = {}
    for policy, items in sorted(groups.items()):
        tp = sum(row["stalled"] and row["first_intervention_step"] is not None for row in items)
        fn = sum(row["stalled"] and row["first_intervention_step"] is None for row in items)
        fp = sum(not row["stalled"] and row["first_intervention_step"] is not None for row in items)
        tn = sum(not row["stalled"] and row["first_intervention_step"] is None for row in items)
        summary[policy] = {
            "tp": tp,
            "fn": fn,
            "fp": fp,
            "tn": tn,
            "stalled_cases": tp + fn,
            "legitimate_cases": fp + tn,
            "tpr": tp / (tp + fn) if tp + fn else None,
            "fpr": fp / (fp + tn) if fp + tn else None,
            "hard_stops": sum(row["first_hard_stop_step"] is not None for row in items),
        }
    return summary


def markdown(report: dict) -> str:
    lines = [
        "# Synthetic progress-detection policy replay",
        "",
        "This is a deterministic policy boundary check, not evidence of model scoring accuracy or a mainline adoption decision. All traces and scores are hand-authored. No model or real tool runs.",
        "",
        "The adapters use the production hooks in separate source checkouts. All three policies are evaluated independently with pinned parameters. "
        "The replay continues counterfactually after stops; it does not measure whether an agent follows a hint.",
        "",
        "| Policy | TP / stalled cases | FP / legitimate cases | TPR | FPR | Cases with hard stop |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for policy, summary in report["summary"].items():
        tpr = f"{summary['tpr']:.1%}" if summary["tpr"] is not None else "n/a"
        fpr = f"{summary['fpr']:.1%}" if summary["fpr"] is not None else "n/a"
        lines.append(f"| {policy} | {summary['tp']} / {summary['stalled_cases']} | {summary['fp']} / {summary['legitimate_cases']} | {tpr} | {fpr} | {summary['hard_stops']} |")
    lines.extend(
        [
            "",
            "Detection means a warn, block, hard_stop, or replan_required audit transition. eval_noncompliance is diagnostic and does not count. "
            "Labels apply to the entire case; each case has one vote. Fixture selection is deliberately adversarial and these rates are not population estimates.",
            "",
            "| Case | Label | Loop first hint / stop | Tool progress first hint / block | Candidate first hint / stop |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    by_case = defaultdict(dict)
    for row in report["rows"]:
        by_case[row["case_id"]][row["policy"]] = row
    for case_id, policies in by_case.items():
        label = "stalled" if next(iter(policies.values()))["stalled"] else "legitimate"
        cells = []
        for policy in ("loop_detection", "tool_progress", "progress_scoring"):
            row = policies[policy]
            cells.append(f"{row['first_intervention_step'] or '—'} / {row['first_hard_stop_step'] or '—'}")
        lines.append(f"| {case_id} | {label} | " + " | ".join(cells) + " |")
    candidates = [row for row in report["rows"] if row["policy"] == "progress_scoring"]
    tokens = candidates[0]["protocol_tokens_per_call"]
    lines.extend(
        [
            "",
            "## Protocol overhead",
            "",
            f"The fixed candidate instruction uses {tokens if tokens is not None else 'unmeasured'} cl100k_base tokens per model call. "
            "Token counts cover content only, excluding provider message envelopes, reasoning, prompt caching, and historical score retransmission (the candidate strips scores). "
            "The protocol is also sent on the initial call; a trace with N tool results measures N+1 protocol injections.",
            "",
            "| Case | Protocol calls | Protocol input tokens | Score output tokens | Hint input tokens |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for row in candidates:
        lines.append(f"| {row['case_id']} | {row['protocol_model_calls']} | {row['protocol_input_tokens']} | {row['score_output_tokens']} | {row['hint_input_tokens']} |")
    incremental = report["incremental_coverage"]
    lines.extend(
        [
            "",
            "Without a verified local tokenizer file, token fields are null; exact UTF-8 byte counts remain in report.json. No tokenizer or dataset is downloaded by the runner.",
            "",
            "## Incremental coverage",
            "",
            f"The union of the independent baseline detections covers {incremental['baseline_union_detected']} of {incremental['stalled_cases']} stalled cases. "
            f"The candidate uniquely detects: {', '.join(incremental['candidate_only_cases']) or 'none'}. "
            "This is a union of fixed-trace detections, not a composed middleware run: earlier baseline stops can prevent later candidate scoring.",
            "",
            "## Decision limits and next evidence",
            "",
            "Distinct result hashes veto the current candidate even with zero task_progress. The optimistic-score and missing-evaluation cases show its dependence on self-score compliance. "
            "Long productive cases still hit the raw-frequency guard; this candidate does not suppress it.",
            "",
            "Before runtime adoption, replay provenance-reviewed real traces with independent task-progress labels and model-generated scores. "
            "Measure scoring calibration/compliance across pinned models, overhead with actual provider tokenizers, end-to-end latency, intervention usefulness, and provider message validity. "
            "This offline report measures none of those outcomes.",
            "",
            "See report.json for source pins, package versions, fixture/config/runner hashes, and every observed audit transition.",
            "",
        ]
    )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-root", type=Path, required=True, help="Explicit local checkout of the pinned PR #5851 revision")
    parser.add_argument("--output-dir", type=Path, required=True, help="A new output directory")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--fixtures", type=Path, default=FIXTURES_PATH)
    parser.add_argument("--tokenizer-file", type=Path, help="Optional verified local cl100k_base.tiktoken vocabulary")
    args = parser.parse_args()
    config, cases = load_inputs(args.config, args.fixtures)
    validate_checkout(REPO_ROOT, config["source_hashes"]["baseline"])
    if git(REPO_ROOT, "diff", "--name-only", config["baseline_revision"], "HEAD", "--", "backend/packages"):
        raise ValueError("Baseline runtime tree must match config.baseline_revision")
    candidate_root = args.candidate_root.resolve()
    validate_checkout(candidate_root, config["source_hashes"]["candidate"])
    if git(candidate_root, "rev-parse", "HEAD") != config["candidate_revision"]:
        raise ValueError("Candidate HEAD must match config.candidate_revision")
    for root in (REPO_ROOT, candidate_root):
        if git(root, "status", "--porcelain", "--", "backend/packages", "backend/uv.lock"):
            raise ValueError("Replay checkout has modified/untracked runtime sources or lockfile")
    if args.tokenizer_file and sha256(args.tokenizer_file) != config["tokenizer_sha256"]:
        raise ValueError("Tokenizer SHA-256 mismatch")
    if args.output_dir.exists():
        raise ValueError("Output directory must be new")
    rows = []
    sources = {}
    for policy in config["policies"]:
        root = candidate_root if policy == "progress_scoring" else REPO_ROOT
        result = worker_result(root, policy, cases, config, args.tokenizer_file)
        rows.extend(result["rows"])
        sources[policy] = result["loaded_sources"]
    stalled_ids = {row["case_id"] for row in rows if row["stalled"]}
    baseline_detected = {row["case_id"] for row in rows if row["stalled"] and row["policy"] != "progress_scoring" and row["first_intervention_step"] is not None}
    candidate_detected = {row["case_id"] for row in rows if row["stalled"] and row["policy"] == "progress_scoring" and row["first_intervention_step"] is not None}
    report = {
        "schema_version": 1,
        "synthetic": True,
        "score_origin": "hand_authored",
        "clock": config["clock"],
        "seed": config["seed"],
        "config": config,
        "text_hash_normalization": "UTF-8 with LF newlines",
        "config_sha256": text_sha256(args.config),
        "fixtures_sha256": text_sha256(args.fixtures),
        "benchmark_sources": {path.name: text_sha256(path) for path in sorted(HERE.glob("*.py"))},
        "baseline_checkout_revision": git(REPO_ROOT, "rev-parse", "HEAD"),
        "candidate_checkout_revision": git(candidate_root, "rev-parse", "HEAD"),
        "baseline_lock_sha256": text_sha256(REPO_ROOT / "backend/uv.lock"),
        "candidate_lock_sha256": text_sha256(candidate_root / "backend/uv.lock"),
        "loaded_source_manifest_sha256": hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest(),
        "python": sys.version.split()[0],
        "packages": {name: importlib.metadata.version(name) for name in ("langchain", "langchain-core", "langgraph", "tiktoken")},
        "shared_dependency_environment": "baseline backend/uv.lock",
        "tokenizer_sha256": sha256(args.tokenizer_file) if args.tokenizer_file else None,
        "provider_latency_ms": None,
        "model_scoring_accuracy": None,
        "rows": rows,
        "summary": summarize(rows),
        "incremental_coverage": {
            "stalled_cases": len(stalled_ids),
            "baseline_union_detected": len(baseline_detected),
            "candidate_only_cases": sorted(candidate_detected - baseline_detected),
        },
    }
    args.output_dir.mkdir(parents=True)
    (args.output_dir / ".gitignore").write_text("*\n", encoding="utf-8")
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.output_dir / "sources.json").write_text(json.dumps(sources, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.output_dir / "report.md").write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
