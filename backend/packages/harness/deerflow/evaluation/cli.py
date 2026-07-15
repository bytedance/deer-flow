from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from typing import Any

import httpx

from deerflow.evaluation.loader import load_eval_suite

DEFAULT_GATEWAY_URL = "http://localhost:8001"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="deerflow-eval", description="Run and inspect DeerFlow evaluation suites")
    parser.add_argument("--gateway-url", default=DEFAULT_GATEWAY_URL, help="Gateway base URL")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Create an eval run from a suite file")
    run.add_argument("suite", help="Path to a YAML or JSON eval suite")
    run.add_argument("--idempotency-key", help="Idempotency-Key header")
    run.add_argument("--start", action="store_true", help="Ask the Gateway to run the eval immediately")
    run.add_argument("--sync", choices=["disabled", "langsmith"], default="disabled", help="External trace sync mode")

    status = subparsers.add_parser("status", help="Fetch eval run status")
    status.add_argument("eval_run_id")

    report = subparsers.add_parser("report", help="Fetch eval run report")
    report.add_argument("eval_run_id")
    report.add_argument("--format", choices=["json", "markdown"], default="json")

    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    client_factory: Callable[..., httpx.Client] = httpx.Client,
    stdout: Any = sys.stdout,
    stderr: Any = sys.stderr,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        with client_factory(base_url=args.gateway_url, timeout=60.0) as client:
            if args.command == "run":
                return _run(args, client, stdout)
            if args.command == "status":
                return _status(args, client, stdout)
            if args.command == "report":
                return _report(args, client, stdout)
    except httpx.HTTPStatusError as exc:
        print(f"Gateway request failed: {exc.response.status_code} {exc.response.text}", file=stderr)
        return 1
    except Exception as exc:
        print(f"deerflow-eval failed: {exc}", file=stderr)
        return 1
    return 0


def _run(args: argparse.Namespace, client: httpx.Client, stdout: Any) -> int:
    loaded = load_eval_suite(args.suite)
    print(f"LangSmith sync: {args.sync}", file=stdout)
    if args.sync != "disabled":
        raise ValueError("LangSmith sync is not implemented in this P0 CLI")
    headers = {"Idempotency-Key": args.idempotency_key} if args.idempotency_key else None
    response = client.post(
        "/api/evals",
        json={
            "suite": loaded.snapshot,
            "config": {"sync": args.sync, "suite_path": str(loaded.path)},
            "start_immediately": args.start,
        },
        headers=headers,
    )
    response.raise_for_status()
    print(json.dumps(response.json(), ensure_ascii=False, indent=2), file=stdout)
    return 0


def _status(args: argparse.Namespace, client: httpx.Client, stdout: Any) -> int:
    response = client.get(f"/api/evals/{args.eval_run_id}")
    response.raise_for_status()
    print(json.dumps(response.json(), ensure_ascii=False, indent=2), file=stdout)
    return 0


def _report(args: argparse.Namespace, client: httpx.Client, stdout: Any) -> int:
    response = client.get(f"/api/evals/{args.eval_run_id}/report", params={"format": args.format})
    response.raise_for_status()
    if args.format == "markdown":
        print(response.text, file=stdout, end="" if response.text.endswith("\n") else "\n")
    else:
        print(json.dumps(response.json(), ensure_ascii=False, indent=2), file=stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
