"""Command-line entry point and launch-mode planning for the DeerFlow TUI.

``plan_launch`` is a pure decision function (fully unit-tested): given argv, TTY
state and the environment, it decides whether to open the terminal UI or run a
headless one-shot. ``main`` wires that decision to the embedded ``DeerFlowClient``
and lazily imports the Textual app only when actually launching the UI, so the
``deerflow`` console script still runs headless commands without Textual present.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

_UNSET = object()

Mode = Literal["tui", "print", "json", "headless-help"]


@dataclass
class LaunchPlan:
    mode: Mode
    message: str | None = None
    read_stdin: bool = False
    thread_id: str | None = None
    continue_recent: bool = False
    forced_tui: bool = False
    reason: str = ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deerflow",
        description="DeerFlow terminal workbench — a TUI over the embedded DeerFlow harness.",
        add_help=True,
    )
    parser.add_argument("message", nargs="*", help="initial prompt for the TUI, or message in --cli mode")
    parser.add_argument(
        "--print",
        dest="print",
        nargs="?",
        const=None,
        default=_UNSET,
        metavar="MESSAGE",
        help="headless one-shot: print the final answer and exit (reads stdin if no MESSAGE)",
    )
    parser.add_argument(
        "--json",
        dest="json",
        nargs="?",
        const=None,
        default=_UNSET,
        metavar="MESSAGE",
        help="headless streaming: emit newline-delimited JSON StreamEvents and exit",
    )
    parser.add_argument("--tui", action="store_true", help="force the terminal UI (error if unavailable)")
    parser.add_argument("--cli", action="store_true", help="force headless/classic mode for one invocation")
    parser.add_argument("--continue", dest="continue_recent", action="store_true", help="resume the most recent thread")
    parser.add_argument("--resume", dest="resume", metavar="THREAD", default=None, help="resume a thread by id or title")
    return parser


def _strip_chat(argv: Sequence[str]) -> list[str]:
    """Accept an optional leading ``chat`` subcommand as an alias for the default surface."""
    argv = list(argv)
    if argv and argv[0] == "chat":
        return argv[1:]
    return argv


def _truthy(value: object) -> bool:
    return isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}


def plan_launch(
    argv: Sequence[str],
    *,
    stdin_isatty: bool,
    stdout_isatty: bool,
    env: dict[str, str],
) -> LaunchPlan:
    """Decide what surface to launch. Pure: no I/O, no client construction."""
    args = build_parser().parse_args(_strip_chat(argv))
    positional = " ".join(args.message).strip() or None
    resume = args.resume
    continue_recent = bool(args.continue_recent)

    if args.print is not _UNSET:
        message = args.print if isinstance(args.print, str) else None
        if message is None and stdin_isatty:
            return LaunchPlan(mode="headless-help", reason="--print needs a MESSAGE argument or piped stdin.")
        return LaunchPlan(mode="print", message=message, read_stdin=message is None, thread_id=resume, continue_recent=continue_recent)

    if args.json is not _UNSET:
        message = args.json if isinstance(args.json, str) else None
        if message is None and stdin_isatty:
            return LaunchPlan(mode="headless-help", reason="--json needs a MESSAGE argument or piped stdin.")
        return LaunchPlan(mode="json", message=message, read_stdin=message is None, thread_id=resume, continue_recent=continue_recent)

    if args.cli:
        if positional:
            return LaunchPlan(mode="print", message=positional, thread_id=resume, continue_recent=continue_recent)
        # Mirror --print: a piped message or --continue is enough to run headless.
        if continue_recent or not stdin_isatty:
            return LaunchPlan(mode="print", message=None, read_stdin=True, thread_id=resume, continue_recent=continue_recent)
        return LaunchPlan(
            mode="headless-help",
            reason='--cli needs a message. Try: deerflow --print "your question".',
        )

    forced_tui = bool(args.tui)
    if forced_tui or _truthy(env.get("DEER_FLOW_TUI")) or (stdin_isatty and stdout_isatty):
        return LaunchPlan(
            mode="tui",
            message=positional,
            thread_id=resume,
            continue_recent=continue_recent,
            forced_tui=forced_tui,
        )

    return LaunchPlan(
        mode="headless-help",
        message=positional,
        thread_id=resume,
        continue_recent=continue_recent,
        reason="No interactive terminal detected. Use --print MESSAGE for one-shot output, or --tui to force the UI.",
    )


# --------------------------------------------------------------------------- #
# Runtime dispatch (not unit-tested here; covered by smoke + integration).
# --------------------------------------------------------------------------- #

_HEADLESS_HELP = """\
deerflow — DeerFlow terminal workbench

  deerflow                      launch the terminal UI (TTY required)
  deerflow --tui                force the terminal UI
  deerflow --continue           resume the most recent thread in the UI
  deerflow --resume THREAD      resume a thread by id or title
  deerflow --print "question"   one-shot answer to stdout
  deerflow --json "question"    stream newline-delimited JSON events
  echo "question" | deerflow --print
"""


def _resolve_message(plan: LaunchPlan) -> str:
    if plan.read_stdin:
        return sys.stdin.read().strip()
    return plan.message or ""


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    plan = plan_launch(
        argv,
        stdin_isatty=sys.stdin.isatty(),
        stdout_isatty=sys.stdout.isatty(),
        env=dict(os.environ),
    )

    if plan.mode == "headless-help":
        if plan.reason:
            print(plan.reason, file=sys.stderr)
        print(_HEADLESS_HELP, file=sys.stderr)
        return 0 if not plan.reason else 2

    if plan.mode == "print":
        return _run_print(plan)

    if plan.mode == "json":
        return _run_json(plan)

    return _run_tui(plan)


def _make_session():
    # Imported lazily so the pure planning path never imports the heavy harness.
    # Headless one-shots never use the threads_meta writer, so skip persistence
    # (no background loop / engine / connection pool just to discard it).
    from .session import open_session

    return open_session(persistence=False)


def _run_print(plan: LaunchPlan) -> int:
    message = _resolve_message(plan)
    if not message:
        print("No message provided.", file=sys.stderr)
        return 2
    session = _make_session()
    thread_id = session.resolve_thread(plan)
    answer = session.client.chat(message, thread_id=thread_id)
    print(answer)
    return 0


def _run_json(plan: LaunchPlan) -> int:
    message = _resolve_message(plan)
    if not message:
        print("No message provided.", file=sys.stderr)
        return 2
    session = _make_session()
    thread_id = session.resolve_thread(plan)
    for event in session.client.stream(message, thread_id=thread_id):
        payload = {"type": event.type, "data": event.data}
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        sys.stdout.flush()
    return 0


def _run_tui(plan: LaunchPlan) -> int:
    try:
        # Absolute import (not `from .app`) so the harness import-boundary check,
        # which records relative module names verbatim, doesn't mistake the sibling
        # `deerflow.tui.app` module for the forbidden top-level `app` package.
        from deerflow.tui.app import run_tui
    except ModuleNotFoundError as exc:  # textual missing
        if getattr(exc, "name", "") == "textual" or "textual" in str(exc):
            msg = "The terminal UI needs the optional 'textual' dependency.\nInstall it with:  uv pip install 'deerflow-harness[tui]'   (or: pip install textual)\n"
            if plan.forced_tui:
                print(msg, file=sys.stderr)
                return 1
            print(msg + "\nFalling back to headless help:\n", file=sys.stderr)
            print(_HEADLESS_HELP, file=sys.stderr)
            return 0
        raise
    return run_tui(plan)


if __name__ == "__main__":
    raise SystemExit(main())
