"""Run the Sprint 1 Deep Research pilot from the repository root."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
HARNESS_DIR = BACKEND_DIR / "packages" / "harness"

for candidate in (str(BACKEND_DIR), str(HARNESS_DIR)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from deerflow.pilot import DeepResearchPilotRequest, DeepResearchPilotRunner


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Sprint 1 Deep Research pilot.")
    parser.add_argument("--objective", required=True, help="Research objective for the pilot task.")
    parser.add_argument("--context-file", help="Optional text/markdown file containing extra context.")
    parser.add_argument("--attachment", action="append", default=[], help="Attachment path. Repeat for multiple files.")
    parser.add_argument(
        "--expected-output",
        action="append",
        default=[],
        help="Expected output line. Repeat for multiple expectations.",
    )
    parser.add_argument(
        "--profile",
        choices=["default", "founder", "operator"],
        help="Shape the final artifact for a founder memo or operator handoff.",
    )
    parser.add_argument(
        "--output-profile",
        dest="legacy_output_profile",
        choices=["default", "founder", "operator", "founder_memo", "operator_memo"],
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--request-id", help="Optional fixed request ID.")
    parser.add_argument("--idempotency-key", help="Optional fixed idempotency key.")
    parser.add_argument("--thread-id", help="Optional fixed DeerFlow thread ID.")
    parser.add_argument("--model", dest="model_name", help="Optional DeerFlow model name override.")
    parser.add_argument("--timeout-seconds", type=int, default=900, help="Fail the pilot after this many seconds.")
    parser.add_argument(
        "--heartbeat-interval-seconds",
        type=int,
        default=45,
        help="Emit a heartbeat every N seconds while the task is quiet.",
    )
    parser.add_argument(
        "--heartbeat-start-after-seconds",
        type=int,
        default=60,
        help="Do not emit heartbeats before this many seconds have elapsed.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    context_summary = ""
    if args.context_file:
        context_summary = Path(args.context_file).read_text(encoding="utf-8")

    selected_profile = args.profile or args.legacy_output_profile or "default"
    request = DeepResearchPilotRequest(
        objective=args.objective,
        context_summary=context_summary,
        attachments=list(args.attachment),
        expected_outputs=list(args.expected_output),
        output_profile=selected_profile,
        request_id=args.request_id,
        idempotency_key=args.idempotency_key,
        thread_id=args.thread_id,
        model_name=args.model_name,
        timeout_seconds=args.timeout_seconds,
        heartbeat_interval_seconds=args.heartbeat_interval_seconds,
        heartbeat_start_after_seconds=args.heartbeat_start_after_seconds,
    )
    result = DeepResearchPilotRunner().run(request)
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
