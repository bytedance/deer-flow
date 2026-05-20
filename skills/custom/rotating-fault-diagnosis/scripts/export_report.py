#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

from _bridge import load_data_analyst_module

_REPORT_MODULE = load_data_analyst_module("export_report.py", "_rotating_export_report")
_DIAGNOSIS_MODULE = load_data_analyst_module("export_diagnosis_report.py", "_rotating_export_diagnosis_report")

for _name in dir(_REPORT_MODULE):
    if _name.startswith("__") or _name == "main":
        continue
    globals().setdefault(_name, getattr(_REPORT_MODULE, _name))

write_report = getattr(_REPORT_MODULE, "write_report")
_markdown_to_html = getattr(_REPORT_MODULE, "_markdown_to_html")
render_diagnosis_markdown = getattr(_DIAGNOSIS_MODULE, "render_diagnosis_markdown")
render_diagnosis_html = getattr(_DIAGNOSIS_MODULE, "render_diagnosis_html")


def _split_token(argv: list[str]) -> tuple[list[str], str | None]:
    forwarded: list[str] = []
    token: str | None = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--access-token":
            if i + 1 >= len(argv):
                raise SystemExit("--access-token requires a value")
            token = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--access-token="):
            token = arg.split("=", 1)[1]
            i += 1
            continue
        forwarded.append(arg)
        i += 1
    return forwarded, token


def main() -> int:
    forwarded, token = _split_token(sys.argv[1:])
    if token:
        os.environ["INS_ACCESS_TOKEN"] = token

    original_argv = sys.argv
    sys.argv = [original_argv[0], *forwarded]
    try:
        return int(_REPORT_MODULE.main())
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    raise SystemExit(main())
